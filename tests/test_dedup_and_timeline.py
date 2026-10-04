"""Tests for timeline deduplication, de-overlapping, mode separation, and sample-accurate audio assembly.

Verifies fixes for user-reported bug:
  "videos rendering အပြီး videos output မှာ အသံ ထပ်ပြီ ပြော နေတယ် caption စာတန်းထိုး ထပ်နေတယ်"
  - Line deduplication (exact & fuzzy matching).
  - Absolute de-overlapping in normalise, build_ass, and export_srt.
  - Mode differentiation: Movie Recap (continuous) vs Dialogue Dubbing (pure dialogue).
  - Sample-accurate timeline audio placement.
"""
from __future__ import annotations

import math
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from recapstudio import ai, config, pipeline, render, subtitles, tts
from recapstudio.tts import PlannedLine

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        msg = f"  [PASS] {name}"
        if extra:
            msg += f" — {extra}"
        print(msg)
    else:
        FAILED += 1
        msg = f"  [FAIL] {name}"
        if extra:
            msg += f" — {extra}"
        print(msg, file=sys.stderr)


def main() -> int:
    print("── 1. Timeline Deduplication & De-overlapping ───────────────")

    # Exact duplicate lines from user issue
    dups = [
        {"start": 12.0, "end": 14.5, "text": "B44 ဝိညာဉ်၊ ကောင်တာ ၃ မှာ မှတ်ဉာဏ်ဖျက်ဖို့ လာပါ"},
        {"start": 12.2, "end": 15.0, "text": "B44 ဝိညာဉ်၊ ကောင်တာ ၃ မှာ မှတ်ဉာဏ်ဖျက်ဖို့ လာပါ"},
    ]
    norm1 = ai.normalise(dups, 90.0)
    check("exact duplicate dialogue is deduplicated to single line", len(norm1) == 1,
          f"{len(norm1)} line: {norm1[0]['text']}")

    # Fuzzy duplicate with slight punctuation/spacing difference
    fuzzy_dups = [
        {"start": 5.0, "end": 8.0, "text": "မင်း ဘယ်သွားမလို့လဲ။"},
        {"start": 5.4, "end": 8.5, "text": "မင်း ဘယ်သွားမလို့လဲ"},
    ]
    norm2 = ai.normalise(fuzzy_dups, 90.0)
    check("fuzzy duplicate dialogue within close window is deduplicated", len(norm2) == 1)

    # Overlapping time lines with different text
    overlap_diff = [
        {"start": 1.0, "end": 5.0, "text": "ပထမ စကားပြောစာ"},
        {"start": 3.0, "end": 7.0, "text": "ဒုတိယ စကားပြောစာ"},
    ]
    norm3 = ai.normalise(overlap_diff, 20.0)
    check("overlapping lines are sequenced without time collision",
          len(norm3) == 2 and norm3[0]["end"] <= norm3[1]["start"],
          f"L1 end={norm3[0]['end']}s <= L2 start={norm3[1]['start']}s")

    print("── 2. Subtitles De-overlapping (ASS & SRT) ─────────────────")
    with tempfile.TemporaryDirectory() as tmp:
        ass_path = Path(tmp) / "test.ass"
        srt_path = Path(tmp) / "test.srt"

        sub_input = [
            {"start": 2.0, "end": 6.0, "text": "စာတန်း ၁"},
            {"start": 4.0, "end": 8.0, "text": "စာတန်း ၂"},
        ]
        subtitles.build_ass(sub_input, 15.0, ass_path)
        ass_content = ass_path.read_text(encoding="utf-8")
        ass_lines = [l for l in ass_content.splitlines() if l.startswith("Dialogue: 0,")]
        check("ASS output contains both lines", len(ass_lines) == 2)

        # Parse ASS start/end times
        # Format: Dialogue: 0,0:00:02.00,0:00:03.96,SubtitleStyle...
        def parse_ass_time(ts_str: str) -> float:
            parts = ts_str.split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

        p1 = ass_lines[0].split(",")
        p2 = ass_lines[1].split(",")
        l1_end = parse_ass_time(p1[2])
        l2_start = parse_ass_time(p2[1])
        check("ASS subtitle 1 finishes before subtitle 2 starts", l1_end <= l2_start,
              f"{l1_end:.2f}s <= {l2_start:.2f}s")

        render.export_srt(sub_input, srt_path)
        srt_content = srt_path.read_text(encoding="utf-8")
        check("SRT output contains timestamps", "-->" in srt_content)

    print("── 3. Sample-Accurate Timeline Audio Assembly ───────────────")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        sr = 44100
        clip1_path = tmp_dir / "c1.wav"
        clip2_path = tmp_dir / "c2.wav"

        # 1.5s tone
        t1 = np.linspace(0, 1.5, int(1.5 * sr), endpoint=False)
        s1 = (np.sin(2 * np.pi * 400 * t1) * 16000).astype(np.int16)
        c1 = np.column_stack([s1, s1])
        with wave.open(str(clip1_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(c1.tobytes())

        # 1.0s tone
        t2 = np.linspace(0, 1.0, int(1.0 * sr), endpoint=False)
        s2 = (np.sin(2 * np.pi * 600 * t2) * 16000).astype(np.int16)
        c2 = np.column_stack([s2, s2])
        with wave.open(str(clip2_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(c2.tobytes())

        master_wav = tmp_dir / "master.wav"
        planned_lines = [
            PlannedLine(index=0, start=1.0, end=3.0, text="first line", target_seconds=2.0),
            PlannedLine(index=1, start=3.5, end=5.0, text="second line", target_seconds=1.5),
        ]
        clips = {0: clip1_path, 1: clip2_path}

        engine = tts.TTSEngine(cache_dir=tmp_dir)
        placed = engine._assemble_timeline(planned_lines, clips, 6.0, master_wav)

        check("master wav was created", master_wav.exists())
        with wave.open(str(master_wav), "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
            check("master wav duration is exact 6.0s", abs(dur - 6.0) < 0.01, f"{dur:.3f}s")
        check("clips were placed at exact timestamps",
              abs(placed[0][0] - 1.0) < 0.01 and abs(placed[1][0] - 3.5) < 0.01)

    print("── 4. Mode Separation (Recap vs Dialogue Dubbing) ────────────")
    prompt_dub = ai._chunk_prompt(0.0, 30.0, "my", "movie", "dialogue", 30.0)
    check("dialogue mode prompt enforces STRICT CHARACTER DIALOGUE DUBBING",
          "STRICT CHARACTER DIALOGUE DUBBING" in prompt_dub)
    check("dialogue mode tells model to leave silence silent",
          "LEAVE IT SILENT" in prompt_dub)

    prompt_recap = ai._chunk_prompt(0.0, 30.0, "my", "movie", "continuous", 30.0)
    check("recap mode prompt enforces CONTINUOUS MOVIE RECAP NARRATION",
          "CONTINUOUS MOVIE RECAP NARRATION" in prompt_recap)

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
