"""Recap Studio MM Pro — FastAPI application (v4.1).

Route map
---------
GET  /                          → SPA shell (static/index.html)
POST /api/auth/login|logout     → session login (cookie + CSRF token)
GET  /api/auth/me               → current account (or 401)
POST /api/auth/register         → self sign-up (RECAP_ALLOW_SIGNUP=1)
POST /api/auth/password         → change own password
GET  /api/admin/users           → account list (admin)
POST /api/admin/users           → create / update / disable accounts (admin)
GET  /api/admin/audit           → audit trail (admin)
GET  /healthz                   → ALB / ECS health check
GET  /api/system                → capabilities, fonts, ffmpeg, disk, defaults
GET  /api/config   POST         → API key / model persistence (multi-key ring)
GET  /api/keys                  → Key #1-#3 status (masked)
POST /api/keys                  → save Key #1-#3 / switch the active slot
POST /api/keys/test             → verify a key against Gemini (Test button)
POST /api/upload/init|chunk|complete  → resumable chunked upload (videos)
GET  /api/upload/status?upload_id=    → resume an interrupted upload
POST /api/upload | /api/upload-logo   → simple upload (logos, small files)
GET  /api/asset?path=           → serve workspace files (Range capable)
POST /api/download-url          → yt-dlp import (fixed URL handling)
POST /api/tasks                 → start a recap job
GET  /api/tasks                 → job history
GET  /api/tasks/active          → newest running/queued job (survives refresh)
GET  /api/tasks/{id}            → live status (progress, stage, logs, ETA)
POST /api/tasks/{id}/cancel     → instant cancellation (kills ffmpeg too)
POST /api/tasks/{id}/rerender   → re-render an edited timeline
DELETE /api/tasks/{id}          → delete job + its files
GET  /api/download/{filename}   → download a rendered artefact
POST /api/thumbnail             → viral thumbnail generator
POST /api/estimate-parts | /api/split-video → shorts splitter (async job)
"""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import uvicorn
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException,
                     Query, Request, Response, UploadFile)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from recapstudio import auth, config, db, fonts, thumbs, webauth
from recapstudio.auth import Principal
from recapstudio.config import ensure_dirs
from recapstudio.jobs import JobStore
from recapstudio.keys import key_ring, mask as mask_key, validate_key
from recapstudio.media import (ffmpeg_available, ffmpeg_version, ffprobe_available,
                               get_video_info, process_registry)
from recapstudio.pipeline import RecapPipeline
from recapstudio.tts import VOICE_CATALOG
from recapstudio.uploads import upload_manager
from recapstudio.uploads import VIDEO_EXT
from recapstudio.util import (cached_dir_size, free_disk_bytes, get_logger, human_bytes,
                              prune_old_files, read_json, safe_unlink, setup_logging)


def _crypto_backend() -> str:
    from recapstudio.crypto import encryption_backend
    return encryption_backend()

setup_logging()
log = get_logger("recap.app")
ensure_dirs()

app = FastAPI(title="Recap Studio MM Pro", version=config.settings.app_version,
              docs_url="/api/docs", redoc_url=None)

