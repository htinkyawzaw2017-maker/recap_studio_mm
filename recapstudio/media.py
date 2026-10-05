"""ffmpeg / ffprobe helpers with real progress reporting.

Why this module exists
----------------------
The previous implementation shelled out to ffmpeg with
``subprocess.run(..., stderr=PIPE)`` and produced **no progress at all**.
Because a recap render is CPU bound and can run for several minutes the UI
looked frozen ("rendering ကြာနေတယ်") even though ffmpeg was working.
Every long running command here streams ``-progress pipe:1`` (or parses
stderr) so the job store can show a live percentage, ETA and speed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from . import config
from .util import CancelledError, get_logger, human_time

log = get_logger("recap.media")

FFMPEG = os.getenv("FFMPEG_BINARY", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BINARY", "ffprobe")
ProgressFn = Optional[Callable[[float, str], None]]

# ── even frame dimensions (v4.3.5) ────────────────────────────────────────
#
# libx264 + ``-pix_fmt yuv420p`` refuses odd frame sizes and dies with::
#
#     [libx264 @ 0x...] height not divisible by 2 (480x853)
#     Error while opening encoder - maybe incorrect parameters such as
#     bit_rate, rate, width or height.
#
# ``scale=W:-2`` normally rounds the computed height to an even number, but
# as soon as ``force_original_aspect_ratio`` is added that rounding is
# defeated: a 720x1280 clip scaled to 480 wide yields 480x853 and the whole
# job dies at the proxy/analysis stage — which the UI showed as a failure in
# the *rendering* step. Short-splitter parts handed to the Studio hit this
# constantly because YouTube/TikTok sources are rarely exactly 16:9.
#
# ``EVEN_DIMENSION_GUARD`` is appended to every filter chain that feeds
# libx264, so no source aspect ratio or SAR can produce an odd frame again.
EVEN_DIMENSION_GUARD = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def with_even_dimensions(vf: str | None) -> str:
    """Return ``vf`` with a trailing guard that forces even width/height.

    Safe to call with ``None`` / ``"null"`` / an empty string — the guard
    alone is a valid filter chain, and it also protects the "no scaling
    requested" path where an odd-sized source would otherwise reach libx264
    untouched.
    """
    chain = (vf or "").strip().strip(",")
    if not chain or chain == "null":
        return EVEN_DIMENSION_GUARD
    if EVEN_DIMENSION_GUARD in chain:
        return chain
    return f"{chain},{EVEN_DIMENSION_GUARD}"

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_SPEED_RE = re.compile(r"speed=\s*([\d.]+)x")
_OUT_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_OUT_TIME_US_RE = re.compile(r"out_time_us=(\d+)")

# ── failure reporting: short Burmese sentence + full raw log ──────────────
#
# v4.3.4. Before this, ``str(exc)`` was the last 2,500 characters of raw
# ffmpeg stderr. Three failed analysis chunks therefore produced a ~7,500
# character blob full of EC2 paths that contain no spaces at all, and that
# blob was pushed straight into `.toast` / `.log-box` → the page became wider
# than the screen ("website zoom ကျယ်သွားတယ်").
#
# Rule now: the exception message is ONE short Burmese sentence that is safe
# inside a toast; the raw log travels in ``.detail`` and the UI renders it
# inside a collapsible <details> panel.
DETAIL_LIMIT = 8000

#: progress key=value blocks that ``-progress pipe:1`` mixes into the output
_PROGRESS_LINE_RE = re.compile(
    r"^\s*(frame|fps|stream_\d+:\d+|stream_\d+_\d+|out_time_ms|out_time_us|out_time|"
    r"bitrate|total_size|dup_frames|drop_frames|speed|progress)\s*=",
    re.IGNORECASE,
)


class FFmpegFailure(RuntimeError):
    """An ffmpeg / ffprobe command failed.

    ``str(exc)`` is a short Burmese sentence (toast safe); ``.detail`` carries
    the raw log for the collapsible panel. Still a ``RuntimeError`` so every
    existing ``except RuntimeError`` keeps working.
    """

    def __init__(self, summary: str, *, detail: str = "", returncode: Optional[int] = None,
                 label: str = "", stage: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail = (detail or "")[-DETAIL_LIMIT:]
        self.returncode = returncode
        self.label = label
        self.stage = stage

    def __str__(self) -> str:  # never leak the raw tail into the UI
        return self.summary


class InputValidationError(ValueError):
    """The uploaded file cannot be used (checked with ffprobe + a decode test).

    Subclasses ``ValueError`` because that is what ``uploads`` / ``pipeline``
    already raise for "this file is not usable", so old handlers still catch it.
    """

    def __init__(self, summary: str, *, detail: str = "", code: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail = (detail or "")[-DETAIL_LIMIT:]
        self.code = code

    def __str__(self) -> str:
        return self.summary


#: (marker in the ffmpeg log, short Burmese explanation)
_ERROR_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("moov atom not found", "moov atom", "invalid atom"),
     "🎬 MP4 ဖိုင် မပြည့်စုံပါ (download/upload ပြတ်နေသည်) — ဖိုင်ကို ပြန်ဒေါင်းလုဒ်/ပြန်တင် လုပ်ပေးပါ။"),
    (("decoder (codec", "decoder not found", "unknown decoder", "no decoder",
      "unsupported codec", "decoder for", "find decoder"),
     "🎬 ဒီဖိုင်၏ video codec ({codec}) ကို server က ffmpeg ဖြင့် ဖွင့်၍ မရပါ (decoder မရှိ)။ "
     "H.264 (avc1) ဖိုင်အဖြစ် ပြန်ဒေါင်းလုဒ် လုပ်ပါ — သို့မဟုတ် server တွင် ffmpeg အသစ် တင်ပါ။"),
    (("received no packets", "no packets", "does not contain any stream",
      "matches no streams", "no stream", "output file is empty"),
     "🎬 video track မှာ packet/frame တစ်ခုမှ မထွက်ပါ (frame=0) — video stream ပျက်နေပါသည်။ "
     "H.264 (avc1) ဖြင့် ပြန်ဒေါင်းလုဒ် လုပ်ပြီး ပြန်တင်ပေးပါ။"),
    (("invalid data found", "invalid nal unit", "error while decoding", "corrupt",
      "damaged", "error decoding"),
     "🎬 ဗီဒီယို frame များ ဖတ်နေစဉ် error တက်ပါသည် — ဖိုင် ပျက်နေနိုင်ပါသည်။ "
     "ပြန်ဒေါင်းလုဒ် (သို့) format ပြောင်း၍ ပြန်တင်ပါ။"),
    (("no such file or directory", "cannot find the file", "file not found"),
     "📂 ဖိုင်/လမ်းကြောင်း ရှာမတွေ့ပါ — ဗီဒီယိုကို ပြန်တင်ပေးပါ။"),
    (("no space left on device", "disk full", "enospc"),
     "💾 Server disk space မလုံလောက်ပါ — EC2 volume (EBS) size တိုးပေးပါ။"),
    (("permission denied", "operation not permitted"),
     "🔒 ဖိုင် ဖတ်/ရေး ခွင့်ပြုချက် မရှိပါ (file permission)။"),
    (("no such filter", "filter not found", "unknown filter", "unrecognized option",
      "option not found", "error initializing filter", "error reinitializing filters",
      "invalid argument"),
     "⚙️ ဒီ server ၏ ffmpeg ဗားရှင်းတွင် လိုအပ်သော filter/option မပါပါ — "
     "ffmpeg အသစ် တင်ရန် လိုအပ်ပါသည် (sudo apt install -y ffmpeg)။"),
    (("cannot allocate memory", "out of memory", "killed", "oom"),
     "🧠 Memory မလုံလောက်ပါ — instance size တိုးပါ (သို့) အခြား job များကို ရပ်ပါ။"),
    (("fontconfig", "cannot find font", "font not found", "could not find font"),
     "🔤 စာလုံး (font) ရှာမတွေ့ပါ — Myanmar font ထည့်ရန် လိုအပ်ပါသည် (fonts-sil-padauk / fonts-noto-core)။"),
    (("name or service not known", "connection refused", "connection timed out",
      "http error", "temporary failure in name resolution", "network is unreachable"),
     "🌐 Network ချိတ်ဆက်မှု မအောင်မြင်ပါ — အင်တာနက်/ဆာဗာ ချိတ်ဆက်မှုကို စစ်ပါ။"),
    (("timed out", "timeout"),
     "⏱️ ffmpeg အချိန် ကျော်လွန်သွားပါသည် — ဖိုင်ကြီးလွန်း/instance သေးနိုင်ပါသည်။"),
    (("error opening output", "could not open", "output file #0"),
     "💾 ထွက်ဖိုင် ဖွင့်၍ မရပါ — disk space (သို့) file permission ကို စစ်ပါ။"),
)

_CODEC_RE = re.compile(r"codec\s+([A-Za-z0-9_\-]+)", re.IGNORECASE)


def ffmpeg_error_lines(text: str) -> list[str]:
    """Raw ffmpeg output without the ``-progress`` key=value noise."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or _PROGRESS_LINE_RE.match(line):
            continue
        out.append(line)
    return out


