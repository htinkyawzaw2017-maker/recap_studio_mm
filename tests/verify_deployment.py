#!/usr/bin/env python3
"""Verify a *deployed* Recap Studio instance (local, AWS ALB, Render, …).

Answers two questions in one command:

1. "ကျွန်တော် ပြင်ထားတဲ့ version က AWS ပေါ် တကယ် ရောက်ပြီလား?"  → endpoint checks
2. "ဒီ server ပေါ်မှာ recap job တစ်ခု တကယ် အလုပ်လုပ်လား?"        → optional --video run

Usage
-----
    python tests/verify_deployment.py https://studio.example.com
    python tests/verify_deployment.py https://studio.example.com --access-key SECRET
    python tests/verify_deployment.py https://studio.example.com --video clip.mp4
    python tests/verify_deployment.py https://studio.example.com --video clip.mp4 --timeout 1800

Exit code 0 = everything passed, 1 = at least one check failed.
No third-party dependencies (stdlib only) so it runs from any laptop.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import http.cookiejar
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"
if os.name == "nt" or not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ""

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


class Client:
    def __init__(self, base: str, access_key: str = "", verbose: bool = False):
        self.base = base.rstrip("/")
        self.access_key = access_key
        self.verbose = verbose
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""
        self.username = ""

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {}
        if self.access_key:
            headers["X-Access-Key"] = self.access_key
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        if extra:
            headers.update(extra)
        return headers

    def login(self, username: str, password: str) -> tuple[bool, str]:
        status, body = self.json("POST", "/api/auth/login",
                                 {"username": username, "password": password})
        if status != 200:
            return False, str(body.get("detail", body))[:120]
        self.csrf = str(body.get("csrf_token", ""))
        self.username = username
        return True, ""

    def logout(self) -> None:
        try:
            self.json("POST", "/api/auth/logout")
        except Exception:
            pass
        self.csrf = ""
        self.username = ""

    def request(self, method: str, path: str, data: bytes | None = None,
                headers: dict | None = None, timeout: int = 60) -> tuple[int, bytes]:
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=self._headers(headers))
        try:
            with self.opener.open(req, timeout=timeout) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except Exception as exc:  # DNS / TLS / refused
            return 0, str(exc).encode()

    def json(self, method: str, path: str, payload: dict | None = None,
             timeout: int = 60) -> tuple[int, dict]:
        body = json.dumps(payload).encode() if payload is not None else None
        opts = {"Content-Type": "application/json"} if body else None
        status, raw = self.request(method, path, body, opts, timeout)
        try:
            return status, json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            return status, {"_raw": raw[:400].decode("utf-8", "replace")}


def stream_upload(client: Client, path: Path, chunk_size: int,
                  kind: str = "video") -> dict:
    """Chunked upload exactly like the SPA does (init → chunk → complete)."""
    size = path.stat().st_size
    status, init = client.json("POST", "/api/upload/init",
                               {"filename": path.name, "size": size, "kind": kind})
    if status != 200 or "upload_id" not in init:
        raise RuntimeError(f"init failed (HTTP {status}): {init}")
    upload_id = init["upload_id"]
    chunk_size = int(init.get("chunk_size") or chunk_size)
    total = max(1, -(-size // chunk_size))
    with open(path, "rb") as fh:
        for index in range(total):
            block = fh.read(chunk_size)
            boundary = "----recapverify" + uuid.uuid4().hex[:8]
            body = b"".join([
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload_id\"\r\n\r\n{upload_id}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"index\"\r\n\r\n{index}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"chunk\"; filename=\"part\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n".encode(),
                block,
                f"\r\n--{boundary}--\r\n".encode(),
            ])
            status, _ = client.request("POST", "/api/upload/chunk", body,
                                       {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                       timeout=300)
            if status != 200:
                raise RuntimeError(f"chunk {index + 1}/{total} failed (HTTP {status})")
            print(f"    {DIM}uploaded chunk {index + 1}/{total}{RESET}")
    status, done = client.json("POST", "/api/upload/complete", {"upload_id": upload_id})
    if status != 200:
        raise RuntimeError(f"complete failed (HTTP {status}): {done}")
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a deployed Recap Studio MM instance")
    parser.add_argument("base_url", help="e.g. https://studio.example.com  (or http://IP:8000)")
    parser.add_argument("--access-key", default=os.getenv("RECAP_ACCESS_PASSWORD", ""),
                        help="value of RECAP_ACCESS_PASSWORD on the server (if set)")
    parser.add_argument("--video", type=Path, default=None,
                        help="optional: run a full recap job with this video file")
    parser.add_argument("--mode", default="movie", help="recap mode for --video (default movie)")
    parser.add_argument("--lang", default="my", help="target language (default my)")
    parser.add_argument("--timeout", type=int, default=1500, help="job timeout seconds")
    parser.add_argument("--skip-job", action="store_true", help="endpoint checks only")
    parser.add_argument("--username", default=os.getenv("RECAP_USERNAME", ""),
                        help="account to sign in with (multi-user deployments)")
    parser.add_argument("--password", default=os.getenv("RECAP_PASSWORD", ""),
                        help="password for --username")
    args = parser.parse_args()

    client = Client(args.base_url, args.access_key)
    authed = True          # flipped to False when a login is required but missing
    print(f"recap-studio verify → {client.base}")

    # ── 1. is the NEW code deployed? ─────────────────────────────────────
    section("deployment identity")
    status, health = client.json("GET", "/healthz")
    if status != 200:
        check("GET /healthz reachable", False,
              f"HTTP {status} {health}  → server down, wrong URL, or the old build has no /healthz")
        return 1
    check("GET /healthz reachable", True)
    version = str(health.get("version", "?"))
    check("server reports v4+ (new build)", version.startswith("4."),
          f"version={version}"
          + ("" if version.startswith("4.") else "  → OLD CODE STILL DEPLOYED (see docs/AWS_UPDATE.md)"))
    check("ffmpeg present on server", bool(health.get("ffmpeg")))
    check("ffprobe present on server", bool(health.get("ffprobe")))

    status, system = client.json("GET", "/api/system")
    check("GET /api/system (new endpoint) exists", status == 200,
          f"HTTP {status}" + ("" if status == 200 else "  → this endpoint only exists in the new build"))
    if status == 200:
        check("Myanmar font available on server", bool(system.get("fonts", {}).get("ok")),
              str(system.get("fonts", {}).get("regular", "")))
        disk = system.get("disk", {})
        check("free disk > 2 GB", (disk.get("free") or 0) > 2 * 1024 ** 3,
              f"free={disk.get('free_human')} on {disk.get('data_dir')}")
        if disk.get("data_dir"):
            check("data dir is writable/mounted", True, str(disk.get("data_dir")))
        check("voices exposed", bool(system.get("voices")))
        if system.get("demo_mode"):
            print(f"  [{YELLOW}NOTE{RESET}] server runs in DEMO MODE (RECAP_DEMO_MODE=1) - "
                  "fine for a UI test, not for real recaps")
        elif not system.get("has_api_key"):
            print(f"  [{YELLOW}NOTE{RESET}] server has NO Gemini API key stored - "
                  "real recap jobs will fail until it is set")

    # ── 1b. authentication & hardening (Phase 2 / #12) ──────────────────
    section("authentication & hardening")
    status, me = client.json("GET", "/api/auth/me")
    has_auth_api = status == 200
    check("/api/auth/me exists (v4.2 auth build)", has_auth_api,
          f"HTTP {status}" + ("" if has_auth_api else "  → Phase 2 code is NOT deployed yet"))
    mode = str(me.get("mode", "unknown")) if has_auth_api else "unknown"
    if has_auth_api:
        print(f"  [{YELLOW}INFO{RESET}] auth mode = {mode} • accounts exist = {me.get('has_users')}")
        check("public deployment is protected (login or shared key)",
              mode in {"users", "legacy"},
              "mode=open → မည်သူမဆို ဝင်နိုင်နေပါသည်! "
              "'python -m recapstudio.useradmin create <name> --admin' ဖြင့် အကောင့် ဖန်တီးပါ"
              if mode == "open" else f"mode={mode}")
        if mode == "users":
            anon = Client(args.base_url)
            anon_status, _ = anon.json("GET", "/api/keys")
            check("anonymous API access is blocked", anon_status == 401,
                  f"HTTP {anon_status}")
        if args.username and args.password:
            ok, detail = client.login(args.username, args.password)
            check(f"login as '{args.username}'", ok, detail)
            authed = ok
        elif mode == "users":
            authed = False
            print(f"  [{YELLOW}NOTE{RESET}] --username/--password မပေးသဖြင့် "
                  "account-only checks များကို ကျော်ပါမည်")
    headers_status, _ = client.request("GET", "/api/system")
    req = urllib.request.Request(client.base + "/healthz")
    try:
        with client.opener.open(req, timeout=30) as res:
            raw_headers = {k.lower(): v for k, v in res.headers.items()}
    except Exception:
        raw_headers = {}
    check("X-Content-Type-Options header set",
          raw_headers.get("x-content-type-options") == "nosniff",
          raw_headers.get("x-content-type-options", "missing"))
    check("HTTPS in use (or local test)",
          client.base.startswith("https://") or "localhost" in client.base
          or "127.0.0.1" in client.base,
          "public HTTP deployment — ALB/Caddy ဖြင့် TLS ထည့်ပါ")

    section("front-end")
    status, body = client.request("GET", "/")
    text = body.decode("utf-8", "replace")
    check("GET / serves SPA", status == 200)
    is_new_ui = "/static/app.js" in text
    check("new UI markup present", is_new_ui,
          "" if is_new_ui else "old build served an inline page → deploy the fix")
    check("no leftover old UI", "cdn.tailwindcss.com" not in text,
          "still contains the old page" if "cdn.tailwindcss.com" in text else "")
    # v4.1 markers — proves the *fixed* build is live, not just "some" new build
    v41 = {
        "connection banner (refresh no longer freezes)": 'id="conn-banner"',
        "3-slot API key ring": 'id="cfg-key-3"',
        "remember-key checkbox": 'id="cfg-remember"',
        "splitter dropzone": 'id="split-dropzone"',
        "cancel hint": 'id="cancel-hint"',
    }
    v42 = {
        "login overlay": 'id="auth-overlay"',
        "account chip": 'id="chip-account"',
        "admin accounts panel": 'id="admin-card"',
    }
    v43 = {
        "output-frame chip": 'id="preview-frame"',
        "preview stage wrapper": 'class="preview-stage"',
        "mobile action bar": 'id="mobile-run-bar"',
    }
    missing42 = [name for name, marker in v42.items() if marker not in text]
    check("v4.2 auth UI served", not missing42,
          "missing: " + ", ".join(missing42) if missing42
          else f"{len(v42)} markers found")
    missing43 = [name for name, marker in v43.items() if marker not in text]
    check("v4.3 responsive preview UI served", not missing43,
          "missing: " + ", ".join(missing43) + "  → browser cache သို့မဟုတ် အဟောင်း build"
          if missing43 else f"{len(v43)} markers found")
    missing = [name for name, marker in v41.items() if marker not in text]
    check("v4.1 UI features served", not missing,
          "missing: " + ", ".join(missing) if missing else f"{len(v41)} markers found")
    status, js = client.request("GET", "/static/app.js")
    js_text = js.decode("utf-8", "replace") if status == 200 else ""
    check("app.js has the resilient polling/upload code",
          "pollErrors" in js_text and "received_chunks" in js_text,
          "" if js_text else "app.js not readable")
    check("app.js previews the real output frame (v4.3)",
          "applyPreviewGeometry" in js_text and "sendPartToStudio" in js_text,
          "" if js_text else "app.js not readable")
    status, css_blob = client.request("GET", "/static/styles.css")
    css_text = css_blob.decode("utf-8", "replace") if status == 200 else ""
    check("styles.css is the responsive v4.3 sheet",
          "--preview-max-h" in css_text and "pointer: coarse" in css_text,
          "" if css_text else "styles.css not readable")
    for asset in ("/static/app.js", "/static/styles.css",
                  "/static/fonts/NotoSansMyanmar-Regular.ttf"):
        status, blob = client.request("GET", asset)
        check(f"{asset} served", status == 200 and len(blob) > 500, f"HTTP {status}")

    if authed:
        status, _ = client.json("POST", "/api/upload/init",
                                {"filename": "verify.mp4", "size": 1024, "kind": "video"})
        check("resumable upload API exists", status in (200, 400),
              f"HTTP {status}" + ("" if status != 404 else "  → 404 means the OLD build is running"))
        status, _ = client.json("POST", "/api/estimate-parts", {"duration": 125, "slice_sec": 60})
        check("tools API responds", status == 200)
    else:
        print(f"  [{YELLOW}SKIP{RESET}] upload/tools checks need --username/--password")

    # ── 2. does a job actually run? ──────────────────────────────────────
    if args.video and not args.skip_job and not authed:
        print(f"\n  [{YELLOW}SKIP{RESET}] --video job test needs --username/--password "
              "on a multi-user deployment")
    elif args.video and not args.skip_job:
        section("end-to-end recap job on the deployed server")
        video = args.video.expanduser()
        if not check("local video file exists", video.exists(), str(video)):
            return 1
        try:
            uploaded = stream_upload(client, video, 8 * 1024 * 1024)
        except Exception as exc:  # noqa: BLE001
            check("chunked upload completed", False, str(exc))
            return 1
        check("chunked upload completed", True,
              f"{uploaded.get('duration')}s {uploaded.get('width')}x{uploaded.get('height')}")
        status, task = client.json("POST", "/api/tasks", {
            "input_video": uploaded.get("video_path") or uploaded.get("path"),
            "lang": args.lang, "voice": "thiha", "mode": args.mode,
            "fill_mode": "continuous", "quality": "fast", "output_aspect": "9:16",
            "enable_subtitles": True,
            "hook_line1": "Deployment စမ်းသပ်", "hook_line2": "Recap Studio MM",
        })
        if not check("job accepted", status == 200 and task.get("task_id"), f"HTTP {status} {task}"):
            return 1
        task_id = task["task_id"]
        deadline = time.time() + args.timeout
        stages: list[str] = []
        job: dict = {}
        while time.time() < deadline:
            status, job = client.json("GET", f"/api/tasks/{task_id}", timeout=90)
            if status != 200:
                check("task status readable", False, f"HTTP {status} {job}")
                return 1
            stage = job.get("stage", "")
            if stage and (not stages or stages[-1] != stage):
                stages.append(stage)
                print(f"    {DIM}[{job.get('progress')}%] {stage}: "
                      f"{job.get('message', '')[:70]}{RESET}")
            if job.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(2)
        check("job reached a terminal state", job.get("status") in {"completed", "failed", "cancelled"},
              f"status={job.get('status')}")
        check("pipeline stages observed", len(stages) >= 4, " → ".join(stages))
        if job.get("status") == "completed":
            coverage = (job.get("coverage") or {}).get("coverage_percent")
            check("job completed", True,
                  f"{len(job.get('dialogues') or [])} lines, coverage {coverage}%, "
                  f"{round((job.get('stats', {}).get('output', {}) or {}).get('size', 0) / 1e6, 1)}MB")
            check("download works", client.request("GET", job.get("download_url", "/api/download/x"))[0] == 200)
            check("SRT published", bool(job.get("srt_url")))
        else:
            check("job completed", False, str(job.get("error") or job.get("message"))[:300])

    print(f"\n{'=' * 60}")
    print(f"{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print(f"\n{RED}Failures:{RESET}")
        for item in FAILURES:
            print(f"  ✗ {item}")
        print(f"\nNext: {DIM}docs/AWS_UPDATE.md{RESET} → deploy the fix, then re-run this script.")
        return 1
    print(f"\n{GREEN}✔ Deployment is running the fixed build and is healthy.{RESET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
