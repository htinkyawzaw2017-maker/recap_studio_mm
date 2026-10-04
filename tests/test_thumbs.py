#!/usr/bin/env python3
"""Offline tests for the #10 nano-banana thumbnail studio.

စမ်းသပ်သည့် အရာများ
  1. frame scoring/picking — မှောင်သော ဖရိမ်များ ကျော်နိုင်ခြင်း
  2. compose() — အရွယ်အစား မှန်ကန်ခြင်း၊ မြန်မာစာ hook မပျက်ခြင်း
  3. generate_variants() — ရွေးစရာ အမျိုးမျိုး + style မတူညီခြင်း
  4. AI fallback — key မရှိလျှင် ဖရိမ်အတိုင်း ဆက်ထုတ်ပေးခြင်း
  5. API — /api/thumb-sources + /api/thumbnails (upload မလို)

ဘယ် network/API key မှ မလိုပါ — ffmpeg + Pillow သာ လိုသည်။
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("RECAP_DEMO_MODE", "1")
os.environ.setdefault("RECAP_FAKE_TTS", "1")
os.environ.setdefault("RECAP_DATA_DIR", tempfile.mkdtemp(prefix="thumbtest_"))

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> bool:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail and not cond else ""))
    return bool(cond)


def make_video(path: Path, seconds: int = 6) -> Path:
    """A tiny test clip: dark first second, bright colourful rest."""
    from recapstudio.media import run_ffmpeg
    run_ffmpeg([
        "-y", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=12:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


def main() -> int:
    from recapstudio import config, thumbs
    from recapstudio.media import ffmpeg_available

    if not ffmpeg_available():
        print("⚠️  ffmpeg မရှိပါ — test ကို ကျော်လိုက်ပါသည်")
        return 0

    work = Path(tempfile.mkdtemp(prefix="thumbs_"))
    video = make_video(work / "clip.mp4")

    print("\n[1] frame picking")
    frames = thumbs.pick_frames(video, count=3, work_dir=work / "cand")
    check("picks the requested number of frames", len(frames) == 3, f"got {len(frames)}")
    check("frames are in story order", [f.second for f in frames] == sorted(f.second for f in frames))
    check("frames land inside the clip", all(0 <= f.second <= 6.1 for f in frames))
    check("every picked frame exists on disk", all(f.path.exists() for f in frames))
    check("frames are scored", all(0.0 <= f.score <= 2.0 for f in frames))

    black = work / "black.jpg"
    from PIL import Image
    Image.new("RGB", (640, 360), (0, 0, 0)).save(black)
    bright = work / "bright.jpg"
    Image.new("RGB", (640, 360), (120, 140, 160)).save(bright)
    check("a black frame scores below a mid-grey one",
          thumbs._frame_score(black) < thumbs._frame_score(bright))

    print("\n[2] compose (Burmese hook burn-in)")
    base = frames[0].path
    for aspect, (w, h) in thumbs.ASPECT_SIZES.items():
        out = work / f"c_{aspect.replace(':', 'x')}.jpg"
        thumbs.compose(base, out, "မကြည့်ရင် နောင်တရမယ်", "အပြီးထိ ကြည့်ပါ", aspect=aspect)
        with Image.open(out) as im:
            size_ok = im.size == (w, h)
        check(f"{aspect} renders at {w}×{h}", size_ok)
        check(f"{aspect} output is a real JPEG", out.stat().st_size > 8000)

    long_hook = work / "long.jpg"
    thumbs.compose(base, long_hook,
                   "ဒီဇာတ်လမ်းကို အစအဆုံး မကြည့်မိရင် တကယ်ကို နောင်တရသွားမှာ သေချာပါတယ်",
                   "နောက်ဆုံးအခန်းက လူတိုင်းကို အံ့အားသင့်စေခဲ့ပါတယ်", aspect="16:9")
    check("a very long Burmese hook still renders", long_hook.exists() and long_hook.stat().st_size > 8000)

    empty_hook = work / "empty.jpg"
    thumbs.compose(base, empty_hook, "", "", aspect="16:9")
    check("empty hooks do not crash", empty_hook.exists())

    styles_out = []
    for style in thumbs.STYLE_ORDER:
        dst = work / f"s_{style}.jpg"
        thumbs.compose(base, dst, "စမ်းသပ်ချက်", "စတိုင်", style=style)
        styles_out.append(dst.read_bytes())
    check("all four styles exist", len(thumbs.STYLES) == 4)
    check("styles produce different images", len({hash(b) for b in styles_out}) == 4)

    print("\n[3] variants + AI fallback")
    check("demo mode reports AI unavailable", thumbs.ai_available() is False)
    check("ai_restyle falls back silently without a key",
          thumbs.ai_restyle(base, work / "never.png") is False)
    check("the fallback writes no file", not (work / "never.png").exists())

    out_dir = work / "out"
    variants = thumbs.generate_variants(video, out_dir, "ထိပ်တန်း ဇာတ်ကွက်", "မလွတ်စေနဲ့",
                                        count=3, aspect="16:9", use_ai=True)
    check("3 variants returned", len(variants) == 3, f"got {len(variants)}")
    check("every variant file exists", all((out_dir / v["filename"]).exists() for v in variants))
    check("variants use different styles", len({v["style"] for v in variants}) == 3)
    check("variants come from different seconds", len({v["second"] for v in variants}) == 3)
    check("ai flag is False without a key", all(v["ai"] is False for v in variants))
    check("variant size matches the aspect", all(v["width"] == 1280 and v["height"] == 720 for v in variants))
    check("download url points at the file",
          all(v["url"] == f"/api/download/{v['filename']}" for v in variants))
    check("preview url is workspace-relative", all(v["preview_url"].startswith("/api/asset?path=") for v in variants))

    one = thumbs.generate_variants(video, out_dir, "တစ်ခုတည်း", "စမ်းသပ်", count=1, aspect="9:16")
    check("count=1 honoured", len(one) == 1)
    check("9:16 variant is portrait", one[0]["width"] == 1080 and one[0]["height"] == 1920)
    check("count is clamped to 4",
          len(thumbs.generate_variants(video, out_dir, "a", "b", count=99)) <= 4)

    print("\n[4] no leftover temp frames")
    # generate_variants() works in config.TMP_DIR and must leave nothing behind
    tmp_left = list(Path(config.TMP_DIR).glob("cand_*.jpg")) + list(Path(config.TMP_DIR).glob("nb_*.png"))
    check("generate_variants cleans its temp frames", not tmp_left, f"{len(tmp_left)} left")
    # pick_frames() hands its winners to the caller, who owns them
    kept = [f for f in frames if f.path.exists()]
    check("pick_frames keeps only the winners for the caller", len(kept) == 3, f"{len(kept)}")
    for f in frames:
        f.path.unlink(missing_ok=True)

    print("\n[5] API surface")
    from fastapi.testclient import TestClient
    import app as app_mod
    client = TestClient(app_mod.app)
    r = client.get("/api/thumb-sources")
    check("/api/thumb-sources returns 200", r.status_code == 200, str(r.status_code))
    body = r.json() if r.status_code == 200 else {}
    check("source list is present", isinstance(body.get("sources"), list))
    check("aspect list is advertised", set(body.get("aspects", [])) == {"16:9", "9:16", "1:1"})
    check("style list is advertised", len(body.get("styles", [])) == 4)
    check("ai_ready is False in demo mode", body.get("ai_ready") is False)

    r = client.post("/api/thumbnails", json={})
    check("missing source is rejected with 400", r.status_code == 400, str(r.status_code))
    r = client.post("/api/thumbnails", json={"video_path": "nope/missing.mp4"})
    check("unknown path is rejected", r.status_code in (400, 404), str(r.status_code))

    # a real request against an uploaded file inside the workspace
    up = config.user_upload_dir("") if hasattr(config, "user_upload_dir") else config.UPLOAD_DIR
    Path(up).mkdir(parents=True, exist_ok=True)
    import shutil
    staged = Path(up) / "clip_for_thumbs.mp4"
    shutil.copy(video, staged)
    r = client.post("/api/thumbnails", json={"video_path": config.rel(staged),
                                             "hook_line1": "ပြီးသွားသော ဗီဒီယို",
                                             "hook_line2": "thumbnail စမ်းသပ်",
                                             "count": 2, "use_ai": False})
    ok = r.status_code == 200
    check("/api/thumbnails generates from a workspace video", ok, r.text[:160])
    if ok:
        data = r.json()
        check("API returns 2 variants", len(data.get("variants", [])) == 2)
        check("API reports the nano-banana model", "flash-image" in data.get("model", ""))
        check("API says AI was not used", data.get("ai_used") is False)
        first = data["variants"][0]
        dl = client.get(first["url"])
        check("variant is downloadable", dl.status_code == 200 and len(dl.content) > 8000,
              str(dl.status_code))

    print("\n[6] upload control removed from the tab")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    thumb_tab = html[html.index('id="tab-thumb"'):html.index('id="tab-split"')]
    check("no dropzone in the thumbnail tab", "thumb-dropzone" not in thumb_tab)
    check("no file input in the thumbnail tab", 'type="file"' not in thumb_tab)
    check("finished-video selector is present", 'id="thumb-source"' in thumb_tab)
    check("aspect selector is present", 'id="thumb-aspect"' in thumb_tab)
    check("AI toggle is present", 'id="thumb-ai"' in thumb_tab)
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    check("js drops the old upload state", "thumbVideo" not in js)
    check("js calls the new endpoint", "'/api/thumbnails'" in js)
    check("js loads sources when the tab opens", "loadThumbSources()" in js)

    shutil.rmtree(work, ignore_errors=True)

    print(f"\n{'=' * 58}\n✅ {len(PASS)} passed   ❌ {len(FAIL)} failed")
    if FAIL:
        for name in FAIL:
            print(f"   - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