def summarize_ffmpeg_error(text: str, *, label: str = "") -> str:
    """Turn a raw ffmpeg log into ONE short Burmese sentence.

    The raw text is not thrown away — callers keep it in
    :attr:`FFmpegFailure.detail` so the UI can show it collapsibly.
    """
    blob = (text or "")
    low = blob.lower()
    for markers, message in _ERROR_PATTERNS:
        for marker in markers:
            if marker in low:
                codec = ""
                if "{codec}" in message:
                    found = _CODEC_RE.search(blob)
                    codec = (found.group(1) if found else _guess_codec(low)) or "unknown"
                prefix = f"[{label}] " if label else ""
                return prefix + message.format(codec=codec)
    lines = ffmpeg_error_lines(blob)
    tail = lines[-1] if lines else ""
    tail = re.sub(r"^\[[^\]]{0,40}\]\s*", "", tail)[:160]
    prefix = f"[{label}] " if label else ""
    if not tail:
        return prefix + "⚙️ ffmpeg လုပ်ဆောင်ချက် မအောင်မြင်ပါ — log ကို ဖွင့်ကြည့်ပါ။"
    return prefix + f"⚙️ ffmpeg အမှား: {tail}"


def _guess_codec(low: str) -> str:
    for name in ("av1", "vp9", "vp8", "hevc", "h265", "h264", "mpeg4", "prores", "vc1", "theora"):
        if name in low:
            return name
    return ""


