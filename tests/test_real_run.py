"""A *real* (non-demo) analysis run, offline.

Every local suite used to run with ``RECAP_DEMO_MODE=1``, which returns before
the code that talks to Gemini. Two bugs shipped straight through that gap:

* v4.1   — the part handed to the SDK was a ``pathlib.Path``
           → "file uri and mime_type are required."
* v4.1.1 — a log line read ``self.sdk`` inside ``TimelineExtractor``
           → "FAILED: 'TimelineExtractor' object has no attribute 'sdk'"

This test drives ``extract_timeline`` with demo mode **off** and a stub
GeminiClient: the real ``build_media_part`` still builds the media part, only
the HTTP call and the proxy encode are replaced. Any undefined attribute,
signature mismatch or bad content part in the analysis path fails here.

Run:  .venv/bin/python tests/test_real_run.py
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import ai, config  # noqa: E402

PASSED = 0
FAILED = 0
LOGS: list[str] = []
PARTS: list = []
CALLS: list[dict] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}" + (f" — {extra}" if extra else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


@dataclasses.dataclass
class _Patch:
    changes: dict

    def __enter__(self):
        self.old = {k: getattr(config.settings, k) for k in self.changes}
        for key, value in self.changes.items():
            object.__setattr__(config.settings, key, value)  # frozen dataclass
        return self

    def __exit__(self, *exc):
        for key, value in self.old.items():
            object.__setattr__(config.settings, key, value)
        return False


def fake_proxy(video_path, start, end, out_path, progress=None):
    """Stand-in for the ffmpeg proxy encode (no ffmpeg needed)."""
    Path(out_path).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
    return Path(out_path)


class StubClient:
    """Real media-part building, offline 'model' answers."""

    def __init__(self, api_key: str = "", key_ring=None, on_switch=None):
        self.api_key = api_key
        self.key_ring = key_ring
        self.on_switch = on_switch
        self.slot = 3
        self.sdk = types.SimpleNamespace(__version__="9.9.9-test")
        self._real = REAL_CLIENT(api_key=api_key or "AIzaSy" + "x" * 33)
        self.switches: list[str] = []

    # the extractor calls exactly these three
    def build_media_part(self, path, label="", progress=None):
        return self._real.build_media_part(path, label=label, progress=progress)

    def generate_json(self, model, parts, schema=None, progress=None,
                      cancel=None, **kwargs):
        CALLS.append({"model": model, "parts": parts, "schema": schema, **kwargs})
        for part in parts:
            PARTS.append(part)
        prompt = next((p for p in parts if isinstance(p, str)), "")
        window = re.search(r"(\d+(?:\.\d+)?)s\s*[–-]\s*(\d+(?:\.\d+)?)s", prompt)
        if window:
            start, end = float(window.group(1)), float(window.group(2))
        else:
            start, end = 0.0, 90.0
        if schema is ai.GAP_FILL_SCHEMA:
            return json.dumps({"lines": []})
        lines = []
        cursor = start
        while cursor < end:
            lines.append({"start": round(cursor, 2), "end": round(min(end, cursor + 2.5), 2),
                          "speaker": "A", "text": f"line at {cursor:.0f}s"})
            cursor += 3.0
        return json.dumps({"hook_line1": "ဒီအပိုင်းမှာ ကြည့်ပါ",
                           "hook_line2": "", "dialogues": lines})

    def delete(self, ref) -> None:
        return None

    def rotate_key(self, error) -> bool:
        return False


REAL_CLIENT = ai.GeminiClient


def main() -> int:
    print("── non-demo analysis run (offline) ────────────────────────")
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "clip.mp4"
        video.write_bytes(b"\x00" * 4096)

        original_client = ai.GeminiClient
        original_proxy = ai.build_proxy
        ai.GeminiClient = StubClient              # type: ignore[assignment]
        ai.build_proxy = fake_proxy               # type: ignore[assignment]
        try:
            with _Patch({"demo_mode": False}):
                result = ai.extract_timeline(
                    "AIzaSy" + "k" * 33, str(video), 90.67,
                    language="my", mode="movie", fill_mode="dialogue",
                    model="gemini-2.5-flash", log_fn=LOGS.append,
                )
        finally:
            ai.GeminiClient = original_client     # type: ignore[assignment]
            ai.build_proxy = original_proxy       # type: ignore[assignment]

    check("the run completed", isinstance(result, dict) and bool(result.get("dialogues")),
          f"{len(result.get('dialogues') or [])} lines")
    check("the key/model log line was emitted",
          any("🔑 Using Gemini key #3" in line and "gemini-2.5-flash" in line for line in LOGS),
          next((l for l in LOGS if "🔑" in l), "(missing)"))
    check("the log line names the google-genai version",
          any("google-genai 9.9.9-test" in line for line in LOGS))
    check("chunk analysis actually called the model", len(CALLS) >= 1, f"{len(CALLS)} call(s)")

    print("── content parts handed to the SDK ────────────────────────")
    paths = [p for p in PARTS if isinstance(p, (pathlib.Path, pathlib.PurePath))]
    check("no pathlib.Path ever reaches the model", not paths, str(paths[:1]))
    media = [p for p in PARTS if not isinstance(p, str)]
    check("media parts were sent", len(media) >= 1, f"{len(media)} part(s)")
    mimes = []
    for part in media:
        blob = getattr(part, "inline_data", None)
        file_data = getattr(part, "file_data", None)
        mimes.append(getattr(blob or file_data, "mime_type", None))
    check("every media part carries a mime type", all(m == "video/mp4" for m in mimes), str(mimes))

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
