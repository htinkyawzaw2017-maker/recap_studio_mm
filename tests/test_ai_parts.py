"""Regression test for the AI *content part* bug (no network, no ffmpeg).

The production failure this locks down:

    [16:38:13] ⚠️ chunk 1 failed: AI request failed: file uri and mime_type are required.

Root cause: the analysis pipeline handed the SDK a raw ``pathlib.Path`` (for
small proxies) or whatever object ``files.upload()`` returned (for big ones).
google-genai does not accept either reliably:

* ``t_part(Path(...))``  → "Unsupported content part type" (1.20 – 2.x) or a
  silently *empty* part (1.0.x) — the video never reached the model.
* ``t_part(File(uri=..., mime_type=""))`` → exactly the message above.

Run:  .venv/bin/python tests/test_ai_parts.py
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
import tempfile
import types as pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.genai import _api_client as api_client  # noqa: E402
from google.genai import _transformers as T  # noqa: E402
from google.genai import types as gtypes  # noqa: E402

from recapstudio import ai  # noqa: E402

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


def t_contents(contents):
    """Call the SDK transformer (signature moved between versions)."""
    try:
        return T.t_contents(contents)  # type: ignore[call-arg]
    except TypeError:
        class _C:
            vertexai = False
        return T.t_contents(_C(), contents)  # type: ignore[call-arg]


def main() -> int:
    print(f"google-genai {__import__('google.genai', fromlist=['x']).__version__}")

    print("── what used to be sent ───────────────────────────────────")
    path = pathlib.Path("/tmp/does-not-matter.mp4")
    try:
        part = T.t_part(path)
        empty = getattr(part, "inline_data", None) is None and getattr(part, "file_data", None) is None
        check("a bare Path is rejected/dropped by the SDK", empty,
              "Path converted to an EMPTY part → video never analysed")
    except Exception as exc:
        check("a bare Path is rejected/dropped by the SDK", True, f"{type(exc).__name__}: {exc}")

    try:
        T.t_part(gtypes.File(name="files/x", uri="https://example/x", mime_type=""))
        check("a File without mime_type raises the production error", False, "no error raised")
    except ValueError as exc:
        check("a File without mime_type raises the production error",
              "file uri and mime_type are required" in str(exc), str(exc))

    print("── mime detection ─────────────────────────────────────────")
    check("mp4 → video/mp4", ai.video_mime("/x/proxy_ab.mp4") == "video/mp4")
    check("mov → quicktime", ai.video_mime("/x/clip.MOV") == "video/quicktime")
    check("unknown extension still yields a video mime",
          ai.video_mime("/x/weird.zzz").startswith("video/"))

    print("── the fix: inline part for small proxies ─────────────────")
    client = ai.GeminiClient(api_key="AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE")
    with tempfile.TemporaryDirectory() as tmp:
        small = Path(tmp) / "proxy_small.mp4"
        small.write_bytes(b"\x00" * 4096)
        part, ref = client.build_media_part(small, label="unit")
        check("no Files-API ref for a small proxy", ref is None)
        check("part is an SDK Part (not a Path)", not isinstance(part, pathlib.Path),
              type(part).__name__)
        inline = getattr(part, "inline_data", None)
        check("part carries inline video bytes", bool(inline and inline.data),
              f"{len(inline.data) if inline and inline.data else 0} bytes")
        check("part carries an explicit mime type", bool(inline and inline.mime_type == "video/mp4"),
              getattr(inline, "mime_type", None))
        # the real SDK transformation (no network) must accept it
        try:
            out = t_contents([part, "prompt"])
            got = out[0].parts[0]
            ok = bool(got.inline_data and got.inline_data.data and got.inline_data.mime_type == "video/mp4")
            check("SDK transformer accepts the part", ok,
                  f"mime={getattr(got.inline_data, 'mime_type', None)}")
        except Exception as exc:
            check("SDK transformer accepts the part", False, f"{type(exc).__name__}: {exc}")

        print("── the fix: Files API part when a ref comes back broken ──")
        # a server/SDK that returns a File *without* mime_type used to fail here
        calls: list = []
        broken = gtypes.File(name="files/abc", uri="https://files.example/abc",
                             state=gtypes.FileState.ACTIVE)  # no mime_type — the broken part

        class _Files:
            def upload(self, file=None, config=None):
                calls.append(("upload", config))
                return broken

            def get(self, name=None, config=None):
                calls.append(("get", name))
                return broken

            def delete(self, name=None):
                return None

        class _Models:
            def generate_content(self, model=None, contents=None, config=None):
                calls.append(("generate", contents))
                return pytypes.SimpleNamespace(text='{"dialogues": []}')

        class _Client:
            def __init__(self, api_key=""):
                self.files = _Files()
                self.models = _Models()

        fake_sdk = pytypes.SimpleNamespace(Client=_Client, types=gtypes, __version__="fake")
        orig_loader = ai._load_sdk
        orig_limit = ai.INLINE_PART_LIMIT
        try:
            ai._load_sdk = lambda: (fake_sdk, True)  # type: ignore[assignment]
            ai.INLINE_PART_LIMIT = 0                 # force the Files-API branch
            c2 = ai.GeminiClient(api_key="AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE")
            part2, ref2 = c2.build_media_part(small, label="big")
            fd = getattr(part2, "file_data", None)
            check("uri is taken from the ref", bool(fd and fd.file_uri),
                  getattr(fd, "file_uri", None))
            check("mime type is filled in even when the ref has none",
                  bool(fd and fd.mime_type == "video/mp4"), getattr(fd, "mime_type", None))
            check("the ref is returned for cleanup", ref2 is broken)
            check("upload passes the mime type explicitly",
                  any(c[0] == "upload" and (c[1] or {}).get("mime_type") == "video/mp4" for c in calls),
                  str([c for c in calls if c[0] == "upload"])[:80])

            out = c2.generate_json("gemini-2.5-flash", [part2, "prompt"])
            gen = [c for c in calls if c[0] == "generate"]
            handed = gen[-1][1][0] if gen else None
            check("generate_json hands over the prepared part", isinstance(handed, gtypes.Part),
                  type(handed).__name__)
            check("generation succeeded with a broken-ref SDK", out.strip() == '{"dialogues": []}', out[:40])

            # a ref with no uri at all must fail loudly, not silently
            class _NoUri(_Client):
                def __init__(self, api_key=""):
                    super().__init__(api_key)
                    self.files = _Files()
                    self.files.upload = lambda file=None, config=None: gtypes.File(
                        name="files/nouri", state=gtypes.FileState.ACTIVE)
                    self.files.get = lambda name=None, config=None: gtypes.File(
                        name="files/nouri", state=gtypes.FileState.ACTIVE)
            fake_sdk.Client = _NoUri
            c3 = ai.GeminiClient(api_key="AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE")
            try:
                c3.build_media_part(small, label="big")
                check("a ref without uri raises a clear error", False, "no error raised")
            except RuntimeError as exc:
                check("a ref without uri raises a clear error", "file uri" in str(exc), str(exc)[:70])
        finally:
            ai._load_sdk = orig_loader  # type: ignore[assignment]
            ai.INLINE_PART_LIMIT = orig_limit

    print("── what now goes over the wire (real SDK, captured HTTP) ──")
    with tempfile.TemporaryDirectory() as tmp:
        proxy = Path(tmp) / "proxy_wire.mp4"
        proxy.write_bytes(b"\x00\x11" * 4096)
        wire_client = ai.GeminiClient(api_key="AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE")
        wire_part, _ = wire_client.build_media_part(proxy, label="wire")
        captured: dict = {}

        def _fake_request(http_method, path, request_dict, http_options=None):
            captured.update(method=http_method, path=path, body=request_dict)
            reply = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
            return api_client.SdkHttpResponse(headers={}, body=json.dumps(reply))

        wire_client._client._api_client.request = _fake_request  # type: ignore[union-attr]
        out = wire_client.generate_json("gemini-2.5-flash", [wire_part, "prompt here"])
        parts = (captured.get("body") or {}).get("contents", [{}])[0].get("parts", [])
        inline = (parts[0].get("inlineData") or parts[0].get("inline_data") or {}) if parts else {}
        mime = inline.get("mimeType") or inline.get("mime_type")
        check("request body carries the video inline", bool(inline.get("data")), f"{len(inline.get('data') or '')} b64 chars")
        check("request body mime is video/mp4", mime == "video/mp4", str(mime))
        check("prompt still travels as text", bool(parts) and parts[1].get("text") == "prompt here")
        check("generation returned the model text", (out or "").strip() == "OK", out[:30])

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
