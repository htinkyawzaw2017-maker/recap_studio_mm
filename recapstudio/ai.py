"""Gemini powered timeline extraction with guaranteed full-video coverage.

Root causes fixed here
----------------------
1. **Analysis stopped early.** One single ``generate_content`` call over the
   whole video with ``max_output_tokens=8192`` simply ran out of output
   tokens on anything longer than a few minutes, so the timeline ended
   mid-video and the dub never reached the end.
2. **Timestamps drifted.** With no offset handling, lines from the second
   half of a long video came back relative to nothing in particular.
3. **One giant upload.** The full-resolution source video was uploaded to
   the Files API for every attempt: slow, quota hungry and frequently
   rejected for long clips.

Now the video is analysed in **parallel, frame-accurate low-cost proxies**
(1 fps, 480p, mono 16 kHz - exactly the sampling Gemini uses internally), each
chunk is asked for timestamps *relative to its own start* which are then
shifted by the chunk offset, and a coverage sweep fills whatever windows the
model left empty so the narration really does run from 0 s to the end.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import config
from .media import run_ffmpeg
from .util import estimate_speech_seconds, get_logger

log = get_logger("recap.ai")

ProgressFn = Optional[Callable[[float, str], None]]

MODEL_ALIASES = {
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.0-flash": "gemini-2.0-flash",
    "gemini-1.5-flash": "gemini-2.5-flash",   # retired upstream -> remap
    "gemini-1.5-pro": "gemini-2.5-pro",
    "gemini-2.0-flash-exp": "gemini-2.0-flash",
}

DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_line1": {"type": "string"},
        "hook_line2": {"type": "string"},
        "dialogues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["start", "end", "text"],
            },
        },
    },
    "required": ["dialogues"],
}

GAP_FILL_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["index", "text"],
            },
        }
    },
    "required": ["lines"],
}


@dataclass
class CoverageReport:
    total_seconds: float = 0.0
    spoken_seconds: float = 0.0
    lines: int = 0
    gaps_filled: int = 0
    longest_gap: float = 0.0
    chunks: int = 0
    per_chunk: list[dict] = None  # type: ignore[assignment]

    def as_dict(self) -> dict:
        pct = (self.spoken_seconds / self.total_seconds * 100.0) if self.total_seconds else 0.0
        return {
            "total_seconds": round(self.total_seconds, 2),
            "spoken_seconds": round(self.spoken_seconds, 2),
            "coverage_percent": round(pct, 1),
            "lines": self.lines,
            "gaps_filled": self.gaps_filled,
            "longest_gap_seconds": round(self.longest_gap, 2),
            "chunks": self.chunks,
            "per_chunk": self.per_chunk or [],
        }


# ── SDK shim ─────────────────────────────────────────────────────────────
def _load_sdk():
    try:
        from google import genai  # type: ignore
        return genai, True
    except ImportError:
        try:
            import google.generativeai as legacy  # type: ignore
            return legacy, False
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "google-genai package မတွေ့ပါ။ `pip install google-genai` လုပ်ပေးပါ။"
            ) from exc


class GeminiClient:
    """Thin wrapper handling both the new and legacy Google SDKs."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API Key ထည့်သွင်းပေးရန် လိုအပ်ပါသည် ချင်ဗျာ။")
        self.api_key = api_key
        self.sdk, self.is_new = _load_sdk()
        self._client = self.sdk.Client(api_key=api_key) if self.is_new else None
        if not self.is_new:
            self.sdk.configure(api_key=api_key)  # type: ignore[attr-defined]

    # -- file handling -------------------------------------------------
    def upload(self, path: str | Path, progress: ProgressFn = None, label: str = ""):
        if progress:
            progress(8, f"📤 {label or 'ဗီဒီယို'} ကို AI server သို့ ပေးပို့နေပါသည်...")
        if self.is_new:
            ref = self._client.files.upload(file=str(path))  # type: ignore[union-attr]
            waited = 0.0
            while True:
                ref = self._client.files.get(name=ref.name)  # type: ignore[union-attr]
                state = str(getattr(ref, "state", "")).upper()
                if "PROCESSING" in state or "PENDING" in state:
                    time.sleep(2)
                    waited += 2
                    if progress:
                        progress(12, f"⏳ AI မှ {label or 'ဗီဒီယို'} ကို ပြင်ဆင်နေပါသည် ({int(waited)}s)...")
                    if waited > 600:
                        raise RuntimeError("AI server မှ ဗီဒီယို ပြင်ဆင်ချိန် ကြာလွန်းနေပါသည်")
                    continue
                if "ACTIVE" in state or state == "":
                    return ref
                raise RuntimeError(f"AI server video processing failed: {state}")
        ref = self.sdk.upload_file(path=str(path))  # type: ignore[attr-defined]
        waited = 0.0
        while True:
            ref = self.sdk.get_file(ref.name)  # type: ignore[attr-defined]
            state = str(getattr(ref.state, "name", ref.state)).upper()
            if "PROCESSING" in state:
                time.sleep(2)
                waited += 2
                if waited > 600:
                    raise RuntimeError("AI server မှ ဗီဒီယို ပြင်ဆင်ချိန် ကြာလွန်းနေပါသည်")
                continue
            if "ACTIVE" in state:
                return ref
            raise RuntimeError(f"AI server video processing failed: {state}")

    def delete(self, ref) -> None:
        try:
            if ref is None:
                return
            if self.is_new:
                self._client.files.delete(name=ref.name)  # type: ignore[union-attr]
            else:
                self.sdk.delete_file(ref.name)  # type: ignore[attr-defined]
        except Exception as exc:  # quota cleanup is best effort
            log.debug("file delete failed: %s", exc)

    # -- generation ----------------------------------------------------
    def generate_json(self, model: str, parts: list, schema: dict | None = None,
                      temperature: float = 0.2, max_tokens: int | None = None,
                      progress: ProgressFn = None, cancel: Callable[[], bool] | None = None) -> str:
        model = MODEL_ALIASES.get(model, model)
        max_tokens = max_tokens or config.settings.ai_max_output_tokens
        attempt = 0
        last_error: Exception | None = None
        while attempt < config.settings.ai_retries:
            if cancel and cancel():
                raise RuntimeError("cancelled")
            try:
                if self.is_new:
                    cfg: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens}
                    if schema:
                        cfg["response_mime_type"] = "application/json"
                        cfg["response_schema"] = schema
                    res = self._client.models.generate_content(  # type: ignore[union-attr]
                        model=model, contents=parts, config=cfg,
                    )
                    text = (getattr(res, "text", "") or "").strip()
                else:
                    legacy_model = self.sdk.GenerativeModel(model)  # type: ignore[attr-defined]
                    gen_cfg: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens}
                    if schema:
                        gen_cfg["response_mime_type"] = "application/json"
                    res = legacy_model.generate_content(
                        parts,
                        generation_config=self.sdk.types.GenerationConfig(**gen_cfg),  # type: ignore[attr-defined]
                    )
                    text = (getattr(res, "text", "") or "").strip()
                if text:
                    return text
                last_error = RuntimeError("AI မှ အလွတ် ပြန်လာပါသည်")
            except Exception as exc:
                last_error = exc
                msg = str(exc).lower()
                retryable = any(k in msg for k in ("503", "unavailable", "429", "quota", "overloaded",
                                                   "deadline", "timeout", "500", "internal"))
                if not retryable or attempt == config.settings.ai_retries - 1:
                    break
                wait = min(30, 4 * (attempt + 1) + (attempt * 2))
                if progress:
                    progress(20, f"⚠️ AI server အလုပ်များနေပါသည် - {wait}s စောင့်ပြီး ပြန်စမ်းပါမည် ({attempt + 1}/{config.settings.ai_retries})")
                time.sleep(wait)
            attempt += 1
        raise RuntimeError(f"AI request failed: {last_error}")


