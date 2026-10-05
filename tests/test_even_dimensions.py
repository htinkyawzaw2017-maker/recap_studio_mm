"""v4.3.5 — libx264 "height not divisible by 2" regression test.

The bug
-------
``build_proxy()`` used::

    -vf scale=480:-2:force_original_aspect_ratio=decrease,fps=1

``-2`` means "compute the height and round it to an even number", but adding
``force_original_aspect_ratio`` cancels that rounding. A 720x1280 clip (what
the short splitter emits) scaled to 480 wide therefore came out as **480x853**
and libx264 aborted::

    [libx264 @ 0x...] height not divisible by 2 (480x853)
    [vost#0:0/libx264 @ 0x...] Error while opening encoder - maybe incorrect
    parameters such as bit_rate, rate, width or height.
    Conversion failed!

The user saw this during the rendering step of a *short splitter → Studio →
recap* job, because the proxy is (re)built for every analysis chunk.

What this file proves
---------------------
1. the OLD filter string still fails (so the test really detects the bug),
2. :data:`recapstudio.ai.PROXY_VF` encodes successfully and yields even
   dimensions for a 720x1280 source,
3. ``build_proxy()`` itself — the real function — succeeds on that source,
4. the render filter chain from ``render._video_filter_chain`` encodes,
5. the splitter's "no reframe" passthrough still works and stays even with
   the guard applied (defensive — see the note in section 5 of ``main``).

Run:  FFMPEG_BINARY=/path/to/ffmpeg python tests/test_even_dimensions.py
(skips itself when ffmpeg is not installed, like test_thumbs.py)
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recapstudio import media  # noqa: E402
from recapstudio.ai import PROXY_VF  # noqa: E402
from recapstudio.media import EVEN_DIMENSION_GUARD, with_even_dimensions  # noqa: E402
from recapstudio.render import _video_filter_chain  # noqa: E402

PASSED = 0
FAILED = 0

#: the exact filter string that shipped before v4.3.5
LEGACY_PROXY_VF = "scale=480:-2:force_original_aspect_ratio=decrease,fps=1"

_DIM_RE = re.compile(r"(\d{2,5})x(\d{2,5})")


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}" + (f" — {extra}" if extra else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([media.FFMPEG, "-hide_banner", "-nostdin", "-y", "-v", "error",
                           *args], capture_output=True, text=True, timeout=300)


def _make_clip(path: Path, width: int, height: int, *, seconds: float = 1.5,
               audio: bool = True, odd_ok: bool = False) -> bool:
    """Build a test clip. ``odd_ok`` uses ffv1, which accepts odd dimensions."""
    cmd = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=15:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if odd_ok:
        cmd += ["-map", "0:v", "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(path)]
    else:
        cmd += ["-map", "0:v"]
        if audio:
            cmd += ["-map", "1:a"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "64k"]
        cmd += [str(path)]
    return _run(cmd).returncode == 0


def _encode_with_vf(src: Path, vf: str, out: Path) -> tuple[int, str, tuple[int, int]]:
    """Encode ``src`` through ``vf``; return (rc, stderr, (w, h) of the output)."""
    proc = _run(["-i", str(src), "-vf", vf, "-frames:v", "1",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                 "-pix_fmt", "yuv420p", str(out)])
    dims = (0, 0)
    probe = subprocess.run([media.FFMPEG, "-hide_banner", "-i", str(out)],
                           capture_output=True, text=True, timeout=120)
    for line in probe.stderr.splitlines():
        if "Video:" in line:
            m = _DIM_RE.search(line)
            if m:
                dims = (int(m.group(1)), int(m.group(2)))
            break
    return proc.returncode, proc.stderr, dims


def main() -> int:
    print("═" * 72)
    print("v4.3.5 — even frame dimensions (libx264 'height not divisible by 2')")
    print("═" * 72)

    if not media.ffmpeg_available():
        print("  [SKIP] ffmpeg not found — set FFMPEG_BINARY to run these checks")
        return 0

    # ── 1. pure-function behaviour of the guard ──────────────────────────
    print("\n── guard helper ──")
    check("guard is appended to a normal chain",
          with_even_dimensions("scale=1280:720") == f"scale=1280:720,{EVEN_DIMENSION_GUARD}",
          with_even_dimensions("scale=1280:720"))
    check("None / empty yields the bare guard",
          with_even_dimensions(None) == EVEN_DIMENSION_GUARD
          and with_even_dimensions("") == EVEN_DIMENSION_GUARD)
    check("'null' (no reframe) is replaced by the guard",
          with_even_dimensions("null") == EVEN_DIMENSION_GUARD,
          "an odd source used to reach libx264 untouched here")
    check("guard is idempotent",
          with_even_dimensions(with_even_dimensions("scale=1:1"))
          == with_even_dimensions("scale=1:1"))
    check("PROXY_VF carries the guard", EVEN_DIMENSION_GUARD in PROXY_VF, PROXY_VF)
    check("PROXY_VF keeps the 480p + 1fps intent",
          "480" in PROXY_VF and "fps=1" in PROXY_VF)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # ── 2. the reported failure: 720x1280 (a short-splitter part) ────
        src = tmpdir / "part_720x1280.mp4"
        if not _make_clip(src, 720, 1280):
            print("  [SKIP] could not build a 720x1280 test clip")
            return 1

        print("\n── the reported case: 720x1280 source ──")
        rc_old, err_old, _ = _encode_with_vf(src, LEGACY_PROXY_VF, tmpdir / "old.mp4")
        reproduced = "not divisible by 2" in err_old
        check("old filter string reproduces the bug",
              reproduced and rc_old != 0,
              "480x853" if reproduced else "bug NOT reproduced — test is stale")

        rc_new, err_new, dims_new = _encode_with_vf(src, PROXY_VF, tmpdir / "new.mp4")
        check("PROXY_VF encodes successfully", rc_new == 0,
              (err_new.strip().splitlines() or [""])[0][:120] if rc_new else f"{dims_new[0]}x{dims_new[1]}")
        check("PROXY_VF output height is even",
              dims_new[1] % 2 == 0 and dims_new[0] % 2 == 0,
              f"{dims_new[0]}x{dims_new[1]}")
        check("PROXY_VF still downscales to 480 wide", dims_new[0] == 480,
              f"width={dims_new[0]}")

        # ── 3. build_proxy() itself, the real function ───────────────────
        print("\n── build_proxy() end to end ──")
        from recapstudio.ai import build_proxy
        proxy = tmpdir / "proxy.mp4"
        try:
            build_proxy(src, 0.0, 1.5, proxy)
            built = proxy.exists() and proxy.stat().st_size > 2048
        except Exception as exc:  # noqa: BLE001 - any failure is a test failure
            built = False
            print(f"         build_proxy raised: {exc}")
        check("build_proxy() succeeds on a 720x1280 source", built,
              f"{proxy.stat().st_size} bytes" if built else "no proxy written")

        # ── 4. render filter chain ───────────────────────────────────────
        print("\n── render._video_filter_chain ──")
        for reframe, tw, th in (("Smart Blur Background", 480, 854),
                                ("Center Crop", 720, 1280),
                                ("Original (no reframe)", 720, 1280)):
            chain, label = _video_filter_chain(reframe, tw, th, None, None, None)
            proc = _run(["-i", str(src), "-filter_complex", chain, "-map", f"[{label}]",
                         "-frames:v", "1", "-c:v", "libx264", "-preset", "ultrafast",
                         "-pix_fmt", "yuv420p", str(tmpdir / "r.mp4")])
            check(f"chain encodes: {reframe} @ {tw}x{th}", proc.returncode == 0,
                  (proc.stderr.strip().splitlines() or [""])[0][:120])

        # ── 5. non-standard aspect source (the splitter's "no reframe" path)
        #
        # NOTE: an odd-*sized* source could not be produced for this test —
        # every encoder tried (libx264, ffv1) normalises yuv420p to even
        # dimensions on the way in, so a 481x857 request came back 480x856.
        # The guard on the "no reframe" path is therefore defensive rather
        # than a fix for a reproduced failure; what is asserted here is that
        # it does not break the passthrough and still yields even frames.
        print("\n── non-standard aspect source, no reframe ──")
        odd = tmpdir / "odd_481x857.mkv"
        if _make_clip(odd, 481, 857, audio=False, odd_ok=True):
            rc, err, dims = _encode_with_vf(odd, with_even_dimensions("null"),
                                            tmpdir / "odd_out.mp4")
            check("passthrough with the guard encodes", rc == 0,
                  (err.strip().splitlines() or [""])[0][:120] if rc else f"{dims[0]}x{dims[1]}")
            check("passthrough output is even", dims[0] % 2 == 0 and dims[1] % 2 == 0,
                  f"{dims[0]}x{dims[1]}")
        else:
            print("  [SKIP] could not build the non-standard-aspect source")

    print("\n" + "═" * 72)
    print(f"  {PASSED} passed, {FAILED} failed")
    print("═" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
