#!/usr/bin/env python3
"""Studio regression — narration budget, mode separation and even portrait proxies.

offline (network မလို၊ ffmpeg မလို) — 49 checks

    python tests/test_narration_fit.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("RECAP_DEMO_MODE", "1")
os.environ.setdefault("RECAP_FAKE_TTS", "1")

from recapstudio import ai, subtitles  # noqa: E402
import recapstudio.tts as tts_module  # noqa: E402
from recapstudio.tts import (PlannedLine, TTSEngine, budget_chars, chars_per_second,  # noqa: E402
                             condense_line, fit_lines_to_windows)

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


print("=== 1. speaking-rate budget ===")
check("Burmese rate is the measured 10.5 chars/s", abs(chars_per_second("my") - 10.5) < 0.01)
check("English is faster than Burmese", chars_per_second("en") > chars_per_second("my"))
check("unknown language falls back to Burmese", chars_per_second("xx") == chars_per_second("my"))
check("4s window ≈ 47 Burmese chars", 40 <= budget_chars(4.0, "my") <= 55, str(budget_chars(4.0, "my")))
check("budget scales with the window",
      budget_chars(8.0, "my") == 2 * budget_chars(4.0, "my"))
check("a zero window still allows a minimum", budget_chars(0.0, "my") >= 8)

print("\n=== 2. condensing an over-long line (#2) ===")
long_my = ("ဒီနေရာမှာတော့ ဇာတ်ကောင်ကြီးက သူ့ရဲ့ သူငယ်ချင်းတွေနဲ့ အတူတူ ခရီးဆက်ဖို့ ဆုံးဖြတ်လိုက်ပြီး၊ "
           "နောက်တစ်နေ့မနက်မှာ မြို့ကြီးဆီကို ထွက်ခွာသွားကြပါတယ်။ ဒါပေမယ့် လမ်းမှာ မမျှော်လင့်ထားတဲ့ "
           "အခက်အခဲတွေနဲ့ ရင်ဆိုင်ရပါတယ်။")
short, changed = condense_line(long_my, 4.0, "my")
check("a 4s window condenses a 3-sentence line", changed)
check("the result fits the budget (+1 for ။)",
      len(short) <= budget_chars(4.0, "my") + 1, f"{len(short)} ≤ {budget_chars(4.0, 'my') + 1}")
check("it still ends like a Burmese sentence", short.endswith("။"), short[-12:])
check("it keeps at least half of the budget",
      len(short) >= budget_chars(4.0, "my") * 0.5, str(len(short)))
kept, unchanged = condense_line("ဒီဇာတ်လမ်း စတင်ပါပြီ။", 8.0, "my")
check("a short line in a long window is untouched", unchanged is False and kept.endswith("။"))
en_short, en_changed = condense_line(
    "He walks into the room, sees the letter on the table, reads it twice and finally understands "
    "that his brother has been lying to him for years.", 3.0, "en")
check("English condenses too", en_changed and len(en_short) <= budget_chars(3.0, "en") + 1,
      f"{len(en_short)} chars")
check("English keeps sentence punctuation", en_short.endswith((".", "!", "?")), en_short[-14:])

print("\n=== 3. fitting a whole timeline ===")
timeline = [
    {"start": 0.0, "end": 4.0, "text": long_my},
    {"start": 4.0, "end": 6.0, "text": "သူတို့ ဘာလုပ်ကြမလဲ။"},
    {"start": 6.0, "end": 30.0, "text": long_my},
]
fitted, n = fit_lines_to_windows([dict(d) for d in timeline], 30.0, "my")
check("over-long lines are condensed", n == 1, f"{n} condensed")
check("the long window keeps its full text", fitted[2]["text"] == long_my)
check("the short window was shortened", len(fitted[0]["text"]) < len(long_my))
check("condensed lines are flagged for the UI", fitted[0].get("condensed") is True)
check("line order is preserved", [round(d["start"], 1) for d in fitted] == [0.0, 4.0, 6.0])
dubbed, dub_condensed = fit_lines_to_windows(
    [dict(d) for d in timeline], 30.0, "my", respect_end=True)
check("dialogue dubbing never condenses or rewrites source dialogue",
      dub_condensed == 0 and [d["text"] for d in dubbed] == [d["text"] for d in timeline])
engine = TTSEngine(cache_dir=Path(tempfile.mkdtemp(prefix="recap_tts_plan_")), workers=1)
strict_plan = engine.plan_lines([
    {"start": 0.0, "end": 2.0, "text": "First source utterance."},
    {"start": 10.0, "end": 12.0, "text": "Second source utterance."},
], 20.0, "en", strict_timing=True)
flex_plan = engine.plan_lines([
    {"start": 0.0, "end": 2.0, "text": "First recap line."},
    {"start": 10.0, "end": 12.0, "text": "Second recap line."},
], 20.0, "en", strict_timing=False)
check("dubbing is bounded by its own end, not the next speaker's start",
      strict_plan[0].hard_limit_seconds <= 2.0
      and strict_plan[0].target_seconds < 2.0,
      f"target={strict_plan[0].target_seconds:.2f}s hard={strict_plan[0].hard_limit_seconds:.2f}s")
check("recap mode can use its planned narration gap",
      flex_plan[0].target_seconds > strict_plan[0].target_seconds)
strict_line = PlannedLine(index=0, start=1.0, end=2.0, text="A source line.",
                          target_seconds=1.0, hard_limit_seconds=1.04)
rate_calls = []
original_duration = tts_module.get_media_duration
original_synthesize = engine.synthesize
def fake_tts(text, voice_cfg, out_mp3, rate_override=None):
    rate_calls.append(rate_override)
    Path(out_mp3).write_bytes(b"fake-mp3")
    return True
tts_module.get_media_duration = lambda path: 1.4
engine.synthesize = fake_tts
try:
    strict_output = engine._fit_to_window(
        strict_line, {"voice": "en-US-Test", "lang": "en"},
        Path(tempfile.mkdtemp(prefix="strict_tts_fit_")), "strict_test", strict_timing=True)
finally:
    tts_module.get_media_duration = original_duration
    engine.synthesize = original_synthesize
check("overlong dialogue is rejected rather than trimmed into a late line",
      strict_output is None and strict_line.skipped and not strict_line.trimmed)
check("dubbing speed-up is capped at 12%", "+12%" in rate_calls,
      ", ".join(str(rate) for rate in rate_calls))
check("every line can now be spoken calmly",
      all(len(d["text"]) <= budget_chars(
          (fitted[i + 1]["start"] if i + 1 < len(fitted) else 30.0) - d["start"], "my") + 2
          for i, d in enumerate(fitted)))

print("\n=== 4. the two modes are really different (#6) ===")
recap_prompt = ai._chunk_prompt(0.0, 60.0, "my", "movie", "continuous", 600.0)
dub_prompt = ai._chunk_prompt(0.0, 60.0, "my", "movie", "dialogue", 600.0)
check("recap mode asks for professional, visually grounded narration",
      "PROFESSIONAL MOVIE RECAP" in recap_prompt and "visible action" in recap_prompt)
check("recap tracks the visible action instead of translating every line",
      "story consequence" in recap_prompt and "do not translate every spoken line" in recap_prompt)
check("dubbing mode is audio-led and forbids invented narration",
      "source audio" in dub_prompt and "ONLY genuine audible speech" in dub_prompt)
check("dubbing mode forbids narration and gap filling",
      "DIALOGUE DUBBING" in dub_prompt and "no narrator voice" in dub_prompt
      and "never add a line to satisfy clip coverage" in dub_prompt)
check("dubbing mode demands precise speech boundaries", "0.3 seconds" in dub_prompt)
check("both prompts carry the real character budget",
      "characters per second" in recap_prompt and "characters per second" in dub_prompt)
check("the budget shown matches tts.budget_chars",
      str(budget_chars(4.0, "my")) in recap_prompt, str(budget_chars(4.0, "my")))
check("style rules ban filler phrases", "Avoid filler" in recap_prompt)

captured_proxy_args = {}
original_run_ffmpeg = ai.run_ffmpeg
def fake_run_ffmpeg(args, **kwargs):
    captured_proxy_args["args"] = args
    return None
ai.run_ffmpeg = fake_run_ffmpeg
try:
    ai.build_proxy("portrait.mp4", 0.0, 5.0,
                   Path(tempfile.gettempdir()) / "proxy_even_dimensions_test.mp4")
finally:
    ai.run_ffmpeg = original_run_ffmpeg
proxy_filter = captured_proxy_args["args"][captured_proxy_args["args"].index("-vf") + 1]
check("portrait proxy rounds both x264 dimensions to even values",
      "force_divisible_by=2" in proxy_filter and "pad=ceil(iw/2)*2:ceil(ih/2)*2" in proxy_filter,
      proxy_filter)
check("thumbnail AI schema includes frame, hook and text-side fields",
      {"timestamp", "headline", "subheadline", "text_position", "rationale"}
      <= set(ai.THUMBNAIL_SCHEMA["properties"]))
ass_path = Path(tempfile.gettempdir()) / "recap_subtitle_width_test.ass"
subtitles.build_ass([], 5.0, ass_path, play_res=(720, 1280), width_percent=80)
subtitle_style = next(line for line in ass_path.read_text(encoding="utf-8").splitlines()
                     if line.startswith("Style: SubtitleStyle,"))
check("burn-in default is 42px and text-box width changes ASS margins",
      ",42," in subtitle_style and subtitle_style.endswith(",2,72,72,280,1"),
      subtitle_style[-40:])
ass_path.unlink(missing_ok=True)

ex = ai.TimelineExtractor(api_key="", fill_mode="dialogue")
ex_cont = ai.TimelineExtractor(api_key="", fill_mode="continuous")
check("dialogue mode disables gap filling", ex._min_gap() > 1000, f"{ex._min_gap():.0f}s")
check("continuous mode still fills 2.5s holes", ex_cont._min_gap() == 2.5)
dialogues = [{"start": 0.0, "end": 2.0, "text": "မင်္ဂလာပါ။"}]
out, filled, longest = ex._coverage_sweep(list(dialogues), 120.0, "x.mp4")
check("dialogue mode adds nothing to the timeline", out == dialogues and filled == 0,
      f"{len(out)} lines, filled={filled}")
check("…but it still reports how much silence there is", longest > 100, f"{longest:.0f}s")

print("\n=== 5. link import hardening (#1) ===")
import app as webapp  # noqa: E402

n = webapp.normalise_media_url
check("youtu.be short link → watch?v=",
      n("https://youtu.be/dQw4w9WgXcQ?si=abc") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      n("https://youtu.be/dQw4w9WgXcQ?si=abc"))
check("playlist/timestamp params are dropped",
      n("https://www.youtube.com/watch?v=abc123DEF45&list=PL1&t=42s")
      == "https://www.youtube.com/watch?v=abc123DEF45")
check("shorts link works",
      n("https://www.youtube.com/shorts/XyZ12345678") == "https://www.youtube.com/watch?v=XyZ12345678")
check("m.youtube + live links work",
      n("https://m.youtube.com/live/AbCdEfGhIjK") == "https://www.youtube.com/watch?v=AbCdEfGhIjK")
check("non-YouTube links survive",
      n("https://vimeo.com/123456789").startswith("https://vimeo.com/123456789"))
check("there is a retry ladder, not a single attempt", len(webapp.YTDLP_ATTEMPTS) >= 4,
      ", ".join(label for label, _ in webapp.YTDLP_ATTEMPTS))
check("the android player is one of the fallbacks",
      any("android" in " ".join(args) for _, args in webapp.YTDLP_ATTEMPTS))
hint = webapp._ytdlp_error_hint("ERROR: Sign in to confirm you're not a bot")
check("bot-check failures explain the cookies fix", "RECAP_YTDLP_COOKIES" in hint, hint[:60])
check("outdated yt-dlp is detected",
      "pip install -U yt-dlp" in webapp._ytdlp_error_hint("nsig extraction failed"))
check("private videos get their own message",
      "သီးသန့်" in webapp._ytdlp_error_hint("ERROR: Private video. Sign in if you've been granted access"))

print("\n" + "=" * 58)
print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
