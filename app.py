import streamlit as st
import os
import re
import time
import json
import glob
import base64
import shutil
import asyncio
import datetime
import subprocess
import urllib.request
from PIL import Image, ImageDraw, ImageFont

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM Pro",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- MYANMAR UNICODE FONT CONFIG -----------------
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
    targets = {
        "Pyidaungsu.ttf": "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf",
        "Padauk-Regular.ttf": "https://raw.githubusercontent.com/googlefonts/padauk/main/fonts/ttf/Padauk-Regular.ttf"
    }
    for fname, url in targets.items():
        if not os.path.exists(fname) or os.path.getsize(fname) < 50000:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp, open(fname, "wb") as out_f:
                    out_f.write(resp.read())
            except Exception:
                pass

ensure_myanmar_fonts()

# ----------------- CONFIG STORAGE -----------------
CONFIG_FILE = ".recap_config.json"

def load_config(key, default=""):
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key, default)
        except Exception:
            pass
    return default

def save_config(key, value):
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

# ----------------- DURATION & TIMING HELPERS -----------------
def get_media_duration(file_path):
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
        data = json.loads(res.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0

def format_time_str(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

# ----------------- LANGUAGE DEFINITIONS & ACCURATE UNICODE -----------------
LANGUAGE_CONFIGS = {
    "🇲🇲 မြန်မာ (Myanmar / Burmese)": {
        "code": "my",
        "default_voice": "မင်းသန့် (Recommended - Agency, Confident Narrator)",
        "default_hook1": "တိရစ္ဆာန်တွေကို တရားစွဲ",
        "default_hook2": "ကြိုးပေးကွပ်မျက်ခဲ့",
        "default_sub_preview": "လူတွေတင် မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ ထူးဆန်းတဲ့ သမိုင်း...",
        "sample_speech": "မင်္ဂလာပါ ကျွန်တော်ကတော့ မင်းသန့်ပါ။ ဒီနေ့မှာတော့ ထူးဆန်းတဲ့ သမိုင်းကြောင်းကို ပြောပြပေးပါမယ် ခင်ဗျာ။",
        "cta_options": {
            "Subscribe လုပ်ထားပေးပါ ခင်ဗျာ": "🔔 Subscribe လုပ်ထားပေးပါ ခင်ဗျာ",
            "Like ပေးခဲ့ပါဦး ခင်ဗျာ": "👍 Like ပေးခဲ့ပါဦး ခင်ဗျာ",
            "Like & Subscribe လုပ်ထားပါ ခင်ဗျာ": "👍 Like & 🔔 Subscribe လုပ်ထားပါ ခင်ဗျာ",
            "စာရင်းသွင်းပါ (Formal Unicode)": "စာရင်းသွင်းပါ"
        },
        "voices": {
            "မင်းသန့် (Recommended - Agency, Confident Narrator)": {
                "voice": "my-MM-ThihaNeural", "pitch": "-2Hz", "rate_offset": 6,
                "desc": "ဆွဲဆောင်မှုရှိပြီး စကားပြောအလွန်ပီပြင်သော Movie Recap အသံ (ထိပ်တန်းရွေးချယ်မှု)"
            },
            "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)": {
                "voice": "my-MM-ThihaNeural", "pitch": "-8Hz", "rate_offset": 4,
                "desc": "ရုပ်ရှင်ဇာတ်လမ်းပြော ရင်ထဲထိစေမည့် အသံဩဇာကြီးမားသော အသံနက်ကြီး (Bass Deep Voice)"
            },
            "သီဟ (Native Male - Action & Dynamic)": {
                "voice": "my-MM-ThihaNeural", "pitch": "+1Hz", "rate_offset": 8,
                "desc": "သွက်လက်တက်ကြွပြီး စိတ်လှုပ်ရှားဖွယ် ဇာတ်ကွက်များအတွက် စကားပြောဟန်"
            },
            "အောင်ကျော် (Radio & Dramatic Narrator)": {
                "voice": "my-MM-ThihaNeural", "pitch": "+4Hz", "rate_offset": 10,
                "desc": "အလွန်သွက်လက်ပြီး ဆွဲဆောင်အားပြင်းသော အသံ"
            },
            "မေသူ (Soft Emotional Voice - Drama & Mystery)": {
                "voice": "my-MM-NilarNeural", "pitch": "+4Hz", "rate_offset": 2,
                "desc": "နူးညံ့ညင်သာပြီး စိတ်ခံစားမှု အပြည့်ပါသော အမျိုးသမီးအသံ"
            }
        }
    },
    "🇺🇸 English (အင်္ဂလိပ်)": {
        "code": "en",
        "default_voice": "Christopher (Cinematic Deep Narrator)",
        "default_hook1": "ANIMALS ON TRIAL",
        "default_hook2": "EXECUTED BY LAW",
        "default_sub_preview": "Have you ever heard of animals being arrested, put on trial, and sentenced in medieval courts?",
        "sample_speech": "Welcome! Today we are looking at an unbelievable true story from ancient history.",
        "cta_options": {
            "Subscribe": "🔔 Subscribe for more!",
            "Like": "👍 Leave a like!",
            "Like & Subscribe": "👍 Like & 🔔 Subscribe!"
        },
        "voices": {
            "Christopher (Cinematic Deep Narrator)": {
                "voice": "en-US-ChristopherNeural", "pitch": "-4Hz", "rate_offset": 5,
                "desc": "Deep, resonant cinematic Hollywood documentary male narrator"
            },
            "Guy (Viral Recap Storyteller - High Retention)": {
                "voice": "en-US-GuyNeural", "pitch": "+0Hz", "rate_offset": 8,
                "desc": "Energetic, engaging TikTok/Shorts movie recapper voice"
            }
        }
    }
}

# ----------------- SESSION STATE -----------------
if "gemini_api_key" not in st.session_state:
    saved_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))
    try:
        if not saved_key and "GEMINI_API_KEY" in st.secrets:
            saved_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    st.session_state.gemini_api_key = saved_key

