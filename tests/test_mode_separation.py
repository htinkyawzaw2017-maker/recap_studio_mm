"""v4.3.5 — recap and dubbing must produce genuinely different instructions.

The bug
-------
``_chunk_prompt()`` hard-coded this as MANDATORY rule 2, marked "THE MOST
IMPORTANT RULE", for **every** mode::

    2. COVER THE WHOLE CLIP ...
       * No silent window longer than 4 seconds anywhere ... where nothing is
         spoken, write short narration describing what is visibly happening so
         the voice-over never stops.

In dialogue/dubbing mode that flatly contradicts the dubbing block ("silence
stays silent"), and because it was flagged as the most important rule the model
followed it — so dubbing kept filling every gap and sounded exactly like a
recap. On top of that every entry in ``MODE_PROMPTS`` said "dub every spoken
line faithfully", so the genre dropdown changed nothing either. Result:
"bathing mode မကွဲပါ — ဘာရွေးရွေး တူနေတယ်".

These checks assert on the *generated prompt text*, which is the exact string
sent to Gemini, so they fail if the two modes ever converge again.

Run:  python tests/test_mode_separation.py   (no ffmpeg needed)
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio.ai import (COVERAGE_RULES, MODE_PROMPTS,  # noqa: E402
                            _chunk_prompt)

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


#: the sentence that used to leak into dubbing mode
CONTINUOUS_ONLY = "No silent window longer than 4 seconds"
DIALOGUE_ONLY = "DO NOT cover the whole clip"


def main() -> int:
    print("═" * 72)
    print("v4.3.5 — recap vs dubbing prompt separation")
    print("═" * 72)

    recap = _chunk_prompt(0.0, 60.0, "my", "auto", "continuous", 600.0)
    dub = _chunk_prompt(0.0, 60.0, "my", "auto", "dialogue", 600.0)

    print("\n── the coverage rule is mode specific ──")
    check("recap prompt keeps the 'no silence > 4s' rule", CONTINUOUS_ONLY in recap)
    check("dubbing prompt does NOT contain it", CONTINUOUS_ONLY not in dub,
          "this is what made dubbing sound like a recap")
    check("dubbing prompt forbids filling silence", DIALOGUE_ONLY in dub)
    check("dubbing prompt keeps silence silent", "silence stays silent" in dub)
    check("recap prompt tells the narrator to watch the action",
          "WATCH THE PICTURE" in recap)
    check("dubbing prompt is voiced as a voice actor", "professional voice actor" in dub)
    check("recap prompt is voiced as a recap narrator", "movie-recap narrator" in recap)

    print("\n── the two prompts really differ ──")
    ratio = difflib.SequenceMatcher(None, recap, dub).ratio()
    check("recap vs dubbing similarity below 0.90", ratio < 0.90, f"similarity={ratio:.3f}")
    differing = sum(1 for a, b in zip(recap.splitlines(), dub.splitlines()) if a != b)
    check("many lines differ", differing >= 5, f"{differing} differing lines")

    print("\n── genre dropdown is no longer a dubbing instruction ──")
    leaked = [k for k, v in MODE_PROMPTS.items() if "dub every" in v.lower()]
    check("no genre prompt says 'dub every ...'", not leaked, f"offenders={leaked}")
    for genre in MODE_PROMPTS:
        p = _chunk_prompt(0.0, 60.0, "my", genre, "continuous", 600.0)
        check(f"genre '{genre}' still yields a recap prompt",
              CONTINUOUS_ONLY in p and "dub every" not in p.lower())

    print("\n── every genre x mode combination builds ──")
    for genre in list(MODE_PROMPTS) + ["nonsense-key"]:
        for fill in ("continuous", "dialogue", "unknown-fill"):
            try:
                out = _chunk_prompt(10.0, 70.0, "my", genre, fill, 600.0)
                ok = bool(out) and "MANDATORY RULES" in out
            except Exception as exc:  # noqa: BLE001
                ok = False
                print(f"         {genre}/{fill} raised {exc}")
            check(f"prompt builds: genre={genre} fill={fill}", ok)

    print("\n── unknown fill_mode falls back to recap, not to a broken prompt ──")
    fallback = _chunk_prompt(0.0, 60.0, "my", "auto", "totally-unknown", 600.0)
    check("unknown fill_mode behaves like 'continuous'", CONTINUOUS_ONLY in fallback)
    check("COVERAGE_RULES covers both real modes",
          set(COVERAGE_RULES) == {"continuous", "dialogue"})

    print("\n── timestamps are still injected correctly ──")
    p = _chunk_prompt(120.0, 180.0, "my", "movie", "continuous", 600.0)
    check("chunk start appears", "120.00s" in p)
    check("'first entry by' is chunk_start+4", "124.00s" in p)
    check("'last entry after' is chunk_end-8", "172.00s" in p)
    d = _chunk_prompt(120.0, 180.0, "my", "movie", "dialogue", 600.0)
    check("dubbing prompt still knows the clip end", "180.00s" in d)

    print("\n" + "═" * 72)
    print(f"  {PASSED} passed, {FAILED} failed")
    print("═" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