def ffmpeg_failure(text: str, *, returncode: Optional[int] = None, label: str = "",
                   stage: str = "") -> FFmpegFailure:
    """Build the short-summary exception for a failed ffmpeg run."""
    return FFmpegFailure(summarize_ffmpeg_error(text, label=label),
                         detail=text, returncode=returncode, label=label, stage=stage)


def explain_exception(exc: BaseException) -> tuple[str, str]:
    """``(short Burmese message, full raw detail)`` for the job store / UI.

    The short part is what lands in a toast / the log box — it must never be a
    multi-line, space-less ffmpeg dump (that is what broke the layout).
    """
    summary = getattr(exc, "summary", "") or ""
    detail = getattr(exc, "detail", "") or ""
    if summary:
        return str(summary)[:900], detail or str(exc)
    raw = str(exc)
    # a *raw* log dump is recognisable: many lines, or far too long for a toast
    if "\n" in raw.strip() or len(raw) > 400:
        return summarize_ffmpeg_error(raw), raw
    return raw[:600], detail


def ffmpeg_available() -> bool:
    return shutil.which(FFMPEG) is not None


def ffprobe_available() -> bool:
    return shutil.which(FFPROBE) is not None


_FILTER_FEATURES: dict[str, bool] = {}


def ffmpeg_filter_supports(filter_name: str, option: str) -> bool:
    """Runtime capability probe (e.g. ``amix`` gained ``normalize`` only in
    ffmpeg 5.1). Keeps the render command working on older distro builds such
    as Debian 11 / Ubuntu 20.04 without hard failing."""
    key = f"{filter_name}:{option}"
    if key not in _FILTER_FEATURES:
        try:
            out = subprocess.run([FFMPEG, "-hide_banner", "-h", f"filter={filter_name}"],
                                 capture_output=True, text=True, timeout=20)
            blob = (out.stdout or "") + (out.stderr or "")
            _FILTER_FEATURES[key] = option in blob
        except Exception:
            _FILTER_FEATURES[key] = False
        log.info("ffmpeg capability %s = %s", key, _FILTER_FEATURES[key])
    return _FILTER_FEATURES[key]


