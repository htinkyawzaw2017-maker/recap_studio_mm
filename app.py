import os
import re
import time
import json
import glob
import shutil
import asyncio
import subprocess
import urllib.request
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

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
  <match target="pattern">
    <test qual="any" name="family"><string>myanmar</string></test>
    <edit name="family" mode="assign" binding="same"><string>Pyidaungsu</string></edit>
  </match>
</fontconfig>""")
    except Exception:
        pass

os.environ["FONTCONFIG_PATH"] = "."

def ensure_myanmar_fonts():
    """Downloads Pyidaungsu font if missing for Burmese subtitles & thumbnails."""
    targets = {
        "Pyidaungsu.ttf": "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf"
    }
    for fname, url in targets.items():
        if not os.path.exists(fname) or os.path.getsize(fname) < 40000:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp, open(fname, "wb") as out_f:
                    out_f.write(resp.read())
            except Exception:
                pass

ensure_myanmar_fonts()

app = FastAPI(title="Recap Studio MM Pro", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("workspace", exist_ok=True)
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
executor = ThreadPoolExecutor(max_workers=2)

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

def has_audio_stream(file_path: str) -> bool:
    try:
        cmd = ["ffprobe", "-i", file_path, "-show_streams", "-select_streams", "a", "-loglevel", "error"]
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
    try:
        img = Image.open(input_path).convert("RGBA")
        pixels = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r > 215 and g > 215 and b > 215:
                    pixels[x, y] = (255, 255, 255, 0)
                elif r < 30 and g < 30 and b < 30:
                    pixels[x, y] = (0, 0, 0, 0)

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
    progress_callback = None
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
                json_str = raw_clean[s_idx:e_idx+1]
                try:
                    return json.loads(json_str, strict=False)
                except Exception:
                    # Forgiving Regex Extractor fallback
                    h1 = "စိတ်ဝင်စားဖွယ်ရာ"
                    h2 = "ဇာတ်ကွက်များ"
                    m_h1 = re.search(r'"hook_line1"\s*:\s*"([^"]+)"', json_str)
                    m_h2 = re.search(r'"hook_line2"\s*:\s*"([^"]+)"', json_str)
                    if m_h1: h1 = m_h1.group(1)
                    if m_h2: h2 = m_h2.group(1)
                    
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

def render_strict_1x_absolute_mixer(
    dialogues: List[Dict[str, Any]],
    voice_cfg: Dict[str, str],
    total_video_duration: float,
    final_audio_path: str,
    progress_callback = None
):
    import edge_tts

    base_silence = "workspace/base_silence.mp3"
    cmd_base = [
        "ffmpeg", "-y", "-threads", "2", "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo:d={total_video_duration:.3f}",
        "-c:a", "libmp3lame", "-b:a", "192k",
        base_silence
    ]
    subprocess.run(cmd_base, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not dialogues:
        shutil.copy(base_silence, final_audio_path)
        return

    segment_files = []
    total_diag = len(dialogues)

    for idx, item in enumerate(dialogues):
        if progress_callback:
            pct = 50 + int((idx / max(1, total_diag)) * 25)
            progress_callback(pct, f"🎙️ အသံသွင်းနေပါသည် ({idx+1}/{total_diag}) - Normal 1x Speed...")

        d_text = clean_script_line(item.get("text", ""), voice_cfg.get("lang", "my"))
        if not d_text:
            continue

        raw_seg = f"workspace/raw_seg_{idx}.mp3"
        comm = edge_tts.Communicate(
            text=d_text,
            voice=voice_cfg["voice"],
            rate=voice_cfg["rate"],
            pitch=voice_cfg["pitch"]
        )
        asyncio.run(comm.save(raw_seg))

        d_start_ms = int(max(0.0, float(item.get("start", 0.0))) * 1000)
        if os.path.exists(raw_seg) and get_media_duration(raw_seg) > 0.05:
            segment_files.append((raw_seg, d_start_ms))

    if not segment_files:
        shutil.copy(base_silence, final_audio_path)
        return

    # Mix segments using adelay directly on the silent timeline
    cmd_mix = ["ffmpeg", "-y", "-threads", "2", "-i", base_silence]
    filter_complex = []
    amix_inputs = ["[0:a]"]

    for i, (seg_file, start_ms) in enumerate(segment_files):
        cmd_mix.extend(["-i", seg_file])
        inp_idx = i + 1
        filter_complex.append(f"[{inp_idx}:a]adelay={start_ms}|{start_ms}[a{inp_idx}]")
        amix_inputs.append(f"[a{inp_idx}]")

    amix_str = "".join(amix_inputs)
    total_inputs = len(segment_files) + 1
    # normalize=0 PREVENTS echo and volume oscillation
    filter_complex.append(f"{amix_str}amix=inputs={total_inputs}:duration=first:dropout_transition=0:normalize=0[aout]")

    cmd_mix.extend([
        "-filter_complex", ";".join(filter_complex),
        "-map", "[aout]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        final_audio_path
    ])

    subprocess.run(cmd_mix, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def hex_to_ass(hex_code: str) -> str:
    h = hex_code.lstrip("#")
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
Style: SubtitleStyle,Pyidaungsu,{font_size},{col_primary},&H000000FF,&H00000000,{back_c},-1,0,0,0,100,100,0,0,{b_style},{outline},{shadow},2,30,30,{v_margin},1
Style: HookStyle,Pyidaungsu,44,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,90,1

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
            
        line = d.get("text", "").strip()
        if line:
            pop_fx = "{\\t(0,120,\\fscx110\\fscy110)\\t(120,240,\\fscx100\\fscy100)}"
            ass_text += f"Dialogue: 0,{fmt_ass_time(st_sec)},{fmt_ass_time(en_sec)},SubtitleStyle,,0,0,0,,{pop_fx}{line}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

def render_dialogue_synced_video(
    input_video: str,
    narration_audio: str,
    ass_path: Optional[str],
    output_video: str,
    logo_path: Optional[str] = None,
    logo_pos: str = "top_right",
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
        v_stream_name = "[vreframed]"
    else:
        base_vfilter = "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280[vreframed]"
        v_stream_name = "[vreframed]"

    sub_filter = f"{v_stream_name}subtitles={ass_path}:fontsdir=.[vsub]" if (ass_path and os.path.exists(ass_path)) else f"{v_stream_name}copy[vsub]"

    pos_map = {
        "top_right": "main_w-overlay_w-24:24",
        "top_left": "24:24",
        "bottom_right": "main_w-overlay_w-24:main_h-overlay_h-24"
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
        overlay_coords = pos_map.get(logo_pos, "main_w-overlay_w-24:24")
        full_complex = (
            f"{base_vfilter};"
            f"{sub_filter};"
            f"[2:v]scale=120:-1,format=rgba[logo];"
            f"[vsub][logo]overlay={overlay_coords}[vfinal];"
            f"{audio_filter}"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "2",
            "-i", input_video,
            "-i", narration_audio,
            "-i", logo_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
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
            "ffmpeg", "-y", "-threads", "2",
            "-i", input_video,
            "-i", narration_audio,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def run_recap_pipeline(task_id: str, payload: Dict[str, Any]):
    task = TASKS[task_id]
    try:
        task["status"] = "processing"
        task["progress"] = 5
        task["message"] = "ဗီဒီယို ဖိုင်အား စစ်ဆေးနေပါသည်..."

        input_video = payload["input_video"]
        video_dur = get_media_duration(input_video)
        if video_dur <= 0.0:
            video_dur = 30.0

        def update_prog(pct, msg):
            task["progress"] = pct
            task["message"] = msg

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

        # Step 2: Strict 1x Audio Dubbing Synthesis
        update_prog(50, "🎙️ Normal 1x Speed အတိုင်း နေရာချထား အသံသွင်းနေပါသည်...")
        voice_key = payload.get("voice", "thiha")
        lang_key = payload.get("lang", "my")
        voice_cfg = VOICE_CATALOG.get(lang_key, {}).get(voice_key, VOICE_CATALOG["my"]["thiha"])

        synced_audio = f"workspace/{task_id}_narration.mp3"
        render_strict_1x_absolute_mixer(
            dialogues=task["dialogues"],
            voice_cfg=voice_cfg,
            total_video_duration=video_dur,
            final_audio_path=synced_audio,
            progress_callback=update_prog
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
        update_prog(88, "🎬 Final Master Video အား Render လုပ်နေပါသည် (Fast)...")
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
            reframe_mode=payload.get("reframe_mode", "Smart Blur Background"),
            mute_original=payload.get("mute_original", True)
        )

        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "🎉 ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ ခင်ဗျာ!"
        task["output_video"] = final_output
        task["download_url"] = f"/api/download/{final_video_name}"

    except Exception as e:
        task["status"] = "failed"
        task["progress"] = 0
        task["message"] = f"❌ Error: {str(e)}"

def run_rerender_pipeline(task_id: str, payload: Dict[str, Any]):
    task = TASKS[task_id]
    try:
        task["status"] = "processing"
        task["progress"] = 20
        task["message"] = "အသစ်ပြင်ဆင်ထားသော Timeline ဖြင့် အသံ ပြန်လည်သွင်းနေပါသည်..."

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
            final_audio_path=synced_audio
        )

        task["progress"] = 65
        task["message"] = "စာတန်းထိုးနှင့် ဗီဒီယို ပေါင်းစပ်နေပါသည်..."

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
            logo_path=task.get("logo_path"),
            logo_pos="top_right",
            reframe_mode=payload.get("reframe_mode", "Smart Blur Background"),
            mute_original=payload.get("mute_original", True)
        )

        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "✨ Re-export အောင်မြင်စွာ ပြီးဆုံးပါပြီ ခင်ဗျာ!"
        task["output_video"] = final_output
        task["download_url"] = f"/api/download/{final_video_name}"

    except Exception as e:
        task["status"] = "failed"
        task["progress"] = 0
        task["message"] = f"❌ Error: {str(e)}"

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
    temp_path = f"workspace/input_{int(time.time())}{ext}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
    duration = get_media_duration(temp_path)
    return {"status": "ok", "video_path": temp_path, "duration": duration}

@app.post("/api/upload-logo")
async def upload_logo_file(logo: UploadFile = File(...)):
    raw_logo = f"workspace/raw_logo_{int(time.time())}.png"
    clean_logo = f"workspace/clean_logo_{int(time.time())}.png"
    with open(raw_logo, "wb") as buffer:
        shutil.copyfileobj(logo.file, buffer)
    process_user_logo(raw_logo, clean_logo)
    return {"status": "ok", "logo_path": clean_logo}

@app.post("/api/download-url")
def download_from_url(payload: Dict[str, str]):
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL လိုအပ်ပါသည်")
    out_path = f"workspace/yt_dl_{int(time.time())}.mp4"
    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out_path, url.split("?")[0]], capture_output=True)
    if os.path.exists(out_path):
        return {"status": "ok", "video_path": out_path, "duration": get_media_duration(out_path)}
    raise HTTPException(status_code=500, detail="Download မအောင်မြင်ပါ")

@app.post("/api/start-task")
def start_recap_task(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    task_id = f"task_{int(time.time())}_{os.urandom(2).hex()}"
    TASKS[task_id] = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "အလုပ် စတင်နေပါသည်...",
        "input_video": payload.get("input_video"),
        "logo_path": payload.get("logo_path"),
        "dialogues": [],
        "output_video": None
    }
    background_tasks.add_task(run_recap_pipeline, task_id, payload)
    return {"status": "ok", "task_id": task_id}

@app.get("/api/task-status/{task_id}")
def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task ရှာမတွေ့ပါ")
    return TASKS[task_id]

@app.post("/api/rerender-task/{task_id}")
def rerender_task(task_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
    if task_id not in TASKS:
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
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် မရှိပါ")

    raw_frame = f"workspace/frame_{int(time.time())}.png"
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
    font_path = "Pyidaungsu.ttf" if os.path.exists("Pyidaungsu.ttf") else None
    font = ImageFont.truetype(font_path, 50) if font_path else ImageFont.load_default()

    draw.text((360, 95), h1, fill=(255, 235, 59, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))
    draw.text((360, 175), h2, fill=(0, 242, 254, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))

    out_thumb = f"workspace/thumb_{int(time.time())}.jpg"
    base.convert("RGB").save(out_thumb, "JPEG", quality=95)
    return FileResponse(out_thumb, media_type="image/jpeg")

@app.post("/api/split-video")
def split_video_endpoint(payload: Dict[str, Any]):
    video_path = payload.get("video_path")
    slice_sec = int(payload.get("slice_sec", 60))
    aspect = payload.get("aspect", "9:16")

    dur = get_media_duration(video_path)
    if dur <= 0:
        raise HTTPException(status_code=400, detail="ဗီဒီယိုဖိုင် မရှိပါ")

    total_parts = max(1, int(dur // slice_sec))
    parts = []

    for i in range(total_parts):
        st_sec = i * slice_sec
        part_name = f"part_{i+1}_{int(time.time())}.mp4"
        out_part = os.path.join("output", part_name)
        vf_scale = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280" if "9:16" in aspect else "scale=1280:720"

        cmd = [
            "ffmpeg", "-y", "-threads", "2", "-ss", str(st_sec), "-t", str(slice_sec),
            "-i", video_path, "-vf", vf_scale,
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            out_part
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(out_part):
            parts.append({"part": i + 1, "url": f"/api/download/{part_name}", "path": out_part})

    return {"status": "ok", "parts": parts}

@app.get("/", response_class=HTMLResponse)
def serve_recap_studio_ui():
    return """<!DOCTYPE html>
