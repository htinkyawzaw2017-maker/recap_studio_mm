"""v4.3.4 — real ffmpeg checks for the new pre-flight + error reporting.

Complements ``test_input_diagnostics.py`` (which mocks ffmpeg): here we build
real files with the real binary and prove that

* a healthy file passes the pre-flight,
* an audio-only file is rejected *before* a job starts,
* an unreadable file is rejected with a short Burmese sentence (not 2,500
  characters of raw stderr),
* ``run_ffmpeg`` failures carry a short message and keep the raw log in
  ``.detail``.

Run:  FFMPEG_BINARY=/path/to/ffmpeg .venv/bin/python tests/test_ffmpeg_diagnostics.py
(without ffmpeg on PATH the file skips itself, exactly like test_thumbs.py)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import media  # noqa: E402

PASSED = 0
FAILED = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}" + (f" — {extra}" if extra else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def _make_clip(path: Path, *, video: bool = True, seconds: float = 2.0) -> bool:
    cmd = [media.FFMPEG, "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=15:duration={seconds}"]
    else:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}"]
    if video:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(path)]
    else:
        cmd += ["-map", "1:a", "-c:a", "aac", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return proc.returncode == 0


def main() -> int:
    if not shutil.which(media.FFMPEG):
        print(f"⚠️  ffmpeg မရှိပါ (`{media.FFMPEG}`) — test ကို ကျော်လိုက်ပါသည်")
        return 0
    print(f"ffmpeg: {media.ffmpeg_version()[:60]}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        good = tmpdir / "good.mp4"
        audio_only = tmpdir / "audio_only.m4a"
        garbage = tmpdir / "garbage.mp4"
        garbage.write_bytes(b"this is not a video at all\n" * 200)

        made_video = _make_clip(good, video=True)
        made_audio = _make_clip(audio_only, video=False)

        print("── decode probe ──────────────────────────────────────────")
        if made_video:
            probe = media._decode_probe(good)
            check("healthy clip decodes", probe["ok"] is True, probe["code"])
            check("frames were counted", (probe["frames"] or 0) >= 1, f"frames={probe['frames']}")
        else:
            check("could not build a test clip (libx264 missing?)", False)

        if made_audio:
            probe_a = media._decode_probe(audio_only)
            check("audio-only file fails the video decode probe", probe_a["ok"] is False,
                  probe_a["code"])
            message = media.summarize_ffmpeg_error(probe_a["text"], label="decode")
            check("its Burmese reason is short", len(message) < 260, f"{len(message)} chars")
            check("its Burmese reason is not raw stderr", "Conversion failed" not in message,
                  message[:70])

        probe_g = media._decode_probe(garbage)
        check("garbage file fails the probe", probe_g["ok"] is False, probe_g["code"])
        s = media.summarize_ffmpeg_error(probe_g["text"], label="decode")
        check("garbage file gets a readable reason",
              len(s) < 260 and any("\u1000" <= c <= "\u109f" for c in s), s[:80])

        print("── run_ffmpeg failure payload ────────────────────────────")
        try:
            media.run_ffmpeg(["-y", "-i", str(garbage), str(tmpdir / "out.mp4")],
                             total_duration=2.0, label="probe", check=True)
            check("run_ffmpeg raised on a broken file", False, "no exception")
        except media.FFmpegFailure as exc:
            check("run_ffmpeg raises FFmpegFailure", True)
            check("message is one short Burmese line",
                  len(str(exc)) < 260 and "\n" not in str(exc), f"{len(str(exc))} chars")
            check("raw log kept in .detail", len(exc.detail) > 0 and "not a video" in exc.detail
                  or "Invalid" in exc.detail, f"{len(exc.detail)} chars")
        except Exception as exc:  # noqa: BLE001
            check("run_ffmpeg raises FFmpegFailure", False, f"{type(exc).__name__}: {exc}")

        try:
            media.run_ffmpeg(["-y", "-i", str(good), "-vf", "definitely_not_a_filter",
                              str(tmpdir / "out2.mp4")],
                             total_duration=2.0, label="filter", check=True)
            check("run_ffmpeg raised on a bad filter", False, "no exception")
        except media.FFmpegFailure as exc:
            check("bad filter → short Burmese message", len(str(exc)) < 260, str(exc)[:70])
            check("bad filter hint mentions ffmpeg/option",
                  "ffmpeg" in str(exc).lower() or "filter" in str(exc).lower(), str(exc)[:80])

        print("── preflight_video end to end ────────────────────────────")
        report = media.preflight_video(garbage)
        check("preflight rejects a broken file", report["ok"] is False, report["code"])
        check("preflight message is toast safe",
              len(report["message"]) < 300 and "\n" not in report["message"],
              f"{len(report['message'])} chars")

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
