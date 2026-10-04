"""v4.3.4 — error reporting + input pre-flight (no network, ffmpeg mocked).

The EC2 report this file locks down:

    AI analysis failed for every chunk:
    chunk 1 (0-190s): FFmpeg error: frame= 0 ... received no packets ...
    chunk 2 (...) ...
    chunk 3 (...) ...

Three problems in one screen:

1. **Wrong label.** ffmpeg died while cutting the analysis proxy — the AI was
   never called. The message blamed the AI/API key.
2. **No pre-flight.** The uploader accepted a file whose video track ffmpeg
   could not decode (AV1/VP9 without a decoder, truncated MP4, audio-only);
   the first real check happened minutes later inside the analysis stage.
3. **Layout.** ``str(exc)`` was 2,500 characters of raw stderr with 130+
   character space-less EC2 paths, repeated for three chunks (≈7,500 chars)
   and printed straight into ``.toast`` / ``.log-box`` — the page became wider
   than the screen ("website zoom ကျယ်သွားတယ်").

Run:  .venv/bin/python tests/test_input_diagnostics.py
"""
from __future__ import annotations

import sys
import types as pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import ai, media  # noqa: E402
from recapstudio.util import CancelledError  # noqa: E402

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


# ── a realistic raw ffmpeg tail (what the user actually saw) ───────────────
NO_PACKETS_LOG = """ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/opt/recap-studio/data/workspace/import_1759568650.webm':
  Duration: 00:12:41.20, start: 0.000000, bitrate: 1204 kb/s
  Stream #0:0(eng): Video: av1 (Main), yuv420p(tv, bt709), 1920x1080, 30 fps, 30 tbr, 1k tbn
  Stream #0:1(eng): Audio: opus, 48000 Hz, stereo, fltp
[Parsed_scale_0 @ 0x55d1f0] w:1920 h:1080 fmt:yuv420p10le
frame=    0 fps=0.0 q=0.0 size=       0kB time=00:00:00.00 bitrate=N/A speed=   0x
frame=    0 fps=0.0 q=0.0 size=       0kB time=00:00:00.00 bitrate=N/A speed=   0x
[out#0/mp4 @ 0x55d1f0] Output file #0 does not contain any stream
[vost#0:0/libx264 @ 0x55d1f0] received no packets
Error opening output file /tmp/recap/proxy_a1b2c3d4.mp4
Conversion failed!
"""

LONG_PATH_LOG = (
    "Error opening output file /opt/recap-studio/data/uploads/very_long_yt_dlp_"
    + "x" * 130 + "/chunk_0001_part_0001_merged_final.mkv\nConversion failed!\n"
)


def test_summarizer_is_short_and_burmese() -> None:
    print("── error summarising ─────────────────────────────────────")
    summary = media.summarize_ffmpeg_error(NO_PACKETS_LOG, label="proxy")
    check("raw ffmpeg dump becomes a short sentence", len(summary) < 260, f"{len(summary)} chars")
    check("summary is Burmese", any("\u1000" <= ch <= "\u109f" for ch in summary), summary[:60])
    check("no -progress noise leaks out", "size=" not in summary and "fps=" not in summary,
          summary[:60])
    check("no raw path leaks into the summary", "/opt/recap-studio" not in summary)

    # the "received no packets" case must NOT be reported as an AI failure
    check("identifies the video-track problem", "video track" in summary or "frame" in summary,
          summary[:80])

    # codec-specific hint (AV1 with no decoder)
    av1 = "Decoder (codec av1) not found for input stream #0:0\nConversion failed!\n"
    s2 = media.summarize_ffmpeg_error(av1, label="decode")
    check("names the missing codec", "av1" in s2.lower(), s2[:90])
    check("suggests the H.264 fix", "h.264" in s2.lower() or "avc1" in s2.lower())

    moov = "moov atom not found\n/tmp/x.mp4: Invalid data found when processing input\n"
    check("explains a truncated mp4", "မပြည့်စုံ" in media.summarize_ffmpeg_error(moov))

    unknown = "Some brand new ffmpeg failure we have never seen\n"
    fallback = media.summarize_ffmpeg_error(unknown)
    check("unknown failures still get a usable line",
          "ffmpeg" in fallback.lower() and len(fallback) < 200, fallback[:80])


def test_exception_message_is_toast_safe() -> None:
    print("── exception payloads ────────────────────────────────────")
    exc = media.ffmpeg_failure(LONG_PATH_LOG, returncode=1, label="proxy")
    text = str(exc)
    check("str(exc) is short", len(text) < 260, f"{len(text)} chars")
    check("str(exc) is a single line", "\n" not in text)
    check("full log is preserved in .detail", LONG_PATH_LOG.strip() in exc.detail)
    check("still a RuntimeError (old handlers keep working)", isinstance(exc, RuntimeError))

    short, detail = media.explain_exception(exc)
    check("explain_exception returns short + full", len(short) < 260 and len(detail) > 100)

    plain = media.explain_exception(ValueError("ဗီဒီယို ကြာချိန် ဖတ်၍ မရပါ"))
    check("plain Burmese ValueErrors are passed through unchanged",
          plain[0] == "ဗီဒီယို ကြာချိန် ဖတ်၍ မရပါ", plain[0])


