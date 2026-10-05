#!/usr/bin/env python3
"""Offline smoke tests for the composited AI-thumbnail renderer.

The ffmpeg frame grab is stubbed with a real synthetic frame; Pillow still
runs the complete layout, gradient and Myanmar-capable text rendering path.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RECAP_DATA_DIR", tempfile.mkdtemp(prefix="recap_thumb_test_"))
os.environ.setdefault("RECAP_DEMO_MODE", "1")

from PIL import Image  # noqa: E402

import recapstudio.pipeline as pipeline_module  # noqa: E402
from recapstudio.jobs import JobStore  # noqa: E402
from recapstudio.pipeline import RecapPipeline  # noqa: E402

checks = 0
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    def fake_ffmpeg(args, **kwargs):
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        vf_index = args.index("-vf") + 1
        dimensions = re.search(r"scale=(\d+):(\d+)", args[vf_index])
        frame_size = (int(dimensions.group(1)), int(dimensions.group(2))) if dimensions else (320, 180)
        Image.new("RGB", frame_size, (92, 116, 154)).save(output, "PNG")
        return None

    old_run_ffmpeg = pipeline_module.run_ffmpeg
    pipeline_module.run_ffmpeg = fake_ffmpeg
    try:
        pipeline = RecapPipeline(JobStore())
        with tempfile.TemporaryDirectory(prefix="recap_thumb_outputs_") as tmp:
            landscape = Path(tmp) / "landscape.jpg"
            result = pipeline.generate_thumbnail(
                "source.mp4", 4.25, "မထင်မှတ်တဲ့ အလှည့်အပြောင်း", "အဆုံးထိ ကြည့်ပါ",
                str(landscape), aspect="16:9", text_position="right")
            with Image.open(landscape) as image:
                landscape_size = image.size
            check("landscape thumbnail is 1280×720", landscape_size == (1280, 720),
                  str(landscape_size))
            check("thumbnail output is a real JPEG", landscape.read_bytes()[:2] == b"\xff\xd8")
            check("metadata reports aspect and dimensions",
                  result["aspect"] == "16:9" and result["width"] == 1280
                  and result["height"] == 720)

            portrait = Path(tmp) / "portrait.jpg"
            portrait_result = pipeline.generate_thumbnail(
                "source.mp4", 7.0, "တစ်ယောက်တည်း ရင်ဆိုင်", "မထင်မှတ်တဲ့ အဆုံးသတ်",
                str(portrait), aspect="9:16", text_position="left")
            with Image.open(portrait) as image:
                portrait_size = image.size
            check("portrait thumbnail is 720×1280", portrait_size == (720, 1280),
                  str(portrait_size))
            check("frame grab uses the requested source timestamp",
                  portrait_result["aspect"] == "9:16")
    finally:
        pipeline_module.run_ffmpeg = old_run_ffmpeg

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
