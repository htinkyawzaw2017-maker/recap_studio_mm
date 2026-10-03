"""Recap Studio MM Pro — FastAPI application (v4.1).

Route map
---------
GET  /                          → SPA shell (static/index.html)
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
                     Query, UploadFile)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from recapstudio import config, fonts
from recapstudio.config import ensure_dirs
from recapstudio.jobs import JobStore
from recapstudio.keys import key_ring, validate_key
from recapstudio.media import (ffmpeg_available, ffmpeg_version, ffprobe_available,
                               get_video_info, process_registry)
from recapstudio.pipeline import RecapPipeline
from recapstudio.tts import VOICE_CATALOG
from recapstudio.uploads import upload_manager
from recapstudio.util import (cached_dir_size, free_disk_bytes, get_logger, human_bytes,
                              prune_old_files, read_json, safe_unlink, setup_logging)

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
    raise HTTPException(status_code=401,
                        detail="Access Key မှန်ကန်မှု မရှိပါ — ⚙️ Settings → Server Access Key "
                               "တွင် server ၏ RECAP_ACCESS_PASSWORD ကို ထည့်ပါ")


def guard(x_access_key: Optional[str] = Header(default=None)) -> None:
    _check_access(x_access_key)


def _json_error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


# ── static SPA ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_ui() -> HTMLResponse:
    index = config.STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Recap Studio</h1><p>static/index.html missing</p>", status_code=500)
    return HTMLResponse(index.read_text(encoding="utf-8"))


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


@app.get("/api/system")
def system_info(x_access_key: Optional[str] = Header(default=None),
                fast: bool = Query(default=True)) -> dict:
    """Capabilities + defaults for the SPA.

    Deliberately reachable *without* the access key: the UI must be able to
    boot (and offer a place to type the access key) even before the secret is
    known. Anything sensitive is masked or omitted in that case.

    ``fast=1`` (default) returns the cached data-directory size instead of
    walking a potentially huge tree — that walk was what made the top bar sit
    at "Engine စစ်ဆေးနေသည်…" on a busy server.
    """
    access_ok = _access_ok(x_access_key)
    try:
        fonts_info = fonts.font_status()
    except Exception as exc:  # never let diagnostics break the page
        log.warning("font status failed: %s", exc)
        fonts_info = {"family": "", "regular": None, "bold": None, "ok": False,
                      "fonts_dir": "", "bundled_ok": False, "error": str(exc)[:200]}
    try:
        disk_used = (cached_dir_size(config.WORKSPACE_DIR, blocking=not fast)
                     + cached_dir_size(config.OUTPUT_DIR, blocking=not fast))
    except Exception:
        disk_used = 0
    ring = key_ring.describe()
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
        "api_keys": ring if access_ok else {"any_key": ring["any_key"], "keys": [],
                                            "max_keys": ring["max_keys"],
                                            "active_slot": 0,
                                            "failover": ring["failover"]},
    }
    return payload


def _has_api_key() -> bool:
    return bool(key_ring.has_key())


def load_api_key() -> str:
    """Active Gemini key (kept for backwards compatibility)."""
    return key_ring.active_key()[0]


@app.get("/api/config")
def get_config(x_access_key: Optional[str] = Header(default=None)) -> dict:
    """Settings payload — also readable before the access key is entered."""
    access_ok = _access_ok(x_access_key)
    saved = read_json(config.CONFIG_FILE, {}) or {}
    ring = key_ring.describe()
    data = {
        "gemini_api_key_set": bool(ring["any_key"]),
        "model": saved.get("model", config.settings.default_model),
        "access_required": bool(config.settings.access_password),
        "access_ok": access_ok,
    }
    if access_ok:
        data.update({
            "gemini_api_key_masked": ring["masked"],
            "api_keys": ring,
            "max_api_keys": ring["max_keys"],
            "defaults": saved.get("defaults", {}),
        })
    else:
        data["api_keys"] = {"keys": [], "active_slot": 0,
                            "max_keys": ring["max_keys"], "failover": ring["failover"]}
    return data


@app.post("/api/config")
def save_config(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    saved = read_json(config.CONFIG_FILE, {}) or {}
    changed_keys: list[dict] = []
    # new multi-key format: {"api_keys": [{"slot": 1, "key": "AIza…"}, …]}
    if isinstance(payload.get("api_keys"), list):
        changed_keys = payload["api_keys"]
    if "gemini_api_key" in payload and str(payload["gemini_api_key"]).strip():
        changed_keys.append({"slot": 1, "key": str(payload["gemini_api_key"]).strip()})
    if changed_keys:
        key_ring.update(changed_keys)
    if "model" in payload:
        saved["model"] = str(payload["model"]).strip()
    if "defaults" in payload and isinstance(payload["defaults"], dict):
        saved["defaults"] = payload["defaults"]
    from recapstudio.util import atomic_write_json
    saved.pop("gemini_api_key", None)      # the ring owns the keys now
    saved.pop("gemini_api_keys", None)
    saved.pop("active_key_index", None)
    atomic_write_json(config.CONFIG_FILE, saved)
    return {"status": "ok", "gemini_api_key_set": bool(key_ring.has_key()),
            "api_keys": key_ring.describe()}


# ── API key ring (Key #1 … #3) ───────────────────────────────────────────
@app.get("/api/keys")
def list_keys(_: None = Depends(guard)) -> dict:
    return {"status": "ok", **key_ring.describe()}


@app.post("/api/keys")
def save_keys(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    """Save slots and/or switch the active one.

    Body: ``{"keys": [{"slot": 2, "key": "AIza…"}], "active_slot": 2}``
    Sending ``key: ""`` clears a slot; ``active_slot`` alone just switches.
    """
    try:
        if isinstance(payload.get("keys"), list):
            key_ring.update(payload["keys"])
        if payload.get("active_slot") is not None:
            key_ring.activate(int(payload["active_slot"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", **key_ring.describe()}


@app.post("/api/keys/test")
def test_keys(payload: dict[str, Any] | None = None,
              _: None = Depends(guard)) -> dict:
    """Validate one key (``{"slot": 2}`` or ``{"key": "AIza…"}``) or all of them."""
    payload = payload or {}
    results: list[dict] = []
    if payload.get("key"):
        ok, message = validate_key(str(payload["key"]))
        results.append({"slot": int(payload.get("slot") or 0), "ok": ok, "message": message,
                        "masked": (str(payload["key"])[:6] + "••••")})
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
    return {"status": "ok", "results": results, "api_keys": key_ring.describe()}


# ── uploads ──────────────────────────────────────────────────────────────
# Chunk handling does blocking disk I/O (an 8 MB write, and up to a multi-GB
# assembly). Running that on the event loop froze *every* other request -
# which is what made the whole site look crashed during a big upload.
@app.post("/api/upload/init")
async def upload_init(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    try:
        session = await run_in_threadpool(
            upload_manager.init,
            str(payload.get("filename", "video.mp4")),
            int(payload.get("size", 0)),
            str(payload.get("kind", "video")),
        )
        return {"status": "ok", **session.to_dict()}
    except Exception as exc:
        raise _json_error(exc) from exc


@app.get("/api/upload/status")
async def upload_status(upload_id: str = Query(...), _: None = Depends(guard)) -> dict:
    """Resume support: which chunks does the server already have?"""
    session = await run_in_threadpool(upload_manager.session_state, upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session ရှာမတွေ့ပါ")
    return {"status": "ok", **session}


@app.post("/api/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
    _: None = Depends(guard),
) -> dict:
    try:
        session = await run_in_threadpool(upload_manager.save_chunk, upload_id, index, chunk.file)
        await chunk.close()
        return {"status": "ok", **session.to_dict()}
    except KeyError as exc:
        raise _json_error(exc, 404) from exc
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload/complete")
async def upload_complete(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    try:
        return await run_in_threadpool(upload_manager.complete,
                                       str(payload.get("upload_id", "")))
    except KeyError as exc:
        raise _json_error(exc, 404) from exc
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload")
async def upload_simple(video: UploadFile = File(...), _: None = Depends(guard)) -> dict:
    """Small-file convenience endpoint (kept for compatibility)."""
    try:
        ext = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
        target = config.WORKSPACE_DIR / f"input_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
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
async def upload_logo(logo: UploadFile = File(...), _: None = Depends(guard)) -> dict:
    try:
        name = logo.filename or "logo.png"
        ext = Path(name).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif", ".tif", ".tiff"}:
            raise ValueError("Logo အတွက် ပုံဖိုင် (PNG/JPG/WEBP) သာ ပံ့ပိုးပါသည်")
        raw = config.LOGO_DIR / f"raw_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
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
        assets = upload_manager.logo_assets(raw)
        safe_unlink(raw)
        return {"status": "ok", "filename": name, **assets}
    except Exception as exc:
        raise _json_error(exc) from exc


@app.get("/api/asset")
def serve_asset(path: str = Query(...), _: None = Depends(guard)) -> FileResponse:
    """Workspace file server.

    ``FileResponse`` implements HTTP Range requests, which is what the in-page
    video preview needs to seek/scrub; adding a short-lived cache header keeps
    reloads snappy without holding stale renders forever.
    """
    try:
        target = config.resolve(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    headers = {"Cache-Control": "public, max-age=600", "Accept-Ranges": "bytes"}
    return FileResponse(str(target), headers=headers)


@app.post("/api/download-url")
def import_from_url(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    """yt-dlp import.

    The previous implementation passed ``url.split("?")[0]`` which *removes
    the video id* from every YouTube link (`watch?v=...`), so downloads from
    the most common source were guaranteed to fail. Errors from yt-dlp are
    now surfaced to the UI instead of a generic failure.
    """
    import subprocess
    import shutil as _shutil

    url = str(payload.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="Video Link ထည့်ပါ")
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link ပုံစံ မမှန်ကန်ပါ (https://... ဖြစ်ရပါမည်)")
    if not _shutil.which("yt-dlp"):
        raise HTTPException(status_code=500, detail="yt-dlp မထည့်သွင်းထားပါ (pip install yt-dlp)")

    out_tmpl = str(config.WORKSPACE_DIR / f"ytdl_{int(time.time())}_{uuid.uuid4().hex[:6]}.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--newline",
        "--restrict-filenames", "--merge-output-format", "mp4",
        "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "-o", out_tmpl, "--print", "after_move:filepath", url,
    ]
    if config.settings.ytdlp_cookies_file and Path(config.settings.ytdlp_cookies_file).exists():
        cmd += ["--cookies", config.settings.ytdlp_cookies_file]
    if config.settings.ytdlp_proxy:
        cmd += ["--proxy", config.settings.ytdlp_proxy]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Download အချိန် ကြာလွန်းနေပါသည် (30 မိနစ်)") from exc

    output = (proc.stdout or "").strip().splitlines()
    downloaded = [Path(line.strip()) for line in output if line.strip().endswith((".mp4", ".mkv", ".webm"))]
    if not downloaded or not downloaded[-1].exists():
        candidates = sorted(config.WORKSPACE_DIR.glob("ytdl_*"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
            hint = ""
            joined = " ".join(tail).lower()
            if "sign in" in joined or "bot" in joined or "cookies" in joined:
                hint = (" YouTube မှ bot စစ်ဆေးမှု ဖြစ်နေပါသည် - cookies ဖိုင် ထည့်ရန် လိုအပ်ပါသည် "
                        "(RECAP_YTDLP_COOKIES)။")
            raise HTTPException(status_code=502,
                                detail=f"Download မအောင်မြင်ပါ။{hint}\n" + "\n".join(tail))
        downloaded = [candidates[-1]]

    path = downloaded[-1]
    final = config.WORKSPACE_DIR / f"import_{int(time.time())}{path.suffix}"
    path.replace(final)
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
def start_task(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    if not payload.get("input_video"):
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ")
    try:
        video_path = config.resolve(payload["input_video"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not video_path.exists():
        raise HTTPException(status_code=400,
                            detail="တင်ထားသော ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ — ပြန်တင်ပေးပါ")
    if not payload.get("api_key") and not key_ring.has_key() and not config.settings.demo_mode:
        raise HTTPException(status_code=400,
                            detail="Gemini API Key မထည့်ရသေးပါ — ⚙️ Settings → API Keys "
                                   "တွင် Key #1 ထည့်ပါ (Key #2/#3 က quota failover အတွက်)")
    job = store.create(kind="recap", request=payload)
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
               _: None = Depends(guard)) -> dict:
    jobs = [job.to_dict(include_logs=False) for job in store.list(limit)]
    return {"status": "ok", "tasks": jobs, "runtime": job_pool_state()}


@app.get("/api/tasks/active")
def active_task(_: None = Depends(guard)) -> dict:
    """Newest running/queued job — lets the UI re-attach after a page reload."""
    for job in store.list(50):
        if job.status in {"running", "queued"}:
            return {"status": "ok", "task": job.to_dict()}
    return {"status": "ok", "task": None}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str, _: None = Depends(guard)) -> dict:
    job = store.get(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    data = job.to_dict()
    data["runtime"] = job_pool_state()
    return data


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, _: None = Depends(guard)) -> dict:
    if store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    if not store.request_cancel(task_id):
        raise HTTPException(status_code=400,
                            detail="ရပ်တန့်၍ မရပါ (ပြီးဆုံးသွားပြီ ဖြစ်နိုင်ပါသည်) — "
                                   "Jobs tab မှ refresh လုပ်ကြည့်ပါ")
    return {"status": "ok", "killed_processes": process_registry.count()}


@app.post("/api/tasks/{task_id}/rerender")
def rerender_task(task_id: str, payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    if store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    submit_job(pipeline.run_rerender, task_id, payload)
    return {"status": "ok", "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, _: None = Depends(guard)) -> dict:
    job = store.get(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    for rel in (job.output_video,):
        if rel:
            try:
                safe_unlink(config.resolve(rel))
            except Exception:
                pass
    store.delete(task_id)
    return {"status": "ok"}


@app.get("/api/download/{filename}")
def download_file(filename: str, _: None = Depends(guard)) -> FileResponse:
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="ဖိုင်အမည် မမှန်ကန်ပါ")
    target = (config.OUTPUT_DIR / safe_name).resolve()
    if config.OUTPUT_DIR.resolve() not in target.parents or not target.exists():
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    media_type = "video/mp4"
    if target.suffix == ".mp3":
        media_type = "audio/mpeg"
    elif target.suffix in {".srt", ".ass"}:
        media_type = "text/plain; charset=utf-8"
    return FileResponse(str(target), media_type=media_type, filename=safe_name)


# ── tools ────────────────────────────────────────────────────────────────
@app.post("/api/thumbnail")
def thumbnail(payload: dict[str, Any], _: None = Depends(guard)) -> FileResponse:
    raw_path = str(payload.get("video_path", ""))
    if not raw_path:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်ရွေးပါ")
    try:
        video_path = str(config.resolve(raw_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")
    out_path = config.OUTPUT_DIR / f"thumb_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
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


@app.post("/api/estimate-parts")
def estimate_parts(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    import math
    duration = float(payload.get("duration", 0) or 0)
    slice_sec = max(5, int(payload.get("slice_sec", 60) or 60))
    if duration <= 0:
        return {"total_parts": 0, "slice_sec": slice_sec, "duration": 0}
    return {"total_parts": max(1, math.ceil(duration / slice_sec)),
            "slice_sec": slice_sec, "duration": duration}


@app.post("/api/split-video")
def split_video(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    """Shorts splitter.

    ``async: true`` (what the UI sends) returns a task id immediately and the
    work runs on the job pool with a live progress bar + working cancel — a
    two hour video used to keep this HTTP request open for minutes, so the
    browser/proxy gave up and the page looked frozen.
    """
    raw_path = str(payload.get("video_path", ""))
    if not raw_path:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်ရွေးပါ")
    try:
        video_path = config.resolve(raw_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")

    if payload.get("async"):
        job = store.create(kind="split", request=payload)
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
        )
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", "parts": parts, "total_parts": len(parts)}


# ── legacy aliases (older front-ends / bookmarks keep working) ───────────
@app.post("/api/start-task", include_in_schema=False)
def legacy_start(payload: dict[str, Any],
                 x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return start_task(payload, None)


@app.get("/api/task-status/{task_id}", include_in_schema=False)
def legacy_status(task_id: str, x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return task_status(task_id, None)


@app.post("/api/rerender-task/{task_id}", include_in_schema=False)
def legacy_rerender(task_id: str, payload: dict[str, Any],
                    x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return rerender_task(task_id, payload, None)


@app.post("/api/generate-thumbnail", include_in_schema=False)
def legacy_thumbnail(payload: dict[str, Any], x_access_key: Optional[str] = Header(default=None)):
    _check_access(x_access_key)
    return thumbnail(payload, None)


# ── housekeeping ─────────────────────────────────────────────────────────
def _janitor_loop() -> None:
    while True:
        try:
            time.sleep(max(60, config.settings.janitor_interval_seconds))
            removed = prune_old_files(config.WORKSPACE_DIR, config.settings.workspace_ttl_hours,
                                      keep_names={"cache", "tasks", "logos", "uploads", "incoming", "tmp"})
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
            for entry in config.OUTPUT_DIR.glob("*"):
                if entry.name in live_outputs:
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