def ffmpeg_version() -> str:
    try:
        out = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True, timeout=20)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "missing"


def _run(cmd: Sequence[str], timeout: int | None = 300, check: bool = False) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="ignore", timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegFailure(f"⏱️ {cmd[0]} သည် {timeout}s အတွင်း မပြီးပါ (timeout) — "
                            "ဖိုင်ကြီး/instance သေးနိုင်ပါသည်။",
                            detail=str(exc), stage=str(cmd[0])) from exc
    if check and proc.returncode != 0:
        tail = (proc.stderr or "")[-DETAIL_LIMIT:]
        log.error("%s failed (%s): %s", cmd[0], proc.returncode, tail[-1500:])
        raise ffmpeg_failure(tail, returncode=proc.returncode, label=Path(str(cmd[0])).name,
                             stage=str(cmd[0]))
    return proc


class ProcessRegistry:
    """Live ffmpeg processes, so a cancel can kill them immediately.

    Previously "ရပ်မည်" only set a flag that was checked between pipeline
    stages: a 40 minute render kept burning CPU and the button looked broken.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._procs: dict[int, subprocess.Popen] = {}
        self._owners: dict[int, str] = {}

    def add(self, proc: subprocess.Popen, owner: str = "") -> None:
        with self._lock:
            self._procs[proc.pid] = proc
            self._owners[proc.pid] = owner

    def remove(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.pop(proc.pid, None)
            self._owners.pop(proc.pid, None)

    def kill_owner(self, owner: str) -> int:
        """Kill every process belonging to ``owner`` (a job id). Returns count."""
        if not owner:
            return 0
        with self._lock:
            targets = [(pid, proc) for pid, proc in self._procs.items()
                       if self._owners.get(pid) == owner]
        killed = 0
        for pid, proc in targets:
            try:
                proc.kill()
                killed += 1
                log.info("killed ffmpeg pid=%s for job %s", pid, owner)
            except Exception:
                continue
        return killed

    def count(self) -> int:
        with self._lock:
            return len(self._procs)


process_registry = ProcessRegistry()


def run_ffmpeg(
    args: Iterable[str],
    *,
    total_duration: float = 0.0,
    label: str = "",
    progress: ProgressFn = None,
    timeout: int | None = None,
    check: bool = True,
    cancel: Optional[Callable[[], bool]] = None,
    owner: str = "",
) -> subprocess.CompletedProcess:
    """Run ffmpeg while streaming progress to ``progress`` (0-100, message).

    ``cancel`` is polled on every progress line (and at least every 2 s), so a
    cancelled job stops the encoder within a couple of seconds.
    ``owner`` links the process to a job id for the ProcessRegistry.
    """
    # ``-progress pipe:1`` is what makes a long encode observable: ffmpeg
    # writes machine readable key=value blocks (out_time_us / speed) to
    # stdout, which we translate into a live percentage + ETA.
    threads = config.settings.ffmpeg_threads
    thread_args = ["-threads", str(threads)] if threads and threads > 0 else []
    cmd = [FFMPEG, "-hide_banner", "-nostdin", *thread_args,
           "-progress", "pipe:1", *[str(a) for a in args]]
    started = time.time()
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="ignore", bufsize=1,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg binary မတွေ့ပါ။ Docker image ထဲတွင် ffmpeg ထည့်သွင်းထားကြောင်း စစ်ဆေးပါ "
            "(packages.txt / Dockerfile)။"
        ) from exc

    process_registry.add(proc, owner)
    tail: list[str] = []
    last_emit = 0.0
    stall_seconds = max(120, int(config.settings.ffmpeg_stall_seconds))
    state = {"last_output": time.time(), "stalled": False, "cancelled": False, "stop": False}

    def _watchdog() -> None:
        """Kills a hung encoder (and answers cancel) even when ffmpeg writes
        no output at all — without this the read loop below could block
        forever and the job would look frozen at e.g. 73%."""
        while not state["stop"] and proc.poll() is None:
            time.sleep(1.0)
            if state["stop"]:
                return
            if cancel and cancel():
                state["cancelled"] = True
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            if time.time() - state["last_output"] > stall_seconds:
                state["stalled"] = True
                log.error("ffmpeg produced no output for %ss - killing pid %s",
                          stall_seconds, proc.pid)
                try:
                    proc.kill()
                except Exception:
                    pass
                return

    watchdog = threading.Thread(target=_watchdog, daemon=True,
                                name=f"ffmpeg-watchdog-{proc.pid}")
    watchdog.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            state["last_output"] = time.time()
            tail.append(line)
            if len(tail) > 120:
                del tail[:60]

            if state["cancelled"] or (cancel and cancel()):
                proc.kill()
                raise CancelledError("အလုပ်ကို ရပ်တန့်လိုက်ပါပြီ")
            if state["stalled"]:
                raise RuntimeError(
                    f"FFmpeg သည် {stall_seconds}s ကြာ တုံ့ပြန်မှု မရှိပါ - ရပ်လိုက်ပါသည် "
                    "(ဖိုင် ပျက်နိုင်/disk ပြည့်နိုင်)။"
                )

            if not progress or total_duration <= 0:
                continue
            now = time.time()
            if now - last_emit < 0.4:
                continue
            seconds = None
            m = _OUT_TIME_US_RE.search(line) or _OUT_TIME_RE.search(line)
            if m:
                if _OUT_TIME_US_RE.search(line):
                    seconds = int(m.group(1)) / 1_000_000.0
                else:
                    seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if seconds is None:
                continue
            pct = max(0.0, min(100.0, seconds / total_duration * 100.0))
            speed_match = _SPEED_RE.search(line)
            speed = float(speed_match.group(1)) if speed_match else 0.0
            eta = ""
            if speed > 0.01 and seconds < total_duration:
                eta = f" • ~{human_time((total_duration - seconds) / speed)} ကျန်ပါသည်"
            last_emit = now
            msg = f"{label} {pct:.0f}%{eta}" if label else f"{pct:.0f}%{eta}"
            if progress:
                # A cancel raised inside the callback must abort the encode -
                # swallowing it here is why "ရပ်မည်" used to do nothing.
                progress(round(pct, 1), msg)
        proc.wait(timeout=timeout)
        if state["cancelled"]:
            raise CancelledError("အလုပ်ကို ရပ်တန့်လိုက်ပါပြီ")
        if state["stalled"]:
            raise RuntimeError(
                f"FFmpeg သည် {stall_seconds}s ကြာ တုံ့ပြန်မှု မရှိပါ - ရပ်လိုက်ပါသည် "
                "(ဖိုင် ပျက်နိုင်/disk ပြည့်နိုင်)။"
            )
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"ffmpeg timed out after {timeout}s")
    finally:
        state["stop"] = True
        process_registry.remove(proc)
        if proc.poll() is None:
            proc.kill()

    stderr_tail = "".join(tail)[-DETAIL_LIMIT:]
    if proc.returncode != 0 and cancel and cancel():
        # ffmpeg died *because* the job was cancelled (the job-level watchdog
        # kills by owner) — report a cancel, never a crash: otherwise the
        # renderer logs "retrying without burn-in" and starts a second encode
        # for a job the user just stopped.
        raise CancelledError("အလုပ်ကို ရပ်တန့်လိုက်ပါပြီ")
    if check and proc.returncode != 0:
        # One short Burmese sentence for the toast; the raw log (progress
        # lines stripped out) stays in .detail for the collapsible panel.
        log.error("ffmpeg failed (%s): %s", proc.returncode, stderr_tail[-2000:])
        raise ffmpeg_failure(stderr_tail, returncode=proc.returncode,
                             label=label or "ffmpeg", stage=label)
    log.debug("ffmpeg finished in %.1fs (%s)", time.time() - started, label)
    return subprocess.CompletedProcess(cmd, proc.returncode, "", stderr_tail)


# ── probing ──────────────────────────────────────────────────────────────
def probe_json(path: str | os.PathLike, timeout: int = 60) -> dict:
    if not path or not Path(path).exists():
        return {}
    proc = _run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(path)],
        timeout=timeout,
    )
    try:
        return json.loads(proc.stdout or "{}")
    except Exception:
        return {}


def get_media_duration(path: str | os.PathLike) -> float:
    """Duration in seconds (0.0 when unknown/unreadable)."""
    if not path or not Path(path).exists():
        return 0.0
    info = probe_json(path)
    fmt = info.get("format") or {}
    for key in ("duration", "DURATION"):
        try:
            value = float(fmt.get(key))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    for stream in info.get("streams", []):
        try:
            value = float(stream.get("duration", 0))
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    # Last resort: decode header only (fast) for containers without duration.
    try:
        proc = _run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=nb_frames,avg_frame_rate", "-of", "json", str(path)])
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        frames = float(stream.get("nb_frames") or 0)
        rate = (stream.get("avg_frame_rate") or "0/1").split("/")
        fps = (float(rate[0]) / float(rate[1])) if len(rate) == 2 and float(rate[1]) else 0
        if frames and fps:
            return frames / fps
    except Exception:
        pass
    return 0.0


def get_video_info(path: str | os.PathLike) -> dict:
    info = probe_json(path)
    result = {
        "duration": 0.0, "width": 0, "height": 0, "fps": 0.0,
        "has_audio": False, "has_video": False, "size": 0,
        "video_codec": "", "audio_codec": "", "rotation": 0,
    }
    try:
        result["size"] = int((info.get("format") or {}).get("size") or 0)
    except Exception:
        pass
    for stream in info.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and not result["has_video"]:
            result["has_video"] = True
            result["width"] = int(stream.get("width") or 0)
            result["height"] = int(stream.get("height") or 0)
            result["video_codec"] = stream.get("codec_name") or ""
            rate = (stream.get("avg_frame_rate") or "0/1").split("/")
            try:
                result["fps"] = float(rate[0]) / float(rate[1]) if float(rate[1]) else 0.0
            except Exception:
                result["fps"] = 0.0
            try:
                for side in stream.get("side_data_list") or []:
                    if "rotation" in side:
                        result["rotation"] = int(float(side["rotation"]))
            except Exception:
                pass
        elif codec_type == "audio" and not result["has_audio"]:
            result["has_audio"] = True
            result["audio_codec"] = stream.get("codec_name") or ""
    if not result["duration"]:
        result["duration"] = get_media_duration(path)
    return result


def has_audio_stream(path: str | os.PathLike) -> bool:
    return get_video_info(path)["has_audio"]


# ── input pre-flight: "will this file survive the pipeline?" ─────────────
# v4.3.4. The EC2 report was
#     AI analysis failed for every chunk:
#     chunk 1 (...) FFmpeg error: ... frame= 0 ... received no packets ...
# i.e. the file died in ffmpeg *before* the AI ever saw it, and the user was
# told the AI failed. Worse, nothing checked the upload: the uploader accepted
# any file with a .mp4 extension, and the first real probe happened minutes
# later inside the analysis stage.
#
# ``preflight_video`` runs ffprobe + a real 5-frame decode test right after the
# upload (and again when a job starts) and answers with a short Burmese reason.

#: decode a handful of frames with ``-f null`` — cheap, but authoritative:
#: an AV1/VP9 file without a decoder fails here instead of 3 minutes later.
DECODE_PROBE_FRAMES = 5
DECODE_PROBE_TIMEOUT = 90


def _decode_probe(path: str | os.PathLike) -> dict:
    """Decode a few video frames. Never raises; reports what ffmpeg said."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "warning", "-progress", "pipe:1",
           "-i", str(path), "-map", "0:v:0", "-frames:v", str(DECODE_PROBE_FRAMES),
           "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="ignore", timeout=DECODE_PROBE_TIMEOUT)
    except FileNotFoundError:
        return {"ok": False, "code": "no_ffmpeg", "frames": None, "returncode": None,
                "text": "ffmpeg binary not found"}
    except subprocess.TimeoutExpired:
        # A slow machine / huge file is NOT proof of a broken file — let the
        # real pipeline decide instead of blocking a working upload.
        return {"ok": True, "code": "timeout", "frames": None, "returncode": None,
                "text": f"decode probe exceeded {DECODE_PROBE_TIMEOUT}s"}
    blob = proc.stdout or ""
    frames = None
    for match in re.finditer(r"frame=(\d+)", blob):
        frames = int(match.group(1))
    low = blob.lower()
    hard_markers = ("decoder (codec", "decoder not found", "unknown decoder",
                    "no decoder", "invalid data found", "moov atom not found",
                    "does not contain any stream", "output file is empty")
    no_packets = "received no packets" in low or "no packets" in low
    if any(marker in low for marker in hard_markers):
        return {"ok": False, "code": "decode_failed", "frames": frames,
                "returncode": proc.returncode, "text": blob}
    if proc.returncode != 0:
        return {"ok": False, "code": "decode_failed", "frames": frames,
                "returncode": proc.returncode, "text": blob}
    if frames == 0 and no_packets:
        return {"ok": False, "code": "no_video_packets", "frames": frames,
                "returncode": proc.returncode, "text": blob}
    if frames is None and no_packets:
        # older ffmpeg builds print no frame= key in -progress; the demuxer
        # message itself is then the only evidence we have
        return {"ok": False, "code": "no_video_packets", "frames": frames,
                "returncode": proc.returncode, "text": blob}
    return {"ok": True, "code": "ok", "frames": frames,
            "returncode": proc.returncode, "text": blob}


