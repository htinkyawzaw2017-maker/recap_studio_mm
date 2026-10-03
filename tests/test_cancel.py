"""Cancel semantics for real ffmpeg runs (offline, a few seconds).

The user reported "ရပ်မရ" (cancel did nothing). The job-level watchdog kills a
job's ffmpeg through the :data:`recapstudio.media.process_registry`; that kill
must surface as :class:`CancelledError` (a clean cancel), **not** as an
"FFmpeg error" — a crash used to trigger the renderer's "retry without burn-in"
fallback, i.e. a second encode for a job the user had just stopped.

Run:  .venv/bin/python tests/test_cancel.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import media  # noqa: E402
from recapstudio.util import CancelledError  # noqa: E402

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


def long_encode(seconds: int, out: Path) -> list[str]:
    """A single long frame is slow to encode and prints no -progress lines."""
    return ["-y", "-f", "lavfi",
            "-i", f"testsrc2=size=3840x2160:rate=25:duration={seconds}",
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", str(out)]


def run_case(label: str, seconds: int, cancelled: bool) -> tuple[str, str, float]:
    """Kill a running ffmpeg via the registry; report how it surfaced."""
    flag = {"cancel": False}
    with tempfile.TemporaryDirectory() as tmp:
        started = threading.Event()

        def killer() -> None:
            started.wait(5)
            time.sleep(0.8)
            if cancelled:
                flag["cancel"] = True          # jobs.py sets this *before* killing
            killed = media.process_registry.kill_owner("test-owner")
            print(f"    (killer: killed={killed}, cancel_flag={flag['cancel']})")

        thread = threading.Thread(target=killer, daemon=True)
        thread.start()
        started.set()
        began = time.time()
        try:
            media.run_ffmpeg(long_encode(seconds, Path(tmp) / "out.mp4"), total_duration=seconds,
                             label=label, check=True, owner="test-owner",
                             cancel=lambda: flag["cancel"])
            return "returned", "", time.time() - began
        except CancelledError as exc:
            return "cancelled", str(exc), time.time() - began
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__, str(exc)[:60], time.time() - began
        finally:
            thread.join(timeout=3)


def main() -> int:
    print("── cancel flag set (user pressed ⏹) ───────────────────────")
    kind, message, elapsed = run_case("cancel", 120, cancelled=True)
    check("killed ffmpeg surfaces as CancelledError", kind == "cancelled", f"{kind}: {message[:50]}")
    check("cancel is reported in Burmese", "ရပ်တန့်" in message, message[:40])
    check("cancel takes effect quickly", elapsed < 6.0, f"{elapsed:.2f}s")

    print("── cancel flag not set (unrelated ffmpeg death) ───────────")
    kind2, message2, _ = run_case("crash", 10, cancelled=False)
    check("a real ffmpeg failure is still an error", kind2 == "RuntimeError",
          f"{kind2}: {message2[:40]}")

    print("── registry bookkeeping ──────────────────────────────────")
    check("no ffmpeg left behind", media.process_registry.count() == 0,
          f"{media.process_registry.count()} registered")

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