# Same-origin SPA: credentials are not needed, so "*" is only used when no
# explicit allow-list is configured (the previous code combined "*" with
# allow_credentials=True, which browsers reject outright).
_origins = list(config.settings.allowed_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=bool(_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

store = JobStore()
pipeline = RecapPipeline(store)
_started_at = time.time()

#: Pipeline jobs get their own worker pool. They used to run as FastAPI
#: BackgroundTasks, i.e. inside Starlette's shared thread pool that also
#: serves uploads — a burst of chunk uploads could starve a running recap and
#: the progress bar appeared to freeze. API routes now never wait for a job.
_JOB_WORKERS = max(1, int(config.settings.max_concurrent_jobs))
job_pool = ThreadPoolExecutor(max_workers=_JOB_WORKERS, thread_name_prefix="recap-job")
_job_queue: "queue.Queue[str]" = queue.Queue()
_active_jobs: set[str] = set()
_jobs_lock = threading.RLock()


def submit_job(target: Callable[..., Any], *args: Any) -> Future:
    """Queue a pipeline call on the job pool (never blocks an HTTP request)."""
    job_id = args[0] if args else ""

    def _wrapped() -> None:
        with _jobs_lock:
            _active_jobs.add(str(job_id))
        try:
            target(*args)
        except BaseException as exc:  # noqa: BLE001 - a job must never die silently
            log.exception("job %s crashed: %s", job_id, exc)
            try:
                store.update(str(job_id), status="failed",
                             message=f"❌ မမျှော်လင့်သော error: {str(exc)[:600]}",
                             error=str(exc)[:600])
            except Exception:
                pass
        finally:
            with _jobs_lock:
                _active_jobs.discard(str(job_id))

    return job_pool.submit(_wrapped)


def job_pool_state() -> dict:
    with _jobs_lock:
        active = len(_active_jobs)
    return {
        "workers": _JOB_WORKERS,
        "active": active,
        "busy": active >= _JOB_WORKERS,
        "ffmpeg_running": process_registry.count(),
    }


# ── security middleware (Phase 2) ────────────────────────────────────────
_api_limiter = auth.RateLimiter(config.settings.api_rate_limit or 10_000, 60.0)
_login_limiter = auth.RateLimiter(config.settings.login_rate_limit or 10_000, 60.0)


@app.middleware("http")
async def _security_middleware(request: Request, call_next):
    """Host allow-list, rate limiting and hardening headers in one place."""
    hosts = config.settings.trusted_hosts
    if hosts:
        host = (request.headers.get("host", "").split(":")[0] or "").lower()
        if host and host not in hosts:
            return JSONResponse({"detail": "Host header ကို လက်မခံပါ"}, status_code=400)

    path = request.url.path
    if path.startswith("/api/") and config.settings.api_rate_limit:
        ident = webauth.client_ip(request) or "anon"
        limiter = _login_limiter if path.startswith("/api/auth/login") else _api_limiter
        allowed, retry_after = limiter.check(f"{ident}:{'login' if limiter is _login_limiter else 'api'}")
        if not allowed:
            return JSONResponse(
                {"detail": "တောင်းဆိုမှု များလွန်းပါသည် — ခဏစောင့်ပြီး ပြန်ကြိုးစားပါ "
                           "(rate limit)"},
                status_code=429, headers={"Retry-After": str(int(retry_after) + 1)})

    response = await call_next(request)

    if config.settings.security_headers:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-XSS-Protection", "0")
        response.headers.setdefault("Permissions-Policy",
                                    "camera=(), microphone=(), geolocation=()")
        frames = (config.settings.frame_ancestors or "self").lower()
        if frames in {"none", "self"}:
            response.headers.setdefault("X-Frame-Options",
                                        "DENY" if frames == "none" else "SAMEORIGIN")
            response.headers.setdefault("Content-Security-Policy",
                                        f"frame-ancestors '{frames}'")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if config.settings.hsts_seconds and webauth.request_is_https(request):
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={int(config.settings.hsts_seconds)}; includeSubDomains")
    return response


# ── helpers ──────────────────────────────────────────────────────────────
def _access_ok(key: Optional[str]) -> bool:
    """True when the caller may use the (optional) shared secret gate."""
    expected = config.settings.access_password
    if not expected:
        return True
    return (key or "").strip() == expected


def _check_access(key: Optional[str]) -> None:
    """Optional shared-secret gate for public AWS deployments."""
    if _access_ok(key):
        return
    raise HTTPException(status_code=401, detail=webauth.ACCESS_KEY_REQUIRED)


#: FastAPI dependencies — every /api route that touches data uses one of these
guard = webauth.require_principal
admin_guard = webauth.require_admin


def _json_error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _scope(principal: Principal) -> str:
    """Ownership scope: the account id in multi-user mode, else "shared"."""
    return principal.scope


def _owned_job(task_id: str, principal: Principal):
    """Fetch a job the caller is allowed to touch (404 otherwise).

    Returning 404 (not 403) for somebody else's task is deliberate: it does
    not confirm that the id exists.
    """
    job = store.get(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    if principal.mode != "users" or principal.is_admin:
        return job
    if (job.user_id or "shared") != principal.scope:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    return job


def _resolve_owned(raw_path: str, principal: Principal) -> Path:
    """Path inside DATA_DIR *and* inside the caller's sandbox."""
    try:
        if principal.mode == "users" and not principal.is_admin:
            return config.resolve_owned(raw_path, principal.scope)
        return config.resolve(raw_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _effective_api_key(principal: Principal, payload: dict[str, Any]) -> str:
    """The Gemini key a job should run with (personal key wins)."""
    if payload.get("api_key"):
        return str(payload["api_key"])
    if principal.mode == "users":
        keys = auth.get_user_keys(principal.user_id)
        if keys:
            return keys[0]
    return ""


def _enforce_job_quota(principal: Principal) -> None:
    """Per-account concurrency / daily limits (multi-user fairness)."""
    if principal.mode != "users":
        return
    user = auth.get_user(principal.user_id) or {}
    limits = auth.user_limits(user)
    max_concurrent = limits["max_concurrent_jobs"]
    if max_concurrent:
        active = store.count_active(principal.scope)
        if active >= max_concurrent:
            raise HTTPException(
                status_code=429,
                detail=f"သင့်အကောင့်တွင် တစ်ပြိုင်နက် job {max_concurrent} ခုသာ run နိုင်ပါသည် — "
                       "လက်ရှိ job ပြီးအောင် စောင့်ပါ သို့မဟုတ် ရပ်လိုက်ပါ")
    daily = limits["daily_job_limit"]
    if daily and auth.jobs_today(principal.user_id) >= daily:
        raise HTTPException(status_code=429,
                            detail=f"ယနေ့အတွက် job {daily} ခု ကန့်သတ်ချက် ပြည့်သွားပါပြီ")
    quota = limits["quota_bytes"]
    if quota:
        used = (cached_dir_size(config.user_workspace_dir(principal.scope), blocking=False)
                + cached_dir_size(config.user_output_dir(principal.scope), blocking=False))
        if used >= quota:
            raise HTTPException(
                status_code=507,
                detail=f"သိမ်းဆည်းမှု ကန့်သတ်ချက် ({human_bytes(quota)}) ပြည့်သွားပါပြီ — "
                       "Jobs tab မှ အဟောင်းများ ဖျက်ပါ")


def _owner_filter(principal: Principal) -> Optional[str]:
    """Which jobs this caller may list (None = every job, admins only)."""
    if principal.mode != "users":
        return None
    return principal.scope


def _download_target(safe_name: str, principal: Principal) -> Optional[Path]:
    """Resolve a download inside the caller's output sandbox.

    Admins (and single-user installs) may also read the shared output root;
    a normal account can only reach files produced by its own jobs.
    """
    candidates = [config.user_output_dir(_scope(principal), create=False) / safe_name]
    if principal.mode != "users" or principal.is_admin:
        candidates.append(config.OUTPUT_DIR / safe_name)
    for candidate in candidates:
        resolved = candidate.resolve()
        if config.OUTPUT_DIR.resolve() not in resolved.parents:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _register_job(job, principal: Principal) -> None:
    try:
        auth.register_job(job.id, job.user_id or "shared", job.kind, job.status)
    except Exception as exc:  # the DB must never block a render
        log.debug("job index write failed: %s", exc)
    auth.audit("job_create", principal=principal, target=job.id, detail=job.kind)


# ── static SPA ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_ui() -> HTMLResponse:
    """Serve the SPA shell with version-stamped asset URLs.

    Browsers cached ``/static/app.js`` aggressively, so after an update the old
    UI kept running (no login screen even though the new build was deployed).
    Stamping ``?v=<app_version>`` makes every release a new URL, and the shell
    itself is never cached.
    """
    index = config.STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Recap Studio</h1><p>static/index.html missing</p>", status_code=500)
    version = config.settings.app_version
    html = (index.read_text(encoding="utf-8")
            .replace("/static/app.js", f"/static/app.js?v={version}")
            .replace("/static/styles.css", f"/static/styles.css?v={version}"))
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok" if ffmpeg_available() and ffprobe_available() else "degraded",
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "uptime_seconds": round(time.time() - _started_at, 1),
        "free_disk": human_bytes(free_disk_bytes()),
        "version": config.settings.app_version,
    }


# ── authentication (Phase 2 — #12) ───────────────────────────────────────
def _login_payload(principal: Principal, extra: Optional[dict] = None) -> dict:
    data = {"status": "ok", "auth": _auth_state(principal)}
    if extra:
        data.update(extra)
    return data


def _auth_state(principal: Optional[Principal]) -> dict:
    mode = auth.auth_mode()
    state = {
        "mode": mode,
        "required": mode != "open",
        "signup_enabled": bool(config.settings.allow_signup) and mode == "users",
        "signup_code_required": bool(config.settings.signup_code),
        "authenticated": principal is not None,
        "user": principal.to_public() if principal else None,
        "password_min_length": config.settings.password_min_length,
        "has_users": auth.user_count() > 0,
    }
    return state


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    """Who am I? — always 200 so the SPA can decide what to render."""
    principal = webauth.optional_principal(request)
    return {"status": "ok", **_auth_state(principal)}


@app.post("/api/auth/login")
def auth_login(payload: dict[str, Any], request: Request, response: Response) -> dict:
    mode = auth.auth_mode()
    ip = webauth.client_ip(request)
    if mode == "open":
        return {"status": "ok", "auth": _auth_state(
            Principal(user_id="public", username="public", role="admin", mode="open"))}
    if mode == "legacy":
        key = str(payload.get("access_key") or payload.get("password") or "")
        if not _access_ok(key):
            auth.audit("login_failed", target="shared", ip=ip, ok=False,
                       detail="legacy access key")
            raise HTTPException(status_code=401, detail=webauth.ACCESS_KEY_REQUIRED)
        auth.audit("login", target="shared", ip=ip, detail="legacy access key")
        return {"status": "ok", "legacy": True,
                "auth": _auth_state(Principal(user_id="shared", username="shared",
                                              role="admin", mode="legacy"))}

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username နှင့် Password ထည့်ပါ")
    user, error = auth.authenticate(username, password, ip)
    if not user:
        auth.audit("login_failed", target=username, ip=ip, ok=False, detail=error)
        raise HTTPException(status_code=401, detail=error)
    session = auth.create_session(user["id"], ip, request.headers.get("user-agent", ""))
    webauth.set_session_cookie(response, request, session["token"], session["csrf_token"],
                               int(max(60.0, config.settings.session_ttl_hours * 3600)))
    principal = Principal(user_id=user["id"], username=user["username"],
                          role=user.get("role", "user"), mode="users",
                          session_token=session["token"], via_cookie=True,
                          must_change_password=bool(user.get("must_change_password")))
    auth.audit("login", principal=principal, target=user["username"], ip=ip)
    log.info("login: %s (%s)", user["username"], ip)
    return _login_payload(principal, {"csrf_token": session["csrf_token"],
                                      "expires_at": session["expires_at"],
                                      # for API clients that cannot keep cookies
                                      "token": session["token"]})


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    principal = webauth.optional_principal(request)
    if principal and principal.session_token:
        auth.revoke_token(principal.session_token)
        auth.audit("logout", principal=principal, ip=webauth.client_ip(request))
    webauth.clear_session_cookie(response)
    return {"status": "ok"}


@app.post("/api/auth/register")
def auth_register(payload: dict[str, Any], request: Request, response: Response) -> dict:
    """Self sign-up — off unless RECAP_ALLOW_SIGNUP=1.

    The very first account is always allowed (and becomes the admin) so a
    fresh install can be claimed from the browser instead of SSH.
    """
    mode = auth.auth_mode()
    ip = webauth.client_ip(request)
    first_account = auth.user_count() == 0 and mode != "legacy"
    if not first_account and not (config.settings.allow_signup and mode == "users"):
        raise HTTPException(status_code=403,
                            detail="အကောင့် အသစ်ဖွင့်ခြင်းကို ပိတ်ထားပါသည် — admin ထံ ဆက်သွယ်ပါ")
    if config.settings.signup_code and not first_account:
        if str(payload.get("invite_code", "")) != config.settings.signup_code:
            raise HTTPException(status_code=403, detail="Invite code မမှန်ကန်ပါ")
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    try:
        user = auth.create_user(username, password,
                                role="admin" if first_account else "user",
                                display_name=str(payload.get("display_name", "")).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = auth.create_session(user["id"], ip, request.headers.get("user-agent", ""))
    webauth.set_session_cookie(response, request, session["token"], session["csrf_token"],
                               int(max(60.0, config.settings.session_ttl_hours * 3600)))
    principal = Principal(user_id=user["id"], username=user["username"],
                          role=user.get("role", "user"), mode="users",
                          session_token=session["token"], via_cookie=True)
    auth.audit("register", principal=principal, target=user["username"], ip=ip,
               detail="first admin" if first_account else "self signup")
    log.info("account created: %s (%s)", user["username"],
             "admin" if first_account else "user")
    return _login_payload(principal, {"csrf_token": session["csrf_token"],
                                      "first_admin": first_account})


@app.post("/api/auth/password")
def auth_change_password(payload: dict[str, Any], request: Request, response: Response,
                         principal: Principal = Depends(guard)) -> dict:
    if principal.mode != "users":
        raise HTTPException(status_code=400,
                            detail="Account mode မဟုတ်သဖြင့် စကားဝှက် မပြောင်းနိုင်ပါ")
    try:
        auth.change_own_password(principal.user_id,
                                 str(payload.get("current_password", "")),
                                 str(payload.get("new_password", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.audit("password_change", principal=principal, ip=webauth.client_ip(request))
    webauth.clear_session_cookie(response)       # every device must sign in again
    return {"status": "ok", "message": "စကားဝှက် ပြောင်းပြီးပါပြီ — ပြန်လည် login ဝင်ပါ"}


@app.get("/api/auth/sessions")
def auth_sessions(principal: Principal = Depends(guard)) -> dict:
    if principal.mode != "users":
        return {"status": "ok", "sessions": []}
    return {"status": "ok", "sessions": auth.list_sessions(principal.user_id)}


@app.post("/api/auth/sessions/revoke")
def auth_revoke_sessions(request: Request, response: Response,
                         principal: Principal = Depends(guard)) -> dict:
    if principal.mode != "users":
        return {"status": "ok", "revoked": 0}
    revoked = auth.revoke_user_sessions(principal.user_id)
    auth.audit("sessions_revoked", principal=principal, detail=str(revoked),
               ip=webauth.client_ip(request))
    webauth.clear_session_cookie(response)
    return {"status": "ok", "revoked": revoked}


# ── admin: accounts & audit ──────────────────────────────────────────────
@app.get("/api/admin/users")
def admin_list_users(principal: Principal = Depends(admin_guard)) -> dict:
    if principal.mode != "users":
        return {"status": "ok", "users": [], "mode": principal.mode,
                "hint": "အကောင့်စနစ် မဖွင့်ရသေးပါ — 'useradmin create' ဖြင့် စတင်ပါ"}
    users = auth.list_users()
    for user in users:
        user["active_jobs"] = store.count_active(user["id"])
        user["jobs_today"] = auth.jobs_today(user["id"])
        user["disk_used"] = (cached_dir_size(config.user_workspace_dir(user["id"]), blocking=False)
                             + cached_dir_size(config.user_output_dir(user["id"]), blocking=False))
    return {"status": "ok", "users": users, "mode": principal.mode,
            "defaults": {
                "max_concurrent_jobs": config.settings.user_max_concurrent_jobs,
                "daily_job_limit": config.settings.user_daily_jobs,
                "quota_bytes": config.settings.user_quota_bytes,
            }}


@app.post("/api/admin/users")
def admin_create_user(payload: dict[str, Any], request: Request,
                      principal: Principal = Depends(admin_guard)) -> dict:
    if principal.mode != "users":
        raise HTTPException(status_code=400,
                            detail="အကောင့်စနစ် မဖွင့်ရသေးပါ (CLI: python -m recapstudio.useradmin create)")
    try:
        user = auth.create_user(
            str(payload.get("username", "")).strip(),
            str(payload.get("password", "")),
            role="admin" if payload.get("admin") else "user",
            display_name=str(payload.get("display_name", "")).strip(),
            must_change_password=bool(payload.get("must_change_password", True)),
            quota_bytes=int(payload.get("quota_bytes") or 0),
            max_concurrent_jobs=int(payload.get("max_concurrent_jobs") or 0),
            daily_job_limit=int(payload.get("daily_job_limit") or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.audit("user_create", principal=principal, target=user["username"],
               ip=webauth.client_ip(request), detail=user["role"])
    return {"status": "ok", "user": user}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: str, payload: dict[str, Any], request: Request,
                      principal: Principal = Depends(admin_guard)) -> dict:
    if principal.mode != "users":
        raise HTTPException(status_code=400, detail="အကောင့်စနစ် မဖွင့်ရသေးပါ")
    if not auth.get_user(user_id):
        raise HTTPException(status_code=404, detail="အကောင့် ရှာမတွေ့ပါ")
    try:
        if payload.get("password"):
            auth.set_password(user_id, str(payload["password"]),
                              must_change=bool(payload.get("must_change_password", True)))
        if payload.get("status"):
            auth.set_status(user_id, str(payload["status"]))
        if payload.get("role"):
            auth.set_role(user_id, str(payload["role"]))
        if any(k in payload for k in ("quota_bytes", "max_concurrent_jobs", "daily_job_limit")):
            auth.set_limits(
                user_id,
                quota_bytes=int(payload["quota_bytes"]) if "quota_bytes" in payload else None,
                max_concurrent_jobs=int(payload["max_concurrent_jobs"])
                if "max_concurrent_jobs" in payload else None,
                daily_job_limit=int(payload["daily_job_limit"])
                if "daily_job_limit" in payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.audit("user_update", principal=principal, target=user_id,
               ip=webauth.client_ip(request),
               detail=",".join(k for k in payload if k != "password"))
    return {"status": "ok", "user": auth.get_user(user_id)}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, request: Request,
                      principal: Principal = Depends(admin_guard)) -> dict:
    if principal.mode != "users":
        raise HTTPException(status_code=400, detail="အကောင့်စနစ် မဖွင့်ရသေးပါ")
    if user_id == principal.user_id:
        raise HTTPException(status_code=400, detail="ကိုယ့်အကောင့်ကိုယ် မဖျက်နိုင်ပါ")
    try:
        auth.delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.audit("user_delete", principal=principal, target=user_id,
               ip=webauth.client_ip(request))
    return {"status": "ok"}


@app.get("/api/admin/audit")
def admin_audit(limit: int = Query(default=100, ge=1, le=1000),
                principal: Principal = Depends(admin_guard)) -> dict:
    return {"status": "ok", "entries": auth.recent_audit(limit),
            "security": auth.security_report()}


@app.get("/api/system")
def system_info(request: Request,
                x_access_key: Optional[str] = Header(default=None),
                fast: bool = Query(default=True)) -> dict:
    """Capabilities + defaults for the SPA.

    Deliberately reachable *without* the access key: the UI must be able to
    boot (and offer a place to type the access key) even before the secret is
    known. Anything sensitive is masked or omitted in that case.

    ``fast=1`` (default) returns the cached data-directory size instead of
    walking a potentially huge tree — that walk was what made the top bar sit
    at "Engine စစ်ဆေးနေသည်…" on a busy server.
    """
    principal = webauth.optional_principal(request)
    access_ok = principal is not None
    try:
        fonts_info = fonts.font_status()
    except Exception as exc:  # never let diagnostics break the page
        log.warning("font status failed: %s", exc)
        fonts_info = {"family": "", "regular": None, "bold": None, "ok": False,
                      "fonts_dir": "", "bundled_ok": False, "error": str(exc)[:200]}
    try:
        if principal and principal.mode == "users" and not principal.is_admin:
            disk_used = (cached_dir_size(config.user_workspace_dir(principal.scope),
                                         blocking=not fast)
                         + cached_dir_size(config.user_output_dir(principal.scope),
                                           blocking=not fast))
        else:
            disk_used = (cached_dir_size(config.WORKSPACE_DIR, blocking=not fast)
                         + cached_dir_size(config.OUTPUT_DIR, blocking=not fast))
    except Exception:
        disk_used = 0
    ring = _keys_payload(principal) if principal else key_ring.describe()
    payload = {
        "version": config.settings.app_version,
        "ffmpeg": {"available": ffmpeg_available(), "version": ffmpeg_version(),
                   "ffprobe": ffprobe_available()},
        "fonts": fonts_info,
        "disk": {
            "free": free_disk_bytes(),
            "free_human": human_bytes(free_disk_bytes()),
            "used_by_app": disk_used,
            "used_by_app_human": human_bytes(disk_used),
            "data_dir": str(config.DATA_DIR) if access_ok else "",
        },
        "limits": {
            "max_upload_bytes": config.settings.max_upload_bytes,
            "upload_chunk_bytes": config.settings.upload_chunk_bytes,
            "max_concurrent_jobs": config.settings.max_concurrent_jobs,
            "max_chunk_seconds": config.settings.max_chunk_seconds,
            "max_api_keys": config.settings.max_api_keys,
            "max_narration_gap": config.settings.max_narration_gap,
        },
        "jobs_runtime": job_pool_state(),
        "modes": ["auto", "movie", "experiment", "craft", "news"],
        "fill_modes": {"continuous": "ဗီဒီယို အစအဆုံး စကားပြောမည် (Recap)",
                       "dialogue": "စကားပြောခန်း ရှိသည့် အချိန်များသာ"},
        "models": list(config.settings.models),
        "default_model": config.settings.default_model,
        "voices": VOICE_CATALOG,
        "aspects": ["9:16", "1:1", "16:9", "original"],
        "qualities": ["fast", "balanced", "quality"],
        "reframes": ["Smart Blur Background", "Center Crop", "Original (no reframe)"],
        "bg_styles": ["Solid Box", "Semi Transparent Box", "Outline Only"],
        "demo_mode": config.settings.demo_mode,
        "has_api_key": bool(ring["any_key"]),
        "access_required": bool(config.settings.access_password),
        "access_ok": access_ok,
        "auth": _auth_state(principal),
        "api_keys": ring if access_ok else {"any_key": ring["any_key"], "keys": [],
                                            "max_keys": ring["max_keys"],
                                            "active_slot": 0,
                                            "failover": ring.get("failover", True)},
    }
    if principal and principal.is_admin:
        payload["security"] = auth.security_report()
    return payload


def _has_api_key() -> bool:
    return bool(key_ring.has_key())


def load_api_key() -> str:
    """Active Gemini key (kept for backwards compatibility)."""
    return key_ring.active_key()[0]


@app.get("/api/config")
def get_config(request: Request) -> dict:
    """Settings payload — also readable before sign-in (masked)."""
    principal = webauth.optional_principal(request)
    access_ok = principal is not None
    saved = read_json(config.CONFIG_FILE, {}) or {}
    ring = _keys_payload(principal) if principal else key_ring.describe()
    data = {
        "gemini_api_key_set": bool(ring["any_key"]),
        "model": saved.get("model", config.settings.default_model),
        "access_required": bool(config.settings.access_password),
        "access_ok": access_ok,
        "auth": _auth_state(principal),
    }
    if access_ok:
        data.update({
            "gemini_api_key_masked": ring.get("masked", ""),
            "api_keys": ring,
            "max_api_keys": ring["max_keys"],
            "defaults": saved.get("defaults", {}),
        })
    else:
        data["api_keys"] = {"keys": [], "active_slot": 0,
                            "max_keys": ring["max_keys"],
                            "failover": ring.get("failover", True)}
    return data


@app.post("/api/config")
def save_config(payload: dict[str, Any],
                principal: Principal = Depends(guard)) -> dict:
    saved = read_json(config.CONFIG_FILE, {}) or {}
    changed_keys: list[dict] = []
    # new multi-key format: {"api_keys": [{"slot": 1, "key": "AIza…"}, …]}
    if isinstance(payload.get("api_keys"), list):
        changed_keys = payload["api_keys"]
    if "gemini_api_key" in payload and str(payload["gemini_api_key"]).strip():
        changed_keys.append({"slot": 1, "key": str(payload["gemini_api_key"]).strip()})
    if changed_keys:
        _save_keys_for(principal, changed_keys)
    # server-wide defaults stay admin-only once accounts exist
    if principal.mode == "users" and not principal.is_admin:
        if "model" in payload or "defaults" in payload:
            raise HTTPException(status_code=403,
                                detail="Server default settings ကို admin သာ ပြောင်းနိုင်ပါသည်")
    if "model" in payload:
        saved["model"] = str(payload["model"]).strip()
    if "defaults" in payload and isinstance(payload["defaults"], dict):
        saved["defaults"] = payload["defaults"]
    from recapstudio.util import atomic_write_json
    saved.pop("gemini_api_key", None)      # the ring owns the keys now
    saved.pop("gemini_api_keys", None)
    saved.pop("active_key_index", None)
    atomic_write_json(config.CONFIG_FILE, saved)
    ring = _keys_payload(principal)
    return {"status": "ok", "gemini_api_key_set": bool(ring["any_key"]),
            "api_keys": ring}


# ── API key ring (Key #1 … #3) ───────────────────────────────────────────
def _keys_payload(principal: Optional[Principal]) -> dict:
    """Server ring for shared installs, the caller's own keys otherwise.

    In multi-user mode one account must never see (or spend) another
    account's Gemini quota, so personal keys are stored encrypted per user
    and the server keys (from .env) are only offered as a read-only
    fallback.
    """
    ring = key_ring.describe()
    if principal is None or principal.mode != "users":
        return ring
    personal = auth.describe_user_keys(principal.user_id)
    server_keys = [k for k in ring["keys"] if k["set"]]
    return {
        "keys": personal["keys"],
        "any_key": personal["any_key"] or bool(server_keys),
        "max_keys": personal["max_keys"],
        "active_slot": next((k["slot"] for k in personal["keys"] if k["set"]), 0),
        "failover": ring.get("failover", True),
        "masked": next((k["masked"] for k in personal["keys"] if k["set"]), ""),
        "personal": True,
        "server_fallback": bool(server_keys),
        "server_keys": len(server_keys),
    }


def _save_keys_for(principal: Principal, entries: list[dict]) -> None:
    if principal.mode != "users":
        key_ring.update(entries)
        return
    for entry in entries or []:
        try:
            slot = int(entry.get("slot", 0))
        except (TypeError, ValueError):
            continue
        if slot < 1:
            continue
        auth.set_user_key(principal.user_id, slot, str(entry.get("key", "")).strip())
    auth.audit("api_keys_update", principal=principal,
               detail=f"{len(entries)} slot(s)")


@app.get("/api/keys")
def list_keys(principal: Principal = Depends(guard)) -> dict:
    return {"status": "ok", **_keys_payload(principal)}


@app.post("/api/keys")
def save_keys(payload: dict[str, Any], principal: Principal = Depends(guard)) -> dict:
    """Save slots and/or switch the active one.

    Body: ``{"keys": [{"slot": 2, "key": "AIza…"}], "active_slot": 2}``
    Sending ``key: ""`` clears a slot; ``active_slot`` alone just switches.
    """
    try:
        if isinstance(payload.get("keys"), list):
            _save_keys_for(principal, payload["keys"])
        if payload.get("active_slot") is not None and principal.mode != "users":
            key_ring.activate(int(payload["active_slot"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", **_keys_payload(principal)}


@app.post("/api/keys/test")
def test_keys(payload: dict[str, Any] | None = None,
              principal: Principal = Depends(guard)) -> dict:
    """Validate one key (``{"slot": 2}`` or ``{"key": "AIza…"}``) or all of them."""
    payload = payload or {}
    results: list[dict] = []
    if payload.get("key"):
        ok, message = validate_key(str(payload["key"]))
        results.append({"slot": int(payload.get("slot") or 0), "ok": ok, "message": message,
                        "masked": mask_key(str(payload["key"]))})
    elif principal.mode == "users":
        for index, key in enumerate(auth.get_user_keys(principal.user_id), start=1):
            ok, message = validate_key(key)
            results.append({"slot": index, "ok": ok, "message": message,
                            "masked": mask_key(key)})
        if not results:
            results.append({"slot": 1, "ok": False, "message": "Key မထည့်ရသေးပါ",
                            "masked": ""})
    else:
        wanted = payload.get("slots")
        for slot in key_ring.slots:
            if wanted and slot.index not in wanted:
                continue
            if not slot.present:
                results.append({"slot": slot.index, "ok": False, "message": "Key မထည့်ရသေးပါ",
                                "masked": ""})
                continue
            ok, message = validate_key(slot.key)
            if ok:
                key_ring.clear_cooldown(slot.index)
            results.append({"slot": slot.index, "ok": ok, "message": message,
                            "masked": slot.to_public()["masked"]})
    return {"status": "ok", "results": results, "api_keys": _keys_payload(principal)}


# ── uploads ──────────────────────────────────────────────────────────────
# Chunk handling does blocking disk I/O (an 8 MB write, and up to a multi-GB
# assembly). Running that on the event loop froze *every* other request -
# which is what made the whole site look crashed during a big upload.
@app.post("/api/upload/init")
async def upload_init(payload: dict[str, Any],
                      principal: Principal = Depends(guard)) -> dict:
    try:
        session = await run_in_threadpool(
            upload_manager.init,
            str(payload.get("filename", "video.mp4")),
            int(payload.get("size", 0)),
            str(payload.get("kind", "video")),
            True,
            _scope(principal),
        )
        return {"status": "ok", **session.to_dict()}
    except Exception as exc:
        raise _json_error(exc) from exc


@app.get("/api/upload/status")
async def upload_status(upload_id: str = Query(...),
                        principal: Principal = Depends(guard)) -> dict:
    """Resume support: which chunks does the server already have?"""
    try:
        session = await run_in_threadpool(upload_manager.session_state, upload_id,
                                          _scope(principal))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session ရှာမတွေ့ပါ")
    return {"status": "ok", **session}


@app.post("/api/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
    principal: Principal = Depends(guard),
) -> dict:
    try:
        session = await run_in_threadpool(upload_manager.save_chunk, upload_id, index,
                                          chunk.file, _scope(principal))
        await chunk.close()
        return {"status": "ok", **session.to_dict()}
    except PermissionError as exc:
        raise _json_error(exc, 403) from exc
    except KeyError as exc:
        raise _json_error(exc, 404) from exc
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload/complete")
async def upload_complete(payload: dict[str, Any],
                          principal: Principal = Depends(guard)) -> dict:
    try:
        return await run_in_threadpool(upload_manager.complete,
                                       str(payload.get("upload_id", "")),
                                       _scope(principal))
    except PermissionError as exc:
        raise _json_error(exc, 403) from exc
    except KeyError as exc:
        raise _json_error(exc, 404) from exc
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload")
async def upload_simple(video: UploadFile = File(...),
                        principal: Principal = Depends(guard)) -> dict:
    """Small-file convenience endpoint (kept for compatibility)."""
    try:
        ext = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
        if ext not in VIDEO_EXT:
            raise ValueError(f"'{ext}' ဗီဒီယိုဖိုင် အမျိုးအစား မဟုတ်ပါ")
        target = (config.user_workspace_dir(_scope(principal))
                  / f"input_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}")
        size = 0
        with open(target, "wb") as fh:
            while True:
                block = await video.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > config.settings.max_upload_bytes:
                    raise ValueError("ဖိုင် အရမ်းကြီးနေပါသည်")
                fh.write(block)
        await video.close()
        if size == 0:
            raise ValueError("ဖိုင် အလွတ် ဖြစ်နေပါသည်")
        info = get_video_info(target)
        return {
            "status": "ok", "video_path": config.rel(target), "size": size,
            "duration": round(info["duration"], 3), "width": info["width"],
            "height": info["height"], "has_audio": info["has_audio"],
            "preview_url": f"/api/asset?path={config.rel(target)}",
        }
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload-logo")
async def upload_logo(logo: UploadFile = File(...),
                      principal: Principal = Depends(guard)) -> dict:
    try:
        name = logo.filename or "logo.png"
        ext = Path(name).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif", ".tif", ".tiff"}:
            raise ValueError("Logo အတွက် ပုံဖိုင် (PNG/JPG/WEBP) သာ ပံ့ပိုးပါသည်")
        raw = (config.user_logo_dir(_scope(principal))
               / f"raw_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}")
        size = 0
        with open(raw, "wb") as fh:
            while True:
                block = await logo.read(512 * 1024)
                if not block:
                    break
                size += len(block)
                if size > 30 * 1024 * 1024:
                    raise ValueError("Logo ဖိုင် 30MB အထက်ကြီးလွန်းပါသည်")
                fh.write(block)
        await logo.close()
        if size == 0:
            raise ValueError("Logo ဖိုင် အလွတ် ဖြစ်နေပါသည်")
        assets = upload_manager.logo_assets(raw, owner=_scope(principal))
        safe_unlink(raw)
        return {"status": "ok", "filename": name, **assets}
    except Exception as exc:
        raise _json_error(exc) from exc


@app.get("/api/asset")
def serve_asset(path: str = Query(...),
                principal: Principal = Depends(guard)) -> FileResponse:
    """Workspace file server.

    ``FileResponse`` implements HTTP Range requests, which is what the in-page
    video preview needs to seek/scrub; adding a short-lived cache header keeps
    reloads snappy without holding stale renders forever.
    """
    target = _resolve_owned(path, principal)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    headers = {"Cache-Control": "private, max-age=600", "Accept-Ranges": "bytes"}
    return FileResponse(str(target), headers=headers)


#: yt-dlp attempt ladder — each entry is tried in order until one works.
#: YouTube keeps rotating its player/signature checks, and a plain call now
#: fails on many EC2 boxes ("Sign in to confirm you're not a bot",
#: "nsig extraction failed", HTTP 403 on fragments). The android/ios players
#: and an IPv4 lock fix the overwhelming majority of those failures.
YTDLP_ATTEMPTS: list[tuple[str, list[str]]] = [
    ("default", []),
    ("android player", ["--extractor-args", "youtube:player_client=android"]),
    ("ios player + IPv4", ["--extractor-args", "youtube:player_client=ios,web_safari",
                           "--force-ipv4"]),
    ("tv player + generic UA", ["--extractor-args", "youtube:player_client=tv",
                                "--user-agent",
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/126.0 Safari/537.36"]),
]


def normalise_media_url(url: str) -> str:
    """Clean a shared link so yt-dlp sees a single video.

    Handles the three shapes people actually paste: `youtu.be/<id>`,
    `/shorts/<id>` and a `watch?v=<id>` that still carries `&list=…`,
    `&t=…`, `?si=…` (share tracking) — the playlist/tracking params make
    yt-dlp download the wrong thing or refuse outright.
    """
    from urllib.parse import parse_qs, urlparse, urlunparse, urlencode

    url = (url or "").strip()
    try:
        u = urlparse(url)
    except ValueError:
        return url
    host = (u.netloc or "").lower().removeprefix("www.").removeprefix("m.")
    if host in ("youtu.be", "youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        vid = ""
        if host == "youtu.be":
            vid = u.path.strip("/").split("/")[0]
        elif u.path.startswith(("/shorts/", "/live/", "/embed/")):
            vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else ""
        else:
            vid = (parse_qs(u.query).get("v") or [""])[0]
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    # non-YouTube: only drop obvious tracking noise
    if u.query:
        keep = {k: v for k, v in parse_qs(u.query).items()
                if k.lower() not in {"si", "feature", "utm_source", "utm_medium", "fbclid"}}
        return urlunparse(u._replace(query=urlencode(keep, doseq=True)))
    return url


def _ytdlp_error_hint(blob: str) -> str:
    """Translate a yt-dlp failure into something the user can act on."""
    low = (blob or "").lower()
    if "sign in to confirm" in low or "not a bot" in low or "cookies" in low:
        return ("YouTube က bot စစ်ဆေးနေပါသည်။ ⚙️ server ပေါ်တွင် cookies ဖိုင် ထည့်ပါ — "
                "`.env` ထဲ `RECAP_YTDLP_COOKIES=/opt/recap-studio/data/cookies.txt` "
                "(browser extension 'Get cookies.txt' ဖြင့် ထုတ်ယူပါ) ပြီးလျှင် restart လုပ်ပါ။")
    if "age" in low and ("restrict" in low or "confirm" in low):
        return "အသက်အရွယ် ကန့်သတ်ထားသော ဗီဒီယို ဖြစ်ပါသည် — cookies ဖိုင် (login ထားသော) လိုအပ်ပါသည်။"
    if "private video" in low or "members-only" in low or "join this channel" in low:
        return "သီးသန့် (private / members-only) ဗီဒီယို ဖြစ်၍ ဒေါင်းလုဒ် မရနိုင်ပါ။"
    if "video unavailable" in low or "removed" in low or "terminated" in low:
        return "ဤဗီဒီယိုကို ဖျက်ထားပြီး (သို့) မရနိုင်တော့ပါ — link ကို ပြန်စစ်ပါ။"
    if "not available in your country" in low or "geo" in low:
        return ("ဤဒေသတွင် ပိတ်ထားသော ဗီဒီယို ဖြစ်ပါသည် — `RECAP_YTDLP_PROXY` ဖြင့် proxy "
                "သတ်မှတ်၍ ပြန်စမ်းနိုင်ပါသည်။")
    if "is live" in low or "live event" in low:
        return "တိုက်ရိုက်ထုတ်လွှင့်နေဆဲ ဗီဒီယိုကို မယူနိုင်ပါ — ပြီးဆုံးပြီးမှ ပြန်စမ်းပါ။"
    if "nsig" in low or "signature" in low or "player" in low:
        return ("yt-dlp အဟောင်း ဖြစ်နေပါသည်။ server ပေါ်တွင် "
                "`sudo /opt/recap-studio/.venv/bin/pip install -U yt-dlp` "
                "ပြီးလျှင် `sudo systemctl restart recap-studio` လုပ်ပါ။")
    if "403" in low or "forbidden" in low:
        return ("YouTube CDN က server ၏ IP ကို ပိတ်ထားပါသည် — ခဏနေ ပြန်စမ်းပါ "
                "(သို့) `RECAP_YTDLP_PROXY` သုံးပါ။")
    if "unsupported url" in low or "no video formats" in low:
        return "ဤ link မှ ဗီဒီယို ရယူ၍ မရပါ — တိုက်ရိုက် ဖိုင်တင်ခြင်းကို သုံးပါ။"
    return ""


@app.post("/api/download-url")
def import_from_url(payload: dict[str, Any],
                    principal: Principal = Depends(guard)) -> dict:
    """yt-dlp import with an attempt ladder and actionable error messages.

    v4.3.1 (#1): a single plain yt-dlp call fails on most EC2 boxes today.
    The link is normalised first (share/playlist params stripped), then up to
    four player back-ends are tried, and whatever still fails is reported in
    Burmese with the exact fix.
    """
    import subprocess
    import shutil as _shutil
    import sys as _sys

    raw_url = str(payload.get("url", "")).strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Video Link ထည့်ပါ")
    if not raw_url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link ပုံစံ မမှန်ကန်ပါ (https://... ဖြစ်ရပါမည်)")
    url = normalise_media_url(raw_url)

    base_cmd = ["yt-dlp"] if _shutil.which("yt-dlp") else [_sys.executable, "-m", "yt_dlp"]
    try:
        probe = subprocess.run(base_cmd + ["--version"], capture_output=True,
                               text=True, timeout=60)
        ytdlp_version = (probe.stdout or "").strip() or "?"
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail="yt-dlp မထည့်သွင်းထားပါ (pip install -U yt-dlp)") from exc

    work_dir = config.user_workspace_dir(_scope(principal))
    stamp = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    out_tmpl = str(work_dir / f"ytdl_{stamp}.%(ext)s")
    common = [
        "--no-playlist", "--no-warnings", "--newline", "--ignore-config",
        "--restrict-filenames", "--merge-output-format", "mp4",
        "--retries", "10", "--fragment-retries", "20", "--concurrent-fragments", "4",
        "--socket-timeout", "30", "--geo-bypass",
        "-f", ("bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]"
               "/bv*[height<=1080]+ba/b[height<=1080]/b"),
        "-o", out_tmpl, "--print", "after_move:filepath",
    ]
    if config.settings.ytdlp_cookies_file and Path(config.settings.ytdlp_cookies_file).exists():
        common += ["--cookies", config.settings.ytdlp_cookies_file]
    if config.settings.ytdlp_proxy:
        common += ["--proxy", config.settings.ytdlp_proxy]

    attempts_log: list[str] = []
    downloaded: list[Path] = []
    last_blob = ""
    for label, extra in YTDLP_ATTEMPTS:
        try:
            proc = subprocess.run(base_cmd + common + extra + [url],
                                  capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504,
                                detail="Download အချိန် ကြာလွန်းနေပါသည် (30 မိနစ်)") from exc
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        found = [Path(ln) for ln in lines if ln.endswith((".mp4", ".mkv", ".webm", ".m4a"))]
        if not found:
            found = sorted(work_dir.glob(f"ytdl_{stamp}.*"), key=lambda p: p.stat().st_mtime)
        found = [f for f in found if f.exists() and f.stat().st_size > 10240]
        if found:
            downloaded = found
            log.info("yt-dlp %s: '%s' ok via %s", ytdlp_version, url, label)
            break
        last_blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        attempts_log.append(f"[{label}] " + (last_blob.splitlines() or ["(no output)"])[-1][:200])
        for leftover in work_dir.glob(f"ytdl_{stamp}.*"):
            leftover.unlink(missing_ok=True)

    if not downloaded:
        hint = _ytdlp_error_hint(last_blob)
        detail = ("Download မအောင်မြင်ပါ (yt-dlp " + ytdlp_version + " — နည်းလမ်း "
                  + str(len(YTDLP_ATTEMPTS)) + " မျိုး စမ်းပြီးပါပြီ)။")
        if hint:
            detail += "\n👉 " + hint
        detail += "\n\n" + "\n".join(attempts_log[-3:])
        raise HTTPException(status_code=502, detail=detail)

    path = downloaded[-1]
    final = work_dir / f"import_{int(time.time())}{path.suffix}"
    path.replace(final)
    for leftover in work_dir.glob(f"ytdl_{stamp}.*"):
        leftover.unlink(missing_ok=True)
    info = get_video_info(final)
    return {
        "status": "ok", "video_path": config.rel(final),
        "duration": round(info["duration"], 3), "width": info["width"],
        "height": info["height"], "has_audio": info["has_audio"],
        "size": final.stat().st_size,
        "preview_url": f"/api/asset?path={config.rel(final)}",
    }


# ── jobs ─────────────────────────────────────────────────────────────────
@app.post("/api/tasks")
def start_task(payload: dict[str, Any], principal: Principal = Depends(guard)) -> dict:
    if not payload.get("input_video"):
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ")
    video_path = _resolve_owned(str(payload["input_video"]), principal)
    if not video_path.exists():
        raise HTTPException(status_code=400,
                            detail="တင်ထားသော ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ — ပြန်တင်ပေးပါ")
    if payload.get("logo_path"):
        _resolve_owned(str(payload["logo_path"]), principal)
    _enforce_job_quota(principal)
    # personal key (multi-user) → payload key → server ring
    personal_key = _effective_api_key(principal, payload)
    if personal_key:
        payload["api_key"] = personal_key
    if not payload.get("api_key") and not key_ring.has_key() and not config.settings.demo_mode:
        raise HTTPException(status_code=400,
                            detail="Gemini API Key မထည့်ရသေးပါ — ⚙️ Settings → API Keys "
                                   "တွင် Key #1 ထည့်ပါ (Key #2/#3 က quota failover အတွက်)")
    job = store.create(kind="recap", request=payload, user_id=_scope(principal),
                       username=principal.username)
    _register_job(job, principal)
    store.update(job.id, input_video=payload.get("input_video", ""))
    store.log(job.id, f"queued (mode={payload.get('mode')}, lang={payload.get('lang')}, "
                      f"voice={payload.get('voice')}, fill={payload.get('fill_mode')}, "
                      f"key_slot={key_ring.active_index + 1 if key_ring.has_key() else 0})")
    if job_pool_state()["busy"]:
        store.log(job.id, "⏳ အခြား job များ run နေပါသည် — အလှည့် စောင့်ပါမည်")
    submit_job(pipeline.run_recap, job.id, payload)
    return {"status": "ok", "task_id": job.id, "queue": job_pool_state()}


@app.get("/api/tasks")
def list_tasks(limit: int = Query(default=30, ge=1, le=200),
               all_users: bool = Query(default=False, alias="all"),
               principal: Principal = Depends(guard)) -> dict:
    scope = None if (principal.is_admin and all_users) else _owner_filter(principal)
    jobs = [job.to_dict(include_logs=False) for job in store.list(limit, user_id=scope)]
    return {"status": "ok", "tasks": jobs, "runtime": job_pool_state(),
            "scope": "all" if scope is None else scope}


@app.get("/api/tasks/active")
def active_task(principal: Principal = Depends(guard)) -> dict:
    """Newest running/queued job — lets the UI re-attach after a page reload."""
    for job in store.list(50, user_id=_owner_filter(principal)):
        if job.status in {"running", "queued"}:
            return {"status": "ok", "task": job.to_dict()}
    return {"status": "ok", "task": None}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str, principal: Principal = Depends(guard)) -> dict:
    job = _owned_job(task_id, principal)
    data = job.to_dict()
    data["runtime"] = job_pool_state()
    return data


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, principal: Principal = Depends(guard)) -> dict:
    _owned_job(task_id, principal)
    if not store.request_cancel(task_id):
        raise HTTPException(status_code=400,
                            detail="ရပ်တန့်၍ မရပါ (ပြီးဆုံးသွားပြီ ဖြစ်နိုင်ပါသည်) — "
                                   "Jobs tab မှ refresh လုပ်ကြည့်ပါ")
    return {"status": "ok", "killed_processes": process_registry.count()}


@app.post("/api/tasks/{task_id}/rerender")
def rerender_task(task_id: str, payload: dict[str, Any],
                  principal: Principal = Depends(guard)) -> dict:
    _owned_job(task_id, principal)
    _enforce_job_quota(principal)
    personal_key = _effective_api_key(principal, payload)
    if personal_key:
        payload["api_key"] = personal_key
    auth.audit("job_rerender", principal=principal, target=task_id)
    submit_job(pipeline.run_rerender, task_id, payload)
    return {"status": "ok", "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, principal: Principal = Depends(guard)) -> dict:
    job = _owned_job(task_id, principal)
    for rel in (job.output_video,):
        if rel:
            try:
                safe_unlink(config.resolve(rel))
            except Exception:
                pass
    store.delete(task_id)
    auth.forget_job(task_id)
    auth.audit("job_delete", principal=principal, target=task_id)
    return {"status": "ok"}


@app.get("/api/download/{filename}")
def download_file(filename: str, principal: Principal = Depends(guard)) -> FileResponse:
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="ဖိုင်အမည် မမှန်ကန်ပါ")
    target = _download_target(safe_name, principal)
    if target is None:
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    media_type = "video/mp4"
    if target.suffix == ".mp3":
        media_type = "audio/mpeg"
    elif target.suffix in {".srt", ".ass"}:
        media_type = "text/plain; charset=utf-8"
    return FileResponse(str(target), media_type=media_type, filename=safe_name)


# ── tools ────────────────────────────────────────────────────────────────
@app.post("/api/thumbnail")
def thumbnail(payload: dict[str, Any],
              principal: Principal = Depends(guard)) -> FileResponse:
    raw_path = str(payload.get("video_path", ""))
    if not raw_path:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်ရွေးပါ")
    video_path = str(_resolve_owned(raw_path, principal))
    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")
    out_path = (config.user_output_dir(_scope(principal))
                / f"thumb_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg")
    try:
        pipeline.generate_thumbnail(
            video_path=video_path,
            timestamp=float(payload.get("timestamp", 2.0)),
            hook1=str(payload.get("hook_line1", "")) or "စိတ်ဝင်စားဖွယ်ရာ",
            hook2=str(payload.get("hook_line2", "")) or "ဇာတ်ကွက်များ",
            output_path=str(out_path),
            style=str(payload.get("style", "bold")),
        )
    except Exception as exc:
        raise _json_error(exc) from exc
    return FileResponse(str(out_path), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/thumb-sources")
def thumb_sources(principal: Principal = Depends(guard)) -> dict:
    """Finished Studio videos the thumbnail tab can work from (#10).

    The tab no longer asks for an upload: everything it needs is already on
    disk, so it lists the *completed* recaps of the caller (newest first) and
    reuses their hook lines as the default caption.
    """
    items: list[dict[str, Any]] = []
    for job in store.list(40, user_id=_owner_filter(principal)):
        if job.status != "completed" or not job.output_video:
            continue
        path = Path(job.output_video)
        if not path.is_absolute():
            path = config.DATA_DIR / job.output_video
        if not path.exists():
            continue
        items.append({
            "task_id": job.id,
            "path": config.rel(path),
            "name": path.name,
            "kind": job.kind,
            "duration": job.duration,
            "created_at": job.created_at,
            "hook_line1": job.hook_line1,
            "hook_line2": job.hook_line2,
            "preview_url": job.preview_url or f"/api/asset?path={config.rel(path)}",
        })
    return {"status": "ok", "sources": items,
            "ai_ready": thumbs.ai_available(key_ring=key_ring),
            "aspects": list(thumbs.ASPECT_SIZES.keys()),
            "styles": [{"id": k, "label": v["label"]} for k, v in thumbs.STYLES.items()]}


@app.post("/api/thumbnails")
def thumbnails(payload: dict[str, Any],
               principal: Principal = Depends(guard)) -> dict:
    """nano-banana viral thumbnails from a finished Studio video (#10)."""
    raw_path = str(payload.get("video_path", "") or "")
    task_id = str(payload.get("task_id", "") or "")
    if not raw_path and task_id:
        job = _owned_job(task_id, principal)
        raw_path = job.output_video or ""
        if not payload.get("hook_line1"):
            payload["hook_line1"] = job.hook_line1
        if not payload.get("hook_line2"):
            payload["hook_line2"] = job.hook_line2
    if not raw_path:
        raise HTTPException(status_code=400, detail="ပြီးသွားသော ဗီဒီယို တစ်ခု ရွေးပါ")
    video_path = _resolve_owned(raw_path, principal)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")
    try:
        variants = thumbs.generate_variants(
            video_path=str(video_path),
            out_dir=config.user_output_dir(_scope(principal)),
            hook1=str(payload.get("hook_line1", "")).strip() or "မကြည့်ရင် နောင်တရမယ်",
            hook2=str(payload.get("hook_line2", "")).strip() or "အပြီးထိ ကြည့်ပါ",
            count=int(payload.get("count", 3) or 3),
            aspect=str(payload.get("aspect", "16:9") or "16:9"),
            use_ai=bool(payload.get("use_ai", True)),
            api_key=_effective_api_key(principal, payload),
            key_ring=key_ring,
            badge=str(payload.get("badge", "") or ""),
        )
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", "variants": variants,
            "ai_used": any(v["ai"] for v in variants),
            "model": thumbs.NANO_BANANA_MODELS[0]}


@app.post("/api/estimate-parts")
def estimate_parts(payload: dict[str, Any],
                   principal: Principal = Depends(guard)) -> dict:
    import math
    duration = float(payload.get("duration", 0) or 0)
    slice_sec = max(5, int(payload.get("slice_sec", 60) or 60))
    if duration <= 0:
        return {"total_parts": 0, "slice_sec": slice_sec, "duration": 0}
    return {"total_parts": max(1, math.ceil(duration / slice_sec)),
            "slice_sec": slice_sec, "duration": duration}


@app.post("/api/split-video")
def split_video(payload: dict[str, Any],
                principal: Principal = Depends(guard)) -> dict:
    """Shorts splitter.

    ``async: true`` (what the UI sends) returns a task id immediately and the
    work runs on the job pool with a live progress bar + working cancel — a
    two hour video used to keep this HTTP request open for minutes, so the
    browser/proxy gave up and the page looked frozen.
    """
    raw_path = str(payload.get("video_path", ""))
    if not raw_path:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်ရွေးပါ")
    video_path = _resolve_owned(raw_path, principal)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")

    if payload.get("async"):
        _enforce_job_quota(principal)
        job = store.create(kind="split", request=payload, user_id=_scope(principal),
                           username=principal.username)
        _register_job(job, principal)
        store.update(job.id, input_video=config.rel(video_path))
        store.log(job.id, f"split queued (slice={payload.get('slice_sec')}s, "
                          f"aspect={payload.get('aspect')})")
        submit_job(pipeline.run_split, job.id, payload)
        return {"status": "queued", "task_id": job.id, "async": True}

    try:
        parts = pipeline.split_video(
            video_path=str(video_path),
            slice_sec=int(payload.get("slice_sec", 60)),
            aspect=str(payload.get("aspect", "9:16")),
            out_dir=config.user_output_dir(_scope(principal)),
        )
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", "parts": parts, "total_parts": len(parts)}


# ── legacy aliases (older front-ends / bookmarks keep working) ───────────
@app.post("/api/start-task", include_in_schema=False)
def legacy_start(payload: dict[str, Any],
                 principal: Principal = Depends(guard)) -> dict:
    return start_task(payload, principal)


@app.get("/api/task-status/{task_id}", include_in_schema=False)
def legacy_status(task_id: str, principal: Principal = Depends(guard)) -> dict:
    return task_status(task_id, principal)


@app.post("/api/rerender-task/{task_id}", include_in_schema=False)
def legacy_rerender(task_id: str, payload: dict[str, Any],
                    principal: Principal = Depends(guard)) -> dict:
    return rerender_task(task_id, payload, principal)


@app.post("/api/generate-thumbnail", include_in_schema=False)
def legacy_thumbnail(payload: dict[str, Any], principal: Principal = Depends(guard)):
    return thumbnail(payload, principal)


# ── housekeeping ─────────────────────────────────────────────────────────
def _janitor_loop() -> None:
    while True:
        try:
            time.sleep(max(60, config.settings.janitor_interval_seconds))
            removed = prune_old_files(config.WORKSPACE_DIR, config.settings.workspace_ttl_hours,
                                      keep_names={"cache", "tasks", "logos", "uploads",
                                                  "incoming", "tmp", "users"})
            # per-account upload sandboxes expire on the same schedule
            for user_dir in config.USERS_DIR.glob("*"):
                if user_dir.is_dir():
                    removed += prune_old_files(user_dir, config.settings.workspace_ttl_hours,
                                               keep_names={"logos"})
            removed += prune_old_files(config.CACHE_DIR, config.settings.workspace_ttl_hours * 2)
            removed += prune_old_files(config.TMP_DIR, 6)
            removed += upload_manager.cleanup_stale()
            # keep outputs longer than scratch files
            live_outputs: set[str] = set()
            for job in store.list(200):
                if job.output_video:
                    live_outputs.add(Path(job.output_video).name)
                for url_key in ("srt_url", "ass_url", "audio_url"):
                    url = getattr(job, url_key, "")
                    if isinstance(url, str) and url:
                        live_outputs.add(Path(url).name)
            for entry in config.OUTPUT_DIR.rglob("*"):
                if entry.name in live_outputs or entry.is_dir():
                    continue
                try:
                    if entry.is_file() and (time.time() - entry.stat().st_mtime) > config.settings.output_ttl_hours * 3600:
                        entry.unlink()
                        removed += 1
                except Exception:
                    continue
            if removed:
                log.info("janitor removed %d stale files (free disk %s)",
                         removed, human_bytes(free_disk_bytes()))
        except Exception as exc:  # never let the janitor die silently
            log.warning("janitor error: %s", exc)


@app.on_event("startup")
def _startup() -> None:
    ensure_dirs()
    log.info("Recap Studio %s starting • data dir=%s • free disk=%s",
             config.settings.app_version, config.DATA_DIR, human_bytes(free_disk_bytes()))
    # ── accounts / sessions / audit DB (Phase 2) ──────────────────────
    try:
        version = db.init()
        result = auth.bootstrap()
        mode = auth.auth_mode()
        log.info("Auth: mode=%s • accounts=%d • db=%s (schema v%d) • secrets=%s",
                 mode, auth.user_count(), config.DB_PATH, version,
                 _crypto_backend())
        for warning in result.warnings:
            log.warning("%s", warning)
    except Exception as exc:  # the studio must still start without the DB
        log.error("auth/database init failed: %s — falling back to %s mode",
                  exc, "legacy" if config.settings.access_password else "open")
    if not ffmpeg_available() or not ffprobe_available():
        log.error("ffmpeg/ffprobe not found on PATH - rendering will fail. "
                  "Install ffmpeg (see Dockerfile / packages.txt).")
    status = fonts.font_status()
    if not status["ok"]:
        log.error("No Myanmar font available - subtitles may render as boxes")
    ring = key_ring.describe()
    if ring["any_key"]:
        log.info("Gemini keys: %d slot(s) set, active #%s, failover=%s",
                 sum(1 for k in ring["keys"] if k["set"]), ring["active_slot"], ring["failover"])
    elif not config.settings.demo_mode:
        log.warning("No Gemini API key configured yet - open ⚙️ Settings in the UI "
                    "(or set GEMINI_API_KEY in .env)")
    if config.settings.demo_mode:
        log.warning("RECAP_DEMO_MODE=1 — AI timeline is synthetic, do not use in production")
    if config.settings.fake_tts:
        log.warning("RECAP_FAKE_TTS=1 — narration is a beep track, do not use in production")
    log.info("Job pool: %d worker(s) • max narration gap %.1fs • ffmpeg stall timeout %ds",
             _JOB_WORKERS, config.settings.max_narration_gap,
             config.settings.ffmpeg_stall_seconds)
    threading.Thread(target=_janitor_loop, daemon=True, name="janitor").start()


@app.on_event("shutdown")
def _shutdown() -> None:
    """Stop encoders cleanly so a restart never leaves zombie ffmpeg jobs."""
    try:
        for job in store.list(50):
            if job.status in {"running", "queued"}:
                process_registry.kill_owner(job.id)
    except Exception:
        pass
    job_pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False,
                proxy_headers=True, forwarded_allow_ips="*")
