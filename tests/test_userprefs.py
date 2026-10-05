#!/usr/bin/env python3
"""SQLite-backed per-account Studio preference regression checks.

Run with ``python tests/test_userprefs.py``. No network or media tools needed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_DATA = Path(tempfile.mkdtemp(prefix="recap_userprefs_"))
os.environ["RECAP_DATA_DIR"] = str(TEST_DATA)
os.environ["RECAP_DB_PATH"] = str(TEST_DATA / "recap.db")
os.environ.setdefault("RECAP_SECRET_KEY", "userprefs-test-key-0123456789-abcdef")

from recapstudio import db, userprefs  # noqa: E402

checks = 0
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    db.reset_for_tests()
    version = db.init(force=True)
    defaults = userprefs.get("alice")
    check("schema v4 is current", version == db.SCHEMA_VERSION == 4, str(version))
    check("42px pop-up caption size is the default", defaults["sub_font_size"] == 42)
    check("caption width has a useful default", defaults["sub_width_percent"] == 90)

    saved = userprefs.save("alice", {
        "fill_mode": "dialogue",
        "sub_font_size": 56,
        "sub_width_percent": 76,
        "sub_v_pos_percent": 38,
        "sub_color_hex": "#AABBCC",
        "enable_subtitles": False,
    })
    check("preferences round-trip through SQLite", userprefs.get("alice") == saved)
    check("colour is canonicalised", saved["sub_color_hex"] == "#aabbcc")
    check("partial updates preserve unrelated values",
          userprefs.save("alice", {"sub_width_percent": 88})["fill_mode"] == "dialogue")
    check("another account cannot see those preferences",
          userprefs.get("bob")["fill_mode"] == "continuous"
          and userprefs.get("bob")["sub_width_percent"] == 90)
    clamped = userprefs.save("alice", {"sub_font_size": 200, "sub_width_percent": 1})
    check("slider values are clamped to supported limits",
          clamped["sub_font_size"] == 72 and clamped["sub_width_percent"] == 60)
    try:
        userprefs.save("alice", {"fill_mode": "narrate-everything"})
        rejected_mode = False
    except ValueError:
        rejected_mode = True
    check("unknown mode is rejected", rejected_mode)
    try:
        userprefs.save("alice", {"sub_color_hex": "not-a-colour"})
        rejected_colour = False
    except ValueError:
        rejected_colour = True
    check("malformed colour is rejected", rejected_colour)
    userprefs.delete("alice")
    check("account cleanup deletes the saved row", userprefs.get("alice") == defaults)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
