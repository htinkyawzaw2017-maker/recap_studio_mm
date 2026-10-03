"""Recap Studio MM Pro — FastAPI application (v4).

Route map
---------
GET  /                          → SPA shell (static/index.html)
GET  /healthz                   → ALB / ECS health check
GET  /api/system                → capabilities, fonts, ffmpeg, disk, defaults
GET  /api/config   POST         → API key / model persistence
POST /api/upload/init|chunk|complete  → resumable chunked upload (videos)
POST /api/upload | /api/upload-logo   → simple upload (logos, small files)
GET  /api/asset?path=           → serve workspace files (Range capable)
POST /api/download-url          → yt-dlp import (fixed URL handling)
POST /api/tasks                 → start a recap job
GET  /api/tasks                 → job history
GET  /api/tasks/{id}            → live status (progress, stage, logs, ETA)
POST /api/tasks/{id}/cancel     → cooperative cancellation
POST /api/tasks/{id}/rerender   → re-render an edited timeline
DELETE /api/tasks/{id}          → delete job + its files
GET  /api/download/{filename}   → download a rendered artefact
POST /api/thumbnail             → viral thumbnail generator
POST /api/estimate-parts | /api/split-video → shorts splitter
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException,
                     Query, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from recapstudio import config, fonts
from recapstudio.config import ensure_dirs
from recapstudio.jobs import JobStore
from recapstudio.media import (ffmpeg_available, ffmpeg_version, ffprobe_available,
                               get_video_info)
from recapstudio.pipeline import RecapPipeline
from recapstudio.tts import VOICE_CATALOG
from recapstudio.uploads import upload_manager
from recapstudio.util import (dir_size_bytes, free_disk_bytes, get_logger, human_bytes,
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
_render_sem = threading.Semaphore(max(1, config.settings.max_concurrent_jobs))
_started_at = time.time()


# ── helpers ──────────────────────────────────────────────────────────────
def _check_access(key: Optional[str]) -> None:
    """Optional shared-secret gate for public AWS deployments."""
    expected = config.settings.access_password
    if not expected:
        return
    if (key or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Access key မှန်ကန်မှု မရှိပါ (Settings တွင် ထည့်ပါ)")


def guard(x_access_key: Optional[str] = Header(default=None)) -> None:
    _check_access(x_access_key)


def _json_error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _run_job(target, *args) -> None:
    """Run a pipeline function under the global concurrency semaphore."""
    with _render_sem:
        target(*args)


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
def system_info(_: None = Depends(guard)) -> dict:
    fonts_info = fonts.font_status()
    return {
        "version": config.settings.app_version,
        "ffmpeg": {"available": ffmpeg_available(), "version": ffmpeg_version(),
                   "ffprobe": ffprobe_available()},
        "fonts": fonts_info,
        "disk": {
            "free": free_disk_bytes(),
            "free_human": human_bytes(free_disk_bytes()),
            "used_by_app": dir_size_bytes(config.WORKSPACE_DIR) + dir_size_bytes(config.OUTPUT_DIR),
            "data_dir": str(config.DATA_DIR),
        },
        "limits": {
            "max_upload_bytes": config.settings.max_upload_bytes,
            "upload_chunk_bytes": config.settings.upload_chunk_bytes,
            "max_concurrent_jobs": config.settings.max_concurrent_jobs,
            "max_chunk_seconds": config.settings.max_chunk_seconds,
        },
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
        "has_api_key": _has_api_key(),
        "access_required": bool(config.settings.access_password),
    }


def _has_api_key() -> bool:
    return bool(load_api_key())


def load_api_key() -> str:
    saved = read_json(config.CONFIG_FILE, {}) or {}
    return (saved.get("gemini_api_key") or config.settings.gemini_api_key or "").strip()


@app.get("/api/config")
def get_config(_: None = Depends(guard)) -> dict:
    saved = read_json(config.CONFIG_FILE, {}) or {}
    key = load_api_key()
    return {
        "gemini_api_key_set": bool(key),
        "gemini_api_key_masked": (key[:6] + "••••" + key[-4:]) if len(key) > 12 else "",
        "model": saved.get("model", config.settings.default_model),
        "defaults": saved.get("defaults", {}),
    }


@app.post("/api/config")
def save_config(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    saved = read_json(config.CONFIG_FILE, {}) or {}
    if "gemini_api_key" in payload:
        saved["gemini_api_key"] = str(payload["gemini_api_key"]).strip()
    if "model" in payload:
        saved["model"] = str(payload["model"]).strip()
    if "defaults" in payload and isinstance(payload["defaults"], dict):
        saved["defaults"] = payload["defaults"]
    from recapstudio.util import atomic_write_json
    atomic_write_json(config.CONFIG_FILE, saved)
    return {"status": "ok", "gemini_api_key_set": bool(saved.get("gemini_api_key"))}


# ── uploads ──────────────────────────────────────────────────────────────
@app.post("/api/upload/init")
async def upload_init(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    try:
        session = upload_manager.init(
            filename=str(payload.get("filename", "video.mp4")),
            total_size=int(payload.get("size", 0)),
            kind=str(payload.get("kind", "video")),
        )
        return {"status": "ok", **session.to_dict()}
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
    _: None = Depends(guard),
) -> dict:
    try:
        session = upload_manager.save_chunk(upload_id, index, chunk.file)
        await chunk.close()
        return {"status": "ok", **session.to_dict()}
    except KeyError as exc:
        raise _json_error(exc, 404) from exc
    except Exception as exc:
        raise _json_error(exc) from exc


@app.post("/api/upload/complete")
async def upload_complete(payload: dict[str, Any], _: None = Depends(guard)) -> dict:
    try:
        return upload_manager.complete(str(payload.get("upload_id", "")))
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
    try:
        target = config.resolve(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    return FileResponse(str(target), headers={"Cache-Control": "public, max-age=3600"})


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
def start_task(payload: dict[str, Any], background: BackgroundTasks,
               _: None = Depends(guard)) -> dict:
    if not payload.get("input_video"):
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ")
    try:
        config.resolve(payload["input_video"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = store.create(kind="recap", request=payload)
    store.update(job.id, input_video=payload.get("input_video", ""))
    store.log(job.id, f"queued (mode={payload.get('mode')}, lang={payload.get('lang')}, "
                      f"voice={payload.get('voice')}, fill={payload.get('fill_mode')})")
    background.add_task(_run_job, pipeline.run_recap, job.id, payload)
    return {"status": "ok", "task_id": job.id}


@app.get("/api/tasks")
def list_tasks(_: None = Depends(guard)) -> dict:
    jobs = [job.to_dict(include_logs=False) for job in store.list(30)]
    return {"status": "ok", "tasks": jobs}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str, _: None = Depends(guard)) -> dict:
    job = store.get(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    return job.to_dict()


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, _: None = Depends(guard)) -> dict:
    if store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    if not store.request_cancel(task_id):
        raise HTTPException(status_code=400, detail="ရပ်တန့်၍ မရပါ (ပြီးဆုံးသွားပြီ ဖြစ်နိုင်ပါသည်)")
    return {"status": "ok"}


@app.post("/api/tasks/{task_id}/rerender")
def rerender_task(task_id: str, payload: dict[str, Any], background: BackgroundTasks,
                  _: None = Depends(guard)) -> dict:
    if store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    background.add_task(_run_job, pipeline.run_rerender, task_id, payload)
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
    raw_path = str(payload.get("video_path", ""))
    if not raw_path:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် အရင်ရွေးပါ")
    try:
        video_path = str(config.resolve(raw_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ")
    try:
        parts = pipeline.split_video(
            video_path=video_path,
            slice_sec=int(payload.get("slice_sec", 60)),
            aspect=str(payload.get("aspect", "9:16")),
        )
    except Exception as exc:
        raise _json_error(exc) from exc
    return {"status": "ok", "parts": parts, "total_parts": len(parts)}


# ── legacy aliases (older front-ends / bookmarks keep working) ───────────
@app.post("/api/start-task", include_in_schema=False)
def legacy_start(payload: dict[str, Any], background: BackgroundTasks,
                 x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return start_task(payload, background, None)


@app.get("/api/task-status/{task_id}", include_in_schema=False)
def legacy_status(task_id: str, x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return task_status(task_id, None)


@app.post("/api/rerender-task/{task_id}", include_in_schema=False)
def legacy_rerender(task_id: str, payload: dict[str, Any], background: BackgroundTasks,
                    x_access_key: Optional[str] = Header(default=None)) -> dict:
    _check_access(x_access_key)
    return rerender_task(task_id, payload, background, None)


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
    threading.Thread(target=_janitor_loop, daemon=True, name="janitor").start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False,
                proxy_headers=True, forwarded_allow_ips="*")
