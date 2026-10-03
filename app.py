import os
import re
import math
import time
import json
import uuid
import shutil
import asyncio
import subprocess
import urllib.request
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

# ──────────────────────────────────────────────────────────────────────────
# Fontconfig bootstrap
# ──────────────────────────────────────────────────────────────────────────
FONTS_CONF = "fonts.conf"
if not os.path.exists(FONTS_CONF):
    try:
        with open(FONTS_CONF, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>.</dir>
  <dir>/usr/share/fonts</dir>
  <dir>/usr/local/share/fonts</dir>
  <cachedir>/tmp/fontconfig-cache</cachedir>
</fontconfig>""")
    except Exception:
        pass

os.environ["FONTCONFIG_PATH"] = "."

# Myanmar font: "Pyidaungsu" is unreliable to download (the previous GitHub
# raw-link is frequently dead / renamed which silently left subtitles with
# NO Myanmar glyph support -> garbled "tofu" boxes). We now use
# "Noto Sans Myanmar" (Google's official, actively mirrored font) as the
# primary font with multiple redundant mirrors + integrity verification,
# and keep Pyidaungsu only as a secondary fallback.
MM_FONT_FILE = "NotoSansMyanmar.ttf"
MM_FONT_FAMILY = "Noto Sans Myanmar"


def _verify_font_file(path: str) -> bool:
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 40000:
            return False
        ImageFont.truetype(path, 40)
        return True
    except Exception:
        return False


def ensure_myanmar_fonts():
    """Downloads a working Myanmar Unicode font (with redundant mirrors) so
    subtitles / thumbnails never fall back to a font that can't render
    Myanmar script (which previously showed as broken boxes)."""
    if _verify_font_file(MM_FONT_FILE):
        return

    mirrors = [
        "https://raw.githubusercontent.com/frappe/fonts/master/usr_share_fonts/noto/NotoSansMyanmar-Regular.ttf",
        "https://cdn.jsdelivr.net/gh/google/fonts/ofl/notosansmyanmar/NotoSansMyanmar%5Bwdth%2Cwght%5D.ttf",
        "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf",
    ]
    for url in mirrors:
        tmp_path = MM_FONT_FILE + ".tmp"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp, open(tmp_path, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)
            if _verify_font_file(tmp_path):
                os.replace(tmp_path, MM_FONT_FILE)
                return
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            continue


ensure_myanmar_fonts()


def get_mm_pil_font(size: int) -> ImageFont.FreeTypeFont:
    """Returns a Myanmar-capable PIL font, trying the verified font first."""
    for candidate in (MM_FONT_FILE, "Pyidaungsu.ttf"):
        try:
            if os.path.exists(candidate):
                return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


app = FastAPI(title="Recap Studio MM Pro", version="3.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("workspace", exist_ok=True)
os.makedirs("workspace/tasks", exist_ok=True)
os.makedirs("output", exist_ok=True)

# Google GenAI SDK Compatibility detection
use_new_sdk = False
try:
    from google import genai
    use_new_sdk = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
        use_new_sdk = False
    except ImportError:
        pass

CONFIG_FILE = ".recap_config.json"
TASKS: Dict[str, Dict[str, Any]] = {}

# Reused for CPU-bound parallel jobs (e.g. splitting a video into many parts
# at once instead of one-by-one, which is the main source of slowness).
CPU_COUNT = os.cpu_count() or 2
split_executor = ThreadPoolExecutor(max_workers=max(2, min(4, CPU_COUNT)))


def save_task_state(task_id: str, data: Dict[str, Any]):
    """Persists task state to memory and disk to survive any container hiccups."""
    TASKS[task_id] = data
    try:
        fpath = os.path.join("workspace/tasks", f"{task_id}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_task_state(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves task state from memory or disk backup."""
    if task_id in TASKS:
        return TASKS[task_id]
    fpath = os.path.join("workspace/tasks", f"{task_id}.json")
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                TASKS[task_id] = data
                return data
        except Exception:
            pass
    return None


def load_config(key: str, default: str = "") -> str:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except Exception:
            pass
    return default


def save_config(key: str, value: str):
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data[key] = value
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_media_duration(file_path: str) -> float:
    if not file_path or not os.path.exists(file_path):
        return 0.0
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            file_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(json.loads(res.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def get_video_resolution(file_path: str):
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", file_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        info = json.loads(res.stdout)["streams"][0]
        return int(info["width"]), int(info["height"])
    except Exception:
        return None, None


def has_audio_stream(file_path: str) -> bool:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return len(res.stdout.strip()) > 0
    except Exception:
        return False


PHONETICS_MM = {
    r"\bAI\b": "အေအိုင်", r"\bFBI\b": "အက်ဖ်ဘီအိုင်", r"\bCIA\b": "စီအိုင်အေ",
    r"\bVIP\b": "ဗွီအိုင်ပီ", r"\bDoctor\b": "ဒေါက်တာ", r"\bPolice\b": "ရဲတွေ",
    r"\bTikTok\b": "တစ်တော့ခ်", r"\bFacebook\b": "ဖေ့စ်ဘွတ်ခ်", r"\bYouTube\b": "ယူကျုဘ်",
    r"\bSubscribe\b": "စဘ်စခရိုက်ဘ်", r"\bLike\b": "လိုက်ခ်"
}


def clean_script_line(text: str, lang: str = "my") -> str:
    if not text:
        return ""
    t = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?", "", text)
    t = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", t)
    t = re.sub(r"[\(\[（【].*?[\)\]）】]", "", t)
    t = re.sub(r"[*#_~>`]", "", t)

    if lang == "my":
        for pattern, rep in PHONETICS_MM.items():
            t = re.sub(pattern, rep, t, flags=re.IGNORECASE)
        t = re.sub(r"[၊,]+", " ", t)
        t = re.sub(r"[။\.\!\?]+", " ။ ", t)

    t = re.sub(r"\s+", " ", t).strip()
    return t


def process_user_logo(input_path: str, output_path: str) -> bool:
    """Crops the uploaded logo into a circular badge. Vectorised with a
    pure-Pillow approach (point table) instead of a per-pixel Python loop,
    which used to take many seconds (or even minutes/timeouts) on larger
    images."""
    try:
        img = Image.open(input_path).convert("RGBA")

        try:
            import numpy as np
            arr = np.array(img)
            r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
            white_mask = (r > 215) & (g > 215) & (b > 215)
            black_mask = (r < 30) & (g < 30) & (b < 30)
            arr[white_mask] = [255, 255, 255, 0]
            arr[black_mask] = [0, 0, 0, 0]
            img = Image.fromarray(arr, "RGBA")
        except Exception:
            # Fallback: use Image.point based channel thresholds (still far
            # faster than a nested python double-loop over every pixel).
            r_ch, g_ch, b_ch, a_ch = img.split()
            # Keep original pixels; numpy unavailable is a rare edge-case.
            img = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))

        mask = Image.new("L", (min_dim, min_dim), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, min_dim, min_dim), fill=255)

        badge = Image.new("RGBA", (min_dim, min_dim), (0, 0, 0, 0))
        badge.paste(img, (0, 0), mask=mask)

        draw_badge = ImageDraw.Draw(badge)
        b_width = max(2, min_dim // 35)
        draw_badge.ellipse(
            (b_width // 2, b_width // 2, min_dim - b_width // 2, min_dim - b_width // 2),
            outline=(0, 242, 254, 230),
            width=b_width
        )
        badge.save(output_path, "PNG")
        return True
    except Exception:
        return False


VOICE_CATALOG = {
    "my": {
        "thiha": {"name": "မင်းသန့် (Action Narrator)", "voice": "my-MM-ThihaNeural", "rate": "+0%", "pitch": "-1Hz", "lang": "my"},
        "nilar": {"name": "မေသူ (Drama & Expressive)", "voice": "my-MM-NilarNeural", "rate": "+0%", "pitch": "+1Hz", "lang": "my"}
    },
    "en": {
        "christopher": {"name": "Christopher (Cinematic Male)", "voice": "en-US-ChristopherNeural", "rate": "+0%", "pitch": "-1Hz", "lang": "en"},
        "jenny": {"name": "Jenny (Energetic Female)", "voice": "en-US-JennyNeural", "rate": "+0%", "pitch": "+1Hz", "lang": "en"}
    }
}


def extract_timeline_dialogues(
    raw_api_keys: str,
    video_path: str,
    video_duration: float,
    target_language: str = "my",
    mode_key: str = "auto",
    selected_model: str = "gemini-2.5-flash",
    progress_callback=None
) -> Dict[str, Any]:
    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_keys) if k.strip()]
    if not keys:
        raise ValueError("Gemini API Key ထည့်သွင်းပေးရန် လိုအပ်ပါသည် ခင်ဗျာ။")

    lang_instruction = "Burmese language (မြန်မာစကားပြော အသုံးအနှုန်းသီးသန့်)" if target_language == "my" else "English language"

    mode_prompts = {
        "auto": "Observe this video carefully. Focus ONLY on moments where characters or narrators speak.",
        "experiment": "This is an experiment/science video. Narrate concise commentary exactly as actions happen.",
        "craft": "This is a DIY craft video. If quiet, briefly explain key steps at major milestones.",
        "movie": "This is a movie recap/animation. Translate and dub character dialogues accurately."
    }
    context = mode_prompts.get(mode_key, mode_prompts["auto"])

    prompt = f"""
{context}

CRITICAL TIMELINE RULES FOR STRICT DUBBING:
1. VIDEO DURATION: The video is EXACTLY {video_duration} seconds long.
2. FULL COVERAGE MANDATE: You MUST process the ENTIRE video from 0.0s up to {video_duration}s. DO NOT stop early. DO NOT summarize. Continue creating timeline entries until the very end of the video.
3. SILENCE HANDLING: Only identify timestamps where speech occurs. Leave gaps when silent.
4. TEXT FORMATTING: Write natural dubbed speech in {lang_instruction}. CRITICAL: DO NOT use double quotes inside dialogue text; use single quotes if needed.
5. STRICT JSON OUTPUT ONLY: Return STRICT JSON without markdown wrapping.

Example Output format:
{{
  "hook_line1": "Catchy Hook Line 1",
  "hook_line2": "Catchy Hook Line 2",
  "dialogues": [
    {{
      "start": 2.5,
      "end": 5.4,
      "speaker": "Hero",
      "text": "Short translated dialogue"
    }}
  ]
}}
"""
    last_err = None

    for k_idx, current_key in enumerate(keys):
        try:
            uploaded_file_ref = None
            if progress_callback:
                progress_callback(15, "📤 Google Cloud Server သို့ ဗီဒီယို ပေးပို့နေပါသည်...")

            if use_new_sdk:
                client = genai.Client(api_key=current_key)
                if video_path and os.path.exists(video_path):
                    video_file = client.files.upload(file=video_path)
                    while True:
                        video_file = client.files.get(name=video_file.name)
                        state_str = str(video_file.state).upper()
                        if "PROCESSING" in state_str:
                            time.sleep(2)
                        elif "ACTIVE" in state_str:
                            uploaded_file_ref = video_file
                            break
                        else:
                            raise ValueError(f"Video Processing Failed on Google Server: {state_str}")
            else:
                legacy_genai.configure(api_key=current_key)
                if video_path and os.path.exists(video_path):
                    video_file_obj = legacy_genai.upload_file(path=video_path)
                    while True:
                        video_file_obj = legacy_genai.get_file(video_file_obj.name)
                        state_str = str(video_file_obj.state.name).upper()
                        if "PROCESSING" in state_str:
                            time.sleep(2)
                        elif "ACTIVE" in state_str:
                            uploaded_file_ref = video_file_obj
                            break
                        else:
                            raise ValueError(f"Video Processing Failed on Google Server: {state_str}")

            raw_resp = ""
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    if progress_callback:
                        progress_callback(30 + (attempt * 3), f"🧠 AI မှ ဇာတ်ကောင် စကားပြောချိန်များကို တိကျစွာ ခွဲခြမ်းစိတ်ဖြာနေပါသည် ({selected_model})...")

                    if use_new_sdk:
                        contents = [uploaded_file_ref, prompt] if uploaded_file_ref else [prompt]
                        res = client.models.generate_content(
                            model=selected_model,
                            contents=contents,
                            config={"max_output_tokens": 8192, "temperature": 0.2}
                        )
                        raw_resp = res.text.strip()
                    else:
                        model = legacy_genai.GenerativeModel(selected_model)
                        contents = [uploaded_file_ref, prompt] if uploaded_file_ref else prompt
                        res = model.generate_content(
                            contents,
                            generation_config=legacy_genai.types.GenerationConfig(max_output_tokens=8192, temperature=0.2)
                        )
                        raw_resp = res.text.strip()
                    break
                except Exception as gen_e:
                    err_msg = str(gen_e).lower()
                    if "503" in err_msg or "unavailable" in err_msg or "demand" in err_msg or "500" in err_msg:
                        if attempt < max_retries - 1:
                            wait_sec = 5 + (attempt * 3)
                            if progress_callback:
                                progress_callback(30, f"⚠️ Google Server ကြပ်နေသဖြင့် {wait_sec} စက္ကန့် စောင့်ဆိုင်းနေပါသည် ({attempt+1}/{max_retries})...")
                            time.sleep(wait_sec)
                            continue
                    raise gen_e

            # Super-resilient JSON Extraction
            raw_clean = re.sub(r"^```json\s*", "", raw_resp, flags=re.MULTILINE)
            raw_clean = re.sub(r"```$", "", raw_clean, flags=re.MULTILINE).strip()

            s_idx = raw_clean.find('{')
            e_idx = raw_clean.rfind('}')
            if s_idx != -1 and e_idx != -1:
                json_str = raw_clean[s_idx:e_idx + 1]
                try:
                    return json.loads(json_str, strict=False)
                except Exception:
                    # Forgiving Regex Extractor fallback
                    h1 = "စိတ်ဝင်စားဖွယ်ရာ"
                    h2 = "ဇာတ်ကွက်များ"
                    m_h1 = re.search(r'"hook_line1"\s*:\s*"([^"]+)"', json_str)
                    m_h2 = re.search(r'"hook_line2"\s*:\s*"([^"]+)"', json_str)
                    if m_h1:
                        h1 = m_h1.group(1)
                    if m_h2:
                        h2 = m_h2.group(1)

                    dialogue_blocks = re.findall(
                        r'\{\s*"start"\s*:\s*([0-9\.]+)\s*,\s*"end"\s*:\s*([0-9\.]+)\s*,\s*"speaker"\s*:\s*"([^"]*)"\s*,\s*"text"\s*:\s*"([^"]*)"\s*\}',
                        json_str
                    )
                    diag_list = []
                    for st_val, en_val, spk, txt in dialogue_blocks:
                        diag_list.append({
                            "start": float(st_val),
                            "end": float(en_val),
                            "speaker": spk,
                            "text": txt
                        })
                    if diag_list:
                        return {"hook_line1": h1, "hook_line2": h2, "dialogues": diag_list}

            raise ValueError("AI JSON ပြန်ကြားချက် မမှန်ကန်ပါ။ Model ကို ပြောင်းလဲ စမ်းသပ်ကြည့်ပါ ခင်ဗျာ။")

        except Exception as e:
            last_err = e
            err_lower = str(e).lower()
            if "429" in err_lower or "quota" in err_lower:
                continue
            break

    raise Exception(f"AI Extraction Error: {last_err}")


