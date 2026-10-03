"""Environment driven configuration and paths.

Everything that used to be hard-coded (workspace/output folders, thread
counts, timeouts, quality presets) lives here so an AWS deployment can be
tuned purely with environment variables / ECS task definitions - no code
change required.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


APP_ROOT = Path(__file__).resolve().parent.parent

# Where runtime data (uploads, renders, cache) is written. On AWS ECS point
# this at a mounted EFS volume / big EBS scratch disk, e.g. RECAP_DATA_DIR=/data
DATA_DIR = Path(os.getenv("RECAP_DATA_DIR", str(APP_ROOT))).resolve()
if not DATA_DIR.is_absolute():
    DATA_DIR = (APP_ROOT / DATA_DIR).resolve()

WORKSPACE_DIR = DATA_DIR / "workspace"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR = WORKSPACE_DIR / "cache"
UPLOAD_DIR = WORKSPACE_DIR / "uploads"
INCOMING_DIR = WORKSPACE_DIR / "incoming"
TASK_DIR = WORKSPACE_DIR / "tasks"
LOGO_DIR = WORKSPACE_DIR / "logos"
TMP_DIR = WORKSPACE_DIR / "tmp"

STATIC_DIR = APP_ROOT / "static"
ASSETS_DIR = APP_ROOT / "assets"
BUNDLED_FONT_DIR = ASSETS_DIR / "fonts"

CONFIG_FILE = DATA_DIR / ".recap_config.json"


@dataclass(frozen=True)
class Settings:
    """Runtime tunables (all overridable via env)."""

    # ── AI ────────────────────────────────────────────────────────────────
    default_model: str = os.getenv("RECAP_DEFAULT_MODEL", "gemini-2.5-flash")
    models: tuple = (
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    )
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    #: extra keys so a quota-exhausted key does not kill a long job.
    #: Slot 2 / 3 can be given in the UI or with GEMINI_API_KEY_2 / _3.
    gemini_api_key_2: str = os.getenv("GEMINI_API_KEY_2", "")
    gemini_api_key_3: str = os.getenv("GEMINI_API_KEY_3", "")
    #: how many key slots the UI is allowed to fill (1 = classic behaviour)
    max_api_keys: int = max(1, _env_int("RECAP_MAX_API_KEYS", 3))
    #: when a key answers 429 / quota / 403 the engine switches to the next
    #: slot automatically instead of failing the whole job
    api_key_failover: bool = _env_bool("RECAP_API_KEY_FAILOVER", True)
    #: seconds a failed key is skipped before it is tried again
    api_key_cooldown: int = _env_int("RECAP_API_KEY_COOLDOWN", 90)
    #: longest single video chunk handed to Gemini (Files API / context safe)
    max_chunk_seconds: int = _env_int("RECAP_MAX_CHUNK_SECONDS", 480)
    #: target number of chunks for very long videos
    target_chunks: int = _env_int("RECAP_TARGET_CHUNKS", 8)
    analyze_workers: int = _env_int("RECAP_ANALYZE_WORKERS", 2)
    ai_max_output_tokens: int = _env_int("RECAP_AI_MAX_TOKENS", 32768)
    ai_retries: int = _env_int("RECAP_AI_RETRIES", 4)
    ai_timeout_seconds: int = _env_int("RECAP_AI_TIMEOUT", 600)
    #: second pass: re-ask a chunk whose answer stopped before the clip end
    ai_tail_pass: bool = _env_bool("RECAP_AI_TAIL_PASS", True)
    #: max narration silence tolerated between two lines (continuous mode)
    max_narration_gap: float = _env_float("RECAP_MAX_NARRATION_GAP", 5.0)
    #: rounds of "fill the silence → re-synthesise" repair after TTS
    coverage_repair_rounds: int = _env_int("RECAP_COVERAGE_REPAIR_ROUNDS", 2)

    # ── TTS ───────────────────────────────────────────────────────────────
    tts_workers: int = _env_int("RECAP_TTS_WORKERS", 8)
    tts_retries: int = _env_int("RECAP_TTS_RETRIES", 3)
    max_tempo: float = _env_float("RECAP_MAX_TEMPO", 1.6)
    max_lag_seconds: float = _env_float("RECAP_MAX_LAG", 0.35)
    default_voice_key: str = "thiha"

    # ── Render ────────────────────────────────────────────────────────────
    render_workers: int = _env_int("RECAP_RENDER_WORKERS", 2)
    video_preset: str = os.getenv("RECAP_X264_PRESET", "veryfast")
    video_crf: int = _env_int("RECAP_X264_CRF", 23)
    audio_bitrate: str = os.getenv("RECAP_AUDIO_BITRATE", "192k")
    loudness_normalize: bool = _env_bool("RECAP_LOUDNORM", True)
    #: 0 = let ffmpeg decide, otherwise cap x264 threads (small EC2 instances
    #: stay responsive while a render runs)
    ffmpeg_threads: int = _env_int("RECAP_FFMPEG_THREADS", 0)
    #: a render that produces no output for this many seconds is treated as
    #: stuck (killed + reported) instead of hanging the job forever
    ffmpeg_stall_seconds: int = _env_int("RECAP_FFMPEG_STALL_SECONDS", 900)

    # ── Limits / housekeeping ─────────────────────────────────────────────
    max_upload_bytes: int = _env_int("RECAP_MAX_UPLOAD_BYTES", 20 * 1024 * 1024 * 1024)
    upload_chunk_bytes: int = _env_int("RECAP_UPLOAD_CHUNK_BYTES", 8 * 1024 * 1024)
    min_free_disk_bytes: int = _env_int("RECAP_MIN_FREE_DISK_BYTES", 2 * 1024 * 1024 * 1024)
    workspace_ttl_hours: float = _env_float("RECAP_WORKSPACE_TTL_HOURS", 12.0)
    output_ttl_hours: float = _env_float("RECAP_OUTPUT_TTL_HOURS", 72.0)
    janitor_interval_seconds: int = _env_int("RECAP_JANITOR_INTERVAL", 1800)
    max_concurrent_jobs: int = _env_int("RECAP_MAX_CONCURRENT_JOBS", 2)

    # ── Access / security ─────────────────────────────────────────────────
    access_password: str = os.getenv("RECAP_ACCESS_PASSWORD", "")
    allowed_origins: tuple = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("RECAP_ALLOWED_ORIGINS", "").split(",") if o.strip()
        )
    )
    ytdlp_cookies_file: str = os.getenv("RECAP_YTDLP_COOKIES", "")
    ytdlp_proxy: str = os.getenv("RECAP_YTDLP_PROXY", "")

    # ── Dev / test switches (never enable on a public deployment) ──────────
    demo_mode: bool = _env_bool("RECAP_DEMO_MODE", False)          # fake AI timeline
    fake_tts: bool = _env_bool("RECAP_FAKE_TTS", False)            # beep instead of speech
    force_reencode: bool = _env_bool("RECAP_FORCE_REENCODE", False)

    app_version: str = "4.1.0"


settings = Settings()


def ensure_dirs() -> None:
    for path in (
        WORKSPACE_DIR, OUTPUT_DIR, CACHE_DIR, UPLOAD_DIR, INCOMING_DIR,
        TASK_DIR, LOGO_DIR, TMP_DIR, STATIC_DIR / "fonts",
    ):
        path.mkdir(parents=True, exist_ok=True)


def rel(path: os.PathLike | str) -> str:
    """Path relative to DATA_DIR when possible (keeps API payloads short)."""
    try:
        p = Path(path).resolve()
        return str(p.relative_to(DATA_DIR))
    except Exception:
        return str(path)


def resolve(rel_or_abs: str) -> Path:
    """Resolve an API supplied path safely inside DATA_DIR.

    Raises ValueError for anything that tries to escape the data root
    (path traversal hardening - important on a public AWS deployment).
    """
    if not rel_or_abs:
        raise ValueError("empty path")
    raw = Path(rel_or_abs)
    candidate = raw if raw.is_absolute() else (DATA_DIR / raw)
    resolved = candidate.resolve()
    root = DATA_DIR.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path outside data dir: {rel_or_abs}")
    return resolved