if "target_language" not in st.session_state:
    st.session_state.target_language = "🇲🇲 မြန်မာ (Myanmar / Burmese)"

cur_lang_cfg = LANGUAGE_CONFIGS[st.session_state.target_language]

if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = cur_lang_cfg["default_hook1"]

if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = cur_lang_cfg["default_hook2"]

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = cur_lang_cfg["default_sub_preview"]

if "sub_v_pos_percent" not in st.session_state:
    st.session_state.sub_v_pos_percent = 22

if "sub_width_percent" not in st.session_state:
    st.session_state.sub_width_percent = 85

if "hook_top_percent" not in st.session_state:
    st.session_state.hook_top_percent = 8

if "sub_font_size" not in st.session_state:
    st.session_state.sub_font_size = 40

if "sub_custom_color" not in st.session_state:
    st.session_state.sub_custom_color = "#FFDF00"  # Vibrant Gold

if "sub_bg_mode" not in st.session_state:
    st.session_state.sub_bg_mode = "Solid Black Box (အမည်းနောက်ခံ)"

if "selected_cta_text" not in st.session_state:
    st.session_state.selected_cta_text = "Like & Subscribe လုပ်ထားပါ ခင်ဗျာ"

if "enable_cta_overlay" not in st.session_state:
    st.session_state.enable_cta_overlay = True

if "last_final_video" not in st.session_state:
    st.session_state.last_final_video = "recap_output.mp4" if os.path.exists("recap_output.mp4") else ""

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.12

