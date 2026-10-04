"""Viral thumbnail studio — v4.3.2 (#10).

ဘာကြောင့် အသစ် ရေးရသလဲ
-----------------------
ယခင် Thumbnail tab သည် **ဗီဒီယို ထပ်တင်ခိုင်း**ပြီး frame တစ်ခုပေါ်တွင် စာ
နှစ်ကြောင်း တင်ရုံသာ ဖြစ်သည်။ လိုအပ်ချက်မှာ —

* Studio မှာ **ပြီးသွားသော ဗီဒီယို**ကိုပဲ သုံးရန် (ထပ်တင်စရာ မလို)၊
* **nano-banana** (Gemini 2.5 Flash Image — အခမဲ့ tier) ဖြင့် frame ကို
  viral thumbnail အဖြစ် ပြန်ပုံဖော်ရန်၊
* တစ်ချက်နှိပ်လျှင် **ရွေးစရာ အများအပြား** ထွက်ရန်။

ဒီဇိုင်း
--------
1. ``pick_frames()``    — ဗီဒီယိုတစ်ခုလုံးမှ အလင်းအမှောင်/အသေးစိတ် အကောင်းဆုံး
   frame များကို ရွေးသည် (မှောင်သော/ဝါးသော frame များ ကျော်)။
2. ``ai_restyle()``     — frame ကို nano-banana သို့ ပို့၍ cinematic poster
   အဖြစ် ပြန်ထုတ်သည် (key မရှိ/မရလျှင် frame အတိုင်း ဆက်သုံး — feature
   ဘယ်တော့မှ မပျက်)။
3. ``compose()``        — မြန်မာစာ hook ကို Pillow + Noto Sans Myanmar ဖြင့်
   ထပ်ရေးသည်။ (image model များသည် မြန်မာစာကို မှန်မှန် မရေးနိုင်သေးသဖြင့်
   စာကို ကိုယ်တိုင် ရေးခြင်းက အမြဲ ပိုသေချာသည်။)
4. ``generate_variants()`` — ၁–၄ မျိုး ထုတ်ပေးသည်။
"""
from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config
from .fonts import get_mm_pil_font
from .media import get_video_info, run_ffmpeg
from .util import get_logger

log = get_logger("recap.thumbs")

#: nano-banana — Google's free-tier image model (a.k.a. Gemini 2.5 Flash Image)
NANO_BANANA_MODELS = ("gemini-2.5-flash-image", "gemini-2.5-flash-image-preview")

#: output frames per aspect ratio (YouTube / Shorts / feed)
ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

#: colour palettes — each variant gets a different one so the user really has
#: a choice instead of four copies of the same picture
STYLES: dict[str, dict] = {
    "bold": {"label": "Bold Yellow", "top": (255, 214, 10), "bottom": (0, 242, 254),
             "shade": 190, "band": None},
    "alert": {"label": "Red Alert", "top": (255, 255, 255), "bottom": (255, 72, 88),
              "shade": 205, "band": (220, 38, 38)},
    "clean": {"label": "Clean White", "top": (255, 255, 255), "bottom": (255, 214, 10),
              "shade": 150, "band": None},
    "neon": {"label": "Neon Violet", "top": (236, 221, 255), "bottom": (167, 139, 250),
             "shade": 200, "band": (109, 40, 217)},
}
STYLE_ORDER = ("bold", "alert", "clean", "neon")

AI_PROMPT = (
    "Re-style this exact video frame into a high-CTR YouTube thumbnail background. "
    "Keep the same subject, pose and composition — do NOT invent a new scene and do not "
    "add any text, letters, numbers, watermark or logo. Make it look cinematic and loud: "
    "punchy contrast, crisp details, warm key light on the subject, slightly darkened and "
    "blurred background, vivid saturated colours, subtle rim light, clean empty space at the "
    "top and bottom so captions can be added later. Photorealistic, sharp, 4k poster quality."
)


@dataclass
class FrameCandidate:
    path: Path
    second: float
    score: float


# ── frame picking ────────────────────────────────────────────────────────
def _frame_score(path: Path) -> float:
    """Cheap "is this frame usable" score: brightness × detail.

    A black fade or a motion-blurred pan makes a terrible thumbnail, and both
    are easy to spot from a down-scaled copy: near-zero brightness, or almost
    no variation between neighbouring pixels.
    """
    try:
        from PIL import Image, ImageFilter, ImageStat
    except Exception:  # pragma: no cover - Pillow is a hard dependency
        return 1.0
    try:
        with Image.open(path) as im:
            small = im.convert("L").resize((160, 90))
            brightness = ImageStat.Stat(small).mean[0] / 255.0
            detail = ImageStat.Stat(small.filter(ImageFilter.FIND_EDGES)).stddev[0] / 64.0
    except Exception:  # noqa: BLE001
        return 0.0
    # mid-bright frames win; very dark or blown-out ones are punished
    light = 1.0 - abs(brightness - 0.55) * 1.8
    return max(0.0, light) * 0.55 + min(1.0, detail) * 0.45


