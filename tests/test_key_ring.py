"""Recap Studio MM — API key ring regression test (no network, no ffmpeg).

Run:  .venv/bin/python tests/test_key_ring.py

Covers the "refresh လုပ်ရင် key ပျောက် / key switch လိုသည်" round:

  * up to three slots, masked in every API payload
  * a slot saved from the browser survives a restart (config file)
  * .env keys are read-only and always win over saved ones
  * choosing the active slot persists
  * quota/429 errors put a key on cooldown and switch to the next key —
    including inside :class:`recapstudio.ai.GeminiClient`
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import config, keys  # noqa: E402

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


@contextlib.contextmanager
def settings_patch(**changes):
    """Temporarily override fields on the frozen Settings instance."""
    original = config.settings
    config.settings = dataclasses.replace(original, **changes)
    try:
        yield config.settings
    finally:
        config.settings = original


def temp_config() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="recap-keys-"))
    return tmp / ".recap_config.json"


KEY_A = "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
KEY_B = "AIzaSyBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
KEY_C = "AIzaSyCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"


def main() -> int:
    print("── masking / slots ────────────────────────────────────────")
    ring = keys.KeyRing(config_file=temp_config(), size=3)
    check("empty ring reports no key", not ring.has_key())
    ring.update([{"slot": 1, "key": KEY_A}, {"slot": 2, "key": KEY_B}])
    public = ring.describe()
    check("two slots filled", sum(1 for k in public["keys"] if k["set"]) == 2)
    raw = json.dumps(public)
    check("raw key never appears in the public payload", KEY_A not in raw and KEY_B not in raw)
    check("public payload is masked", "AIzaSy" in public["keys"][0]["masked"] and "AAAA" in public["keys"][0]["masked"],
          public["keys"][0]["masked"])
    check("size capped at three", public["max_keys"] == 3)

    print("── persistence (page refresh / restart) ───────────────────")
    ring2 = keys.KeyRing(config_file=ring.config_file, size=3)
    check("keys survive a reload", ring2.has_key() and len(ring2.all_keys()) == 2)
    check("slot 1 key identical after reload", ring2.slots[0].key == KEY_A)

    print("── activation ─────────────────────────────────────────────")
    ring2.activate(2)
    check("activate() switches the active slot", ring2.describe()["active_slot"] == 2)
    check("active_key() follows the slot", ring2.active_key()[0] == KEY_B)
    ring3 = keys.KeyRing(config_file=ring2.config_file, size=3)
    check("active slot persists across restart", ring3.describe()["active_slot"] == 2)
    try:
        ring3.activate(3)
        check("activating an empty slot is refused", False, "no error raised")
    except ValueError as exc:
        check("activating an empty slot is refused", "Key #3" in str(exc), str(exc)[:60])

    print("── .env keys are read-only ────────────────────────────────")
    with settings_patch(gemini_api_key=KEY_C, gemini_api_key_2="", gemini_api_key_3=""):
        env_ring = keys.KeyRing(config_file=ring2.config_file, size=3)
        check("env key takes slot 1", env_ring.slots[0].key == KEY_C, env_ring.slots[0].key[:12])
        check("env slot is flagged read_only", env_ring.describe()["keys"][0]["read_only"] is True)
        env_ring.update([{"slot": 1, "key": KEY_A}])
        check("env slot cannot be overwritten from the browser", env_ring.slots[0].key == KEY_C)
        check("all_keys() puts the active slot first",
              env_ring.all_keys()[0] == env_ring.active_key()[0])

    print("── quota failover ─────────────────────────────────────────")
    with settings_patch(api_key_failover=True, api_key_cooldown=60,
                            gemini_api_key="", gemini_api_key_2="", gemini_api_key_3=""):
        ring4 = keys.KeyRing(config_file=temp_config(), size=3)
        ring4.update([{"slot": 1, "key": KEY_A}, {"slot": 2, "key": KEY_B}, {"slot": 3, "key": KEY_C}])
        ring4.activate(1)
        messages: list[str] = []
        nxt = ring4.rotate_after_failure(1, "429 RESOURCE_EXHAUSTED: quota exceeded", messages.append)
        check("rotate returns the next key", nxt == KEY_B, str(nxt)[:12])
        check("active slot moved to #2", ring4.describe()["active_slot"] == 2)
        check("switch is announced to the UI log", bool(messages) and "Key #2" in messages[0], messages[0] if messages else "")
        check("failed key reports a cooldown", ring4.describe()["keys"][0]["cooldown_seconds"] > 0)
        nxt2 = ring4.rotate_after_failure(2, "429 quota", None)
        check("a second failure moves on to #3", nxt2 == KEY_C)
        nxt3 = ring4.rotate_after_failure(3, "429 quota", None)
        check("no healthy key left returns None", nxt3 is None)
        ring4.clear_cooldown(1)
        check("clear_cooldown() makes a key usable again",
                  ring4.describe()["keys"][0]["cooldown_seconds"] == 0)

    print("── failover inside GeminiClient (fake SDK) ────────────────")
    from recapstudio import ai

    class _FakeModels:
        def __init__(self, key: str, sink: list):
            self.key = key
            self.sink = sink

        def generate_content(self, model=None, contents=None, config=None):
            self.sink.append(self.key)
            if self.key == KEY_A:
                raise RuntimeError("429 RESOURCE_EXHAUSTED: You exceeded your current quota")
            return type("R", (), {"text": '{"dialogues": []}'})()

    class _FakeClient:
        def __init__(self, api_key=""):
            self.models = _FakeModels(api_key, calls)

    class _FakeSDK:
        Client = _FakeClient

    calls: list[str] = []
    saved_loader = ai._load_sdk
    original_settings = config.settings
    try:
        ai._load_sdk = lambda: (_FakeSDK, True)  # type: ignore[assignment]
        config.settings = dataclasses.replace(config.settings, gemini_api_key="",
                                              gemini_api_key_2="", gemini_api_key_3="")
        ring5 = keys.KeyRing(config_file=temp_config(), size=3)
        ring5.update([{"slot": 1, "key": KEY_A}, {"slot": 2, "key": KEY_B}])
        ring5.activate(1)
        notices: list[str] = []
        client = ai.GeminiClient(key_ring=ring5, on_switch=notices.append)
        out = client.generate_json("gemini-2.5-flash", ["prompt"])
        check("client survived the bad key", out.strip().startswith("{"), out[:40])
        check("client retried with the next key", calls == [KEY_A, KEY_B], str([c[:8] for c in calls]))
        check("client announced the switch", bool(notices), notices[0] if notices else "")
        check("client switched slot number", client.slot == 2, str(client.slot))
    finally:
        ai._load_sdk = saved_loader  # type: ignore[assignment]
        config.settings = original_settings

    print("── timing sanity ──────────────────────────────────────────")
    t0 = time.time()
    for _ in range(200):
        ring4.describe()
    check("describe() stays cheap (200 calls < 1s)", time.time() - t0 < 1.0, f"{time.time() - t0:.3f}s")

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