# ── JSON parsing ─────────────────────────────────────────────────────────
def parse_dialogues(raw: str) -> dict:
    """Forgiving JSON parser (models occasionally wrap output in prose)."""
    if not raw:
        raise ValueError("AI ပြန်ကြားချက် အလွတ် ဖြစ်နေပါသည်")
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    payload = None
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            payload = json.loads(candidate, strict=False)
        except Exception:
            payload = None
    if payload is None:
        payload = _regex_salvage(text)
    if payload is None:
        raise ValueError("AI JSON ပြန်ကြားချက် ဖတ်၍ မရပါ - model ကို ပြောင်း၍ ပြန်စမ်းပါ")

    dialogues = []
    for item in payload.get("dialogues") or payload.get("lines") or []:
        try:
            st = float(item.get("start", 0))
            en = float(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        text_value = str(item.get("text") or item.get("line") or "").strip()
        if not text_value:
            continue
        if en <= st:
            en = st + max(1.0, estimate_speech_seconds(text_value))
        dialogues.append({
            "start": max(0.0, st),
            "end": max(0.0, en),
            "speaker": str(item.get("speaker") or item.get("character") or "").strip()[:40],
            "text": text_value,
        })
    return {
        "hook_line1": str(payload.get("hook_line1") or payload.get("hookLine1") or "").strip(),
        "hook_line2": str(payload.get("hook_line2") or payload.get("hookLine2") or "").strip(),
        "dialogues": dialogues,
    }


def _regex_salvage(text: str) -> Optional[dict]:
    """Last-resort extractor for truncated / malformed model output.

    Long recaps are the usual reason a response is cut off mid-JSON (the
    output-token ceiling), so this must cope with a *missing closing brace*
    and even an unterminated string - otherwise a nearly complete answer
    would be thrown away and the video would be left half dubbed.
    """
    dialogues = []
    for fragment in text.split("{"):
        match_start = re.search(r'"start"\s*:\s*([0-9.]+)', fragment)
        if not match_start:
            continue
        match_end = re.search(r'"end"\s*:\s*([0-9.]+)', fragment)
        match_text = (re.search(r'"(?:text|line)"\s*:\s*"((?:[^"\\]|\\.)*)"', fragment)
                      or re.search(r'"(?:text|line)"\s*:\s*"([^"]*)$', fragment))
        if not match_text:
            continue
        try:
            st = float(match_start.group(1))
            en = float(match_end.group(1)) if match_end else st + 2.5
        except ValueError:
            continue
        line = match_text.group(1).replace('\\"', '"').replace("\\n", " ").strip()
        if line:
            dialogues.append({"start": st, "end": en if en > st else st + 2.5,
                              "speaker": "", "text": line})
    if not dialogues:
        return None
    h1 = re.search(r'"hook_line1"\s*:\s*"([^"]*)"', text)
    h2 = re.search(r'"hook_line2"\s*:\s*"([^"]*)"', text)
    log.warning("JSON salvage recovered %d lines from malformed model output", len(dialogues))
    return {
        "hook_line1": h1.group(1) if h1 else "",
        "hook_line2": h2.group(1) if h2 else "",
        "dialogues": dialogues,
    }


# ── chunk planning ───────────────────────────────────────────────────────
def plan_chunks(duration: float, max_seconds: int | None = None,
                target_chunks: int | None = None) -> list[tuple[float, float]]:
    max_seconds = max_seconds or config.settings.max_chunk_seconds
    target_chunks = target_chunks or config.settings.target_chunks
    if duration <= 0:
        return []
    if duration <= max_seconds:
        return [(0.0, duration)]
    count = max(2, min(target_chunks, int(duration // max_seconds) + 1))
    length = duration / count
    chunks: list[tuple[float, float]] = []
    cursor = 0.0
    for index in range(count):
        end = duration if index == count - 1 else min(duration, cursor + length)
        chunks.append((round(cursor, 3), round(end, 3)))
        cursor = end
    return [(s, e) for s, e in chunks if e - s > 1.0]


def build_proxy(video_path: str | Path, start: float, end: float, out_path: str | Path,
                progress: ProgressFn = None) -> Path:
    """1 fps / 480p / mono 16 kHz proxy - the exact sampling Gemini uses.

    Cuts encode time by ~20x, makes uploads tiny and keeps the chunk start
    frame-accurate (``-ss`` after ``-i``), which is what makes absolute
    timestamps trustworthy.
    """
    length = max(0.5, end - start)
    run_ffmpeg([
        "-y",
        "-ss", f"{start:.3f}", "-i", str(video_path), "-t", f"{length:.3f}",
        "-vf", "scale=480:-2:force_original_aspect_ratio=decrease,fps=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-ar", "16000",
        "-movflags", "+faststart",
        str(out_path),
    ], total_duration=length, label="proxy", progress=None, check=True)
    return Path(out_path)


# ── prompts ──────────────────────────────────────────────────────────────
MODE_PROMPTS = {
    "auto": "Judge the genre yourself, then dub every spoken line faithfully.",
    "movie": "This is a film / animation / drama. Dub every character line and keep the story flowing.",
    "experiment": "This is a science, review or experiment video. Dub the narrator and on-screen speech.",
    "craft": "This is a DIY / craft / cooking video. Dub the narrator and any spoken instructions.",
    "news": "This is a news / documentary style video. Dub every spoken sentence faithfully.",
}

FILL_MODE_PROMPTS = {
    "continuous": (
        "The recap must be narrated CONTINUOUSLY from the first second to the last second. "
        "Wherever nobody is speaking on screen, write short connective narration that keeps the "
        "story moving (describe what is visibly happening and what it leads to). Never invent facts."
    ),
    "dialogue": "Only translate/dub moments where characters actually speak. Leave silence silent.",
}


def _chunk_prompt(chunk_start: float, chunk_end: float, target_language: str,
                  mode_key: str, fill_mode: str, duration: float,
                  boundary_hint: str = "") -> str:
    lang_instruction = (
        "Burmese language (မြန်မာစကားပြော အသုံးအနှုန်းသီးသန့်၊ သဘာဝကျသော မြန်မာစကားဖြင့်)"
        if target_language == "my" else
        "natural spoken English"
    )
    style_block = ""
    if target_language == "my":
        try:
            from .lexicon import lexicon
            hint = "\n".join(lexicon.connectors_hint(26).splitlines())
            if hint:
                style_block = (
                    "\nSTORYTELLING CONNECTORS (use these exact Burmese words so the recap flows "
                    "like a human narrator, not a translation):\n" + hint + "\n"
                )
        except Exception:
            style_block = ""
    return f"""You are a professional film dubbing director and Myanmar recap script writer.

VIDEO SEGMENT: this clip is ONLY a part of a longer video. The clip starts at {chunk_start:.2f}s and
ends at {chunk_end:.2f}s (total video length = {duration:.2f}s).

{MODE_PROMPTS.get(mode_key, MODE_PROMPTS['auto'])}
{FILL_MODE_PROMPTS.get(fill_mode, FILL_MODE_PROMPTS['continuous'])}
{style_block}

MANDATORY RULES
1. TIMESTAMPS ARE ABSOLUTE: use seconds counted from the START OF THE FULL VIDEO.
   The first second of this clip is {chunk_start:.2f}s (NOT 0). The last is {chunk_end:.2f}s.
2. COVER THE WHOLE CLIP: keep producing entries until the clip's final seconds.
   Do not stop early, do not summarise the ending, do not skip the middle.
3. Write every line in {lang_instruction}. Keep each line short enough to speak inside its window
   (about 12-16 Burmese characters per second of window). Long windows get 2-3 shorter lines.
4. NO double quotes inside text. Use single quotes if needed. No timestamps, no scene directions,
   no camera instructions, no speaker labels inside the text itself.
5. Never invent names, places, numbers or events that are not visible/audible in the clip.
6. Return STRICT JSON only (no markdown fences).{" boundary_hint" if boundary_hint else ""}

JSON SHAPE
{{
  "hook_line1": "short punchy hook in Burmese",
  "hook_line2": "second hook line in Burmese",
  "dialogues": [
    {{"start": {chunk_start:.2f}, "end": {chunk_start + 4:.2f}, "speaker": "Hero", "text": "မြန်မာလို စကားပြောစာ"}}
  ]
}}"""


def _gap_fill_prompt(gaps: list[dict], lang: str, context_lines: list[dict]) -> str:
    lang_word = "Burmese" if lang == "my" else "English"
    gap_block = "\n".join(
        f"- index {g['index']}: {g['start']:.1f}s → {g['end']:.1f}s "
        f"({g['end'] - g['start']:.1f}s long, roughly {int(g['chars'])} {lang_word} characters)"
        for g in gaps
    )
    context_block = "\n".join(
        f"  [{c['start']:.1f}s] {c['text']}" for c in context_lines
    ) or "  (none)"
    return f"""You are finishing a {lang_word} recap voice-over. Some windows of the timeline have no
line yet and the narration must not fall silent there.

KNOWN LINES AROUND THE GAPS (for continuity only):
{context_block}

WINDOWS TO FILL:
{gap_block}

Rules:
1. Write ONE line per window, exactly the requested speaking length (about 13 Burmese characters
   per second for Burmese, 15 characters per second for English). Never exceed the window.
2. Continue the story smoothly from the surrounding lines. You may summarise or connect what the
   surrounding lines already established, but do NOT invent new names, numbers or events.
3. Plain {lang_word} only: no quotes, no brackets, no timestamps, no stage directions.
4. Return STRICT JSON only: {{"lines": [{{"index": 0, "text": "..."}}]}}"""


# ── demo mode ────────────────────────────────────────────────────────────
_DEMO_SENTENCES = [
    "ဒီဇာတ်လမ်းရဲ့ အစကတည်းက စိတ်ဝင်စားစရာတွေ ဖြစ်လာတယ်။",
    "ဇာတ်ကောင်တွေရဲ့ ဆုံးဖြတ်ချက်က ဇာတ်လမ်းကို လှန်လိုက်တယ်။",
    "အန္တရာယ်ကြီးတစ်ခု နီးလာတာကို သူတို့ သတိမထားမိကြဘူး။",
    "ဒီအခိုက်အတန့်မှာ အားလုံးရဲ့ အခြေအနေ ပြောင်းသွားတယ်။",
    "ဆက်ပြီးတော့ သူတို့ ဘယ်လိုရင်ဆိုင်မလဲ ကြည့်ရအောင်။",
    "အဆုံးသတ်မှာ မမျှော်လင့်တဲ့ အလှည့်အပြောင်း တစ်ခု ရှိလာတယ်။",
]


def demo_timeline(duration: float, lang: str = "my") -> dict:
    """Deterministic offline timeline (RECAP_DEMO_MODE) so the pipeline can be
    exercised without an API key - used by the smoke test and the UI demo."""
    lines = []
    slot = max(6.0, min(14.0, duration / 12.0 if duration else 10.0))
    t = 0.5
    idx = 0
    while t < max(1.0, duration - 1.0):
        text = _DEMO_SENTENCES[idx % len(_DEMO_SENTENCES)]
        length = min(slot - 0.6, max(2.0, estimate_speech_seconds(text, lang)))
        lines.append({
            "start": round(t, 2),
            "end": round(min(duration, t + length), 2),
            "speaker": "Demo",
            "text": text,
        })
        t += slot
        idx += 1
    return {
        "hook_line1": "ဒီဇာတ်လမ်းကို လွတ်သွားရင် နောင်တရလိမ့်မယ်",
        "hook_line2": "အဆုံးအထိ ကြည့်ကြည့်ပါ",
        "dialogues": lines,
    }


# ── merging / coverage ───────────────────────────────────────────────────
def normalise(dialogues: Iterable[dict], duration: float) -> list[dict]:
    cleaned: list[dict] = []
    for item in sorted(dialogues, key=lambda d: float(d.get("start", 0))):
        try:
            st = max(0.0, min(float(item.get("start", 0)), duration))
            en = max(0.0, min(float(item.get("end", st + 2.0)), duration))
        except (TypeError, ValueError):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        if not text:
            continue
        if en <= st:
            en = min(duration, st + max(1.2, estimate_speech_seconds(text)))
        cleaned.append({"start": st, "end": en,
                        "speaker": str(item.get("speaker", ""))[:40], "text": text})

    # de-overlap: a line may never run into the next line's start
    merged: list[dict] = []
    for idx, line in enumerate(cleaned):
        if idx + 1 < len(cleaned):
            nxt = cleaned[idx + 1]["start"]
            if line["end"] > nxt:
                line["end"] = max(line["start"] + 0.4, nxt)
        merged.append(line)
    return merged


def find_gaps(dialogues: list[dict], duration: float, min_gap: float,
              include_head_tail: bool = True) -> list[dict]:
    gaps: list[dict] = []
    cursor = 0.0
    for line in dialogues:
        if line["start"] - cursor >= min_gap:
            gaps.append({"start": cursor, "end": line["start"]})
        cursor = max(cursor, line["end"])
    if include_head_tail and duration - cursor >= min_gap:
        gaps.append({"start": cursor, "end": duration})
    return gaps


class TimelineExtractor:
    """Full pipeline: chunked analysis + coverage sweep."""

    def __init__(self, api_key: str, model: str, target_language: str = "my",
                 mode: str = "auto", fill_mode: str = "continuous",
                 progress: ProgressFn = None, cancel: Optional[Callable[[], bool]] = None,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.api_key = api_key
        self.model = MODEL_ALIASES.get(model, model)
        self.lang = target_language
        self.mode = mode
        self.fill_mode = fill_mode
        self.progress = progress
        self.cancel = cancel
        self.log = log_fn or (lambda msg: log.info(msg))
        # Demo mode is an *explicit* opt-in (RECAP_DEMO_MODE=1). A missing API
        # key must never silently produce a fake beep-narrated video.
        self.demo = bool(config.settings.demo_mode)
        self.client: Optional[GeminiClient] = None

    def _emit(self, pct: float, message: str) -> None:
        if self.progress:
            try:
                self.progress(pct, message)
            except Exception:
                pass

    def _check_cancel(self) -> None:
        if self.cancel and self.cancel():
            raise RuntimeError("cancelled")

    # ── main entry ─────────────────────────────────────────────────────
    def run(self, video_path: str, duration: float) -> dict:
        if self.demo:
            self.log("Demo mode: synthetic timeline (API key မလိုအပ်ပါ)")
            data = demo_timeline(duration, self.lang)
            report = self._coverage(data["dialogues"], duration, 0)
            return {"hook_line1": data["hook_line1"], "hook_line2": data["hook_line2"],
                    "dialogues": data["dialogues"], "coverage": report}

        if not self.api_key:
            raise ValueError(
                "Gemini API Key မထည့်ရသေးပါ။ Settings tab မှ API Key ထည့်သွင်းပေးပါ "
                "(သို့မဟုတ် စမ်းသပ်ရန် RECAP_DEMO_MODE=1 ဖြင့် run ပါ)။"
            )
        self.client = GeminiClient(self.api_key)
        chunks = plan_chunks(duration)
        self.log(f"Analysis chunks: {len(chunks)} → {[f'{s:.0f}-{e:.0f}s' for s, e in chunks]}")
        self._emit(6, f"🧠 ဗီဒီယိုကို အပိုင်း {len(chunks)} ပိုင်းခွဲ၍ AI ဖြင့် စစ်ဆေးနေပါသည်...")

        results: list[dict] = []
        per_chunk: list[dict] = []
        errors: list[str] = []
        workers = max(1, min(config.settings.analyze_workers, len(chunks)))
        done = 0
        from concurrent.futures import as_completed
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analyze") as pool:
            futures = {
                pool.submit(self._analyze_chunk, video_path, start, end, duration, idx, len(chunks)): (idx, start, end)
                for idx, (start, end) in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx, start, end = futures[future]
                self._check_cancel()
                try:
                    payload, count = future.result()
                    results.extend(payload["dialogues"])
                    per_chunk.append({"index": idx + 1, "start": round(start, 1),
                                      "end": round(end, 1), "lines": count})
                    if payload.get("hook_line1") or payload.get("hook_line2"):
                        results.append({"__hook__": payload})
                except Exception as exc:
                    errors.append(f"chunk {idx + 1} ({start:.0f}-{end:.0f}s): {exc}")
                    self.log(f"⚠️ chunk {idx + 1} failed: {exc}")
                done += 1
                self._emit(8 + (done / len(chunks)) * 62,
                           f"🧠 AI စစ်ဆေးပြီး {done}/{len(chunks)} အပိုင်း "
                           f"({start:.0f}-{end:.0f}s) ✅")

        if not results and errors:
            raise RuntimeError("AI analysis failed for every chunk:\n" + "\n".join(errors[:3]))

        hooks = [r for r in results if isinstance(r, dict) and "__hook__" in r]
        dialogues = normalise([r for r in results if "__hook__" not in r], duration)
        hook1 = next((h["__hook__"].get("hook_line1", "") for h in hooks if h["__hook__"].get("hook_line1")), "")
        hook2 = next((h["__hook__"].get("hook_line2", "") for h in hooks if h["__hook__"].get("hook_line2")), "")

        # ── coverage sweep ────────────────────────────────────────────
        dialogues, filled, longest = self._coverage_sweep(dialogues, duration, video_path)
        report = self._coverage(dialogues, duration, filled, per_chunk, longest)
        if errors:
            report["warnings"] = errors
        self.log(f"Coverage: {report['coverage_percent']}% "
                 f"({report['spoken_seconds']}s / {report['total_seconds']}s), "
                 f"{report['lines']} lines, {filled} gaps filled, longest gap {longest:.1f}s")
        return {"hook_line1": hook1, "hook_line2": hook2, "dialogues": dialogues,
                "coverage": report}

    # ── one chunk ──────────────────────────────────────────────────────
    def _analyze_chunk(self, video_path: str, start: float, end: float,
                       duration: float, index: int, total: int) -> tuple[dict, int]:
        self._check_cancel()
        assert self.client is not None
        proxy = Path(config.TMP_DIR) / f"proxy_{uuid.uuid4().hex[:8]}.mp4"
        ref = None
        try:
            build_proxy(video_path, start, end, proxy)
            # very small chunks can go inline (faster, no Files API wait)
            part: Any = proxy
            if proxy.stat().st_size > 18 * 1024 * 1024:
                ref = self.client.upload(proxy, self.progress,
                                         label=f"အပိုင်း {index + 1}/{total}")
                part = ref
            prompt = _chunk_prompt(start, end, self.lang, self.mode, self.fill_mode, duration)
            raw = self.client.generate_json(self.model, [part, prompt], DIALOGUE_SCHEMA,
                                            progress=self.progress, cancel=self.cancel)
            payload = parse_dialogues(raw)
            clip_len = max(0.5, end - start)
            lines = payload["dialogues"]
            # Models occasionally answer relative to the clip even when told
            # to use absolute video time. If *every* timestamp fits inside the
            # clip then the answer was relative -> shift it by the offset.
            looks_relative = bool(lines) and max(l["start"] for l in lines) < clip_len - 0.5
            shifted = []
            for line in lines:
                if looks_relative:
                    line_start = min(duration, start + line["start"])
                    line_end = min(duration, start + line["end"])
                else:
                    line_start = min(duration, max(start, line["start"]))
                    line_end = min(duration, max(line_start + 0.5, line["end"]))
                shifted.append({"start": line_start, "end": line_end,
                                "speaker": line.get("speaker", ""), "text": line["text"]})
            payload["dialogues"] = shifted
            return payload, len(shifted)
        finally:
            if ref is not None:
                self.client.delete(ref)
            proxy.unlink(missing_ok=True)

    # ── gap filling ────────────────────────────────────────────────────
    def _coverage_sweep(self, dialogues: list[dict], duration: float,
                        video_path: str) -> tuple[list[dict], int, float]:
        min_gap = 2.5 if self.fill_mode == "continuous" else 8.0
        gaps = find_gaps(dialogues, duration, min_gap)
        longest = max((g["end"] - g["start"] for g in gaps), default=0.0)
        if not gaps or self.demo:
            return dialogues, 0, longest

        self._emit(72, f"🧩 လွတ်နေသော အပိုင်း {len(gaps)} ခုကို ဖြည့်စွက်နေပါသည်...")
        # Large gaps usually mean the model skipped a whole scene: re-analyse
        # that region's video instead of guessing from text alone.
        big_gaps = [g for g in gaps if (g["end"] - g["start"]) > 25.0][:4]
        region_lines: list[dict] = []
        for gap in big_gaps:
            self._check_cancel()
            try:
                payload, count = self._analyze_chunk(video_path, gap["start"], gap["end"],
                                                     duration, -1, -1)
                region_lines.extend(payload["dialogues"])
                self.log(f"↻ re-analysed {gap['start']:.0f}-{gap['end']:.0f}s → {count} lines")
            except Exception as exc:
                self.log(f"⚠️ region re-analysis failed ({gap['start']:.0f}s): {exc}")
        if region_lines:
            dialogues = normalise(dialogues + region_lines, duration)

        # remaining gaps → short connective narration (text only, fast)
        gaps = [g for g in find_gaps(dialogues, duration, min_gap) if (g["end"] - g["start"]) <= 40.0]
        filled = 0
        if gaps:
            filled = self._fill_gaps_with_text(dialogues, gaps, duration)
            if filled:
                dialogues = normalise(dialogues, duration)
        longest = max((g["end"] - g["start"] for g in find_gaps(dialogues, duration, 3.0)), default=0.0)
        return dialogues, filled, longest

    def _fill_gaps_with_text(self, dialogues: list[dict], gaps: list[dict],
                             duration: float) -> int:
        assert self.client is not None
        payload_gaps = []
        context: list[dict] = []
        for idx, gap in enumerate(gaps[:40]):
            length = gap["end"] - gap["start"]
            payload_gaps.append({
                "index": idx,
                "start": gap["start"],
                "end": gap["end"],
                "chars": max(10, int(length * (12 if self.lang == "my" else 14))),
            })
            before = [d for d in dialogues if d["end"] <= gap["start"]][-2:]
            after = [d for d in dialogues if d["start"] >= gap["end"]][:2]
            for item in before + after:
                context.append({"start": item["start"], "text": item["text"]})
        context = context[-24:]
        prompt = _gap_fill_prompt(payload_gaps, self.lang, context)
        try:
            raw = self.client.generate_json(self.model, [prompt], GAP_FILL_SCHEMA,
                                            temperature=0.4, max_tokens=8192,
                                            progress=self.progress, cancel=self.cancel)
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except Exception as exc:
            self.log(f"⚠️ gap fill failed: {exc}")
            return 0
        added = 0
        for item in data.get("lines", []):
            try:
                gap = payload_gaps[int(item["index"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if not text:
                continue
            est = estimate_speech_seconds(text, self.lang)
            if est > (gap["end"] - gap["start"]) + 1.0:
                text = text[: max(10, int(len(text) * (gap["end"] - gap["start"]) / est))]
            dialogues.append({"start": gap["start"], "end": gap["end"], "speaker": "Recap",
                              "text": text})
            added += 1
        # also cover the first couple of seconds if the recap opens silent
        if not any(d["start"] < 1.0 for d in dialogues) and duration > 6:
            dialogues.append({"start": 0.2, "end": min(4.0, duration), "speaker": "Recap",
                              "text": "ဒီဇာတ်လမ်းကို အခုပဲ ကြည့်လိုက်ရအောင်။"})
            added += 1
        self.log(f"Coverage sweep added {added} narration lines")
        return added

    def _coverage(self, dialogues: list[dict], duration: float, filled: int,
                  per_chunk: list[dict] | None = None, longest: float = 0.0) -> dict:
        spoken = sum(max(0.0, d["end"] - d["start"]) for d in dialogues)
        report = CoverageReport(
            total_seconds=duration, spoken_seconds=spoken, lines=len(dialogues),
            gaps_filled=filled, longest_gap=longest, chunks=len(per_chunk or []),
            per_chunk=per_chunk or [],
        )
        return report.as_dict()


def extract_timeline(api_key: str, video_path: str, duration: float, *,
                     language: str = "my", mode: str = "auto", fill_mode: str = "continuous",
                     model: str = None, progress: ProgressFn = None,
                     cancel: Optional[Callable[[], bool]] = None,
                     log_fn: Optional[Callable[[str], None]] = None) -> dict:
    extractor = TimelineExtractor(
        api_key=api_key, model=model or config.settings.default_model,
        target_language=language, mode=mode, fill_mode=fill_mode,
        progress=progress, cancel=cancel, log_fn=log_fn,
    )
    return extractor.run(video_path, duration)