def preflight_video(path: str | os.PathLike, *, decode: bool = True) -> dict:
    """Check an upload before a job burns 30 minutes on it.

    Returns (never raises)::

        {"ok": bool, "code": str, "message": str,   # short Burmese, toast safe
         "detail": str,                             # raw ffprobe/ffmpeg log
         "warnings": [str], "info": {...}, "frames": int | None}
    """
    report: dict = {"ok": True, "code": "ok", "message": "", "detail": "",
                    "warnings": [], "info": {}, "frames": None}
    target = Path(str(path))
    if not str(path) or not target.exists():
        return {**report, "ok": False, "code": "missing",
                "message": "📂 ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ — ဗီဒီယိုကို ပြန်တင်ပေးပါ။"}
    try:
        size = target.stat().st_size
    except OSError as exc:
        return {**report, "ok": False, "code": "unreadable",
                "message": "📂 ဖိုင်ကို ဖတ်၍ မရပါ (permission/disk)။", "detail": str(exc)}
    if size < 4096:
        return {**report, "ok": False, "code": "empty",
                "message": f"📂 ဖိုင်က အလွန်သေးငယ်ပါ ({size} bytes) — upload ပြတ်နေသည်။ "
                           "ဗီဒီယိုကို ပြန်တင်ပေးပါ။"}
    if not ffprobe_available() or not ffmpeg_available():
        return {**report, "ok": False, "code": "no_ffmpeg",
                "message": "⚙️ Server ပေါ်တွင် ffmpeg/ffprobe မတွေ့ပါ — "
                           "`sudo apt install -y ffmpeg` ဖြင့် တင်ပြီး service ကို restart ပါ။"}
    probe = _run([FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)],
                 timeout=90)
    raw_detail = (probe.stderr or "")[-DETAIL_LIMIT:]
    if probe.returncode != 0:
        return {**report, "ok": False, "code": "unreadable",
                "message": summarize_ffmpeg_error(probe.stderr or "", label="ffprobe"),
                "detail": raw_detail}
    info = get_video_info(target)
    report["info"] = info
    if not info["has_video"]:
        return {**report, "ok": False, "code": "no_video",
                "message": "🎬 ဒီဖိုင်ထဲမှာ video track မပါပါ (အသံဖိုင် သို့မဟုတ် ပျက်နေသော ဖိုင် "
                           "ဖြစ်နိုင်သည်) — ဗီဒီယိုဖိုင်အဖြစ် ပြန်တင်ပေးပါ။",
                "detail": raw_detail}
    if info["duration"] <= 0.5:
        return {**report, "ok": False, "code": "no_duration",
                "message": "🎬 ဗီဒီယို ကြာချိန် ဖတ်၍ မရပါ (0s) — ဖိုင် ပျက်နေနိုင်ပါသည်။ "
                           "ပြန်ဒေါင်းလုဒ်/ပြန်တင် လုပ်ပေးပါ။",
                "detail": raw_detail}
    if not info["has_audio"]:
        report["warnings"].append(
            "🔇 ဒီဖိုင်မှာ အသံ (audio) track မပါပါ — recap/dub အသံထည့်ရာတွင် ခက်ခဲနိုင်ပါသည်။")
    if decode:
        probe_result = _decode_probe(target)
        report["frames"] = probe_result.get("frames")
        report["decode"] = {"code": probe_result["code"], "returncode": probe_result["returncode"]}
        if not probe_result["ok"]:
            report.update(
                ok=False, code=probe_result["code"],
                message=summarize_ffmpeg_error(probe_result["text"] or "",
                                               label="decode"),
                detail=(probe_result["text"] or raw_detail)[-DETAIL_LIMIT:],
            )
        elif probe_result["code"] == "timeout":
            report["warnings"].append("⏱️ ဖိုင် စစ်ဆေးချိန် ကျော်လွန်သွားသည် — စစ်ဆေးမှု ကျန် "
                                      "အဆင့်များကို ဆက်လုပ်ပါမည်။")
    if report["ok"] and not report["message"]:
        report["message"] = (f"✅ ဗီဒီယို အဆင်သင့် ({human_time(info['duration'])} • "
                             f"{info['width']}x{info['height']} • {info['video_codec'] or '?'})")
    return report