def pick_frames(video_path: str | Path, count: int = 3,
                duration: float | None = None,
                work_dir: Path | None = None) -> list[FrameCandidate]:
    """Grab ``count`` good-looking frames spread across the video."""
    video_path = str(video_path)
    if duration is None:
        duration = float(get_video_info(video_path).get("duration") or 0.0)
    duration = max(0.5, duration)
    work_dir = Path(work_dir or config.TMP_DIR)
    work_dir.mkdir(parents=True, exist_ok=True)

    # sample more than we need, then keep the best ones
    samples = max(count, min(10, count * 3))
    first, last = duration * 0.08, duration * 0.92
    span = max(0.1, last - first)
    tag = uuid.uuid4().hex[:6]
    out: list[FrameCandidate] = []
    for i in range(samples):
        second = first + span * (i / max(1, samples - 1))
        dst = work_dir / f"cand_{tag}_{i}.jpg"
        try:
            run_ffmpeg(["-y", "-ss", f"{second:.3f}", "-i", video_path, "-frames:v", "1",
                        "-q:v", "2", str(dst)], check=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("frame grab failed at %.1fs: %s", second, exc)
            continue
        if dst.exists() and dst.stat().st_size > 2048:
            out.append(FrameCandidate(path=dst, second=round(second, 2), score=_frame_score(dst)))
    if not out:
        raise RuntimeError("ဗီဒီယိုမှ ဖရိမ် ဖမ်းယူ၍ မရပါ — ဖိုင် ပျက်နေနိုင်သည်။")

    best = sorted(out, key=lambda c: c.score, reverse=True)[:count]
    best.sort(key=lambda c: c.second)           # keep story order
    for cand in out:
        if cand not in best:
            cand.path.unlink(missing_ok=True)
    return best


# ── nano-banana ──────────────────────────────────────────────────────────
def ai_available(api_key: str = "", key_ring=None) -> bool:
    if config.settings.demo_mode:
        return False
    if api_key:
        return True
    try:
        from .keys import default_key_ring
        ring = key_ring or default_key_ring
        return bool(ring and ring.has_key())
    except Exception:  # noqa: BLE001
        return False


def ai_restyle(frame: Path, out_path: Path, api_key: str = "", key_ring=None,
               prompt: str = AI_PROMPT,
               cancel: Optional[Callable[[], bool]] = None) -> bool:
    """nano-banana edit of ``frame``. Returns ``False`` if AI is unavailable.

    Never raises for the caller: a thumbnail must still appear when the key is
    missing, the quota is gone or the model is busy — the original frame is
    used instead (and the UI says so).
    """
    if not ai_available(api_key, key_ring):
        return False
    try:
        from .ai import GeminiClient
        client = GeminiClient(api_key=api_key, key_ring=key_ring)
        part = client.build_image_part(frame)
        last_error: Exception | None = None
        for model in NANO_BANANA_MODELS:
            try:
                data = client.generate_image(model, [part, prompt], cancel=cancel)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            if data:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                if out_path.exists() and out_path.stat().st_size > 4096:
                    log.info("nano-banana thumbnail via %s (%d bytes)", model, out_path.stat().st_size)
                    return True
        if last_error:
            log.warning("nano-banana failed: %s", last_error)
    except Exception as exc:  # noqa: BLE001
        log.warning("nano-banana unavailable: %s", exc)
    return False


# ── composition ──────────────────────────────────────────────────────────
def _wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines, current = [], words[0]
    for word in words[1:]:
        probe = f"{current} {word}"
        if draw.textlength(probe, font=font) <= max_width:
            current = probe
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def compose(base_image: Path, out_path: Path, hook1: str, hook2: str,
            aspect: str = "16:9", style: str = "bold", badge: str = "") -> Path:
    """Burn the Burmese hook text onto ``base_image`` and save a JPEG."""
    from PIL import Image, ImageDraw

    width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
    palette = STYLES.get(style, STYLES["bold"])

    with Image.open(base_image) as src:
        img = src.convert("RGB")
        # cover-crop to the exact frame
        scale = max(width / img.width, height / img.height)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.LANCZOS)
        left = (img.width - width) // 2
        top = (img.height - height) // 2
        base = img.crop((left, top, left + width, top + height)).convert("RGBA")

    shade = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shade)
    strength = int(palette["shade"])
    # readable gradients top & bottom instead of one flat grey box
    for i in range(int(height * 0.34)):
        alpha = int(strength * (1 - i / (height * 0.34)) ** 1.4)
        sdraw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))
    for i in range(int(height * 0.30)):
        y = height - 1 - i
        alpha = int(strength * 0.85 * (1 - i / (height * 0.30)) ** 1.4)
        sdraw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    base = Image.alpha_composite(base, shade)

    draw = ImageDraw.Draw(base)
    big = get_mm_pil_font(int(width * (0.085 if aspect != "9:16" else 0.075)), bold=True)
    small = get_mm_pil_font(int(width * (0.052 if aspect != "9:16" else 0.046)), bold=True)

    top_lines = _wrap(draw, hook1, big, int(width * 0.92), 2)
    bottom_lines = _wrap(draw, hook2, small, int(width * 0.88), 2)

    badge_text = (badge or "RECAP").strip().upper()[:14]
    band_bottom = 0
    if palette["band"] and top_lines and badge_text:
        bfont = get_mm_pil_font(int(width * 0.030), bold=True)
        pad_x, pad_y = int(width * 0.022), int(width * 0.012)
        tw = int(draw.textlength(badge_text, font=bfont))
        bx, by = int(width * 0.045), int(height * 0.045)
        band_h = int(width * 0.030) + pad_y * 2
        draw.rounded_rectangle([bx, by, bx + tw + pad_x * 2, by + band_h],
                               radius=int(band_h * 0.28), fill=palette["band"] + (238,))
        draw.text((bx + pad_x + tw // 2, by + band_h // 2), badge_text, font=bfont,
                  fill=(255, 255, 255, 255), anchor="mm")
        band_bottom = by + band_h

    y = max(int(height * 0.06), band_bottom + int(height * 0.025))
    for line in top_lines:
        draw.text((width // 2, y), line, font=big, fill=palette["top"] + (255,), anchor="ma",
                  stroke_width=max(4, int(width * 0.007)), stroke_fill=(0, 0, 0, 255))
        y += int(width * (0.10 if aspect != "9:16" else 0.09))

    y = int(height * (0.78 if aspect != "9:16" else 0.84))
    for line in bottom_lines:
        draw.text((width // 2, y), line, font=small, fill=palette["bottom"] + (255,), anchor="ma",
                  stroke_width=max(3, int(width * 0.005)), stroke_fill=(0, 0, 0, 255))
        y += int(width * 0.065)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


# ── public entry point ───────────────────────────────────────────────────
def generate_variants(video_path: str | Path, out_dir: Path, hook1: str, hook2: str,
                      count: int = 3, aspect: str = "16:9", use_ai: bool = True,
                      api_key: str = "", key_ring=None, badge: str = "",
                      progress: Optional[Callable[[float, str], None]] = None,
                      cancel: Optional[Callable[[], bool]] = None) -> list[dict]:
    """Produce ``count`` ready-to-post thumbnails for a finished video."""
    count = max(1, min(4, int(count or 3)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = get_video_info(str(video_path))
    frames = pick_frames(video_path, count=count, duration=float(info.get("duration") or 0.0))
    wants_ai = bool(use_ai) and ai_available(api_key, key_ring)
    tag = uuid.uuid4().hex[:6]
    results: list[dict] = []

    for idx, cand in enumerate(frames):
        if cancel and cancel():
            break
        if progress:
            progress(10 + (80 * idx) / max(1, len(frames)),
                     f"🖼️ Thumbnail {idx + 1}/{len(frames)} ဖန်တီးနေသည်…")
        style = STYLE_ORDER[idx % len(STYLE_ORDER)]
        base = cand.path
        ai_used = False
        if wants_ai:
            ai_path = Path(config.TMP_DIR) / f"nb_{tag}_{idx}.png"
            if ai_restyle(cand.path, ai_path, api_key=api_key, key_ring=key_ring, cancel=cancel):
                base, ai_used = ai_path, True
        out_path = out_dir / f"thumb_{tag}_{idx + 1}.jpg"
        try:
            compose(base, out_path, hook1, hook2, aspect=aspect, style=style, badge=badge)
        except Exception as exc:  # noqa: BLE001
            log.warning("compose failed (%s): %s", out_path.name, exc)
            continue
        finally:
            if ai_used:
                Path(base).unlink(missing_ok=True)
        width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
        results.append({
            "index": idx + 1,
            "path": config.rel(out_path),
            "filename": out_path.name,
            "url": f"/api/download/{out_path.name}",
            "preview_url": f"/api/asset?path={config.rel(out_path)}",
            "second": cand.second,
            "style": style,
            "style_label": STYLES[style]["label"],
            "ai": ai_used,
            "width": width,
            "height": height,
            "size": out_path.stat().st_size if out_path.exists() else 0,
        })

    for cand in frames:
        cand.path.unlink(missing_ok=True)
    if not results:
        raise RuntimeError("Thumbnail ဖန်တီး၍ မရပါ — ဗီဒီယိုဖိုင်ကို စစ်ဆေးပါ။")
    if progress:
        progress(100, f"✅ Thumbnail {len(results)} မျိုး ပြီးပါပြီ")
    return results


__all__ = ["generate_variants", "pick_frames", "compose", "ai_restyle", "ai_available",
           "ASPECT_SIZES", "STYLES", "STYLE_ORDER", "NANO_BANANA_MODELS", "AI_PROMPT"]
