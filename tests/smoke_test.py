#!/usr/bin/env python3
"""Offline end-to-end smoke test.

Runs the real pipeline (proxy building, timeline planning, time-fitting,
ASS/SRT generation, logo overlay, final ffmpeg render) **without** network
access by using the demo AI timeline and fake TTS beeps:

    RECAP_DEMO_MODE=1 RECAP_FAKE_TTS=1 python tests/smoke_test.py

Also exercises the HTTP layer with Starlette's TestClient: uploads (simple +
chunked), task lifecycle, cancel, thumbnail, estimate, splitter and the
path-traversal guards.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="recap_smoke_"))
os.environ.setdefault("RECAP_DEMO_MODE", "1")
os.environ.setdefault("RECAP_FAKE_TTS", "1")
os.environ.setdefault("RECAP_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("RECAP_LOG_LEVEL", "WARNING")

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def section(name: str) -> None:
    print(f"\n=== {name} ===")


def main() -> int:
    section("imports")
    from recapstudio import config
    from recapstudio.config import ensure_dirs
    ensure_dirs()
    from recapstudio import ai, fonts, media, render, subtitles, tts
    from recapstudio.uploads import UploadManager
    import app as webapp

    check("ffmpeg available", media.ffmpeg_available(), media.ffmpeg_version()[:40])
    check("ffprobe available", media.ffprobe_available())
    check("myanmar font resolvable", fonts.font_status()["ok"], str(fonts.font_status()["regular"]))

    section("synthetic source video")
    source = TMP / "source.mp4"
    media.generate_test_media(source, seconds=18.0, resolution="1280x720", with_audio=True)
    info = media.get_video_info(source)
    check("video generated", info["duration"] > 15, f"{info['duration']:.2f}s {info['width']}x{info['height']}")
    check("audio stream detected", info["has_audio"])

    section("timeline planning (time fitting)")
    dialogues = [
        {"start": 0.5, "end": 4.0, "text": "ဒီဇာတ်လမ်းရဲ့ အစကတည်းက စိတ်ဝင်စားစရာတွေ ဖြစ်လာတယ်။"},
        {"start": 4.2, "end": 6.0, "text": "ဒီအခိုက်အတန့်မှာ အားလုံးရဲ့ အခြေအနေ ပြောင်းသွားတယ်။"},
        {"start": 6.1, "end": 7.0, "text": "ဆက်ပြီးတော့ သူတို့ ဘယ်လိုရင်ဆိုင်မလဲ ကြည့်ရအောင်။"},
        {"start": 12.0, "end": 17.5, "text": "အဆုံးသတ်မှာ မမျှော်လင့်တဲ့ အလှည့်အပြောင်း တစ်ခု ရှိလာတယ်။"},
    ]
    planned = tts.tts_engine.plan_lines(dialogues, info["duration"], "my")
    check("all lines planned", len(planned) == 4, f"{len(planned)} lines")
    overflows = [p for p in planned if p.target_seconds <= 0]
    check("no zero-length windows", not overflows)
    check("line window derived from the next line's start",
          abs(planned[1].target_seconds - (6.1 - 4.2 - 0.06)) < 0.02,
          f"{planned[1].target_seconds:.2f}s")
    check("wide window is not capped by the model's end hint",
          abs(planned[3].target_seconds - (info["duration"] - 12.0 - 0.06)) < 0.05,
          f"{planned[3].target_seconds:.2f}s")

    section("narration mixdown")
    work = TMP / "work"
    result = tts.tts_engine.build_narration(
        dialogues=dialogues,
        voice_cfg={"voice": "my-MM-ThihaNeural", "rate": "+0%", "pitch": "+0Hz", "lang": "my", "name": "t"},
        duration=info["duration"], work_dir=work, tag="smoke",
    )
    check("mixdown produced audio", Path(result.audio_path).exists())
    check("mixdown spans the full video",
          abs(result.duration - info["duration"]) < 0.35,
          f"{result.duration:.2f}s vs video {info['duration']:.2f}s")
    check("no line was dropped", result.stats()["lines"] == 4)
    narration_mp3 = TMP / "narration.mp3"
    tts.master_audio(result.audio_path, narration_mp3, info["duration"])
    check("mp3 mastered", narration_mp3.exists() and narration_mp3.stat().st_size > 3000)

    section("subtitles")
    ass = TMP / "subs.ass"
    subtitles.build_ass(dialogues, info["duration"], ass, hook_line1="Hook {one}",
                        hook_line2="Hook, two", v_margin=280)
    check("ass written", ass.exists() and ass.stat().st_size > 400)
    body = ass.read_text(encoding="utf-8")
    check("braces escaped out of ASS text", "{one}" not in body)
    srt = TMP / "subs.srt"
    render.export_srt(dialogues, srt)
    check("srt written", srt.exists() and "-->" in srt.read_text(encoding="utf-8"))
    arg = subtitles.ass_filter_arg(ass, fonts.FONTS_DIR)
    check("subtitles filter argument escaped", "filename='" in arg and ":\\" not in arg)

    section("logo processing")
    from PIL import Image, ImageDraw
    logo_src = TMP / "logo.png"
    img = Image.new("RGB", (400, 400), (255, 255, 255))
    ImageDraw.Draw(img).ellipse((80, 80, 320, 320), fill=(20, 120, 200))
    img.save(logo_src)
    manager = UploadManager(TMP / "data" / "workspace" / "incoming", TMP / "data" / "workspace")
    assets = manager.logo_assets(logo_src)
    logo_path = config.DATA_DIR / assets["logo_path"]
    check("logo badge created", logo_path.exists() and assets["logo_processed"])
    check("logo badge is square png",
          Image.open(logo_path).size[0] == Image.open(logo_path).size[1])

    section("final render (subtitles + logo + blur reframe)")
    out_video = TMP / "master.mp4"
    t0 = time.time()
    progress_events: list[float] = []
    rendered = render.render_master(
        input_video=str(source), narration_wav=str(result.audio_path),
        output_video=str(out_video), ass_path=str(ass), logo_path=str(logo_path),
        logo_pos=(82, 4), reframe="Smart Blur Background", mute_original=True,
        quality="fast", target_size=(720, 1280), duration=info["duration"],
        progress=lambda pct, msg: progress_events.append(pct),
    )
    elapsed = time.time() - t0
    out_info = media.get_video_info(out_video)
    check("master rendered", out_video.exists() and out_video.stat().st_size > 20000)
    check("render reported progress", len(progress_events) >= 1, f"{len(progress_events)} events")
    check("output is 9:16 720x1280", (out_info["width"], out_info["height"]) == (720, 1280),
          f"{out_info['width']}x{out_info['height']}")
    check("output duration matches input", abs(out_info["duration"] - info["duration"]) < 0.5,
          f"{out_info['duration']:.2f}s")
    check("subtitles burned in", rendered["burned_subtitles"])
    check("render finished in reasonable time", elapsed < 240, f"{elapsed:.1f}s")

    section("proxy build (what Gemini actually receives)")
    proxy = ai.build_proxy(str(source), 1.0, 7.0, TMP / "proxy.mp4")
    pinfo = media.get_video_info(proxy)
    check("proxy is 1 fps low-res with audio",
          pinfo["has_audio"] and pinfo["fps"] <= 1.5 and pinfo["width"] <= 480,
          f"{pinfo['width']}x{pinfo['height']} @{pinfo['fps']}fps {media.get_media_duration(proxy):.1f}s")
    check("proxy is much smaller than the source",
          proxy.stat().st_size < source.stat().st_size / 5,
          f"{proxy.stat().st_size} vs {source.stat().st_size} bytes")

    section("audio ducking + silent-source render")
    check("amix capability probed", isinstance(media.ffmpeg_filter_supports("amix", "normalize"), bool))
    duck_out = TMP / "ducked.mp4"
    render.render_master(input_video=str(source), narration_wav=str(result.audio_path),
                         output_video=str(duck_out), reframe="Original (no reframe)",
                         mute_original=False, keep_original_level=0.3, quality="fast",
                         target_size=(1280, 720), duration=info["duration"])
    check("ducking render produced output",
          duck_out.exists() and media.get_video_info(duck_out)["has_audio"])
    silent = TMP / "silent.mp4"
    media.generate_test_media(silent, seconds=6.0, resolution="480x854", with_audio=False)
    wide = TMP / "wide.mp4"
    render.render_master(input_video=str(silent), narration_wav=str(narration_mp3),
                         output_video=str(wide), reframe="Center Crop", mute_original=True,
                         quality="fast", target_size=(1280, 720), duration=6.0)
    winfo = media.get_video_info(wide)
    check("silent portrait source renders to 16:9 with audio",
          (winfo["width"], winfo["height"]) == (1280, 720) and winfo["has_audio"],
          f"{winfo['width']}x{winfo['height']}")

    section("render fast path (no visual work)")
    fast_out = TMP / "fast.mp4"
    t0 = time.time()
    rendered_fast = render.render_master(
        input_video=str(source), narration_wav=str(narration_mp3),
        output_video=str(fast_out), reframe="Original (no reframe)", mute_original=True,
        quality="fast", target_size=(1280, 720), duration=info["duration"],
    )
    fast_elapsed = time.time() - t0
    check("fast path used stream copy", rendered_fast["fast_path"])
    check("fast path is quick", fast_elapsed < 60, f"{fast_elapsed:.1f}s")

    section("chunk plan")
    for duration, expected_min in ((30, 1), (600, 2), (5400, 5)):
        chunks = ai.plan_chunks(float(duration))
        covered = sum(e - s for s, e in chunks)
        check(f"{duration}s fully covered by {len(chunks)} chunk(s)",
              abs(covered - duration) < 0.5 and len(chunks) >= expected_min,
              f"{len(chunks)} chunks, {covered:.0f}s")
    parsed = ai.parse_dialogues('```json\n{"hook_line1":"a","hook_line2":"b","dialogues":'
                                '[{"start":1,"end":3,"speaker":"x","text":"မင်္ဂလာပါ"}]}\n```')
    check("json parser handles fenced output", len(parsed["dialogues"]) == 1)
    salvaged = ai.parse_dialogues('{"dialogues":[{"start":2,"end":5,"text":"broken json"')
    check("json salvage recovers truncated output", len(salvaged["dialogues"]) == 1)
    norm = ai.normalise([{"start": 0, "end": 10, "text": "a"}, {"start": 4, "end": 8, "text": "b"}], 20.0)
    check("overlaps de-overlapped on merge", norm[0]["end"] <= norm[1]["start"])
    gaps = ai.find_gaps(norm, 20.0, 2.0)
    check("gaps detected for coverage sweep", any(g["start"] >= 8 for g in gaps))

    section("fake tts noise")
    check("fake tts produced audio", media.get_media_duration(result.audio_path) > 5)

    section("HTTP layer")
    from fastapi.testclient import TestClient
    client = TestClient(webapp.app)
    check("GET /healthz", client.get("/healthz").json()["status"] == "ok")
    check("GET / serves the SPA", "RECAP STUDIO" in client.get("/").text.upper())
    check("GET /static/app.js", client.get("/static/app.js").status_code == 200)
    check("GET /static/styles.css", client.get("/static/styles.css").status_code == 200)
    check("bundled font served", client.get("/static/fonts/NotoSansMyanmar-Regular.ttf").status_code == 200)
    sysinfo = client.get("/api/system").json()
    check("system info reports fonts ok", sysinfo["fonts"]["ok"])

    with open(source, "rb") as fh:
        up = client.post("/api/upload", files={"video": ("clip.mp4", fh, "video/mp4")})
    check("simple upload ok", up.status_code == 200 and up.json()["status"] == "ok", str(up.text)[:120])
    video_rel = up.json()["video_path"]

    # chunked upload (same file, 2 chunks) - the flow the SPA uses
    payload = source.read_bytes()
    init = client.post("/api/upload/init", json={"filename": "clip2.mp4", "size": len(payload), "kind": "video"}).json()
    check("chunked upload init", init["status"] == "ok" and init["expected_chunks"] >= 1)
    size = init["chunk_size"]
    for idx in range(init["expected_chunks"]):
        block = payload[idx * size:(idx + 1) * size]
        r = client.post("/api/upload/chunk",
                        files={"chunk": (f"part_{idx}", block, "application/octet-stream")},
                        data={"upload_id": init["upload_id"], "index": str(idx)})
        assert r.status_code == 200, r.text
    done = client.post("/api/upload/complete", json={"upload_id": init["upload_id"]}).json()
    check("chunked upload assembled", done["status"] == "ok" and done["size"] == len(payload),
          f"{done.get('size')} bytes")
    check("chunked upload probed duration", done["duration"] > 15)
    check("preview url returned", done["preview_url"].startswith("/api/asset?path="))

    asset = client.get(done["preview_url"])
    check("asset served to browser", asset.status_code == 200 and len(asset.content) > 1000)
    check("path traversal blocked", client.get("/api/asset?path=../../etc/passwd").status_code == 400)

    logo_up = client.post("/api/upload-logo", files={"logo": ("logo.png", logo_src.read_bytes(), "image/png")})
    check("logo upload ok", logo_up.status_code == 200 and logo_up.json()["logo_path"], str(logo_up.text)[:140])

    est = client.post("/api/estimate-parts", json={"duration": 125.0, "slice_sec": 60}).json()
    check("estimate parts = 3", est["total_parts"] == 3)

    # NOTE: Starlette's TestClient runs BackgroundTasks inline, so this POST
    # returns only after the job finished - that is why stage polling below
    # usually observes the terminal state directly.
    task = client.post("/api/tasks", json={
        "input_video": video_rel, "lang": "my", "voice": "thiha", "mode": "auto",
        "fill_mode": "continuous", "quality": "fast", "output_aspect": "9:16",
        "enable_subtitles": True, "logo_path": logo_up.json()["logo_path"],
        "hook_line1": "Hook", "hook_line2": "Test",
    }).json()
    check("task created", task.get("task_id", "").startswith("task_"))
    job_id = task["task_id"]
    deadline = time.time() + 420
    seen_stages = set()
    final = None
    while time.time() < deadline:
        job = client.get(f"/api/tasks/{job_id}").json()
        seen_stages.add(job.get("stage"))
        if job["status"] in {"completed", "failed", "cancelled"}:
            final = job
            break
        time.sleep(1.5)
    check("task reached a terminal state", final is not None,
          (final or {}).get("message", "timeout")[:160])
    if final and final["status"] == "completed":
        check("task progress 100%", final["progress"] == 100)
        check("stages all done", all(s == "done" for s in final["stages"].values()))
        check("coverage reported", final["coverage"]["coverage_percent"] > 0,
              f"{final['coverage']['coverage_percent']}%")
        check("dialogues present", len(final["dialogues"]) > 0, f"{len(final['dialogues'])} lines")
        executed = [key for key, value in final["stages"].items() if value == "done"]
        check("whole stage pipeline executed", len(executed) == len(final["stages"]),
              ",".join(executed))
        logs = "\n".join(final.get("logs", []))
        check("job log records each stage", "Input OK" in logs and "Narration mastered" in logs and "DONE" in logs)
        dl = client.get(final["download_url"])
        check("download works", dl.status_code == 200 and len(dl.content) > 20000,
              f"{len(dl.content)} bytes")
        if final.get("srt_url"):
            check("srt published", client.get(final["srt_url"]).status_code == 200)
        else:
            check("srt published", False, "no srt_url")
    else:
        check("task completed", False, (final or {}).get("error", "no result")[:300])

    thumb = client.post("/api/thumbnail", json={"video_path": video_rel, "timestamp": 1.0,
                                                "hook_line1": "စမ်းသပ်", "hook_line2": "ပုံ"})
    check("thumbnail endpoint returns jpeg",
          thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8", f"HTTP {thumb.status_code}")

    split = client.post("/api/split-video", json={"video_path": video_rel, "slice_sec": 8,
                                                  "aspect": "original"})
    check("splitter produced parts", split.status_code == 200 and len(split.json()["parts"]) >= 2,
          f"{len(split.json().get('parts', [])) if split.status_code == 200 else split.text[:120]}")

    check("cancel of unknown task is a clean 404", client.post("/api/tasks/nope/cancel").status_code == 404)
    check("download traversal blocked", client.get("/api/download/..%2F..%2Fetc%2Fpasswd").status_code in {400, 404})

    print(f"\n{'=' * 58}")
    print(f"{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"  ✗ {item}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"\nSmoke test crashed: {exc}")
        raise SystemExit(2)