def generate_test_media(path: str | os.PathLike, seconds: float = 12.0,
                        resolution: str = "1280x720", with_audio: bool = True) -> None:
    """Synthetic clip used by the offline smoke test."""
    args = [
        "-y", "-f", "lavfi", "-i", f"testsrc2=size={resolution}:rate=30:duration={seconds}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}"]
        args += ["-map", "0:v", "-map", "1:a", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p"]
    if with_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args += [str(path)]
    run_ffmpeg(args, check=True)


def make_silence_wav(duration_sec: float, out_path: str | os.PathLike) -> str:
    """Exact length silent stereo WAV (used for timeline gaps).

    Note: ``anullsrc=...:d=`` is only supported by ffmpeg >= 5.0; the
    length is therefore set with ``-t`` which works on every version.
    """
    duration_sec = max(0.02, float(duration_sec))
    run_ffmpeg([
        "-y", "-threads", "1", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{duration_sec:.4f}",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out_path),
    ], check=True)
    return str(out_path)


def encode_mp3(src: str | os.PathLike, out_path: str | os.PathLike,
               bitrate: str = "192k", progress: ProgressFn = None) -> str:
    duration = get_media_duration(src)
    run_ffmpeg(["-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", bitrate, str(out_path)],
               total_duration=duration, label="MP3", progress=progress, check=True)
    return str(out_path)