def test_ai_never_blames_itself_for_an_ffmpeg_failure() -> None:
    print("── ffmpeg failure vs AI failure ──────────────────────────")
    proxy_exc = ai.ProxyBuildError("🎬 ffmpeg က ဗီဒီယိုကို ဖြတ်ထုတ်၍ မရပါ။ " + "x" * 3000,
                                   detail="raw" * 500)
    failure = (1, 0.0, 190.0, proxy_exc)
    err = ai.aggregate_chunk_failure([failure], 1)
    check("all-proxy failures raise ProxyBuildError", isinstance(err, ai.ProxyBuildError))
    check("message does not say 'AI analysis failed'",
          "AI analysis failed" not in str(err), str(err)[:70])
    check("message says ffmpeg could not cut the video", "ffmpeg" in str(err))
    check("message stays short even with a huge source string",
          len(str(err)) < 500, f"{len(str(err))} chars")

    ai_exc = RuntimeError("AI request failed: 429 RESOURCE_EXHAUSTED quota")
    err2 = ai.aggregate_chunk_failure([(1, 0.0, 60.0, ai_exc)], 1)
    check("a genuine AI failure is reported as an AI failure",
          "AI" in str(err2) and "quota" in str(err2), str(err2)[:80])
    check("AI failure message stays short", len(str(err2)) < 400, f"{len(str(err2))} chars")


def test_short_reason_clamps_raw_text() -> None:
    print("── per-chunk log lines ───────────────────────────────────")
    raw = RuntimeError("FFmpeg error: " + "y" * 5000)
    line = ai._short_reason(raw)
    check("_short_reason clamps to ~220 chars", len(line) <= 221, f"{len(line)} chars")
    check("_short_reason never contains a newline", "\n" not in line)


def _fake_media(preflight: dict) -> None:
    """Monkeypatch the ffprobe / decode helpers preflight_video relies on."""
    media._run = lambda cmd, timeout=90, check=False: pytypes.SimpleNamespace(  # type: ignore[assignment]
        returncode=0, stdout="{}", stderr="")
    media.get_video_info = lambda path: {  # type: ignore[assignment]
        "duration": 120.0, "width": 1920, "height": 1080, "fps": 30.0,
        "has_audio": True, "has_video": True, "size": 1024 * 1024,
        "video_codec": "av1", "audio_codec": "aac", "rotation": 0,
    }
    media._decode_probe = lambda path: preflight  # type: ignore[assignment]
    media.ffprobe_available = lambda: True  # type: ignore[assignment]
    media.ffmpeg_available = lambda: True   # type: ignore[assignment]


def test_preflight_rejects_undecodable_video() -> None:
    print("── upload pre-flight ─────────────────────────────────────")
    import tempfile
    original = (media._run, media.get_video_info, media._decode_probe,
                media.ffprobe_available, media.ffmpeg_available)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(b"\x00" * 8192)
    tmp.close()
    fake_path = tmp.name
    try:
        _fake_media({"ok": False, "code": "no_video_packets", "frames": 0,
                     "returncode": 1, "text": NO_PACKETS_LOG})
        report = media.preflight_video(fake_path)
        check("undecodable video is rejected", report["ok"] is False, report["code"])
        check("rejection message is short + Burmese",
              len(report["message"]) < 300 and any("\u1000" <= c <= "\u109f" for c in report["message"]),
              report["message"][:60])
        check("raw log is kept as detail", "/opt/recap-studio" in report["detail"])

        _fake_media({"ok": True, "code": "ok", "frames": 5, "returncode": 0, "text": ""})
        good = media.preflight_video(fake_path)
        check("a healthy file passes", good["ok"] is True, good["message"][:60])
        check("healthy files report no warnings", good["warnings"] == [])

        media.get_video_info = lambda path: {  # type: ignore[assignment]
            "duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "has_audio": True,
            "has_video": False, "size": 10, "video_codec": "", "audio_codec": "mp3",
            "rotation": 0,
        }
        no_video = media.preflight_video(fake_path)
        check("audio-only upload is rejected", no_video["ok"] is False, no_video["code"])
        check("audio-only message explains why", "video" in no_video["message"].lower(),
              no_video["message"][:60])
    finally:
        (media._run, media.get_video_info, media._decode_probe,
         media.ffprobe_available, media.ffmpeg_available) = original
        Path(fake_path).unlink(missing_ok=True)


def test_pipeline_keeps_detail_out_of_the_message() -> None:
    print("── job store payload ────────────────────────────────────")
    from recapstudio.jobs import Job
    job = Job(id="job_x", error_detail="raw" * 100)
    data = job.to_dict()
    check("error_detail travels to the UI", data.get("error_detail") == "raw" * 100)
    check("error_hint exists for the 'what to do' line", "error_hint" in data)
    loaded = Job(**{k: v for k, v in data.items() if k in Job.__dataclass_fields__})
    check("old task files keep loading (dataclass filter)", loaded.error_detail == "raw" * 100)


def main() -> int:
    test_summarizer_is_short_and_burmese()
    test_exception_message_is_toast_safe()
    test_ai_never_blames_itself_for_an_ffmpeg_failure()
    test_short_reason_clamps_raw_text()
    test_preflight_rejects_undecodable_video()
    test_pipeline_keeps_detail_out_of_the_message()
    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
