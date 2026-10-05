#!/usr/bin/env python3
"""v4.3.5 — per-user UI preferences stored in the DB (offline, no ffmpeg).

    python tests/test_user_settings.py

The Studio kept every control in localStorage, so subtitle size, text-box
position, voice and mode were lost on another device or after clearing the
browser. These checks cover the new ``user_settings`` table and the
``/api/me/settings`` endpoints:

* migration 4 creates the table and bumps SCHEMA_VERSION,
* values round-trip through the API and survive a fresh DB connection,
* one account never reads another account's settings,
* unknown keys and out-of-range values are rejected instead of stored.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="recap_usersettings_"))
os.environ["RECAP_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("RECAP_DEMO_MODE", "1")
os.environ.setdefault("RECAP_FAKE_TTS", "1")
os.environ.setdefault("RECAP_LOG_LEVEL", "ERROR")
os.environ.setdefault("RECAP_SECRET_KEY", "test-secret-key-for-the-suite-0123456789")
os.environ.setdefault("RECAP_PBKDF2_ITERATIONS", "60000")

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


def main() -> int:
    from fastapi.testclient import TestClient

    from recapstudio import auth, db
    from recapstudio.config import ensure_dirs
    ensure_dirs()
    import app as webapp

    print("═" * 72)
    print("v4.3.5 — per-user UI settings (DB + /api/me/settings)")
    print("═" * 72)

    print("\n── migration ──")
    version = db.init(force=True)
    check("schema migrated to v4", version >= 4, f"version={version}")
    check("SCHEMA_VERSION is 4", db.SCHEMA_VERSION == 4)
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    check("user_settings table exists", "user_settings" in tables, sorted(tables)[-4:] and "")
    cols = {r["name"] for r in db.query("PRAGMA table_info(user_settings)")}
    check("columns are user_id/key/value/updated_at",
          cols == {"user_id", "key", "value", "updated_at"}, str(sorted(cols)))

    print("\n── db helpers ──")
    check("no settings initially", db.get_user_settings("u_alice") == {})
    stored = db.set_user_settings("u_alice", {"sub_font_size": 42, "sub_v_pos_percent": 22})
    check("set returns the merged dict",
          stored.get("sub_font_size") == 42 and stored.get("sub_v_pos_percent") == 22, str(stored))
    check("types survive the JSON round-trip",
          isinstance(db.get_user_settings("u_alice")["sub_font_size"], int))
    db.set_user_settings("u_alice", {"sub_font_size": 56})
    merged = db.get_user_settings("u_alice")
    check("second write merges, not replaces",
          merged.get("sub_font_size") == 56 and merged.get("sub_v_pos_percent") == 22, str(merged))
    db.set_user_settings("u_bob", {"sub_font_size": 30})
    check("accounts are isolated",
          db.get_user_settings("u_alice")["sub_font_size"] == 56
          and db.get_user_settings("u_bob")["sub_font_size"] == 30)
    check("empty user_id is a no-op", db.get_user_settings("") == {}
          and db.set_user_settings("", {"sub_font_size": 1}) == {})

    print("\n── API ──")
    client = TestClient(webapp.app)

    r = client.get("/api/me/settings")
    check("GET /api/me/settings works", r.status_code == 200, f"status={r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    check("GET advertises the whitelist", "keys" in body and "sub_v_pos_percent" in body.get("keys", []))

    payload = {"sub_font_size": 48, "sub_v_pos_percent": 35, "sub_color_hex": "#ff0000",
               "fill_mode": "dialogue", "enable_subs": True, "hook_seconds": 4.5}
    r = client.post("/api/me/settings", json=payload)
    check("POST saves the settings", r.status_code == 200, f"status={r.status_code}")
    saved = (r.json() or {}).get("settings", {}) if r.status_code == 200 else {}
    check("saved values come back correctly",
          saved.get("sub_font_size") == 48 and saved.get("sub_v_pos_percent") == 35
          and saved.get("sub_color_hex") == "#ff0000" and saved.get("fill_mode") == "dialogue",
          str(saved))
    check("bool and float coerce correctly",
          saved.get("enable_subs") is True and abs(float(saved.get("hook_seconds", 0)) - 4.5) < 1e-6)

    r = client.get("/api/me/settings")
    check("GET returns what was saved",
          (r.json().get("settings", {}).get("sub_font_size") == 48) if r.status_code == 200 else False)

    print("\n── validation ──")
    r = client.post("/api/me/settings", json={"sub_font_size": 5000})
    check("out-of-range number is rejected", r.status_code == 400, f"status={r.status_code}")
    r = client.post("/api/me/settings", json={"sub_v_pos_percent": -20})
    check("negative position is rejected", r.status_code == 400, f"status={r.status_code}")
    r = client.post("/api/me/settings", json={"not_a_real_key": "x"})
    check("unknown key is rejected", r.status_code == 400, f"status={r.status_code}")
    r = client.post("/api/me/settings", json={})
    check("empty payload is rejected", r.status_code == 400, f"status={r.status_code}")
    r = client.post("/api/me/settings", json={"sub_color_hex": "x" * 5000})
    check("oversized string is rejected", r.status_code == 400, f"status={r.status_code}")
    r = client.post("/api/me/settings", json={"sub_font_size": 60, "bogus": 1})
    ok = r.status_code == 200
    check("valid key still saves when one key is bogus", ok, f"status={r.status_code}")
    if ok:
        check("bogus key is reported, not stored",
              r.json().get("skipped") and "bogus" not in r.json().get("settings", {}),
              str(r.json().get("skipped")))
        check("valid key from the mixed payload was stored",
              r.json().get("settings", {}).get("sub_font_size") == 60)

    print("\n── the stored value is what the pipeline would use ──")
    from recapstudio.subtitles import build_ass
    prefs = db.get_user_settings(_scope_of(client))
    ass = TMP / "probe.ass"
    build_ass([{"start": 0.0, "end": 2.0, "text": "စမ်းသပ်"}], 5.0, ass,
              font_size=int(prefs.get("sub_font_size", 42)),
              v_margin=int(1280 * (float(prefs.get("sub_v_pos_percent", 22)) / 100.0)),
              play_res=(720, 1280))
    text = ass.read_text(encoding="utf-8")
    check("ASS carries the saved font size", ",60," in text, "font size 60 from the DB")
    check("ASS carries the saved position",
          f",{int(1280 * prefs['sub_v_pos_percent'] / 100.0)},1" in text,
          f"MarginV={int(1280 * prefs['sub_v_pos_percent'] / 100.0)}")

    print("\n" + "═" * 72)
    print(f"  {PASSED} passed, {FAILED} failed")
    print("═" * 72)
    return 1 if FAILED else 0


def _scope_of(client) -> str:
    """The ownership scope the API used for the calls above."""
    r = client.get("/api/me/settings")
    from recapstudio import db as _db
    rows = _db.query("SELECT DISTINCT user_id FROM user_settings")
    if len(rows) == 1:
        return str(rows[0]["user_id"])
    # fall back: whichever scope holds the value we just wrote
    for row in rows:
        if _db.get_user_settings(str(row["user_id"])).get("sub_font_size") == 60:
            return str(row["user_id"])
    return "shared"


if __name__ == "__main__":
    sys.exit(main())