<html lang="my" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ Recap Studio MM Pro - High-Speed Master Studio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Plus+Jakarta+Sans:wght@400;600;700&family=Pyidaungsu:wght@400;700&display=swap" rel="stylesheet">
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
                        sans: ['Plus Jakarta Sans', 'Pyidaungsu', 'sans-serif']
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
                    <p class="text-xs text-slate-400">Normal 1x Speed Locked Absolute Dubbing • FastAPI Engine</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="badge-sync px-3 py-1 rounded-full text-xs font-bold">1X STRICT DUBBING</span>
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
                            <span>2. 🎙️ အသံနှင့် Logo ထိန်းချုပ်မှု</span>
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
                                <label class="block text-xs font-semibold text-slate-400 mb-1">🎙️️ Narrator အသံ</label>
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

                    <button onclick="startDubbingTask()" id="btn-start-dub" class="w-full py-4 rounded-xl font-orbitron font-extrabold text-base bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 tracking-wider shadow-lg shadow-cyan-500/25 transition-all">
                        ⚡ ONE-CLICK STRICT 1X SYNC DUBBING စတင်မည်
                    </button>
                </div>

                <!-- Right Video Player & Live Task Status -->
                <div class="lg:col-span-5 space-y-6">
                    <div class="neo-card p-6 rounded-2xl">
                        <h3 class="text-cyan-400 font-bold text-lg mb-4">📱 Live Preview</h3>
                        <video id="preview-player" controls class="w-full rounded-xl bg-black border border-slate-800 aspect-[9/16] object-contain"></video>

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
                    <label class="block text-xs font-semibold text-slate-400 mb-1">ဖမ်းယူမည့် စက္ကန့်</label>
                    <input type="number" id="thumb-sec" value="2.5" step="0.5" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                </div>
                <button onclick="generateThumbnail()" class="w-full py-3 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded-xl text-sm">
                    ✨ Thumbnail Snapshot ဖန်တီးမည်
                </button>
                <div id="thumb-preview-box" class="hidden mt-4 text-center">
                    <img id="thumb-img" class="w-64 mx-auto rounded-xl border border-slate-700 shadow-xl" src="" alt="Thumbnail">
                </div>
            </div>
        </div>

        <!-- TAB 4: SHORTS SPLITTER -->
        <div id="tab-split" class="hidden space-y-6">
            <div class="neo-card p-6 rounded-2xl max-w-2xl mx-auto space-y-4">
                <h3 class="text-cyan-400 font-bold text-lg">🍿 Multi-Part Auto Splitter (1 GB Support)</h3>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">အပိုင်းတစ်ခုစီ၏ ကြာချိန်</label>
                        <select id="split-slice" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                            <option value="30">၃၀ စက္ကန့်</option>
                            <option value="60" selected>၆၀ စက္ကန့် (၁ မိနစ်)</option>
                            <option value="90">၉၀ စက္ကန့်</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 mb-1">ဗီဒီယိုပုံစံ</label>
                        <select id="split-aspect" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-sm outline-none focus:border-cyan-400">
                            <option value="9:16">9:16 ဒေါင်လိုက် (Shorts/TikTok)</option>
                            <option value="16:9">မူရင်း 16:9 အလျားလိုက်</option>
                        </select>
                    </div>
                </div>
                <button onclick="startSplitter()" class="w-full py-3 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold rounded-xl text-sm">
                    ✂ အပိုင်းတိုများ အလိုအလျောက် ခွဲထုတ်မည်
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
                    infoBox.innerHTML = `⏱️ ဗီဒီယို ကြာချိန်: <b>${data.duration.toFixed(2)} စက္ကန့်</b> (${Math.floor(data.duration/60)}:0${Math.floor(data.duration%60)})`;
                    infoBox.classList.remove('hidden');
                    showToast('✅ ဗီဒီယို အဆင်သင့်ဖြစ်ပါပြီ!');
                }
            } catch (err) {
                showToast('❌ Upload မအောင်မြင်ပါ', true);
            }
        });

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
                    showToast('✅ ဒေါင်းလုဒ် အောင်မြင်ပါပြီ!');
                }
            } catch (e) {
                showToast('❌ Video Download မရပါ', true);
            }
        }

        async function startDubbingTask() {
            if (!currentUploadedVideo) return showToast('ကျေးဇူးပြု၍ ဗီဒီယို အရင်တင်ပေးပါ', true);
            const apiKey = document.getElementById('cfg-api-key').value.trim();
            if (!apiKey) return showToast('Gemini API Key ထည့်သွင်းပေးပါ', true);

            const payload = {
                input_video: currentUploadedVideo,
                api_key: apiKey,
                model: document.getElementById('cfg-model').value,
                mode: document.getElementById('mode-select').value,
                lang: document.getElementById('lang-select').value,
                voice: document.getElementById('voice-select').value,
                reframe_mode: document.getElementById('reframe-select').value,
                mute_original: document.getElementById('mute-original-check').checked,
                enable_subtitles: document.getElementById('enable-sub-check').checked
            };

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
                    const data = await res.json();
                    
                    document.getElementById('progress-percent').innerText = `${data.progress}%`;
                    document.getElementById('progress-label').innerText = data.message;
                    document.getElementById('progress-bar-fill').style.width = `${data.progress}%`;

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

            const payload = {
                dialogues: newDiags,
                hook_line1: document.getElementById('edit-hook1').value,
                hook_line2: document.getElementById('edit-hook2').value,
                voice: document.getElementById('voice-select').value,
                lang: document.getElementById('lang-select').value,
                mute_original: document.getElementById('mute-original-check').checked,
                enable_subtitles: true
            };

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

        async function generateThumbnail() {
            if (!currentUploadedVideo) return showToast('ဗီဒီယို အရင်တင်ပေးပါ', true);
            showToast('📸 Snapshot ဖမ်းယူနေပါသည်...');
            try {
                const res = await fetch('/api/generate-thumbnail', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        video_path: currentUploadedVideo,
                        timestamp: parseFloat(document.getElementById('thumb-sec').value),
                        hook_line1: document.getElementById('edit-hook1')?.value || "စိတ်ဝင်စားဖွယ်ရာ",
                        hook_line2: document.getElementById('edit-hook2')?.value || "ဇာတ်ကွက်များ"
                    })
                });
                const blob = await res.blob();
                document.getElementById('thumb-img').src = URL.createObjectURL(blob);
                document.getElementById('thumb-preview-box').classList.remove('hidden');
                showToast('✅ Thumbnail အဆင်သင့်ဖြစ်ပါပြီ!');
            } catch (e) {
                showToast('❌ Thumbnail မရပါ', true);
            }
        }

        async function startSplitter() {
            if (!currentUploadedVideo) return showToast('ဗီဒီယို အရင်တင်ပေးပါ', true);
            showToast('✂ အပိုင်းခွဲထုတ်နေပါသည်...');
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
                const data = await res.json();
                const container = document.getElementById('split-results');
                container.innerHTML = '';
                data.parts.forEach(p => {
                    const box = document.createElement('div');
                    box.className = 'p-3 bg-slate-900 border border-slate-800 rounded-xl text-center space-y-2';
                    box.innerHTML = `
                        <div class="text-xs font-bold text-cyan-400">Part ${p.part}</div>
                        <a href="${p.url}" download class="inline-block px-4 py-1.5 bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 rounded-lg text-xs font-bold">Download Part ${p.part}</a>
                    `;
                    container.appendChild(box);
                });
                showToast('✅ ခွဲထုတ်ခြင်း ပြီးပါပြီ!');
            } catch (e) {
                showToast('❌ Splitter Error', true);
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
