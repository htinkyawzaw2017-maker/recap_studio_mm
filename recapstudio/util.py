"""Logging, disk and small shared helpers."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from . import config

_LOG_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """Structured-ish plain logs; uvicorn captures stdout on AWS."""
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, (level or os.getenv("RECAP_LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _LOG_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


log = get_logger("recap.util")


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            return f"{num:3.1f}{unit}" if unit != "B" else f"{int(num)}B"
        num /= 1024.0
    return f"{num:.1f}TB"


def human_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def free_disk_bytes(path: Path | str = config.DATA_DIR) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except Exception:
        return 0


def total_disk_bytes(path: Path | str = config.DATA_DIR) -> int:
    try:
        return shutil.disk_usage(str(path)).total
    except Exception:
        return 0


def ensure_disk_space(required_bytes: int, path: Path | str = config.DATA_DIR) -> None:
    """Fail fast with a friendly message instead of a mysterious ffmpeg ENOSPC."""
    free = free_disk_bytes(path)
    floor = max(config.settings.min_free_disk_bytes, required_bytes)
    if free and free < floor:
        raise RuntimeError(
            f"လုံလောက်သော disk space မရှိပါ။ လိုအပ်ချက် ~{human_bytes(floor)}၊ "
            f"လက်ရှိ free {human_bytes(free)} ဖြစ်ပါသည်။ "
            "Docker/EC2 volume size ကို တိုးပေးပါ (RECAP_DATA_DIR ကို EBS/EFS ပေါ်တွင် ထားနိုင်ပါသည်)။"
        )


def atomic_write_json(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as exc:  # never let bookkeeping kill a render
        log.warning("atomic_write_json failed for %s: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def safe_unlink(path: Path | str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def safe_rmtree(path: Path | str | None) -> None:
    if not path:
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def slugify_filename(name: str, max_len: int = 80) -> str:
    """Sanitise an upload filename (no path separators / weird unicode)."""
    base = os.path.basename(name or "file")
    base = unicodedata.normalize("NFKC", base)
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in "._- ()[]")
    cleaned = cleaned.strip().replace(" ", "_")
    cleaned = cleaned or "file"
    if "." in cleaned:
        stem, _, ext = cleaned.rpartition(".")
        stem = stem[:max_len] or "file"
        ext = "".join(ch for ch in ext if ch.isalnum())[:8]
        return f"{stem}.{ext}" if ext else stem
    return cleaned[:max_len]


def prune_old_files(directory: Path | str, ttl_hours: float, keep_names: Iterable[str] = ()) -> int:
    """Delete files older than ttl_hours. Returns number of files removed."""
    directory = Path(directory)
    if not directory.exists() or ttl_hours <= 0:
        return 0
    keep = set(keep_names)
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    for entry in directory.iterdir():
        if entry.name in keep:
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
            elif entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except Exception:
            continue
    return removed


def dir_size_bytes(directory: Path | str) -> int:
    total = 0
    directory = Path(directory)
    if not directory.exists():
        return 0
    for root, _dirs, files in os.walk(directory):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except Exception:
                continue
    return total


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def estimate_speech_seconds(text: str, lang: str = "my", chars_per_second: float = 0.0) -> float:
    """Rough spoken-length estimate used before/without synthesis.

    Burmese script packs more meaning per character than Latin text, so a
    Burmese line is estimated at ~13 glyphs/second while English around
    ~15 characters/second (≈ 2.6 words/second at 5.8 chars/word).
    """
    text = (text or "").strip()
    if not text:
        return 0.0
    rate = chars_per_second or (13.0 if lang == "my" else 15.0)
    # Digits / punctuation are spoken differently but this is only a hint.
    return max(0.6, len(text) / rate)