# ----------------- TEXT CLEANING & SCRIPT HELPER -----------------
def clean_script_for_narration(text):
    if not text:
        return ""
    text = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?\s*[:\s-]*", "", text)
    text = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", text)
    text = re.sub(r"[\(\[（【].*?[\)\]）】]", "", text)
    text = re.sub(r"[*#_~>`]", "", text)
    text = re.sub(r"(?i)\b(scene|visual|audio|narrator|intro|outro|video)\s*\d*[:\-]*", "", text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    cleaned_text = " ".join(lines)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text

def prepare_uninterrupted_narration_text(raw_text, lang_code="my"):
    if not raw_text:
        return ""
    t = clean_script_for_narration(raw_text)
    t = re.sub(r"\n+", " ", t)
    if lang_code == "my":
        t = t.replace("။", " ").replace("၊", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t

# ----------------- AI SCRIPT GENERATOR WITH PACING CONTROL -----------------
def generate_pacing_matched_script(api_key, model_name, video_path, target_duration_sec, custom_instructions):
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # For Burmese, normal recap pace is ~4.0 to 4.5 syllables per sec (roughly 1.8 to 2.2 words)
    target_words = max(35, int(target_duration_sec * 2.1))
    
    prompt = f"""
သတိပြုရန် အချက်: ဗီဒီယိုသည် အတိအကျ {round(target_duration_sec)} စက္ကန့် ({round(target_duration_sec/60, 1)} မိနစ်) ရှည်လျားပါသည်။
အသံဖတ်ကြားချိန်သည် ဗီဒီယိုစတင်သည့် စက္ကန့် ၀ မှ အဆုံးထိ အတိအကျ ကိုက်ညီစေရန်အတွက် စကားလုံးပေါင်း အနီးစပ်ဆုံး {target_words} လုံးခန့် ပါဝင်သော မြန်မာစကားပြောသီးသန့် Recap ဇာတ်ညွှန်းကို ရေးပေးပါ ခင်ဗျာ။
စောစောပြီးသွားခြင်း သို့မဟုတ် ဗီဒီယိုထက် ပိုရှည်နေခြင်း လုံးဝ မဖြစ်ရပါ။
အချိန်မှတ် (0:00) နှင့် နံပါတ်စဉ်များ လုံးဝမထည့်ပါနှင့်။
မုဒ်နှင့် အသံဟန်: ဆွဲဆောင်မှုရှိပြီး စိတ်လှုပ်ရှားဖွယ် ဇာတ်လမ်းပြောဟန် (Movie Recap Style) ဖြစ်ရပါမည်။
အပိုညွှန်ကြားချက်များ: {custom_instructions}
"""
    video_file = None
    if video_path and os.path.exists(video_path):
        try:
            video_file = genai.upload_file(path=video_path)
            wait_count = 0
            while video_file.state.name == "PROCESSING" and wait_count < 25:
                time.sleep(2)
                wait_count += 1
                video_file = genai.get_file(video_file.name)
            if video_file.state.name != "ACTIVE":
                video_file = None
        except Exception:
            video_file = None

    model = genai.GenerativeModel(model_name)
    if video_file:
        res = model.generate_content([video_file, prompt])
    else:
        res = model.generate_content(prompt)

    script_text = clean_script_for_narration(res.text)

    # Generate 2-line Hook
    hook_prompt = f"""ဒီ Script အတွက် ဗီဒီယိုအပေါ်ဆုံးတွင် တင်ရန် ဆွဲဆောင်မှုရှိသော ၂ ကြောင်း Hook ခေါင်းစဉ် ရေးပေးပါ ခင်ဗျာ:\nLINE 1: <စကားလုံး ၃-၄ လုံး>\nLINE 2: <စကားလုံး ၃-၄ လုံး>\n\nScript:\n{script_text[:400]}"""
    try:
        h_res = model.generate_content(hook_prompt).text
        lines = [re.sub(r"^(line\s*[12]|၁|၂|[12])\s*[:\.\)။\-]*\s*", "", l).strip() for l in h_res.split("\n") if l.strip()]
        hook1 = lines[0] if len(lines) > 0 else "ထူးဆန်းသော သမိုင်း"
        hook2 = lines[1] if len(lines) > 1 else "တရားရုံး၏ အဆုံးအဖြတ်"
    except Exception:
        hook1, hook2 = "ထူးဆန်းသော သမိုင်း", "တရားရုံး၏ အဆုံးအဖြတ်"

    return script_text, hook1, hook2

# ----------------- NATURAL VOICE GENERATION (EDGE-TTS) -----------------
async def run_edge_tts(text, voice_name, output_path, rate="+0%", pitch="+0Hz"):
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def generate_voice_file(text, voice_dict, output_audio_path, target_duration=None):
    voice_code = voice_dict["voice"]
    base_pitch = voice_dict["pitch"]
    
    # Estimate base speed
    flowing_text = prepare_uninterrupted_narration_text(text, lang_code="my")
    temp_initial_audio = "temp_raw_tts.mp3"
    
    # 1. Run at base rate
    asyncio.run(run_edge_tts(flowing_text, voice_code, temp_initial_audio, rate=f"+{voice_dict['rate_offset']}%", pitch=base_pitch))
    initial_dur = get_media_duration(temp_initial_audio)

    # 2. Perfect micro-adjustment if target_duration is given
    if target_duration and target_duration > 5.0 and initial_dur > 1.0:
        ratio = initial_dur / target_duration
        # Safe natural range: 0.88x to 1.15x
        if 0.85 <= ratio <= 1.25:
            cmd = [
                "ffmpeg", "-y",
                "-i", temp_initial_audio,
                "-filter:a", f"atempo={ratio:.3f}",
                output_audio_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
        elif ratio < 0.85:
            # Voice finished slightly early -> pad silence at the end naturally
            pad_sec = target_duration - initial_dur
            cmd = [
                "ffmpeg", "-y",
                "-i", temp_initial_audio,
                "-af", f"apad=pad_dur={pad_sec:.2f}",
                output_audio_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
            
    shutil.copyfile(temp_initial_audio, output_audio_path)

# ----------------- BURMESE UNICODE ASS SUBTITLE BUILDER -----------------
def hex_to_ass_color(hex_str, alpha="00"):
    hex_clean = hex_str.lstrip("#")
    if len(hex_clean) == 6:
        r, g, b = hex_clean[0:2], hex_clean[2:4], hex_clean[4:6]
        return f"&H{alpha}{b}{g}{r}&".upper()
    return "&H0000FFFF&"

def create_ass_subtitles(
    hook_line1, hook_line2, script_text, total_duration, ass_path,
    font_name="Pyidaungsu", sub_font_size=40, sub_margin_v=240, hook_top_margin_v=110,
    hex_color="#FFDF00", bg_mode="Solid Black Box (အမည်းနောက်ခံ)",
    enable_hook=True, max_chars=28, cta_text="", cta_start_time=0
):
    def format_ass_time(seconds):
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds - int(seconds)) * 100)
        return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"

    sub_primary = hex_to_ass_color(hex_color, "00")
    
    if "Solid Black Box" in bg_mode:
        border_style = "3"
        outline = "1.5"
        shadow = "0"
        back_colour = "&H80000000"
    elif "Semi-Transparent" in bg_mode:
        border_style = "3"
        outline = "1"
        shadow = "0"
        back_colour = "&H40000000"
    else:  # Glow / Outline
        border_style = "1"
        outline = "3.8"
        shadow = "2"
        back_colour = "&H00000000"

    ass_content = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SubtitleStyle,{font_name},{sub_font_size},{sub_primary},&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,30,30,{sub_margin_v},1
Style: HookStyle,{font_name},44,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,{hook_top_margin_v},1
Style: CTAStyle,{font_name},38,&H00FFFFFF,&H000000FF,&H00000000,&H200000D0,-1,0,0,0,100,100,0,0,3,2,0,2,20,20,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Top Hook Title
    if enable_hook and (hook_line1 or hook_line2):
        hook_display = f"{hook_line1}\\N{hook_line2}" if hook_line1 and hook_line2 else (hook_line1 or hook_line2)
        ass_content += f"Dialogue: 1,0:00:00.00,{format_ass_time(total_duration)},HookStyle,,0,0,0,,{hook_display}\n"

    # Synchronized Subtitles
    raw_segments = [s.strip() for s in re.split(r"[၊။\.\?\!\n]+", script_text) if s.strip()]
    chunks = []
    for seg in raw_segments:
        if len(seg) <= max_chars:
            chunks.append(seg)
        else:
            words = seg.split(" ")
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 <= max_chars:
                    cur = (cur + " " + w).strip()
                else:
                    if cur: chunks.append(cur)
                    cur = w
            if cur: chunks.append(cur)

    if not chunks: chunks = [script_text]
    chunk_time = total_duration / len(chunks)

    for idx, chunk in enumerate(chunks):
        st_t = idx * chunk_time
        en_t = min((idx + 1) * chunk_time, total_duration)
        ass_content += f"Dialogue: 0,{format_ass_time(st_t)},{format_ass_time(en_t)},SubtitleStyle,,0,0,0,,{chunk}\n"

    # End Screen CTA Popup (Last 6 seconds)
    if cta_text and cta_start_time > 0:
        ass_content += f"Dialogue: 2,{format_ass_time(cta_start_time)},{format_ass_time(total_duration)},CTAStyle,,0,0,0,,{cta_text}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

# ----------------- FFMPEG RENDER ENGINE -----------------
def render_master_video(input_video_path, audio_narration_path, ass_path, output_video_path, bgm_volume=0.12):
    v_dur = get_media_duration(input_video_path)
    a_dur = get_media_duration(audio_narration_path)
    render_duration = max(v_dur, a_dur) if v_dur > 0 else 60.0

    # Ensure background music track
    temp_bgm = "temp_bgm.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"aevalsrc=sin(85*2*PI*t)*0.03+sin(130*2*PI*t)*0.02:d={render_duration+2}",
        "-c:a", "libmp3lame", temp_bgm
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 9:16 Vertical Crop & Anti-Copyright micro-adjustment
    vf_base = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,eq=contrast=1.03:brightness=0.01:saturation=1.05"
    if ass_path and os.path.exists(ass_path):
        vf_base += f",subtitles={ass_path}:fontsdir=."

    # Mix Voiceover + Low Ducking BGM
    filter_complex = f"[0:v]{vf_base}[vfinal];[1:a]volume=1.0[voice];[2:a]volume={bgm_volume:.2f}[bgm];[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[afinal]"

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", input_video_path,
        "-i", audio_narration_path,
        "-i", temp_bgm,
        "-t", str(render_duration),
        "-filter_complex", filter_complex,
        "-map", "[vfinal]",
        "-map", "[afinal]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "192k",
        output_video_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.markdown("### 🎬 **RECAP STUDIO MM**")
    st.caption("Professional 1-Click Video Recap Generator")
    st.markdown("---")
    
    if st.session_state.gemini_api_key:
        st.success("🔑 Gemini API: Active")
    else:
        st.warning("⚠️ Gemini API Key မရှိသေးပါ")

    st.markdown("#### ⚙️ Quick Settings")
    model_choice = st.selectbox("🤖 AI Model", ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"], index=0)
    voice_choice = st.selectbox("🎙️ Narrator Voice", list(cur_lang_cfg["voices"].keys()), index=0)
    bgm_vol = st.slider("🎵 Background Music Volume", 0.0, 0.4, float(st.session_state.saved_bgm_vol), 0.02)
    st.session_state.saved_bgm_vol = bgm_vol

# ----------------- MAIN UI -----------------
st.title("🎬 Professional Movie Recap Studio")
st.markdown("One-Click ဖြင့် အသံ၊ ဇာတ်ညွှန်းနှင့် အရုပ် ၁၀၀% ကိုက်ညီသော ဗီဒီယိုများ ပြုလုပ်နိုင်ပါသည် ခင်ဗျာ။")

if not st.session_state.gemini_api_key:
    key_input = st.text_input("🔑 Google Gemini API Key ရိုက်ထည့်ပါ", type="password")
    if key_input:
        st.session_state.gemini_api_key = key_input
        save_config("gemini_api_key", key_input)
        st.rerun()

col_input_left, col_input_right = st.columns([1.2, 1.0])

with col_input_left:
    st.markdown("#### 1. 📤 ဗီဒီယို ဖိုင်တင်ပါ (သို့မဟုတ် YouTube/TikTok Link)")
    uploaded_file = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ", type=["mp4", "mov", "webm"])
    video_url = st.text_input("သို့မဟုတ် Video Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=...")

    if uploaded_file:
        with open("temp_input.mp4", "wb") as f:
            f.write(uploaded_file.getbuffer())

    v_dur = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
    if v_dur > 0:
        st.info(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(v_dur)} ({round(v_dur)} စက္ကန့်)**")

    custom_notes = st.text_area("အထူးညွှန်ကြားချက်များ (စိတ်ကြိုက်)", value="စိတ်လှုပ်ရှားဖွယ် ဟာသနှောသော ရုပ်ရှင်ဇာတ်လမ်းပြောဟန် ရေးပေးပါ ခင်ဗျာ။")

with col_input_right:
    st.markdown("#### 2. 🎯 Call-to-Action (CTA) & Typography")
    cta_choice = st.selectbox(
        "ဗီဒီယိုအဆုံးသတ် ခလုတ် (Select Like / Subscribe CTA)",
        list(cur_lang_cfg["cta_options"].keys()),
        index=2
    )
    st.session_state.selected_cta_text = cur_lang_cfg["cta_options"][cta_choice]

    col_cp1, col_cp2 = st.columns(2)
    with col_cp1:
        st.session_state.sub_custom_color = st.color_picker("🎨 စာတန်းထိုး အရောင် (Color)", st.session_state.sub_custom_color)
    with col_cp2:
        st.session_state.sub_bg_mode = st.selectbox("📦 နောက်ခံစတိုင် (Style)", ["Solid Black Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline & Glow (အနားကွပ်)"])

st.markdown("---")

# ----------------- ONE-CLICK EXECUTION BUTTON -----------------
col_exec_1, col_exec_2 = st.columns([1.5, 1.0])

with col_exec_1:
    one_click = st.button("⚡ ONE-CLICK MAGIC RECAP (အကုန်တစ်ခါတည်း အပြီးအစီး ပြုလုပ်ရန်)", type="primary", use_container_width=True)

with col_exec_2:
    manual_script_only = st.button("📝 Script သာ အရင်ထုတ်ယူမည်", use_container_width=True)

if one_click or manual_script_only:
    if not os.path.exists("temp_input.mp4") and not video_url:
        st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် Link ထည့်ပေးပါ ခင်ဗျာ။")
    elif not st.session_state.gemini_api_key:
        st.error("Gemini API Key လိုအပ်ပါသည် ခင်ဗျာ။")
    else:
        # Download if link provided
        if video_url and not uploaded_file:
            with st.spinner("ဗီဒီယိုအား ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "temp_input.mp4", video_url.split("?")[0]], capture_output=True)

        target_dur = get_media_duration("temp_input.mp4")
        if target_dur <= 0.0:
            target_dur = 60.0

        with st.spinner(f"⏱️ {round(target_dur)} စက္ကန့်အတိအကျ ကိုက်ညီသော Recap Script နှင့် Hook ထုတ်ယူနေပါသည်..."):
            script_out, h1, h2 = generate_pacing_matched_script(
                api_key=st.session_state.gemini_api_key,
                model_name=model_choice,
                video_path="temp_input.mp4" if os.path.exists("temp_input.mp4") else None,
                target_duration_sec=target_dur,
                custom_instructions=custom_notes
            )
            st.session_state.recap_script_text = script_out
            st.session_state.top_hook_text = h1
            st.session_state.bottom_hook_text = h2

        if one_click:
            with st.spinner("🎙️ အသံဖတ်ကြားခြင်းနှင့် စက္ကန့်မလွဲ Sync ပြုလုပ်နေပါသည်..."):
                voice_meta = cur_lang_cfg["voices"][voice_choice]
                audio_out = "final_synced_voice.mp3"
                generate_voice_file(script_out, voice_meta, audio_out, target_duration=target_dur)

            with st.spinner("📝 Myanmar Unicode စာတန်းထိုးများကို အချိန်ကိုက် ချိန်ညှိနေပါသည်..."):
                ass_out = "final_subs.ass"
                cta_start = max(0.0, target_dur - 6.0)
                calc_v_margin = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                calc_hk_margin = int(1280 * (st.session_state.hook_top_percent / 100.0))

                create_ass_subtitles(
                    hook_line1=st.session_state.top_hook_text,
                    hook_line2=st.session_state.bottom_hook_text,
                    script_text=script_out,
                    total_duration=target_dur,
                    ass_path=ass_out,
                    font_name="Pyidaungsu",
                    sub_font_size=st.session_state.sub_font_size,
                    sub_margin_v=calc_v_margin,
                    hook_top_margin_v=calc_hk_margin,
                    hex_color=st.session_state.sub_custom_color,
                    bg_mode=st.session_state.sub_bg_mode,
                    cta_text=st.session_state.selected_cta_text,
                    cta_start_time=cta_start
                )

            with st.spinner("🎬 Final MP4 ဗီဒီယိုအား Render ပြုလုပ်နေပါသည်..."):
                final_mp4 = "recap_output.mp4"
                render_master_video(
                    input_video_path="temp_input.mp4",
                    audio_narration_path=audio_out,
                    ass_path=ass_out,
                    output_video_path=final_mp4,
                    bgm_volume=st.session_state.saved_bgm_vol
                )
                st.session_state.last_final_video = final_mp4
                st.success("🎉 Final Video အောင်မြင်စွာ ထွက်ရှိပါပြီ ခင်ဗျာ!")

st.markdown("---")

# ----------------- LIVE HOVER CANVAS & PREVIEW -----------------
st.markdown("### 📱 Interactive Video & Subtitle Placement Canvas")
st.caption("စလိုက်ဒါများကို ရွှေ့ကြည့်ပြီး Subtitle နှင့် Hook နေရာကို တိုက်ရိုက် ကြည့်ရှုစစ်ဆေးနိုင်ပါသည် ခင်ဗျာ။")

col_prev_canvas, col_prev_controls = st.columns([1.1, 1.3])

with col_prev_controls:
    st.markdown("#### ⚙️ Placement & Visual Adjustments")
    st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ (Subtitle Height % from bottom)", 5, 80, int(st.session_state.sub_v_pos_percent))
    st.session_state.hook_top_percent = st.slider("↕️ Hook ခေါင်းစဉ် အမြင့်နေရာ (Top %)", 2, 25, int(st.session_state.hook_top_percent))
    st.session_state.sub_width_percent = st.slider("↔️ စာတန်းထိုး အကျယ် (Width %)", 50, 95, int(st.session_state.sub_width_percent))
    st.session_state.sub_font_size = st.slider("🔤 စာလုံး အရွယ်အစား (Font Size)", 28, 56, int(st.session_state.sub_font_size))

    st.markdown("##### 📝 Hook Text တိုက်ရိုက်ပြင်ရန်:")
    c_h1, c_h2 = st.columns(2)
    with c_h1:
        st.session_state.top_hook_text = st.text_input("Line 1 Hook", value=st.session_state.top_hook_text)
    with c_h2:
        st.session_state.bottom_hook_text = st.text_input("Line 2 Hook", value=st.session_state.bottom_hook_text)

    st.markdown("##### 📄 ဇာတ်ညွှန်း စာသား (Script):")
    st.session_state.recap_script_text = st.text_area("Script", value=st.session_state.recap_script_text, height=100, label_visibility="collapsed")

with col_prev_canvas:
    st.markdown("#### 👁️ Direct Phone Preview (Live Hover Canvas)")
    
    # CSS for realistic hover card
    preview_box_style = "background: rgba(0,0,0,0.85); border-radius: 8px; padding: 6px 14px;" if "Solid" in st.session_state.sub_bg_mode else ("background: rgba(0,0,0,0.45); backdrop-filter: blur(5px); border-radius: 8px; padding: 6px 14px;" if "Semi" in st.session_state.sub_bg_mode else "background: transparent; text-shadow: -2px -2px 0 #000, 2px -2px 0 #000, 0 3px 6px #000;")

    sample_sub = clean_script_for_narration(st.session_state.recap_script_text)[:65] + "..." if st.session_state.recap_script_text else "မြန်မာယူနီကုဒ် စာတန်းထိုး နမူနာ..."

    interactive_html = f"""
    <div style="width: 100%; max-width: 320px; height: 520px; margin: 0 auto; background: radial-gradient(circle, #102538, #050c13); border: 3px solid #1e40af; border-radius: 24px; position: relative; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.8); transition: transform 0.3s ease;">
        <!-- Top Hook Title -->
        <div style="position: absolute; top: {st.session_state.hook_top_percent}%; left: 0; width: 100%; text-align: center; padding: 0 10px;">
            <div style="display: inline-block; background: rgba(0,0,0,0.9); border: 1.5px solid #FFD700; color: #FFDF00; font-size: 13px; font-weight: 800; padding: 4px 10px; border-radius: 6px;">
                {st.session_state.top_hook_text}<br>{st.session_state.bottom_hook_text}
            </div>
        </div>

        <!-- Center CTA Overlay Preview -->
        <div style="position: absolute; top: 48%; left: 10%; width: 80%; text-align: center;">
            <div style="background: #e11d48; color: white; padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; box-shadow: 0 4px 12px rgba(225,29,72,0.5);">
                {st.session_state.selected_cta_text}
            </div>
        </div>

        <!-- Subtitle Box with Hover Effect -->
        <div style="position: absolute; bottom: {st.session_state.sub_v_pos_percent}%; left: {(100 - st.session_state.sub_width_percent) / 2}%; width: {st.session_state.sub_width_percent}%; text-align: center;">
            <div style="border: 2px dashed #38bdf8; {preview_box_style} cursor: pointer; transition: all 0.2s ease;" onmouseover="this.style.transform='scale(1.04)'" onmouseout="this.style.transform='scale(1)'">
                <span style="color: {st.session_state.sub_custom_color}; font-size: {int(st.session_state.sub_font_size * 0.35)}px; font-weight: bold; line-height: 1.3;">
                    {sample_sub}
                </span>
            </div>
        </div>
    </div>
    <div style="text-align: center; font-size: 11px; color: #94a3b8; margin-top: 6px;">
        စလိုက်ဒါများကို ရွှေ့လိုက်ပါက Subtitle အမြင့်နေရာ ({st.session_state.sub_v_pos_percent}%) ကို အချိန်နှင့်တပြေးညီ မြင်တွေ့ရပါမည်
    </div>
    """
    st.markdown(interactive_html, unsafe_allow_html=True)

# ----------------- FINAL EXPORT PLAYER -----------------
st.markdown("---")
if st.session_state.last_final_video and os.path.exists(st.session_state.last_final_video):
    st.markdown("### 📥 Final Exported Video")
    col_v1, col_v2 = st.columns([1.2, 1.0])
    with col_v1:
        st.video(st.session_state.last_final_video)
    with col_v2:
        st.success("✅ အသံနှင့် အရုပ် ၁၀၀% ကိုက်ညီသော ဗီဒီယို အသင့်ဖြစ်ပါပြီ ခင်ဗျာ။")
        with open(st.session_state.last_final_video, "rb") as vf:
            st.download_button(
                label="📥 Final MP4 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်",
                data=vf.read(),
                file_name="recap_studio_master.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True
            )