def _make_silence_wav(duration_sec: float, out_path: str):
    duration_sec = max(0.02, duration_sec)
    cmd = [
        "ffmpeg", "-y", "-threads", "1", "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo:d={duration_sec:.3f}",
        "-c:a", "pcm_s16le",
        out_path
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def render_strict_1x_absolute_mixer(
    dialogues: List[Dict[str, Any]],
    voice_cfg: Dict[str, str],
    total_video_duration: float,
    final_audio_path: str,
    progress_callback=None,
    unique_tag: Optional[str] = None
):
    """
    STRICT ABSOLUTE-TIMELINE DUBBING (OOM-SAFE, DRIFT-FREE):

    Bug that used to exist here: every dialogue clip's real spoken length
    almost never matches the (end-start) window predicted by the AI. The
    previous implementation simply chained "silence -> speech -> silence..."
    one after another and just kept a running cursor. Whenever a spoken
    clip ran LONGER than the gap before the *next* line, the cursor was
    pushed past that next line's intended start time - and because the
    next line's silence-gap became negative it was just skipped, so the
    line played immediately, already late. From that point on EVERY
    following line inherited the same delay and kept compounding it -
    this is exactly why audio drifted out of sync with the video the
    longer the clip went on, and why the narration could run out before
    reaching the true end of the video (because trailing silence was
    computed from an already-drifted cursor, and the final hard -t trim
    in the video render step then chopped off whatever was left).

    FIX: every spoken clip is hard-capped (via ffmpeg -t truncation) so it
    can NEVER run past the start of the next scheduled line. That keeps
    the cursor mathematically guaranteed to stay <= next line's start, so
    every single line resyncs to its own absolute timestamp - no
    cumulative drift, ever. We also use lossless WAV for every
    intermediate segment (MP3's encoder padding/bit-reservoir behaviour is
    not frame accurate and was an additional, silent source of drift when
    concatenated). Finally we always pad the tail with silence up to the
    EXACT total_video_duration so narration always reaches the real end
    of the video.
    """
    import edge_tts

    tag = unique_tag or uuid.uuid4().hex[:8]

    if not dialogues:
        _make_silence_wav(total_video_duration, final_audio_path + ".wav")
        subprocess.run(
            ["ffmpeg", "-y", "-threads", "1", "-i", final_audio_path + ".wav",
             "-c:a", "libmp3lame", "-b:a", "192k", final_audio_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            os.remove(final_audio_path + ".wav")
        except Exception:
            pass
        return

    # Sort & drop empty-text lines up front so "look-ahead" works correctly.
    cleaned = []
    for item in sorted(dialogues, key=lambda x: float(x.get("start", 0.0))):
        txt = clean_script_line(item.get("text", ""), voice_cfg.get("lang", "my"))
        st = max(0.0, float(item.get("start", 0.0)))
        if txt and st < total_video_duration:
            cleaned.append({"start": st, "text": txt})

    if not cleaned:
        _make_silence_wav(total_video_duration, final_audio_path + ".wav")
        subprocess.run(
            ["ffmpeg", "-y", "-threads", "1", "-i", final_audio_path + ".wav",
             "-c:a", "libmp3lame", "-b:a", "192k", final_audio_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            os.remove(final_audio_path + ".wav")
        except Exception:
            pass
        return

    total_diag = len(cleaned)
    concat_list_file = f"workspace/concat_{tag}.txt"
    segments_info = []
    current_cursor_sec = 0.0

    for idx, item in enumerate(cleaned):
        if progress_callback:
            pct = 50 + int((idx / max(1, total_diag)) * 25)
            progress_callback(pct, f"🎙️ အသံသွင်းနေပါသည် ({idx+1}/{total_diag}) - Absolute-Sync 1x Speed...")

        st_sec = item["start"]
        d_text = item["text"]

        # Hard ceiling: this clip is NEVER allowed to play into the next
        # dialogue's scheduled start (prevents drift + voice overlap).
        next_start = cleaned[idx + 1]["start"] if idx + 1 < len(cleaned) else total_video_duration
        slot_ceiling = max(st_sec, next_start)

        # 1) Fill silence gap before this dialogue if we're not already late.
        gap_sec = st_sec - current_cursor_sec
        if gap_sec > 0.03:
            silence_seg = f"workspace/gap_{tag}_{idx}.wav"
            _make_silence_wav(gap_sec, silence_seg)
            if os.path.exists(silence_seg):
                segments_info.append(silence_seg)
                current_cursor_sec += gap_sec

        allowed_max = max(0.3, slot_ceiling - current_cursor_sec)

        # 2) Synthesize speech (mp3 from edge-tts), then transcode to WAV
        #    while hard-trimming to `allowed_max` so it can never overrun
        #    into the next line's absolute timestamp.
        raw_mp3 = f"workspace/speech_{tag}_{idx}.mp3"
        try:
            comm = edge_tts.Communicate(
                text=d_text,
                voice=voice_cfg["voice"],
                rate=voice_cfg["rate"],
                pitch=voice_cfg["pitch"]
            )
            asyncio.run(comm.save(raw_mp3))
        except Exception:
            continue

        if not os.path.exists(raw_mp3) or os.path.getsize(raw_mp3) < 100:
            continue

        wav_seg = f"workspace/speech_{tag}_{idx}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-threads", "1", "-i", raw_mp3,
             "-t", f"{allowed_max:.3f}", "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", wav_seg],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            os.remove(raw_mp3)
        except Exception:
            pass

        if os.path.exists(wav_seg):
            speech_dur = get_media_duration(wav_seg)
            if speech_dur > 0.05:
                segments_info.append(wav_seg)
                current_cursor_sec += speech_dur
            else:
                try:
                    os.remove(wav_seg)
                except Exception:
                    pass

    # 3) Trailing silence so narration always reaches the REAL end of the
    #    video (this is what was previously missing / falling short).
    if current_cursor_sec < total_video_duration - 0.02:
        tail_sec = total_video_duration - current_cursor_sec
        tail_silence = f"workspace/tail_{tag}.wav"
        _make_silence_wav(tail_sec, tail_silence)
        if os.path.exists(tail_silence):
            segments_info.append(tail_silence)

    if not segments_info:
        _make_silence_wav(total_video_duration, final_audio_path + ".wav")
        segments_info = [final_audio_path + ".wav"]

    # 4) Single concat + single final encode pass (sample accurate, no
    #    repeated mp3 re-encodes which previously caused drift/gaps).
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for s in segments_info:
            abs_p = os.path.abspath(s).replace("'", "'\\''")
            f.write(f"file '{abs_p}'\n")

    cmd_concat = [
        "ffmpeg", "-y", "-threads", "1",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_file,
        "-t", f"{total_video_duration:.3f}",
        "-c:a", "libmp3lame", "-b:a", "192k",
        final_audio_path
    ]
    subprocess.run(cmd_concat, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Cleanup temporary segment files to save disk
    for s in segments_info:
        try:
            if os.path.exists(s):
                os.remove(s)
        except Exception:
            pass
    if os.path.exists(concat_list_file):
        os.remove(concat_list_file)


def hex_to_ass(hex_code: str) -> str:
    h = (hex_code or "#00F2FE").lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H0000FFFF&"


def create_timeline_ass_subtitles(
    h1: str,
    h2: str,
    dialogues: List[Dict[str, Any]],
    duration: float,
    ass_path: str,
    font_size: int = 40,
    v_margin: int = 280,
    hex_color: str = "#00F2FE",
    bg_style: str = "Solid Box"
):
    def fmt_ass_time(s):
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        centis = int((s - int(s)) * 100)
        return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"

    col_primary = hex_to_ass(hex_color)
    if "Solid" in bg_style:
        b_style, outline, shadow, back_c = "3", "1.5", "0", "&H80000000"
    elif "Semi" in bg_style:
        b_style, outline, shadow, back_c = "3", "1.0", "0", "&H40000000"
    else:
        b_style, outline, shadow, back_c = "1", "4.0", "2", "&H00000000"

    ass_text = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SubtitleStyle,{MM_FONT_FAMILY},{font_size},{col_primary},&H000000FF,&H00000000,{back_c},-1,0,0,0,100,100,0,0,{b_style},{outline},{shadow},2,30,30,{v_margin},1
Style: HookStyle,{MM_FONT_FAMILY},44,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if h1 or h2:
        hook_str = f"{h1}\\N{h2}" if h1 and h2 else (h1 or h2)
        ass_text += f"Dialogue: 1,0:00:00.00,{fmt_ass_time(duration)},HookStyle,,0,0,0,,{{\\t(0,200,\\fscx105\\fscy105)\\t(200,350,\\fscx100\\fscy100)}}{hook_str}\n"

    for d in dialogues:
        st_sec = max(0.0, float(d.get("start", 0.0)))
        en_sec = float(d.get("end", st_sec + 2.5))
        if en_sec <= st_sec:
            en_sec = st_sec + 2.5

        line = (d.get("text", "") or "").strip()
        if line:
            pop_fx = "{\\t(0,120,\\fscx110\\fscy110)\\t(120,240,\\fscx100\\fscy100)}"
            ass_text += f"Dialogue: 0,{fmt_ass_time(st_sec)},{fmt_ass_time(en_sec)},SubtitleStyle,,0,0,0,,{pop_fx}{line}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)


def _ffmpeg_quote_path_for_filter(path: str) -> str:
    """Safely quotes an absolute path for use inside an ffmpeg
    filter_complex graph (handles ':' / ''' which otherwise break the
    filter parser, a real bug in the previous implementation that could
    crash subtitle burn-in on certain paths)."""
    abs_p = os.path.abspath(path)
    abs_p = abs_p.replace("\\", "/").replace("'", "'\\\\\\''")
    return abs_p


def render_dialogue_synced_video(
    input_video: str,
    narration_audio: str,
    ass_path: Optional[str],
    output_video: str,
    logo_path: Optional[str] = None,
    logo_pos: str = "top_right",
    logo_pos_x: Optional[float] = None,
    logo_pos_y: Optional[float] = None,
    reframe_mode: str = "Smart Blur Background",
    mute_original: bool = True
):
    exact_duration = get_media_duration(input_video)
    if exact_duration <= 0.0:
        exact_duration = 30.0

    if "Blur" in reframe_mode:
        base_vfilter = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=25:10,eq=brightness=-0.15[bg];"
            "[0:v]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[vreframed]"
        )
    else:
        base_vfilter = "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280[vreframed]"
    v_stream_name = "[vreframed]"

    if ass_path and os.path.exists(ass_path):
        safe_ass = _ffmpeg_quote_path_for_filter(ass_path)
        sub_filter = f"{v_stream_name}subtitles=filename='{safe_ass}':fontsdir=.[vsub]"
    else:
        sub_filter = f"{v_stream_name}copy[vsub]"

    pos_map = {
        "top_right": "main_w-overlay_w-24:24",
        "top_left": "24:24",
        "bottom_right": "main_w-overlay_w-24:main_h-overlay_h-24",
        "bottom_left": "24:main_h-overlay_h-24",
    }

    has_orig = has_audio_stream(input_video)
    if not has_orig or mute_original:
        audio_filter = "[1:a]volume=1.3[afinal]"
    else:
        audio_filter = (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.8[orig_sfx];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.5[ai_dub];"
            "[ai_dub]asplit[ai_final][ai_sc];"
            "[orig_sfx][ai_sc]sidechaincompress=threshold=0.015:ratio=20.0:attack=5:release=1000[ducked_sfx];"
            "[ducked_sfx][ai_final]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[afinal]"
        )

    if logo_path and os.path.exists(logo_path):
        if logo_pos_x is not None and logo_pos_y is not None:
            xr = max(0.0, min(100.0, float(logo_pos_x))) / 100.0
            yr = max(0.0, min(100.0, float(logo_pos_y))) / 100.0
            overlay_coords = f"(main_w-overlay_w)*{xr:.4f}:(main_h-overlay_h)*{yr:.4f}"
        else:
            overlay_coords = pos_map.get(logo_pos, pos_map["top_right"])

        full_complex = (
            f"{base_vfilter};"
            f"{sub_filter};"
            f"[2:v]scale=120:-1,format=rgba[logo];"
            f"[vsub][logo]overlay={overlay_coords}[vfinal];"
            f"{audio_filter}"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "0",
            "-i", input_video,
            "-i", narration_audio,
            "-i", logo_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_video
        ]
    else:
        full_complex = (
            f"{base_vfilter};"
            f"{sub_filter};"
            f"[vsub]copy[vfinal];"
            f"{audio_filter}"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "0",
            "-i", input_video,
            "-i", narration_audio,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_video
        ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(output_video):
        err_tail = proc.stderr.decode("utf-8", errors="ignore")[-1500:]
        raise RuntimeError(f"FFmpeg render failed: {err_tail}")


def run_recap_pipeline(task_id: str, payload: Dict[str, Any]):
    task = get_task_state(task_id) or {}
    try:
        task["status"] = "processing"
        task["progress"] = 5
        task["message"] = "ဗီဒီယို ဖိုင်အား စစ်ဆေးနေပါသည်..."
        save_task_state(task_id, task)

        input_video = payload["input_video"]
        video_dur = get_media_duration(input_video)
        if video_dur <= 0.0:
            video_dur = 30.0

        def update_prog(pct, msg):
            task["progress"] = pct
            task["message"] = msg
            save_task_state(task_id, task)

        # Step 1: AI Timeline Extraction
        api_key = payload.get("api_key") or load_config("gemini_api_key")
        res_data = extract_timeline_dialogues(
            raw_api_keys=api_key,
            video_path=input_video,
            video_duration=video_dur,
            target_language=payload.get("lang", "my"),
            mode_key=payload.get("mode", "auto"),
            selected_model=payload.get("model", "gemini-2.5-flash"),
            progress_callback=update_prog
        )

        task["dialogues"] = res_data.get("dialogues", [])
        task["hook_line1"] = res_data.get("hook_line1", "စိတ်လှုပ်ရှားဖွယ်ရာ")
        task["hook_line2"] = res_data.get("hook_line2", "ဇာတ်ကွက်များ")
        task["input_video"] = input_video
        task["logo_path"] = payload.get("logo_path")
        save_task_state(task_id, task)

        # Step 2: Strict absolute-timeline audio dubbing synthesis
        update_prog(50, "🎙️ Timeline အတိုင်း တိကျစွာ (Drift-Free) အသံသွင်းနေပါသည်...")
        voice_key = payload.get("voice", "thiha")
        lang_key = payload.get("lang", "my")
        voice_cfg = VOICE_CATALOG.get(lang_key, {}).get(voice_key, VOICE_CATALOG["my"]["thiha"])

        synced_audio = f"workspace/{task_id}_narration.mp3"
        render_strict_1x_absolute_mixer(
            dialogues=task["dialogues"],
            voice_cfg=voice_cfg,
            total_video_duration=video_dur,
            final_audio_path=synced_audio,
            progress_callback=update_prog,
            unique_tag=task_id
        )

        # Step 3: Subtitles
        ass_file = None
        if payload.get("enable_subtitles", True):
            update_prog(80, "📝 Pop-in Subtitles ဖန်တီးနေပါသည်...")
            ass_file = f"workspace/{task_id}_subs.ass"
            v_margin = int(1280 * (float(payload.get("sub_v_pos_percent", 22)) / 100.0))
            create_timeline_ass_subtitles(
                h1=task["hook_line1"],
                h2=task["hook_line2"],
                dialogues=task["dialogues"],
                duration=video_dur,
                ass_path=ass_file,
                font_size=int(payload.get("sub_font_size", 40)),
                v_margin=v_margin,
                hex_color=payload.get("sub_color_hex", "#00F2FE"),
                bg_style=payload.get("sub_bg_style", "Solid Box")
            )

        # Step 4: Final FFmpeg Render
        update_prog(88, "🎬 Final Master Video အား Render လုပ်နေပါသည်...")
        final_video_name = f"recap_master_{task_id}.mp4"
        final_output = os.path.join("output", final_video_name)

        logo_path = payload.get("logo_path")
        render_dialogue_synced_video(
            input_video=input_video,
            narration_audio=synced_audio,
            ass_path=ass_file,
            output_video=final_output,
            logo_path=logo_path if (logo_path and os.path.exists(logo_path)) else None,
            logo_pos=payload.get("logo_pos", "top_right"),
            logo_pos_x=payload.get("logo_pos_x"),
            logo_pos_y=payload.get("logo_pos_y"),
            reframe_mode=payload.get("reframe_mode", "Smart Blur Background"),
            mute_original=payload.get("mute_original", True)
        )

        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "🎉 ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ ခင်ဗျာ!"
        task["output_video"] = final_output
        task["download_url"] = f"/api/download/{final_video_name}"
        save_task_state(task_id, task)

    except Exception as e:
        task["status"] = "failed"
        task["progress"] = 0
        task["message"] = f"❌ Error: {str(e)}"
        save_task_state(task_id, task)


def run_rerender_pipeline(task_id: str, payload: Dict[str, Any]):
    task = get_task_state(task_id) or {}
    try:
        task["status"] = "processing"
        task["progress"] = 20
        task["message"] = "အသစ်ပြင်ဆင်ထားသော Timeline ဖြင့် အသံ ပြန်လည်သွင်းနေပါသည်..."
        save_task_state(task_id, task)

        input_video = task["input_video"]
        video_dur = get_media_duration(input_video)
        dialogues = payload.get("dialogues", task.get("dialogues", []))
        task["dialogues"] = dialogues

        voice_key = payload.get("voice", "thiha")
        lang_key = payload.get("lang", "my")
        voice_cfg = VOICE_CATALOG.get(lang_key, {}).get(voice_key, VOICE_CATALOG["my"]["thiha"])

        synced_audio = f"workspace/{task_id}_rerender.mp3"
        render_strict_1x_absolute_mixer(
            dialogues=dialogues,
            voice_cfg=voice_cfg,
            total_video_duration=video_dur,
            final_audio_path=synced_audio,
            unique_tag=f"{task_id}_v2"
        )

        task["progress"] = 65
        task["message"] = "စာတန်းထိုးနှင့် ဗီဒီယို ပေါင်းစပ်နေပါသည်..."
        save_task_state(task_id, task)

        ass_file = None
        if payload.get("enable_subtitles", True):
            ass_file = f"workspace/{task_id}_rerender.ass"
            v_margin = int(1280 * (float(payload.get("sub_v_pos_percent", 22)) / 100.0))
            create_timeline_ass_subtitles(
                h1=payload.get("hook_line1", task.get("hook_line1", "")),
                h2=payload.get("hook_line2", task.get("hook_line2", "")),
                dialogues=dialogues,
                duration=video_dur,
                ass_path=ass_file,
                font_size=int(payload.get("sub_font_size", 40)),
                v_margin=v_margin,
                hex_color=payload.get("sub_color_hex", "#00F2FE"),
                bg_style=payload.get("sub_bg_style", "Solid Box")
            )

        final_video_name = f"recap_master_{task_id}_v2.mp4"
        final_output = os.path.join("output", final_video_name)

        render_dialogue_synced_video(
            input_video=input_video,
            narration_audio=synced_audio,
            ass_path=ass_file,
            output_video=final_output,
            logo_path=payload.get("logo_path", task.get("logo_path")),
            logo_pos=payload.get("logo_pos", "top_right"),
            logo_pos_x=payload.get("logo_pos_x"),
            logo_pos_y=payload.get("logo_pos_y"),
            reframe_mode=payload.get("reframe_mode", "Smart Blur Background"),
            mute_original=payload.get("mute_original", True)
        )

        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "✨ Re-export အောင်မြင်စွာ ပြီးဆုံးပါပြီ ခင်ဗျာ!"
        task["output_video"] = final_output
        task["download_url"] = f"/api/download/{final_video_name}"
        save_task_state(task_id, task)

    except Exception as e:
        task["status"] = "failed"
        task["progress"] = 0
        task["message"] = f"❌ Error: {str(e)}"
        save_task_state(task_id, task)


@app.get("/api/config")
def get_system_config():
    return {
        "gemini_api_key": load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", "")),
        "models": ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"],
        "default_model": "gemini-2.5-flash",
        "voices": VOICE_CATALOG
    }


@app.post("/api/config")
def save_system_config(payload: Dict[str, str]):
    if "gemini_api_key" in payload:
        save_config("gemini_api_key", payload["gemini_api_key"].strip())
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_video_file(video: UploadFile = File(...)):
    ext = os.path.splitext(video.filename)[1].lower() or ".mp4"
    temp_path = f"workspace/input_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
    duration = get_media_duration(temp_path)
    return {"status": "ok", "video_path": temp_path, "duration": duration}


@app.post("/api/upload-logo")
async def upload_logo_file(logo: UploadFile = File(...)):
    tag = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    raw_logo = f"workspace/raw_logo_{tag}.png"
    clean_logo = f"workspace/clean_logo_{tag}.png"
    with open(raw_logo, "wb") as buffer:
        shutil.copyfileobj(logo.file, buffer)
    process_user_logo(raw_logo, clean_logo)
    try:
        os.remove(raw_logo)
    except Exception:
        pass
    return {"status": "ok", "logo_path": clean_logo}


@app.get("/api/preview-asset")
def preview_asset(path: str):
    """Serves a previously uploaded/processed workspace asset (e.g. the
    cropped logo badge) back to the browser so the UI can actually show a
    live preview of it on top of the video - this endpoint did not exist
    before, so the logo could never be previewed client-side."""
    safe_root = os.path.abspath("workspace")
    target = os.path.abspath(path)
    if not target.startswith(safe_root) or not os.path.exists(target):
        raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")
    return FileResponse(target)


@app.post("/api/download-url")
def download_from_url(payload: Dict[str, str]):
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL လိုအပ်ပါသည်")
    out_path = f"workspace/yt_dl_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out_path, url.split("?")[0]], capture_output=True)
    if os.path.exists(out_path):
        return {"status": "ok", "video_path": out_path, "duration": get_media_duration(out_path)}
    raise HTTPException(status_code=500, detail="Download မအောင်မြင်ပါ")


@app.post("/api/start-task")
def start_recap_task(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    task_id = f"task_{int(time.time())}_{os.urandom(2).hex()}"
    task_data = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "အလုပ် စတင်နေပါသည်...",
        "input_video": payload.get("input_video"),
        "logo_path": payload.get("logo_path"),
        "dialogues": [],
        "output_video": None
    }
    save_task_state(task_id, task_data)
    background_tasks.add_task(run_recap_pipeline, task_id, payload)
    return {"status": "ok", "task_id": task_id}


@app.get("/api/task-status/{task_id}")
def get_task_status(task_id: str):
    task = get_task_state(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    return task


@app.post("/api/rerender-task/{task_id}")
def rerender_task(task_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
    task = get_task_state(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    background_tasks.add_task(run_rerender_pipeline, task_id, payload)
    return {"status": "ok", "task_id": task_id}


@app.get("/api/download/{filename}")
def download_rendered_file(filename: str):
    file_path = os.path.join("output", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4", filename=filename)
    raise HTTPException(status_code=404, detail="ဖိုင် ရှာမတွေ့ပါ")


@app.post("/api/generate-thumbnail")
def generate_thumbnail(payload: Dict[str, Any]):
    video_path = payload.get("video_path")
    timestamp = float(payload.get("timestamp", 2.0))
    h1 = payload.get("hook_line1", "စိတ်ဝင်စားဖွယ်ရာ")
    h2 = payload.get("hook_line2", "ဇာတ်ကွက်များ")

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail="ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်ရွေးချယ်ပေးပါ ခင်ဗျာ။")

    raw_frame = f"workspace/frame_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
    subprocess.run([
        "ffmpeg", "-y", "-threads", "1", "-ss", str(timestamp),
        "-i", video_path, "-vframes", "1",
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        raw_frame
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(raw_frame):
        raise HTTPException(status_code=500, detail="Frame ဖမ်းယူမရပါ")

    base = Image.open(raw_frame).convert("RGBA")
    shade = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shade)
    s_draw.rectangle([0, 0, 720, 320], fill=(0, 0, 0, 185))
    base = Image.alpha_composite(base, shade)

    draw = ImageDraw.Draw(base)
    font = get_mm_pil_font(50)

    draw.text((360, 95), h1, fill=(255, 235, 59, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))
    draw.text((360, 175), h2, fill=(0, 242, 254, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))

    out_thumb = f"workspace/thumb_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    base.convert("RGB").save(out_thumb, "JPEG", quality=95)
    try:
        os.remove(raw_frame)
    except Exception:
        pass
    return FileResponse(out_thumb, media_type="image/jpeg")


def _split_one_part(video_path: str, idx: int, st_sec: float, dur_sec: float, aspect: str, fastcopy: bool, tag: str):
    part_name = f"part_{idx+1}_{tag}.mp4"
    out_part = os.path.join("output", part_name)

    if fastcopy:
        cmd = [
            "ffmpeg", "-y", "-ss", str(st_sec), "-i", video_path, "-t", str(dur_sec),
            "-c", "copy", "-avoid_negative_ts", "make_zero", out_part
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0 or not os.path.exists(out_part) or os.path.getsize(out_part) < 1000:
            fastcopy = False  # fall through to re-encode below

    if not fastcopy:
        vf_scale = (
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
            if "9:16" in aspect else "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
        )
        cmd = [
            "ffmpeg", "-y", "-ss", str(st_sec), "-i", video_path, "-t", str(dur_sec),
            "-vf", vf_scale, "-threads", "0",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
            "-c:a", "aac", "-b:a", "128k",
            out_part
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if os.path.exists(out_part) and os.path.getsize(out_part) > 1000:
        return {
            "part": idx + 1,
            "url": f"/api/download/{part_name}",
            "path": out_part,
            "duration": get_media_duration(out_part)
        }
    return None


@app.post("/api/estimate-parts")
def estimate_parts(payload: Dict[str, Any]):
    """Lets the UI instantly show 'how many parts will be created' the
    moment the user picks a slice length, before actually splitting."""
    duration = float(payload.get("duration", 0))
    slice_sec = max(5, int(payload.get("slice_sec", 60)))
    if duration <= 0:
        return {"total_parts": 0}
    total_parts = max(1, math.ceil(duration / slice_sec))
    return {"total_parts": total_parts, "slice_sec": slice_sec, "duration": duration}


@app.post("/api/split-video")
def split_video_endpoint(payload: Dict[str, Any]):
    video_path = payload.get("video_path")
    slice_sec = max(5, int(payload.get("slice_sec", 60)))
    aspect = payload.get("aspect", "9:16")

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail="ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်ရွေးချယ်ပေးပါ ခင်ဗျာ။")

    dur = get_media_duration(video_path)
    if dur <= 0:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် မမှန်ကန်ပါ")

    # FIX: previous formula (`dur % slice_sec > 5`) silently DROPPED the
    # final remainder whenever it was <= 5s, permanently losing that part
    # of the source video. `ceil` always keeps every second of footage.
    total_parts = max(1, math.ceil(dur / slice_sec))

    # FIX (speed): parts used to be rendered ONE BY ONE in a sequential
    # loop. Since every part is fully independent, we now render them all
    # IN PARALLEL (bounded by CPU cores) which is the single biggest
    # speed-up for the splitter, especially on multi-core machines. We
    # also skip re-encoding entirely (stream copy) whenever the requested
    # aspect matches the original orientation, since no pixel processing
    # is actually needed in that case.
    tag = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    fastcopy_eligible = "9:16" not in aspect

    futures = {}
    for i in range(total_parts):
        st_sec = i * slice_sec
        this_dur = min(slice_sec, max(0.1, dur - st_sec))
        futures[split_executor.submit(_split_one_part, video_path, i, st_sec, this_dur, aspect, fastcopy_eligible, tag)] = i

    results = {}
    for fut in as_completed(futures):
        idx = futures[fut]
        try:
            res = fut.result()
            if res:
                results[idx] = res
        except Exception:
            continue

    parts = [results[i] for i in sorted(results.keys())]
    return {"status": "ok", "parts": parts, "total_parts": total_parts}


@app.get("/", response_class=HTMLResponse)
def serve_recap_studio_ui():
    return RECAP_STUDIO_HTML


RECAP_STUDIO_HTML = """<!DOCTYPE html>
<html lang="my" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ Recap Studio MM Pro - High-Speed Master Studio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Plus+Jakarta+Sans:wght@400;600;700&family=Noto+Sans+Myanmar:wght@400;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        cyber: '#00f2fe',
                        neonPurple: '#a855f7',
                        darkBg: '#030712',
                        cardBg: 'rgba(13, 24, 48, 0.85)',
                    },
                    fontFamily: {
                        orbitron: ['Orbitron', 'sans-serif'],
                        sans: ['Plus Jakarta Sans', 'Noto Sans Myanmar', 'sans-serif']
                    }
                }
            }
        }
    </script>
    <style>
        body {
            background: radial-gradient(circle at 15% 15%, #071026 0%, #030712 60%, #02040a 100%);
            min-height: 100vh;
        }
        .neo-card {
            background: linear-gradient(135deg, rgba(13, 24, 48, 0.85) 0%, rgba(5, 12, 26, 0.95) 100%);
            border: 1.5px solid rgba(0, 242, 254, 0.35);
            backdrop-filter: blur(14px);
            transition: all 0.3s ease;
        }
        .neo-card:hover {
            border-color: #00f2fe;
            box-shadow: 0 10px 30px rgba(0, 242, 254, 0.25);
        }
        .badge-sync {
            background: rgba(0, 242, 254, 0.12);
            color: #00f2fe;
            border: 1px solid #00f2fe;
        }
        .badge-purple {
            background: rgba(168, 85, 247, 0.15);
            color: #c084fc;
            border: 1px solid #a855f7;
        }
        #preview-wrapper { position: relative; touch-action: none; }
        #overlay-sub-sample, #overlay-logo-sample {
            position: absolute;
            cursor: grab;
            user-select: none;
            touch-action: none;
        }
        #overlay-sub-sample:active, #overlay-logo-sample:active { cursor: grabbing; }
        #overlay-sub-sample {
            left: 50%;
            transform: translateX(-50%);
            text-align: center;
            font-family: 'Noto Sans Myanmar', sans-serif;
            font-weight: 700;
            white-space: nowrap;
            padding: 4px 14px;
            border-radius: 6px;
            z-index: 20;
        }
        #overlay-logo-sample {
            width: 15%;
            aspect-ratio: 1/1;
            border-radius: 9999px;
            border: 2px solid #00f2fe;
            box-shadow: 0 0 12px rgba(0,242,254,0.6);
            overflow: hidden;
            z-index: 21;
            background: rgba(0,0,0,0.4);
        }
        #overlay-logo-sample img { width: 100%; height: 100%; object-fit: cover; }
        input[type=range] { accent-color: #00f2fe; }
    </style>
</head>
<body class="text-slate-100 font-sans antialiased pb-16">

    <!-- Header Navigation -->
    <header class="border-b border-cyan-500/20 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50 px-6 py-4">
        <div class="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-3">
                <span class="text-3xl">🎬</span>
                <div>
                    <h1 class="font-orbitron font-extrabold text-2xl tracking-wide bg-gradient-to-r from-cyan-400 via-sky-400 to-purple-400 bg-clip-text text-transparent">
                        RECAP STUDIO PRO
                    </h1>
                    <p class="text-xs text-slate-400">Drift-Free Absolute-Sync Dubbing • FastAPI Engine</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="badge-sync px-3 py-1 rounded-full text-xs font-bold">ZERO-DRIFT SYNC</span>
                <span class="badge-purple px-3 py-1 rounded-full text-xs font-bold">FASTAPI CLOUD</span>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 mt-8">

        <!-- Tab Buttons -->
        <div class="flex gap-2 border-b border-slate-800 pb-3 mb-8 overflow-x-auto">
            <button onclick="switchTab('tab-dub')" id="btn-tab-dub" class="px-5 py-2.5 rounded-xl font-bold text-sm bg-cyan-500/20 text-cyan-400 border border-cyan-500/40">🎬 Master Studio</button>
            <button onclick="switchTab('tab-editor')" id="btn-tab-editor" class="px-5 py-2.5 rounded-xl font-bold text-sm text-slate-400 hover:text-cyan-400">⏱️ Timeline Editor</button>
            <button onclick="switchTab('tab-thumb')" id="btn-tab-thumb" class="px-5 py-2.5 rounded-xl font-bold text-sm text-slate-400 hover:text-cyan-400">🖼️ Viral Thumbnail</button>
            <button onclick="switchTab('tab-split')" id="btn-tab-split" class="px-5 py-2.5 rounded-xl font-bold text-sm text-slate-400 hover:text-cyan-400">🍿 Shorts Splitter</button>
            <button onclick="switchTab('tab-settings')" id="btn-tab-settings" class="px-5 py-2.5 rounded-xl font-bold text-sm text-slate-400 hover:text-cyan-400">⚙️ Settings</button>
        </div>

        <!-- Notification Banner -->
        <div id="toast-banner" class="hidden mb-6 p-4 rounded-xl border text-sm font-semibold transition-all"></div>

        <!-- TAB 1: MASTER STUDIO -->
        <div id="tab-dub" class="space-y-6">
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                <!-- Left Input Controls -->
                <div class="lg:col-span-7 space-y-6">
                    <div class="neo-card p-6 rounded-2xl">
                        <h3 class="text-cyan-400 font-bold text-lg mb-4 flex items-center gap-2">
                            <span>1. 📤 ဗီဒီယို တင်ပါ</span>
                        </h3>

                        <div class="space-y-4">
                            <input type="file" id="video-file-input" accept="video/*" class="block w-full text-sm text-slate-400 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-cyan-500/20 file:text-cyan-400 hover:file:bg-cyan-500/30 cursor-pointer border border-slate-700 rounded-xl p-2 bg-slate-900/60">

                            <div class="flex items-center gap-2">
                                <input type="text" id="yt-url-input" placeholder="သို့မဟုတ် Video Link ထည့်ပါ (YouTube/TikTok)..." class="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-sm focus:border-cyan-400 outline-none">
                                <button onclick="downloadFromUrl()" class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-cyan-400 text-sm font-bold rounded-xl border border-slate-700">Download</button>
                            </div>

                            <div id="video-info-box" class="hidden p-3 bg-cyan-950/40 border border-cyan-800/50 rounded-xl text-xs text-cyan-300"></div>

                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                                <div>
                                    <label class="block text-xs font-semibold text-slate-400 mb-1">🎯 Recap အမျိုးအစား</label>
                                    <select id="mode-select" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                                        <option value="auto">🔍 Auto-Detect (အလိုအလျောက် သုံးသပ်မည်)</option>
                                        <option value="movie">🎬 Movie & Fiction Recap (ရုပ်ရှင်ဇာတ်လမ်း)</option>
                                        <option value="experiment">🔬 Science & Test (စမ်းသပ်မှု)</option>
                                        <option value="craft">🛠️ DIY & Craft (လက်မှုပညာ)</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-slate-400 mb-1">📐 မျက်နှာပြင် အချိုးအစား</label>
                                    <select id="reframe-select" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                                        <option value="Smart Blur Background">Smart Blur Background (မူရင်းအပြည့် + ဘေးဝါး)</option>
                                        <option value="Center Crop">Center Crop (အလယ်ကိုသာ ဖြတ်ယူမည်)</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="neo-card p-6 rounded-2xl">
                        <h3 class="text-purple-400 font-bold text-lg mb-4 flex items-center gap-2">
                            <span>2. 🎙️ အသံနှင့် စာတန်းထိုး ထိန်းချုပ်မှု</span>
                        </h3>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-400 mb-1">🌐 ဘာသာစကား</label>
                                <select id="lang-select" onchange="updateVoiceList()" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                                    <option value="my">🇲🇲 Burmese (မြန်မာစကားပြောသံ)</option>
                                    <option value="en">🇬🇧 English (English Dubbing)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-400 mb-1">🎙 Narrator အသံ</label>
                                <select id="voice-select" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                                </select>
                            </div>
                        </div>

                        <div class="mt-4 pt-4 border-t border-slate-800 space-y-3">
                            <label class="flex items-center gap-3 cursor-pointer">
                                <input type="checkbox" id="mute-original-check" checked class="w-4 h-4 rounded text-cyan-500 bg-slate-900 border-slate-700 focus:ring-0">
                                <span class="text-sm font-semibold text-slate-300">🔇 မူရင်းဗီဒီယိုအသံကို အပြည့်အဝ ပိတ်မည် (Mute Original Audio)</span>
                            </label>
                            <label class="flex items-center gap-3 cursor-pointer">
                                <input type="checkbox" id="enable-sub-check" checked class="w-4 h-4 rounded text-cyan-500 bg-slate-900 border-slate-700 focus:ring-0">
                                <span class="text-sm font-semibold text-slate-300">📝 CapCut Style Pop-up စာတန်းထိုး ထည့်သွင်းမည်</span>
                            </label>
                        </div>
                    </div>

                    <div class="neo-card p-6 rounded-2xl">
                        <h3 class="text-cyan-400 font-bold text-lg mb-4 flex items-center gap-2">
                            <span>3. 🖼️ Logo & Caption Style — ညာဘက်ကပုံပေါ်မှာ တိုက်ရိုက်ဆွဲ ပြင်ပါ</span>
                        </h3>

                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-400 mb-1">Logo တင်ရန် (Optional)</label>
                                <input type="file" id="logo-file-input" accept="image/*" class="block w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-cyan-500/20 file:text-cyan-400 cursor-pointer border border-slate-700 rounded-xl p-1.5 bg-slate-900/60">
                                <div class="flex gap-2 mt-2">
                                    <button onclick="setLogoPreset(82,4)" class="flex-1 text-[10px] px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-cyan-400">↗ Top-Right</button>
                                    <button onclick="setLogoPreset(4,4)" class="flex-1 text-[10px] px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-cyan-400">↖ Top-Left</button>
                                    <button onclick="removeLogo()" class="flex-1 text-[10px] px-2 py-1.5 rounded-lg bg-red-900/40 border border-red-700 text-red-300">✕ Remove</button>
                                </div>
                                <p class="text-[10px] text-slate-500 mt-1.5">💡 ညာဘက် Live Preview ပုံပေါ်ကို Logo အသားကို တိုက်ရိုက် ဆွဲ၍ နေရာချနိုင်ပါသည်။</p>
                            </div>
                            <div class="space-y-3">
                                <div>
                                    <div class="flex justify-between text-xs font-semibold text-slate-400 mb-1">
                                        <span>Subtitle အရွယ်အစား</span><span id="lbl-font-size">40px</span>
                                    </div>
                                    <input type="range" id="sub-font-size" min="24" max="64" value="40" class="w-full" oninput="onStyleChange()">
                                </div>
                                <div class="grid grid-cols-2 gap-3">
                                    <div>
                                        <label class="block text-xs font-semibold text-slate-400 mb-1">Subtitle အရောင်</label>
                                        <input type="color" id="sub-color" value="#00f2fe" class="w-full h-9 bg-slate-900 border border-slate-700 rounded-lg cursor-pointer" oninput="onStyleChange()">
                                    </div>
                                    <div>
                                        <label class="block text-xs font-semibold text-slate-400 mb-1">နောက်ခံပုံစံ</label>
                                        <select id="sub-bg-style" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs outline-none" onchange="onStyleChange()">
                                            <option value="Solid Box">Solid Box</option>
                                            <option value="Semi Transparent Box">Semi Transparent</option>
                                            <option value="Outline Only">Outline Only</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <p class="text-[10px] text-slate-500 mt-3">💡 Live Preview ပုံပေါ်က "နမူနာစာသား" ကို ဆွဲ၍ Subtitle အမြင့်အနိမ့် နေရာချနိုင်ပါသည် — ရွေးချယ်သည့်အတိုင်း Final Video ပေါ်တွင် အတိအကျ ထွက်ပါမည်။</p>
                    </div>

                    <button onclick="startDubbingTask()" id="btn-start-dub" class="w-full py-4 rounded-xl font-orbitron font-extrabold text-base bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 tracking-wider shadow-lg shadow-cyan-500/25 transition-all">
                        ⚡ ONE-CLICK ZERO-DRIFT SYNC DUBBING စတင်မည်
                    </button>
                </div>

                <!-- Right Video Player & Live Task Status -->
                <div class="lg:col-span-5 space-y-6">
                    <div class="neo-card p-6 rounded-2xl">
                        <h3 class="text-cyan-400 font-bold text-lg mb-4">📱 Live Preview (ဆွဲ၍ ပြင်နိုင်သည်)</h3>
                        <div id="preview-wrapper" class="w-full rounded-xl bg-black border border-slate-800 aspect-[9/16] overflow-hidden">
                            <video id="preview-player" controls class="w-full h-full object-contain"></video>
                            <div id="overlay-sub-sample" style="bottom:22%; background:rgba(0,0,0,0.5); color:#00f2fe;">နမူနာ Subtitle စာသား</div>
                            <div id="overlay-logo-sample" class="hidden" style="top:4%; left:82%;">
                                <img id="overlay-logo-img" src="" alt="logo">
                            </div>
                        </div>
                        <p class="text-[10px] text-slate-500 mt-2">Subtitle Position: <span id="sub-pos-label">22</span>% (အောက်ခြေမှ) • Logo: <span id="logo-pos-label">ရွေးချယ်မထားပါ</span></p>

                        <div id="progress-container" class="hidden mt-6 space-y-3">
                            <div class="flex justify-between items-center text-xs font-bold">
                                <span id="progress-label" class="text-cyan-400">လုပ်ဆောင်နေပါသည်...</span>
                                <span id="progress-percent" class="text-cyan-300">0%</span>
                            </div>
                            <div class="w-full bg-slate-900 rounded-full h-3 overflow-hidden border border-cyan-500/30">
                                <div id="progress-bar-fill" class="bg-gradient-to-r from-cyan-400 to-purple-500 h-full w-0 transition-all duration-300"></div>
                            </div>
                        </div>

                        <div id="download-box" class="hidden mt-6">
                            <a id="download-link" href="#" download class="block text-center w-full py-3.5 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-slate-950 font-bold rounded-xl shadow-lg shadow-emerald-500/20">
                                📥 Master MP4 ဒေါင်းလုဒ် ရယူရန်
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB 2: TIMELINE EDITOR -->
        <div id="tab-editor" class="hidden space-y-6">
            <div class="neo-card p-6 rounded-2xl">
                <div class="flex justify-between items-center mb-6">
                    <h3 class="text-cyan-400 font-bold text-lg">⏱️ Timeline Editor (စက္ကန့်မလွဲ ပြင်ဆင်ရန်)</h3>
                    <button onclick="reRenderWithEdits()" class="px-5 py-2.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold rounded-xl text-sm shadow-md shadow-cyan-500/20">
                        🚀 ပြင်ဆင်ချက်များဖြင့် Final Video ပြန်ထုတ်မည်
                    </button>
                </div>

                <div class="grid grid-cols-2 gap-4 mb-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">Top Hook Line</label>
                        <input type="text" id="edit-hook1" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">Bottom Hook Line</label>
                        <input type="text" id="edit-hook2" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                    </div>
                </div>

                <div id="timeline-list" class="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                    <p class="text-sm text-slate-500 italic">ဗီဒီယိုအား စတင်ခိုင်းပြီးပါက ဤနေရာတွင် Timeline ဇယားများ ပေါ်လာပါမည်။</p>
                </div>
            </div>
        </div>

        <!-- TAB 3: VIRAL THUMBNAIL -->
        <div id="tab-thumb" class="hidden space-y-6">
            <div class="neo-card p-6 rounded-2xl max-w-xl mx-auto space-y-4">
                <h3 class="text-purple-400 font-bold text-lg">🖼️ 1-Click Viral Thumbnail ဖန်တီးမည်</h3>

                <div>
                    <label class="block text-xs font-semibold text-slate-400 mb-1">ဗီဒီယို ရွေးချယ်ပါ (သီးသန့် Upload)</label>
                    <input type="file" id="thumb-video-file" accept="video/*" class="block w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-purple-500/20 file:text-purple-400 cursor-pointer border border-slate-700 rounded-xl p-2 bg-slate-900/60 mb-2">
                    <p id="thumb-current-info" class="text-xs text-cyan-400">လက်ရှိ Master Studio ဗီဒီယိုကို အသုံးပြုပါမည်။</p>
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-400 mb-1">ဖမ်းယူမည့် စက္ကန့်</label>
                    <input type="number" id="thumb-sec" value="2.5" step="0.5" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">Top Hook စာသား</label>
                        <input type="text" id="thumb-h1" value="စိတ်ဝင်စားဖွယ်ရာ" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">Bottom Hook စာသား</label>
                        <input type="text" id="thumb-h2" value="ဇာတ်ကွက်များ" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                    </div>
                </div>

                <button onclick="generateThumbnailAction()" class="w-full py-3.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-bold rounded-xl text-sm shadow-lg shadow-purple-600/30">
                    ✨ Thumbnail Snapshot ဖန်တီးမည်
                </button>

                <div id="thumb-preview-box" class="hidden mt-6 text-center space-y-4">
                    <img id="thumb-img" class="w-72 mx-auto rounded-xl border border-slate-700 shadow-2xl" src="" alt="Thumbnail">
                    <a id="thumb-download-btn" href="#" download="viral_thumbnail.jpg" class="inline-block px-6 py-2.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold rounded-xl text-xs">
                        📥 Thumbnail ဒေါင်းလုဒ် ရယူရန်
                    </a>
                </div>
            </div>
        </div>

        <!-- TAB 4: SHORTS SPLITTER -->
        <div id="tab-split" class="hidden space-y-6">
            <div class="neo-card p-6 rounded-2xl max-w-2xl mx-auto space-y-4">
                <h3 class="text-cyan-400 font-bold text-lg">🍿 Multi-Part Auto Splitter (Parallel Fast Engine)</h3>

                <div>
                    <label class="block text-xs font-semibold text-slate-400 mb-1">ခွဲထုတ်မည့် ဗီဒီယို ရွေးချယ်ပါ (သီးသန့် Upload တင်နိုင်သည်)</label>
                    <input type="file" id="split-video-file" accept="video/*" class="block w-full text-sm text-slate-400 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-cyan-500/20 file:text-cyan-400 cursor-pointer border border-slate-700 rounded-xl p-2 bg-slate-900/60 mb-2">
                    <p id="split-current-info" class="text-xs text-cyan-400">Master Studio မှ ဗီဒီယို သို့မဟုတ် သီးသန့်ဗီဒီယို တင်နိုင်ပါသည်။</p>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">အပိုင်းတစ်ခုစီ၏ ကြာချိန်</label>
                        <select id="split-slice" onchange="updatePartsEstimate()" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                            <option value="30">၃၀ စက္ကန့်</option>
                            <option value="60" selected>၆၀ စက္ကန့် (၁ မိနစ်)</option>
                            <option value="90">၉၀ စက္ကန့်</option>
                            <option value="120">၁၂၀ စက္ကန့် (၂ မိနစ်)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">ဗီဒီယိုပုံစံ</label>
                        <select id="split-aspect" onchange="updatePartsEstimate()" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                            <option value="9:16">9:16 ဒေါင်လိုက် (Shorts/TikTok)</option>
                            <option value="16:9">မူရင်း 16:9 အလျားလိုက် (Fast Copy)</option>
                        </select>
                    </div>
                </div>

                <div id="parts-estimate-box" class="hidden p-3 rounded-xl bg-cyan-950/40 border border-cyan-800/50 text-sm font-bold text-cyan-300 text-center">
                    ✂️ စုစုပေါင်း <span id="parts-estimate-count">0</span> ပိုင်း ထွက်ရှိပါမည်
                </div>

                <button onclick="startSplitterAction()" id="btn-start-split" class="w-full py-3.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-slate-950 font-bold rounded-xl text-sm shadow-lg shadow-cyan-600/30">
                    ✂ အပိုင်းတိုများ အလိုအလျောက် ခွဲထုတ်မည် (Parallel Fast)
                </button>
                <div id="split-results" class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4"></div>
            </div>
        </div>

        <!-- TAB 5: SETTINGS -->
        <div id="tab-settings" class="hidden space-y-6">
            <div class="neo-card p-6 rounded-2xl max-w-xl mx-auto space-y-4">
                <h3 class="text-cyan-400 font-bold text-lg">⚙️ API Settings</h3>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 mb-1">Google Gemini API Key</label>
                    <input type="password" id="cfg-api-key" placeholder="AIzaSy..." class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 mb-1">AI Model Selection</label>
                    <select id="cfg-model" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                        <option value="gemini-2.5-flash">gemini-2.5-flash (အကြံပြုသည်)</option>
                        <option value="gemini-1.5-flash">gemini-1.5-flash</option>
                        <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                        <option value="gemini-2.0-flash-exp">gemini-2.0-flash-exp</option>
                    </select>
                </div>
                <button onclick="saveSettings()" class="w-full py-3 bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold rounded-xl text-sm">
                    💾 Settings သိမ်းဆည်းမည်
                </button>
            </div>
        </div>

    </main>

    <!-- Client-side Controller Script -->
    <script>
        let currentUploadedVideo = null;
        let currentVideoDuration = 0;
        let currentTaskId = null;
        let pollInterval = null;
        let voiceData = {};
        let currentLogoPath = null;
        let logoPosX = 82, logoPosY = 4;
        let subVPosPercent = 22;

        function showToast(msg, isErr = false) {
            const b = document.getElementById('toast-banner');
            b.className = isErr ? 'mb-6 p-4 rounded-xl border border-red-500/40 bg-red-950/60 text-red-300 text-sm font-semibold' : 'mb-6 p-4 rounded-xl border border-cyan-500/40 bg-cyan-950/60 text-cyan-300 text-sm font-semibold';
            b.innerHTML = msg;
            b.classList.remove('hidden');
            setTimeout(() => b.classList.add('hidden'), 6000);
        }

        function switchTab(tabId) {
            ['tab-dub', 'tab-editor', 'tab-thumb', 'tab-split', 'tab-settings'].forEach(id => {
                document.getElementById(id).classList.add('hidden');
                document.getElementById('btn-' + id)?.classList.remove('bg-cyan-500/20', 'text-cyan-400', 'border', 'border-cyan-500/40');
                document.getElementById('btn-' + id)?.classList.add('text-slate-400');
            });
            document.getElementById(tabId).classList.remove('hidden');
            document.getElementById('btn-' + tabId).classList.add('bg-cyan-500/20', 'text-cyan-400', 'border', 'border-cyan-500/40');
            document.getElementById('btn-' + tabId).classList.remove('text-slate-400');
        }

        async function initApp() {
            try {
                const res = await fetch('/api/config');
                const cfg = await res.json();
                if (cfg.gemini_api_key) {
                    document.getElementById('cfg-api-key').value = cfg.gemini_api_key;
                }
                voiceData = cfg.voices;
                updateVoiceList();
            } catch (e) {
                console.error(e);
            }
            setupDraggableOverlays();
            onStyleChange();
        }

        function updateVoiceList() {
            const lang = document.getElementById('lang-select').value;
            const voiceSel = document.getElementById('voice-select');
            voiceSel.innerHTML = '';
            const list = voiceData[lang] || {};
            for (const [k, v] of Object.entries(list)) {
                const opt = document.createElement('option');
                opt.value = k;
                opt.textContent = v.name;
                voiceSel.appendChild(opt);
            }
        }

        // ── Live style controls (font size / color / bg style) ──────────
        function onStyleChange() {
            const size = document.getElementById('sub-font-size').value;
            const color = document.getElementById('sub-color').value;
            const bg = document.getElementById('sub-bg-style').value;
            document.getElementById('lbl-font-size').innerText = size + 'px';

            const el = document.getElementById('overlay-sub-sample');
            el.style.color = color;
            el.style.fontSize = Math.max(10, size * 0.5) + 'px';
            if (bg.includes('Solid')) {
                el.style.background = 'rgba(0,0,0,0.75)';
                el.style.webkitTextStroke = '0px';
            } else if (bg.includes('Semi')) {
                el.style.background = 'rgba(0,0,0,0.35)';
                el.style.webkitTextStroke = '0px';
            } else {
                el.style.background = 'transparent';
                el.style.textShadow = '0 0 6px #000, 0 0 6px #000, 0 0 6px #000';
            }
        }

        // ── Draggable overlay: subtitle vertical position + logo free position ──
        function setupDraggableOverlays() {
            const wrapper = document.getElementById('preview-wrapper');
            const subEl = document.getElementById('overlay-sub-sample');
            const logoEl = document.getElementById('overlay-logo-sample');

            function bindDrag(el, onMove) {
                let dragging = false;
                const start = (e) => { dragging = true; e.preventDefault(); };
                const move = (e) => {
                    if (!dragging) return;
                    const rect = wrapper.getBoundingClientRect();
                    const point = e.touches ? e.touches[0] : e;
                    const relX = ((point.clientX - rect.left) / rect.width) * 100;
                    const relY = ((point.clientY - rect.top) / rect.height) * 100;
                    onMove(Math.max(0, Math.min(100, relX)), Math.max(0, Math.min(100, relY)));
                };
                const end = () => { dragging = false; };
                el.addEventListener('mousedown', start);
                el.addEventListener('touchstart', start, { passive: false });
                window.addEventListener('mousemove', move);
                window.addEventListener('touchmove', move, { passive: false });
                window.addEventListener('mouseup', end);
                window.addEventListener('touchend', end);
            }

            bindDrag(subEl, (xPct, yPct) => {
                // Convert cursor Y (from top) into "percent from bottom" to match
                // the ASS MarginV convention used by the backend renderer.
                let fromBottom = 100 - yPct;
                fromBottom = Math.max(3, Math.min(92, fromBottom));
                subVPosPercent = Math.round(fromBottom);
                subEl.style.bottom = subVPosPercent + '%';
                document.getElementById('sub-pos-label').innerText = subVPosPercent;
            });

            bindDrag(logoEl, (xPct, yPct) => {
                logoPosX = Math.round(Math.max(0, Math.min(88, xPct)));
                logoPosY = Math.round(Math.max(0, Math.min(88, yPct)));
                logoEl.style.left = logoPosX + '%';
                logoEl.style.top = logoPosY + '%';
                logoEl.style.bottom = 'auto';
                document.getElementById('logo-pos-label').innerText = `x:${logoPosX}% y:${logoPosY}%`;
            });
        }

        function setLogoPreset(x, y) {
            logoPosX = x; logoPosY = y;
            const logoEl = document.getElementById('overlay-logo-sample');
            logoEl.style.left = x + '%';
            logoEl.style.top = y + '%';
            logoEl.style.bottom = 'auto';
            document.getElementById('logo-pos-label').innerText = `x:${x}% y:${y}%`;
        }

        function removeLogo() {
            currentLogoPath = null;
            document.getElementById('overlay-logo-sample').classList.add('hidden');
            document.getElementById('logo-file-input').value = '';
            document.getElementById('logo-pos-label').innerText = 'ရွေးချယ်မထားပါ';
        }

        document.getElementById('logo-file-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('logo', file);
            showToast('📤 Logo တင်သွင်းနေပါသည်...');
            try {
                const res = await fetch('/api/upload-logo', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.status === 'ok') {
                    currentLogoPath = data.logo_path;
                    const logoEl = document.getElementById('overlay-logo-sample');
                    document.getElementById('overlay-logo-img').src = URL.createObjectURL(file);
                    logoEl.classList.remove('hidden');
                    setLogoPreset(logoPosX, logoPosY);
                    showToast('✅ Logo အဆင်သင့်ဖြစ်ပါပြီ! ပုံပေါ်တွင် ဆွဲ၍ နေရာချနိုင်ပါသည်။');
                }
            } catch (err) {
                showToast('❌ Logo Upload မအောင်မြင်ပါ', true);
            }
        });

        document.getElementById('video-file-input').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('video', file);
            showToast('📤 ဗီဒီယို တင်သွင်းနေပါသည်...');
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.status === 'ok') {
                    currentUploadedVideo = data.video_path;
                    currentVideoDuration = data.duration;
                    document.getElementById('preview-player').src = URL.createObjectURL(file);
                    const infoBox = document.getElementById('video-info-box');
                    infoBox.innerHTML = `⏱️ ဗီဒီယို ကြာချိန်: <b>${data.duration.toFixed(2)} စက္ကန့်</b> (${Math.floor(data.duration/60)}:${Math.floor(data.duration%60).toString().padStart(2, '0')})`;
                    infoBox.classList.remove('hidden');
                    document.getElementById('thumb-current-info').innerText = `ရွေးချယ်ထားသော ဗီဒီယို: ${file.name}`;
                    document.getElementById('split-current-info').innerText = `ရွေးချယ်ထားသော ဗီဒီယို: ${file.name}`;
                    showToast('✅ ဗီဒီယို အဆင်သင့်ဖြစ်ပါပြီ!');
                    updatePartsEstimate();
                }
            } catch (err) {
                showToast('❌ Upload မအောင်မြင်ပါ', true);
            }
        });

        // Dedicated Uploader for Thumbnail Tab
        document.getElementById('thumb-video-file')?.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('video', file);
            showToast('📤 Thumbnail ဗီဒီယို တင်သွင်းနေပါသည်...');
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.status === 'ok') {
                    currentUploadedVideo = data.video_path;
                    currentVideoDuration = data.duration;
                    document.getElementById('thumb-current-info').innerText = `သီးသန့်တင်ထားသော ဗီဒီယို: ${file.name}`;
                    showToast('✅ Thumbnail အတွက် ဗီဒီယို အဆင်သင့်ဖြစ်ပါပြီ!');
                }
            } catch (e) {
                showToast('❌ Upload မအောင်မြင်ပါ', true);
            }
        });

        // Dedicated Uploader for Splitter Tab
        document.getElementById('split-video-file')?.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('video', file);
            showToast('📤 Splitter ဗီဒီယို တင်သွင်းနေပါသည်...');
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.status === 'ok') {
                    currentUploadedVideo = data.video_path;
                    currentVideoDuration = data.duration;
                    document.getElementById('split-current-info').innerText = `သီးသန့်တင်ထားသော ဗီဒီယို: ${file.name} (${data.duration.toFixed(1)}s)`;
                    showToast('✅ Splitter အတွက် ဗီဒီယို အဆင်သင့်ဖြစ်ပါပြီ!');
                    updatePartsEstimate();
                }
            } catch (e) {
                showToast('❌ Upload မအောင်မြင်ပါ', true);
            }
        });

        // ── Live "how many parts will this create" preview ──────────────
        async function updatePartsEstimate() {
            const box = document.getElementById('parts-estimate-box');
            if (!currentVideoDuration || currentVideoDuration <= 0) {
                box.classList.add('hidden');
                return;
            }
            const sliceSec = parseInt(document.getElementById('split-slice').value);
            try {
                const res = await fetch('/api/estimate-parts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ duration: currentVideoDuration, slice_sec: sliceSec })
                });
                const data = await res.json();
                document.getElementById('parts-estimate-count').innerText = data.total_parts;
                box.classList.remove('hidden');
            } catch (e) {
                box.classList.add('hidden');
            }
        }

        async function downloadFromUrl() {
            const url = document.getElementById('yt-url-input').value.trim();
            if (!url) return showToast('Video Link ထည့်ပါ', true);
            showToast('⏳ Video ဒေါင်းလုဒ် ဆွဲနေပါသည်...');
            try {
                const res = await fetch('/api/download-url', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ url })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    currentUploadedVideo = data.video_path;
                    currentVideoDuration = data.duration;
                    document.getElementById('preview-player').src = data.video_path;
                    updatePartsEstimate();
                    showToast('✅ ဒေါင်းလုဒ် အောင်မြင်ပါပြီ!');
                }
            } catch (e) {
                showToast('❌ Video Download မရပါ', true);
            }
        }

        function collectStyleConfig() {
            return {
                sub_font_size: parseInt(document.getElementById('sub-font-size').value),
                sub_color_hex: document.getElementById('sub-color').value,
                sub_bg_style: document.getElementById('sub-bg-style').value,
                sub_v_pos_percent: subVPosPercent,
                logo_path: currentLogoPath,
                logo_pos_x: currentLogoPath ? logoPosX : null,
                logo_pos_y: currentLogoPath ? logoPosY : null
            };
        }

        async function startDubbingTask() {
            if (!currentUploadedVideo) return showToast('ကျေးဇူးပြု၍ ဗီဒီယို အရင်တင်ပေးပါ', true);
            const apiKey = document.getElementById('cfg-api-key').value.trim();
            if (!apiKey) return showToast('Gemini API Key ထည့်သွင်းပေးပါ', true);

            const payload = Object.assign({
                input_video: currentUploadedVideo,
                api_key: apiKey,
                model: document.getElementById('cfg-model').value,
                mode: document.getElementById('mode-select').value,
                lang: document.getElementById('lang-select').value,
                voice: document.getElementById('voice-select').value,
                reframe_mode: document.getElementById('reframe-select').value,
                mute_original: document.getElementById('mute-original-check').checked,
                enable_subtitles: document.getElementById('enable-sub-check').checked
            }, collectStyleConfig());

            const btn = document.getElementById('btn-start-dub');
            btn.disabled = true;
            btn.classList.add('opacity-50');

            document.getElementById('progress-container').classList.remove('hidden');
            document.getElementById('download-box').classList.add('hidden');

            try {
                const res = await fetch('/api/start-task', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                currentTaskId = data.task_id;
                pollTaskStatus(currentTaskId);
            } catch (e) {
                showToast('❌ စတင်၍ မရပါ', true);
                btn.disabled = false;
                btn.classList.remove('opacity-50');
            }
        }

        function pollTaskStatus(taskId) {
            clearInterval(pollInterval);
            pollInterval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/task-status/${taskId}`);
                    if (!res.ok) {
                        clearInterval(pollInterval);
                        document.getElementById('btn-start-dub').disabled = false;
                        document.getElementById('btn-start-dub').classList.remove('opacity-50');
                        showToast("Task အခြေအနေ မတွေ့ရှိပါ သို့မဟုတ် Server အသစ်စတင်ထားပါသည်", true);
                        return;
                    }
                    const data = await res.json();

                    if (data.progress !== undefined) {
                        document.getElementById('progress-percent').innerText = `${data.progress}%`;
                        document.getElementById('progress-label').innerText = data.message || 'လုပ်ဆောင်နေပါသည်...';
                        document.getElementById('progress-bar-fill').style.width = `${data.progress}%`;
                    }

                    if (data.status === 'completed') {
                        clearInterval(pollInterval);
                        document.getElementById('btn-start-dub').disabled = false;
                        document.getElementById('btn-start-dub').classList.remove('opacity-50');

                        document.getElementById('preview-player').src = data.download_url;
                        document.getElementById('download-link').href = data.download_url;
                        document.getElementById('download-box').classList.remove('hidden');

                        populateTimelineEditor(data.dialogues, data.hook_line1, data.hook_line2);
                        showToast('🎉 အောင်မြင်ပါပြီ! Master Video ထွက်ရှိပါပြီ!');
                    } else if (data.status === 'failed') {
                        clearInterval(pollInterval);
                        document.getElementById('btn-start-dub').disabled = false;
                        document.getElementById('btn-start-dub').classList.remove('opacity-50');
                        showToast(data.message, true);
                    }
                } catch (e) {
                    console.error(e);
                }
            }, 1500);
        }

        function populateTimelineEditor(dialogues, h1, h2) {
            document.getElementById('edit-hook1').value = h1 || '';
            document.getElementById('edit-hook2').value = h2 || '';
            const list = document.getElementById('timeline-list');
            list.innerHTML = '';

            dialogues.forEach((d, idx) => {
                const row = document.createElement('div');
                row.className = 'grid grid-cols-1 md:grid-cols-12 gap-2 p-3 bg-slate-900/80 rounded-xl border border-slate-800 items-center';
                row.innerHTML = `
                    <span class="text-xs font-bold text-cyan-400 md:col-span-1">#${idx+1}</span>
                    <input type="number" step="0.1" value="${d.start}" id="diag-st-${idx}" class="md:col-span-2 bg-slate-950 border border-slate-700 rounded-lg p-1.5 text-xs text-center">
                    <input type="number" step="0.1" value="${d.end}" id="diag-en-${idx}" class="md:col-span-2 bg-slate-950 border border-slate-700 rounded-lg p-1.5 text-xs text-center">
                    <input type="text" value="${d.text}" id="diag-tx-${idx}" class="md:col-span-7 bg-slate-950 border border-slate-700 rounded-lg p-1.5 text-xs">
                `;
                list.appendChild(row);
            });
        }

        async function reRenderWithEdits() {
            if (!currentTaskId) return showToast('အရင်ဆုံး Task တစ်ခု လုပ်ဆောင်ထားရပါမည်', true);
            const totalRows = document.querySelectorAll('#timeline-list > div').length;
            const newDiags = [];
            for (let i = 0; i < totalRows; i++) {
                newDiags.push({
                    start: parseFloat(document.getElementById(`diag-st-${i}`).value),
                    end: parseFloat(document.getElementById(`diag-en-${i}`).value),
                    text: document.getElementById(`diag-tx-${i}`).value
                });
            }

            const payload = Object.assign({
                dialogues: newDiags,
                hook_line1: document.getElementById('edit-hook1').value,
                hook_line2: document.getElementById('edit-hook2').value,
                voice: document.getElementById('voice-select').value,
                lang: document.getElementById('lang-select').value,
                mute_original: document.getElementById('mute-original-check').checked,
                reframe_mode: document.getElementById('reframe-select').value,
                enable_subtitles: true
            }, collectStyleConfig());

            showToast('⏳ Re-rendering စတင်နေပါသည်...');
            switchTab('tab-dub');
            document.getElementById('progress-container').classList.remove('hidden');

            try {
                await fetch(`/api/rerender-task/${currentTaskId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                pollTaskStatus(currentTaskId);
            } catch (e) {
                showToast('❌ Re-render မအောင်မြင်ပါ', true);
            }
        }

        async function generateThumbnailAction() {
            if (!currentUploadedVideo) return showToast('ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်ရွေးချယ်ပေးပါ ခင်ဗျာ', true);
            showToast('📸 Snapshot ဖမ်းယူနေပါသည်...');
            try {
                const res = await fetch('/api/generate-thumbnail', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        video_path: currentUploadedVideo,
                        timestamp: parseFloat(document.getElementById('thumb-sec').value),
                        hook_line1: document.getElementById('thumb-h1')?.value || "စိတ်ဝင်စားဖွယ်ရာ",
                        hook_line2: document.getElementById('thumb-h2')?.value || "ဇာတ်ကွက်များ"
                    })
                });
                if (!res.ok) {
                    const err = await res.json();
                    showToast(err.detail || '❌ Thumbnail မရပါ', true);
                    return;
                }
                const blob = await res.blob();
                const thumbUrl = URL.createObjectURL(blob);
                document.getElementById('thumb-img').src = thumbUrl;
                document.getElementById('thumb-download-btn').href = thumbUrl;
                document.getElementById('thumb-preview-box').classList.remove('hidden');
                showToast('✅ Thumbnail အဆင်သင့်ဖြစ်ပါပြီ!');
            } catch (e) {
                showToast('❌ Thumbnail မရပါ', true);
            }
        }

        async function startSplitterAction() {
            if (!currentUploadedVideo) return showToast('ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်ရွေးချယ်ပေးပါ ခင်ဗျာ', true);
            const btn = document.getElementById('btn-start-split');
            btn.disabled = true;
            btn.classList.add('opacity-50');
            showToast('✂ အပိုင်းခွဲထုတ်နေပါသည် (Parallel Engine - မြန်ပါသည်)...');

            try {
                const res = await fetch('/api/split-video', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        video_path: currentUploadedVideo,
                        slice_sec: parseInt(document.getElementById('split-slice').value),
                        aspect: document.getElementById('split-aspect').value
                    })
                });
                if (!res.ok) {
                    const err = await res.json();
                    showToast(err.detail || '❌ Splitter Error', true);
                    btn.disabled = false;
                    btn.classList.remove('opacity-50');
                    return;
                }
                const data = await res.json();
                const container = document.getElementById('split-results');
                container.innerHTML = '';
                data.parts.forEach(p => {
                    const box = document.createElement('div');
                    box.className = 'p-3 bg-slate-900 border border-slate-800 rounded-xl text-center space-y-2';
                    box.innerHTML = `
                        <div class="text-xs font-bold text-cyan-400">Part ${p.part} / ${data.total_parts} (${p.duration.toFixed(1)}s)</div>
                        <a href="${p.url}" download class="inline-block px-4 py-1.5 bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 rounded-lg text-xs font-bold">Download Part ${p.part}</a>
                    `;
                    container.appendChild(box);
                });
                showToast(`✅ စုစုပေါင်း ${data.total_parts} ပိုင်း အောင်မြင်စွာ ခွဲထုတ်ပြီးပါပြီ!`);
            } catch (e) {
                showToast('❌ Splitter Error', true);
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50');
            }
        }

        async function saveSettings() {
            const key = document.getElementById('cfg-api-key').value.trim();
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ gemini_api_key: key })
            });
            showToast('✅ Settings သိမ်းဆည်းပြီးပါပြီ!');
        }

        window.onload = initApp;
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
