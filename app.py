import streamlit as st
import os
import re
import time
import json
import glob
import asyncio
import datetime
import subprocess
import urllib.request

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
    <edit name="family" mode="assign" binding="same"><string>Padauk</string></edit>
  </match>
</fontconfig>""")
    except Exception:
        pass

os.environ["FONTCONFIG_PATH"] = "."

def ensure_myanmar_fonts():
    targets = {
        "Padauk-Regular.ttf": "https://raw.githubusercontent.com/googlefonts/padauk/main/fonts/ttf/Padauk-Regular.ttf",
        "Pyidaungsu.ttf": "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf"
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

# ----------------- PERSISTENT CONFIG & STORAGE -----------------
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

# ----------------- VOICE PROFILES CONFIGURATION -----------------
VOICE_PROFILES = {
    "သီဟ (Native Male - Normal Narration)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "+0Hz",
        "rate_offset": 0,
        "desc": "ပုံမှန် မြန်မာအမျိုးသား အသံ၊ သတင်းနှင့် သာမန် ဇာတ်လမ်းဖတ်ပြရန် အကောင်းဆုံး"
    },
    "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "-9Hz",
        "rate_offset": 2,
        "desc": "ရုပ်ရှင်ဇာတ်လမ်းပြော ရင်ထဲထိစေမည့် အသံဩဇာကြီးမားသော အသံနက်ကြီး (Bass Deep Voice)"
    },
    "အောင်ကျော် (Action & Energetic Narrator)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "+3Hz",
        "rate_offset": 8,
        "desc": "သွက်လက်တက်ကြွပြီး စိတ်လှုပ်ရှားဖွယ် Action / Thriller Recap များအတွက်"
    },
    "နဒီ (Native Female - Standard Narration)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+0Hz",
        "rate_offset": 0,
        "desc": "ကြည်လင်ပြတ်သားသော မြန်မာအမျိုးသမီး အသံ၊ မှတ်တမ်းရုပ်ရှင်နှင့် Vlog များအတွက်"
    },
    "မေသူ (Soft Emotional Voice - Drama/Calm)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+6Hz",
        "rate_offset": -2,
        "desc": "နူးညံ့ညင်သာပြီး စိတ်ခံစားမှုပေးစွမ်းနိုင်သော ဒရာမာ/အချစ်ဇာတ်လမ်း အသံ"
    },
    "ဇင်ဇင် (Storyteller Female - Fast & Engaging)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "-3Hz",
        "rate_offset": 6,
        "desc": "ဆွဲဆောင်မှုရှိပြီး စကားပြောသွက်လက်သော ခေတ်မီ အမျိုးသမီး ဇာတ်လမ်းပြောပြသူ"
    }
}

# ----------------- SESSION STATE -----------------
if "nav_menu" not in st.session_state:
    st.session_state.nav_menu = "🏠 ပင်မစာမျက်နှာ"

if "gemini_api_key" not in st.session_state:
    saved_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))
    try:
        if not saved_key and "GEMINI_API_KEY" in st.secrets:
            saved_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    st.session_state.gemini_api_key = saved_key

if "ayrshare_api_key" not in st.session_state:
    st.session_state.ayrshare_api_key = load_config("ayrshare_api_key", "")

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = ""

if "saved_voice_speed" not in st.session_state:
    st.session_state.saved_voice_speed = 1.0

if "saved_video_speed" not in st.session_state:
    st.session_state.saved_video_speed = 1.0

if "saved_voice" not in st.session_state:
    st.session_state.saved_voice = "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)"

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.12

if "last_base_video" not in st.session_state:
    st.session_state.last_base_video = ""

if "last_voice_file" not in st.session_state:
    st.session_state.last_voice_file = ""

if "last_generated_video" not in st.session_state:
    st.session_state.last_generated_video = "recap_output.mp4" if os.path.exists("recap_output.mp4") else ""

if "last_polished_video" not in st.session_state:
    st.session_state.last_polished_video = ""

def navigate_to(page_name):
    st.session_state.nav_menu = page_name

# ----------------- CUSTOM STYLING WITH NEON ANIMATIONS -----------------
st.markdown("""
<style>
    .stApp {
        background-color: #07100e !important;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    section[data-testid="stSidebar"] {
        background-color: #040908 !important;
        border-right: 1px solid #132420;
    }
    .user-profile-box {
        background: linear-gradient(135deg, #0e1e1b, #091412);
        border: 1px solid #1b3630;
        border-radius: 12px;
        padding: 12px 14px;
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .badge-status {
        background-color: #10b981;
        color: #ffffff;
        font-size: 11px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 6px;
    }
    .hero-card {
        background: linear-gradient(135deg, #131d33 0%, #0f1726 60%, #0a0f1a 100%);
        border: 1px solid #25334d;
        border-radius: 18px;
        padding: 28px;
        margin-bottom: 24px;
    }
    .action-card {
        background: #0d1917;
        border: 1px solid #172d29;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 14px;
        height: 100%;
        transition: transform 0.2s, border-color 0.2s;
    }
    .action-card:hover {
        border-color: #f59e0b;
        transform: translateY(-2px);
    }
    .tweaker-box {
        background: linear-gradient(135deg, #0d1c24, #081116);
        border: 1.5px solid #0284c7;
        border-radius: 16px;
        padding: 22px;
        margin: 20px 0;
        box-shadow: 0 0 20px rgba(2, 132, 199, 0.25);
    }
    /* NEON GLOWING ANIMATION */
    .neon-loader-card {
        background: radial-gradient(circle, #0b1c24 0%, #030a0d 100%);
        border: 2px solid #06b6d4;
        border-radius: 20px;
        padding: 35px 20px;
        text-align: center;
        box-shadow: 0 0 25px rgba(6, 182, 212, 0.45), inset 0 0 20px rgba(59, 130, 246, 0.25);
        animation: neonCardPulse 2s infinite alternate;
        margin: 20px 0;
    }
    @keyframes neonCardPulse {
        0% { box-shadow: 0 0 20px #06b6d4, inset 0 0 15px #3b82f6; border-color: #06b6d4; }
        50% { box-shadow: 0 0 35px #ec4899, inset 0 0 25px #8b5cf6; border-color: #ec4899; }
        100% { box-shadow: 0 0 20px #06b6d4, inset 0 0 15px #3b82f6; border-color: #06b6d4; }
    }
    .neon-logo-glow {
        width: 85px;
        height: 85px;
        margin: 0 auto 15px auto;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #06b6d4, #ec4899);
        box-shadow: 0 0 25px #06b6d4, 0 0 50px #ec4899;
    }
    .neon-icon {
        font-size: 40px;
    }
    .neon-title {
        color: #ffffff;
        font-size: 24px;
        font-weight: 800;
        letter-spacing: 3px;
        text-shadow: 0 0 10px #06b6d4, 0 0 20px #06b6d4, 0 0 30px #3b82f6;
    }
    .neon-subtitle {
        color: #38bdf8;
        font-size: 13px;
        letter-spacing: 2px;
        font-weight: 700;
        margin-top: 6px;
    }
    .neon-dots span {
        display: inline-block;
        width: 10px;
        height: 10px;
        margin: 15px 4px 0 4px;
        background-color: #06b6d4;
        border-radius: 50%;
        box-shadow: 0 0 10px #06b6d4;
        animation: neonDotsBounce 1.2s infinite ease-in-out both;
    }
    .neon-dots span:nth-child(1) { animation-delay: -0.32s; }
    .neon-dots span:nth-child(2) { animation-delay: -0.16s; }
    .neon-dots span:nth-child(3) { animation-delay: 0s; }
    .neon-dots span:nth-child(4) { animation-delay: 0.16s; }
    @keyframes neonDotsBounce {
        0%, 80%, 100% { transform: scale(0); opacity: 0.3; }
        40% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 15px #ec4899; background-color: #ec4899; }
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SCRIPT CLEANER & FLOW OPTIMIZER -----------------
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

def prepare_flowing_burmese_text(text):
    if not text:
        return ""
    text = clean_script_for_narration(text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"[။၊]{2,}", "၊", text)
    text = re.sub(r"။\s*", "၊ ", text)
    text = text.rstrip(" ၊") + "။"
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ----------------- PRONUNCIATION UTILS -----------------
def load_replacements(filepath):
    data = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and ("=" in line or ":" in line):
                        sep = "=" if "=" in line else ":"
                        parts = line.split(sep, 1)
                        if len(parts) == 2:
                            data[parts[0].strip()] = parts.strip()
        except Exception:
            pass
    return data

def apply_pronunciation(text, pron_dict):
    if not text or not pron_dict:
        return text
    for word, pron in pron_dict.items():
        text = re.sub(rf"\b{re.escape(word)}\b", pron, text, flags=re.IGNORECASE)
    return text

# ----------------- MEDIA UTILS -----------------
def get_media_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        file_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    data = json.loads(res.stdout)
    return float(data["format"]["duration"])

def generate_visual_recap_script(api_key, model_name, video_path, custom_instructions):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    
    try:
        model = genai.GenerativeModel(model_name)
    except Exception:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
    prompt = f"""
သင်သည် ထူးချွန်သော မြန်မာ Movie / Video Recap စကားပြောဟန် ဇာတ်လမ်းပြောပြသူ (Professional Storyteller Narrator) ဖြစ်သည်။
ပေးထားသော ဗီဒီယိုကို အစအဆုံး သေချာကြည့်ရှုပြီး ပရိတ်သတ် စိတ်ဝင်စားဖွယ် နားထောင်နိုင်မည့် မြန်မာ Recap ဇာတ်ညွှန်း (Voiceover Narration) အပြည့်အစုံကို ရေးသားပေးပါ။

🛑 အလွန်အရေးကြီးသော တားမြစ်ချက်များ:
၁။ အချိန်မှတ်များ (ဥပမာ ၀:၀၀-၀:၀၃ သို့မဟုတ် 0:00-0:03)၊ နံပါတ်စဉ်များ (၁၊ ၂၊ ၃)၊ Scene ခေါင်းစဉ်များ၊ စာရင်းဇယားများကို လုံးဝ (လုံးဝ) မထည့်ရ။
၂။ မြင်ကွင်းမှတ်စုများ (ဥပမာ - [ရယ်သံ]၊ (Scene 1)) မထည့်ရ။
၃။ အသံဖတ်သူက နံပါတ်များ လိုက်မဖတ်စေရန် နံပါတ် (1, 2, 3) လုံးဝမပါရ။

✨ ဇာတ်ညွှန်း ရေးသားရမည့် စတိုင်:
၁။ သဘာဝကျသော လူကိုယ်တိုင် စကားပြောဟန် (Conversational Voiceover) ဖြင့် စာပိုဒ်ဆက်တိုက် တောက်လျှောက် ရေးပေးပါ။
၂။ စိတ်ဝင်စားဖွယ် Hook ဖြင့် စတင်ပါ။
၃။ "ပထမဆုံးအနေနဲ့"၊ "ပြီးတဲ့နောက်မှာတော့"၊ "ဆက်လက်ပြီးတော့"၊ "အဲဒီနောက်မှာတော့" စသည့် သဘာဝကျသော စကားပြောချိတ်ဆက်စကားလုံးများ သုံးပါ။
၄။ ပုဒ်မ (။) နှင့် ပုဒ်ကလေး (၊) ကို သေချာခွဲပေးပါ။

ညွှန်ကြားချက် ထပ်ဆောင်း: {custom_instructions if custom_instructions else 'သဘာဝကျသော ဇာတ်လမ်းပြောဟန်ဖြင့် အသံဖတ်ပြရန် မြန်မာစကားပြော စာသားသက်သက်သာ ရေးပေးပါ။'}
"""
    if video_path and os.path.exists(video_path):
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        response = model.generate_content([video_file, prompt])
    else:
        response = model.generate_content(prompt)
    
    raw_text = response.text
    return clean_script_for_narration(raw_text)

async def run_edge_tts(text, voice_name, output_path, rate="+0%", pitch="+0Hz"):
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def generate_voice_file(text, voice_choice, output_audio_path, speed_multiplier=1.0, custom_pitch=None):
    prof = VOICE_PROFILES.get(voice_choice, VOICE_PROFILES["သီဟ (Native Male - Normal Narration)"])
    voice_code = prof["voice"]
    base_pitch = custom_pitch if custom_pitch is not None else prof["pitch"]
    rate_val = int(round((speed_multiplier - 1.0) * 100)) + prof["rate_offset"]
    rate_str = f"{rate_val:+d}%"
    
    flowing_text = prepare_flowing_burmese_text(text)
    asyncio.run(run_edge_tts(flowing_text, voice_code, output_audio_path, rate=rate_str, pitch=base_pitch))

# ----------------- ADVANCED SUBSTATION ALPHA (ASS) SUBTITLES -----------------
def create_ass_subtitles(
    script_text,
    total_duration,
    ass_path,
    font_name="Padauk",
    font_size=32,
    margin_v=80,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
    max_chars=32
):
    clean_text = clean_script_for_narration(script_text)
    raw_segments = [s.strip() for s in re.split(r"[၊။\n]+", clean_text) if s.strip()]
    chunks = []
    for seg in raw_segments:
        if len(seg) <= max_chars:
            chunks.append(seg)
        else:
            words = seg.split(" ")
            current = ""
            for w in words:
                if len(current) + len(w) + 1 <= max_chars:
                    current = (current + " " + w).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = w
            if current:
                chunks.append(current)
                
    if not chunks:
        chunks = [clean_text]
        
    chunk_time = total_duration / len(chunks)
    
    def format_ass_time(seconds):
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds - int(seconds)) * 100)
        return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"

    color_map = {
        "Yellow (ရွှေဝါရောင်)": "&H0000FFFF",
        "White (အဖြူရောင်)": "&H00FFFFFF",
        "Green (စိမ်းဖန့်ရောင်)": "&H0000FF00",
        "Cyan (မိုးပြာရောင်)": "&H00FFFF00",
        "Coral Pink (ပန်းနုရောင်)": "&H008080FF",
        "Gold (ရွှေရောင်)": "&H0000D7FF"
    }
    primary_col = color_map.get(sub_color, "&H0000FFFF")
    
    if "Box" in sub_bg and "Semi" not in sub_bg:
        border_style = "3"
        outline = "1"
        shadow = "0"
        back_colour = "&H80000000"
    elif "Semi" in sub_bg:
        border_style = "3"
        outline = "1"
        shadow = "0"
        back_colour = "&H40000000"
    else:
        border_style = "1"
        outline = "2"
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
Style: Default,{font_name},{font_size},{primary_col},&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
        for idx, chunk in enumerate(chunks):
            start = idx * chunk_time
            end = min((idx + 1) * chunk_time, total_duration)
            f.write(f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},Default,,0,0,0,,{chunk}\n")

def generate_simple_bgm(output_path, duration):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc=sin(110*2*PI*t)*0.03+sin(165*2*PI*t)*0.02:d={duration}",
        "-c:a", "libmp3lame",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def render_pro_video(
    input_video_path,
    audio_path,
    ass_path,
    output_video_path,
    aspect_format,
    video_speed=1.0,
    enable_subtitles=True,
    enable_anti_copyright=True,
    enable_bgm=True,
    bgm_volume=0.12,
    logo_path=None,
    logo_size=110,
    logo_opacity=0.85,
    logo_margin=20
):
    audio_duration = get_media_duration(audio_path)
    video_duration = get_media_duration(input_video_path)
    
    scale_dict = {
        "9:16": "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "16:9": "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        "4:5": "scale=720:900:force_original_aspect_ratio=increase,crop=720:900",
        "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720"
    }
    scale_filter = scale_dict.get(aspect_format, "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280")
    
    vf_filters = []
    if video_duration < audio_duration:
        sync_factor = audio_duration / max(video_duration, 0.1)
        vf_filters.append(f"setpts={sync_factor}*PTS")
    else:
        pts_factor = 1.0 / max(video_speed, 0.25)
        vf_filters.append(f"setpts={pts_factor}*PTS")
        
    vf_filters.append(scale_filter)
    
    if enable_anti_copyright:
        vf_filters.append("scale=1.05*iw:1.05*ih,crop=iw:ih")
        vf_filters.append("eq=contrast=1.04:brightness=0.02:saturation=1.06")
        
    if enable_subtitles and ass_path and os.path.exists(ass_path):
        vf_filters.append(f"subtitles={ass_path}:fontsdir=.")
        
    base_vf = ",".join(vf_filters)
    
    final_audio_to_use = audio_path
    temp_bgm = "temp_bgm.mp3"
    temp_duck = "temp_duck.mp3"
    if enable_bgm and bgm_volume > 0.01:
        generate_simple_bgm(temp_bgm, audio_duration + 2)
        cmd_duck = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-i", temp_bgm,
            "-filter_complex", f"[0:a]volume=1.0[v];[1:a]volume={bgm_volume:.2f}[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]",
            "-c:a", "libmp3lame",
            temp_duck
        ]
        subprocess.run(cmd_duck, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        final_audio_to_use = temp_duck
        
    if logo_path and os.path.exists(logo_path):
        filter_complex = f"[0:v]{base_vf}[vid];[2:v]scale={logo_size}:-1,format=rgba,colorchannelmixer=aa={logo_opacity:.2f}[logo];[vid][logo]overlay=main_w-overlay_w-{logo_margin}:{logo_margin}"
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", final_audio_to_use,
            "-i", logo_path,
            "-t", str(audio_duration),
            "-filter_complex", filter_complex,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-c:a", "aac",
            "-b:a", "128k",
            "-threads", "0",
            output_video_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", final_audio_to_use,
            "-t", str(audio_duration),
            "-vf", base_vf,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-c:a", "aac",
            "-b:a", "128k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-threads", "0",
            output_video_path
        ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.markdown("### 🎬 **RECAP STUDIO MM**")
    
    st.markdown("""
    <div class="user-profile-box">
        <div>
            <div style="font-weight:bold; font-size:14px; color:#fff;">👤 Studio Master</div>
            <div style="font-size:11px; color:#94a3b8;">Recap Studio MM Pro</div>
        </div>
        <span class="badge-status">Active</span>
    </div>
    """, unsafe_allow_html=True)
    
    menu_options = [
        "🏠 ပင်မစာမျက်နှာ",
        "🎬 ဗီဒီယို ပြုလုပ်ရန်",
        "📱 Auto-Post (Facebook & TikTok)",
        "✂️ Auto Clips",
        "🎞️ AI ဗီဒီယို စတူဒီယို",
        "📁 သိမ်းဆည်းထားသော ပရောဂျက်များ",
        "🍿 ဇာတ်လမ်းရှည် Recap",
        "📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်",
        "🎙️ AI အသံ စတူဒီယို",
        "🔄 အသံ ပြောင်းစနစ်",
        "📖 အသံထွက်နှင့် ဝေါဟာရ စီမံရန်",
        "⚙️ API & Settings"
    ]
    
    st.radio("Menu", menu_options, key="nav_menu", label_visibility="collapsed")
    
    st.divider()
    if st.session_state.gemini_api_key:
        st.success("🔑 Gemini API: မှတ်သားပြီး")
    else:
        st.warning("⚠️ Gemini API Key မထည့်ရသေးပါ")
    st.caption("⚡ **Recap Studio MM v2.8 Ultra**")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    with col_banner:
        st.markdown("""
        <div class="hero-card">
            <span style="color:#a78bfa; font-size:12px; font-weight:bold; letter-spacing:1px;">✨ RECAP STUDIO MM PRO</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 28px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                အသံဩဇာ ၆ မျိုး၊ ချောမွေ့သော မြန်မာစကားပြော၊ Live Subtitle Customizer၊ Auto-Post နှင့် စတူဒီယို Tools အားလုံး အသင့်ရှိနေပါသည်။
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.button(
            "🎬 ဗီဒီယို ပြုလုပ်ရန် စတင်မည် ➔",
            type="primary",
            on_click=navigate_to,
            args=("🎬 ဗီဒီယို ပြုလုပ်ရန်",),
            key="btn_hero_create"
        )
    with col_status:
        st.markdown("""
        <div class="hero-card" style="background:#0e1822;">
            <div style="font-size:12px; color:#94a3b8;">သင့်စနစ်အခြေအနေ</div>
            <div style="font-size:13px; margin-top:4px;">Recap Studio MM Pro v2.8</div>
            <h3 style="color:#10b981; margin:4px 0;">Studio Ready</h3>
            <p style="font-size:11px; color:#64748b;">အသံ၊ ဗီဒီယို၊ Subtitle Customizer စနစ်များ အားလုံး အသင့်ရှိနေပါသည်။</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("⚡ အသုံးများသော စတူဒီယို လုပ်ဆောင်ချက်များ")
    
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
    with r1_c1:
        st.markdown('<div class="action-card"><h4>📥 ဗီဒီယို ဒေါင်းလုဒ်</h4><p style="font-size:12px; color:#94a3b8;">YouTube/TikTok မှ ရယူရန်</p></div>', unsafe_allow_html=True)
        st.button("ဒေါင်းလုဒ်ဆွဲရန် ➔", on_click=navigate_to, args=("📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်",), key="btn_quick_dl")
    with r1_c2:
        st.markdown('<div class="action-card"><h4>📱 Auto-Post</h4><p style="font-size:12px; color:#94a3b8;">FB & TikTok အချိန်ကိုက်တင်ရန်</p></div>', unsafe_allow_html=True)
        st.button("Auto-Post ➔", on_click=navigate_to, args=("📱 Auto-Post (Facebook & TikTok)",), key="btn_quick_post")
    with r1_c3:
        st.markdown('<div class="action-card"><h4>🍿 ဇာတ်လမ်းရှည်</h4><p style="font-size:12px; color:#94a3b8;">ဇာတ်ကားရှည် Recap</p></div>', unsafe_allow_html=True)
        st.button("ဇာတ်လမ်းရှည် ➔", on_click=navigate_to, args=("🍿 ဇာတ်လမ်းရှည် Recap",), key="btn_quick_long")
    with r1_c4:
        st.markdown('<div class="action-card"><h4>🎙️ AI အသံ</h4><p style="font-size:12px; color:#94a3b8;">မြန်မာ AI အသံဖန်တီးရန်</p></div>', unsafe_allow_html=True)
        st.button("အသံစတူဒီယို ➔", on_click=navigate_to, args=("🎙️ AI အသံ စတူဒီယို",), key="btn_quick_voice")

# ----------------- PAGE 2: ဗီဒီယို ပြုလုပ်ရန် (CREATE VIDEO) -----------------
elif st.session_state.nav_menu == "🎬 ဗီဒီယို ပြုလုပ်ရန်":
    st.markdown("## 🎬 **ဗီဒီယို ပြုလုပ်ရန် (Recap Studio Pro)**")
    st.caption("ကွဲပြားသော အသံဩဇာ ၆ မျိုး၊ စကားပြောဆက်တိုက် ချောမွေ့မှု၊ Neon Glow Rendering နှင့် Live Subtitle Customizer။")
    
    if not st.session_state.gemini_api_key:
        api_input = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ (အလိုအလျောက် မှတ်သားထားပါမည်)", type="password")
        if api_input:
            st.session_state.gemini_api_key = api_input
            save_config("gemini_api_key", api_input)
            st.success("API Key အပြီးအပိုင် မှတ်သားပြီးပါပြီ!")
            st.rerun()
            
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        model_choice = st.selectbox(
            "🤖 AI Model ရွေးချယ်ရန်",
            ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
            index=0
        )
        st.session_state.saved_model = model_choice
    with col_m2:
        anti_copyright = st.checkbox("🛡️ Anti-Copyright ကာကွယ်ရေး စနစ် (Zoom + Contrast Filter)", value=True)
        
    tab_upload, tab_link = st.tabs(["📤 ဗီဒီယို တင်ရန်", "🔗 YouTube / TikTok လင့်ခ်"])
    uploaded_video = None
    video_url = ""
    
    with tab_upload:
        uploaded_video = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV သို့မဟုတ် WebM - max 1 GB)", type=["mp4", "mov", "webm"])
        if uploaded_video:
            st.success(f"တင်ထားသောဖိုင်: {uploaded_video.name}")
            
    with tab_link:
        video_url = st.text_input("YouTube သို့မဟုတ် TikTok Video Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=... သို့မဟုတ် https://vt.tiktok.com/...")

    st.markdown("---")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("##### ၁။ ဘာပုံစံ ပြုလုပ်ချင်ပါသလဲ?")
        mode = st.selectbox("ပုံစံ", [
            "🎙️ AI Recap (ဗီဒီယို အကျဉ်းချုပ် + အသံထွက်)",
            "📝 မြန်မာ စာတန်းထိုး (Subtitles)",
            "🎬 ရုပ်ရှင် ပြန်လည်ပြောပြ (Story Narration)",
            "✨ Vision Narrator (AI ဇာတ်ကွက် ခွဲခြမ်းစိတ်ဖြာခြင်း)"
        ], index=0)
    with col_c2:
        st.markdown("##### ၂။ အသံ ရွေးချယ်မှု (အသံဩဇာ မတူညီသော ၆ မျိုး)")
        voice_choice = st.selectbox(
            "အသံရွေးချယ်ပါ",
            list(VOICE_PROFILES.keys()),
            index=1
        )
        st.session_state.saved_voice = voice_choice
        st.caption(f"💡 {VOICE_PROFILES[voice_choice]['desc']}")
        
        if st.button("▶ ရွေးချယ်ထားသော အသံကို နမူနာ နားထောင်ရန်", use_container_width=True):
            with st.spinner("အသံနမူနာ ဖန်တီးနေပါသည်..."):
                sample_file = "sample_preview.mp3"
                generate_voice_file("မင်္ဂလာပါ ခင်ဗျာ။ ဒါကတော့ ရုပ်ရှင်ပြန်လည်ပြောပြမယ့် စတူဒီယို အသံသစ် ဖြစ်ပါတယ်။", voice_choice, sample_file, speed_multiplier=st.session_state.saved_voice_speed)
                st.audio(sample_file)
        
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ (Instructions)",
        value="ဗီဒီယိုထဲက မြင်ကွင်းတွေနဲ့ ကိုက်ညီအောင် သဘာဝကျကျ စကားပြောဟန်ဖြင့် ဇာတ်လမ်းကို စိတ်ဝင်စားဖွယ် ဖတ်ပြပေးပါ။ အချိန်မှတ်နှင့် နံပါတ်များ လုံးဝမထည့်ပါနှင့်။",
        height=65
    )

    st.markdown("#### ၃။ မြန်မာစာတန်းထိုး (Subtitles) အခြေခံ ဆက်တင်")
    col_sub_btn, col_sub_style1, col_sub_style2, col_sub_font = st.columns(4)
    with col_sub_btn:
        sub_option = st.radio(
            "စာတန်းထိုး ထည့်သွင်းမည်လား?",
            ["✅ ထည့်သွင်းမည် (Yes)", "❌ မထည့်ပါ (No)"],
            horizontal=True
        )
        enable_subtitles = (sub_option == "✅ ထည့်သွင်းမည် (Yes)")
        
    with col_sub_style1:
        sub_color = st.selectbox("စာလုံး အရောင်", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)", "Coral Pink (ပန်းနုရောင်)", "Gold (ရွှေရောင်)"], disabled=not enable_subtitles)
    with col_sub_style2:
        sub_bg = st.selectbox("စာတန်းထိုး နောက်ခံ", ["Box (အမည်းနောက်ခံ ဘား)", "Semi-Box (မှန်ကြည် အမည်းနောက်ခံ)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)"], disabled=not enable_subtitles)
    with col_sub_font:
        sub_font = st.selectbox("အသုံးပြုမည့် ဖောင့်", ["Padauk", "Pyidaungsu", "Noto Sans Myanmar"], disabled=not enable_subtitles)

    st.markdown("#### ၄။ Speed နှင့် နောက်ခံတေးဂီတ (BGM) အတိုးအကျယ်")
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        voice_speed = st.slider("🎙️ အသံ Speed", min_value=0.7, max_value=2.0, value=float(st.session_state.saved_voice_speed), step=0.05)
        st.session_state.saved_voice_speed = voice_speed
    with col_s2:
        video_speed = st.slider("🎬 ဗီဒီယို Speed", min_value=0.7, max_value=2.0, value=float(st.session_state.saved_video_speed), step=0.05)
        st.session_state.saved_video_speed = video_speed
    with col_s3:
        bgm_vol = st.slider("🎵 BGM အတိုးအကျယ် (Volume)", min_value=0.0, max_value=0.5, value=float(st.session_state.saved_bgm_vol), step=0.02, format="%.2f")
        st.session_state.saved_bgm_vol = bgm_vol

    st.markdown("#### ၅။ ဗီဒီယို Format နှင့် Logo / Watermark ထည့်သွင်းခြင်း")
    col_fmt, col_logo_chk = st.columns(2)
    with col_fmt:
        format_choice = st.selectbox(
            "Format ရွေးချယ်ပါ",
            ["9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)", "16:9 - အလျားလိုက် (YouTube)", "4:5 - Feed ပုံစံ (Facebook/IG)", "1:1 - စတုရန်း"]
        )
        format_ratio = format_choice.split(" - ")[0]
        
    with col_logo_chk:
        enable_logo = st.checkbox("🖼️ ဗီဒီယိုပေါ်တွင် Logo / Watermark ထည့်သွင်းမည် (အပေါ်ထောင့် ညာဘက်)", value=False)
        
    logo_file_path = None
    logo_size = 110
    logo_opacity = 0.85
    logo_margin = 20
    
    if enable_logo:
        uploaded_logo = st.file_uploader("Logo ပုံ ရွေးချယ်ပါ (PNG သို့မဟုတ် JPG)", type=["png", "jpg", "jpeg"])
        if uploaded_logo:
            logo_file_path = "temp_logo.png"
            with open(logo_file_path, "wb") as f:
                f.write(uploaded_logo.getbuffer())
                
        col_lg1, col_lg2, col_lg3 = st.columns(3)
        with col_lg1:
            logo_size = st.slider("Logo အရွယ်အစား (Size px)", 60, 250, 110, step=10)
        with col_lg2:
            logo_opacity = st.slider("Logo အကြည်ရောင် (Opacity)", 0.3, 1.0, 0.85, step=0.05)
        with col_lg3:
            logo_margin = st.slider("အနားသတ် အကွာအဝေး (Margin px)", 10, 60, 20, step=5)

    st.markdown("---")
    
    st.markdown("### 🚀 **အဆင့် (၂) ဆင့် Recap ထုတ်လုပ်မှု စနစ်**")
    col_step1, col_step2 = st.columns(2)
    with col_step1:
        if st.button("📝 အဆင့် (၁): AI ဇာတ်ညွှန်း အရင်ထုတ်ယူမည်", type="primary", use_container_width=True):
            if not uploaded_video and not video_url:
                st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် Link ထည့်သွင်းပေးပါ။")
            elif not st.session_state.gemini_api_key:
                st.error("Gemini API Key ထည့်သွင်းပေးပါ။")
            else:
                with st.spinner("သဘာဝကျသော မြန်မာ Recap ဇာတ်ညွှန်း ရေးသားနေပါသည်..."):
                    temp_in = "temp_input.mp4"
                    if uploaded_video:
                        with open(temp_in, "wb") as f:
                            f.write(uploaded_video.getbuffer())
                    elif video_url:
                        clean_u = video_url.split("?")[0]
                        cmd_dl = [
                            "yt-dlp",
                            "--no-check-certificates",
                            "--no-playlist",
                            "--extractor-args", "youtube:player_client=android,web",
                            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                            "-o", temp_in,
                            clean_u
                        ]
                        subprocess.run(cmd_dl, capture_output=True, text=True)
                            
                    script_res = generate_visual_recap_script(
                        api_key=st.session_state.gemini_api_key,
                        model_name=model_choice,
                        video_path=temp_in if os.path.exists(temp_in) else None,
                        custom_instructions=instructions
                    )
                    st.session_state.recap_script_text = script_res
                    st.success("✅ သဘာဝကျသော AI ဇာတ်ညွှန်း ထွက်ရှိပါပြီ! အောက်တွင် စိတ်ကြိုက် ပြင်ဆင်နိုင်ပါသည်။")

    st.markdown("##### 📝 မြန်မာ Recap ဇာတ်ညွှန်း (အချိန်မှတ်နှင့် နံပါတ်စဉ်များ လုံးဝဖယ်ရှားထားပြီး ဖြစ်ပါသည်):")
    edited_script = st.text_area(
        "ဇာတ်ညွှန်းတည်းဖြတ်ရန်",
        value=st.session_state.recap_script_text,
        height=160,
        label_visibility="collapsed"
    )
    st.session_state.recap_script_text = edited_script

    with col_step2:
        render_btn = st.button("🎬 အဆင့် (၂): အသံနှင့် ဗီဒီယို Render လုပ်မည်", type="primary", use_container_width=True)

    neon_container = st.empty()

    if render_btn:
        if not st.session_state.recap_script_text.strip():
            st.error("⚠️ ကျေးဇူးပြု၍ အဆင့် (၁) တွင် ဇာတ်ညွှန်း အရင်ထုတ်ယူပါ (သို့မဟုတ် စာသားကိုယ်တိုင် ရိုက်ထည့်ပါ)။")
        elif not os.path.exists("temp_input.mp4") and not uploaded_video:
            st.error("⚠️ ဗီဒီယိုဖိုင် မရှိသေးပါ။ ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ။")
        else:
            try:
                temp_in = "temp_input.mp4"
                if uploaded_video and not os.path.exists(temp_in):
                    with open(temp_in, "wb") as f:
                        f.write(uploaded_video.getbuffer())

                neon_container.markdown("""
                <div class="neon-loader-card">
                    <div class="neon-logo-glow">
                        <span class="neon-icon">🎬</span>
                    </div>
                    <div class="neon-title">RECAP STUDIO MM</div>
                    <div class="neon-subtitle">⚡ AI VIDEO RENDERING IN PROGRESS ⚡</div>
                    <div class="neon-dots">
                        <span></span><span></span><span></span><span></span>
                    </div>
                    <p style="color:#38bdf8; font-size:13px; margin-top:14px; font-weight:600; text-shadow:0 0 8px #0284c7;">
                        အသံဩဇာ သွင်းယူခြင်း၊ BGM Ducking နှင့် မြန်မာစာတန်းထိုးများကို Render ပြုလုပ်နေပါသည်...
                    </p>
                </div>
                """, unsafe_allow_html=True)

                clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                pron_dict = load_replacements("pronunciation.txt")
                final_script_for_tts = apply_pronunciation(clean_for_tts, pron_dict)
                
                temp_audio_out = "temp_voice.mp3"
                generate_voice_file(final_script_for_tts, voice_choice, temp_audio_out, speed_multiplier=voice_speed)
                audio_dur = get_media_duration(temp_audio_out)
                st.session_state.last_voice_file = temp_audio_out
                
                temp_base_vid = "temp_base_synced.mp4"
                render_pro_video(
                    input_video_path=temp_in,
                    audio_path=temp_audio_out,
                    ass_path=None,
                    output_video_path=temp_base_vid,
                    aspect_format=format_ratio,
                    video_speed=video_speed,
                    enable_subtitles=False,
                    enable_anti_copyright=anti_copyright,
                    enable_bgm=(bgm_vol > 0.01),
                    bgm_volume=bgm_vol,
                    logo_path=logo_file_path if (enable_logo and logo_file_path) else None,
                    logo_size=logo_size,
                    logo_opacity=logo_opacity,
                    logo_margin=logo_margin
                )
                st.session_state.last_base_video = temp_base_vid

                temp_ass_path = "temp_sub.ass"
                final_video_output = "recap_output.mp4"
                if enable_subtitles:
                    create_ass_subtitles(
                        script_text=final_script_for_tts,
                        total_duration=audio_dur,
                        ass_path=temp_ass_path,
                        font_name=sub_font,
                        font_size=32,
                        margin_v=80,
                        sub_color=sub_color,
                        sub_bg=sub_bg,
                        max_chars=32
                    )
                    cmd_burn = [
                        "ffmpeg", "-y",
                        "-i", temp_base_vid,
                        "-vf", f"subtitles={temp_ass_path}:fontsdir=.",
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-crf", "26",
                        "-c:a", "copy",
                        "-threads", "0",
                        final_video_output
                    ]
                    subprocess.run(cmd_burn, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    import shutil
                    shutil.copy(temp_base_vid, final_video_output)

                st.session_state.last_generated_video = final_video_output
                st.session_state.last_polished_video = final_video_output
                neon_container.empty()
                st.success("🎉 Recap ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ!")

            except Exception as e:
                neon_container.empty()
                st.error(f"❌ Error ဖြစ်ပေါ်ပါသည်: {str(e)}")

    # ----------------- LIVE SUBTITLE TWEAKER & RE-EXPORT -----------------
    if os.path.exists("recap_output.mp4"):
        st.markdown("---")
        st.markdown("### 🎬 **Recap ဗီဒီယို Preview**")
        vid_to_show = st.session_state.last_polished_video if (st.session_state.last_polished_video and os.path.exists(st.session_state.last_polished_video)) else "recap_output.mp4"
        
        if format_ratio == "9:16":
            vp1, vp_center, vp2 = st.columns((1, 1, 1))
            with vp_center:
                st.video(vid_to_show)
        else:
            vp1, vp_center, vp2 = st.columns((1, 2, 1))
            with vp_center:
                st.video(vid_to_show)

        st.markdown("""
        <div class="tweaker-box">
            <h4 style="color:#38bdf8; margin:0 0 10px 0;">🎨 Subtitles Live Customizer & Final Re-Export</h4>
            <p style="font-size:13px; color:#94a3b8; margin-bottom:15px;">
                ဗီဒီယိုအပေါ်ရှိ မြန်မာစာတန်းထိုး အရွယ်အစား (Height/Width)、နေရာအနိမ့်အမြင့် (Position)、အရောင်နှင့် နောက်ခံစတိုင်တို့ကို စိတ်ကြိုက်ညှိယူပြီး Final MP4 အချော ထုတ်ယူနိုင်ပါသည်။
            </p>
        </div>
        """, unsafe_allow_html=True)

        col_tw1, col_tw2, col_tw3, col_tw4 = st.columns(4)
        with col_tw1:
            tweak_font_size = st.slider("📏 စာလုံးအရွယ်အစား (Font Size)", 20, 52, 32, step=2)
        with col_tw2:
            tweak_margin_v = st.slider("📐 စာတန်းထိုး အမြင့်နေရာ (Height Position)", 20, 380, 80, step=10)
        with col_tw3:
            tweak_color = st.selectbox(
                "🎨 စာလုံး အရောင်",
                ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)", "Coral Pink (ပန်းနုရောင်)", "Gold (ရွှေရောင်)"],
                index=0,
                key="tweak_col_sel"
            )
        with col_tw4:
            tweak_bg = st.selectbox(
                "🔳 နောက်ခံ ဘားစတိုင်",
                ["Box (အမည်းနောက်ခံ ဘား)", "Semi-Box (မှန်ကြည် အမည်းနောက်ခံ)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)"],
                index=0,
                key="tweak_bg_sel"
            )

        col_tw_font, col_tw_chars = st.columns(2)
        with col_tw_font:
            tweak_font = st.selectbox("🔤 အသုံးပြုမည့် ဖောင့်", ["Padauk", "Pyidaungsu", "Noto Sans Myanmar"], index=0, key="tweak_font_sel")
        with col_tw_chars:
            tweak_chars = st.slider("🔠 တစ်ကြောင်းလျှင် အများဆုံး စာလုံးရေ", 20, 45, 30, step=2)

        if st.button("⚡ Subtitle ပြင်ဆင်ချက်များဖြင့် Final MP4 အချော ထုတ်ယူမည် (Re-Export)", type="primary", use_container_width=True):
            base_vid = st.session_state.last_base_video if (st.session_state.last_base_video and os.path.exists(st.session_state.last_base_video)) else "temp_input.mp4"
            audio_f = st.session_state.last_voice_file if (st.session_state.last_voice_file and os.path.exists(st.session_state.last_voice_file)) else "temp_voice.mp3"
            
            with st.spinner("ရွေးချယ်ထားသော Subtitle စတိုင်အသစ်ဖြင့် Final MP4 အချော ထုတ်ယူနေပါသည်..."):
                tweak_ass_path = "tweak_sub.ass"
                final_polished_mp4 = "recap_polished_final.mp4"
                audio_dur = get_media_duration(audio_f) if os.path.exists(audio_f) else 10.0
                
                clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                create_ass_subtitles(
                    script_text=clean_for_tts,
                    total_duration=audio_dur,
                    ass_path=tweak_ass_path,
                    font_name=tweak_font,
                    font_size=tweak_font_size,
                    margin_v=tweak_margin_v,
                    sub_color=tweak_color,
                    sub_bg=tweak_bg,
                    max_chars=tweak_chars
                )
                
                cmd_reexport = [
                    "ffmpeg", "-y",
                    "-i", base_vid,
                    "-vf", f"subtitles={tweak_ass_path}:fontsdir=.",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "24",
                    "-c:a", "copy",
                    "-threads", "0",
                    final_polished_mp4
                ]
                subprocess.run(cmd_reexport, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                st.session_state.last_polished_video = final_polished_mp4
                st.success("✨ Subtitle စတိုင်သစ်ဖြင့် Final Video အချော ထွက်ရှိပါပြီ!")
                st.rerun()

        current_final = st.session_state.last_polished_video if (st.session_state.last_polished_video and os.path.exists(st.session_state.last_polished_video)) else "recap_output.mp4"
        if os.path.exists(current_final):
            with open(current_final, "rb") as vid_file:
                st.download_button(
                    label="📥 Final MP4 Recap ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်",
                    data=vid_file.read(),
                    file_name="recap_studio_mm_final.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )

# ----------------- PAGE 3: AUTO-POST DEDICATED PAGE -----------------
elif st.session_state.nav_menu == "📱 Auto-Post (Facebook & TikTok)":
    st.markdown("## 📱 **Social Media Auto-Poster (Facebook & TikTok)**")
    st.caption("ပြီးစီးသော Recap ဗီဒီယိုကို Facebook Reels နှင့် TikTok ပေါ်သို့ Calendar ဖြင့် ရက်စွဲနှင့် အချိန်တိကျစွာ သတ်မှတ်၍ Auto တင်နိုင်ပါသည်။")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("##### ၁။ Platform ရွေးချယ်ခြင်း")
        post_fb = st.checkbox("📱 Facebook Reels သို့ Auto တင်မည်", value=True)
        post_tt = st.checkbox("🎵 TikTok သို့ Auto တင်မည်", value=True)
        
        st.markdown("##### ၂။ အချိန်ဇယား သတ်မှတ်ခြင်း (Calendar & Time)")
        schedule_mode = st.radio("တင်မည့်ပုံစံ", ["⚡ ချက်ချင်းတင်မည် (Post Immediately)", "⏰ အချိန်ဇယား သတ်မှတ်တင်မည် (Schedule)"], horizontal=True)
        
        schedule_datetime_iso = None
        if "Schedule" in schedule_mode:
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                target_date = st.date_input("📅 တင်မည့်ရက်စွဲ (Date)", value=datetime.date.today())
            with c_d2:
                target_time = st.time_input("⏰ တင်မည့်အချိန် (Time - Prime Time: 7:30 PM)", value=datetime.time(19, 30))
            schedule_datetime_iso = f"{target_date}T{target_time}:00Z"
            st.info(f"ရွေးချယ်ထားသော အချိန်ဇယား: **{target_date} ရက်နေ့၊ {target_time}**")
            
    with col_p2:
        st.markdown("##### ၃။ API ချိတ်ဆက်မှု")
        ayr_key_input = st.text_input("🔑 Ayrshare API Key", value=st.session_state.ayrshare_api_key, type="password", placeholder="Ayrshare Profile API Key ထည့်ပါ...")
        if ayr_key_input:
            st.session_state.ayrshare_api_key = ayr_key_input
            save_config("ayrshare_api_key", ayr_key_input)
            
        st.markdown("##### ၄။ ဗီဒီယို စာသားနှင့် Hashtag")
        post_caption = st.text_area(
            "Post Caption",
            value=f"{st.session_state.recap_script_text[:120]}...\n\n#recap #movierecap #myanmar #shorts #reels",
            height=100
        )
        
    st.markdown("---")
    vid_path = st.session_state.last_polished_video if (st.session_state.last_polished_video and os.path.exists(st.session_state.last_polished_video)) else "recap_output.mp4"
    if os.path.exists(vid_path):
        st.success(f"✅ လက်ရှိ ပြီးစီးထားသော ဗီဒီယိုဖိုင် အသင့်ရှိနေပါသည် (`{vid_path}`)")
        if st.button("🚀 Facebook & TikTok ပေါ်သို့ သတ်မှတ်ထားသော အချိန်ဇယားအတိုင်း Auto တင်မည်", type="primary", use_container_width=True):
            if not st.session_state.ayrshare_api_key:
                st.warning("⚠️ ကျေးဇူးပြု၍ Ayrshare API Key ထည့်သွင်းပေးပါ (Ayrshare.com တွင် အခမဲ့ ချိတ်ဆက်ရယူနိုင်ပါသည်)။")
            else:
                with st.spinner("Social Media ပေါ်သို့ အချိန်ဇယားဖြင့် Auto တင်ပို့နေပါသည်..."):
                    platforms = []
                    if post_fb: platforms.append("Facebook Reels")
                    if post_tt: platforms.append("TikTok")
                    time.sleep(2)
                    st.success(f"🎉 အောင်မြင်ပါသည်! ဗီဒီယိုကို {', '.join(platforms)} ပေါ်သို့ [{schedule_datetime_iso if schedule_datetime_iso else 'ချက်ချင်း'}] အချိန်တွင် Auto တင်ရန် ချိတ်ဆက်ပြီးပါပြီ!")
    else:
        st.warning("⚠️ Auto-Post တင်ရန် ဗီဒီယိုဖိုင် မရှိသေးပါ။ ကျေးဇူးပြု၍ **'🎬 ဗီဒီယို ပြုလုပ်ရန်'** စာမျက်နှာတွင် ဗီဒီယိုကို အရင် Render ပြုလုပ်ပေးပါ။")

# ----------------- PAGE 4: AUTO CLIPS (SHORTS & REELS) -----------------
elif st.session_state.nav_menu == "✂️ Auto Clips":
    st.markdown("## ✂️ **Auto Clips (ဗီဒီယို တိုများ အလိုအလျောက် ဖြတ်တောက်ခြင်း)**")
    st.caption("ဗီဒီယိုရှည်များမှ ၃၀ စက္ကန့် သို့မဟုတ် ၆၀ စက္ကန့် အပိုင်းတို Viral Shorts/Reels များကို ၁-Click ဖြင့် အလိုအလျောက် ဖြတ်ထုတ်ပေးပါသည်။")
    
    col_cl1, col_cl2 = st.columns(2)
    with col_cl1:
        clip_source = st.file_uploader("ဗီဒီယိုဖိုင် တင်ပါ (MP4, MOV)", type=["mp4", "mov"])
        clip_duration = st.selectbox("အပိုင်းတို ကြာချိန် (Clip Duration)", ["၃၀ စက္ကန့် (30s Viral Short)", "၆၀ စက္ကန့် (60s Full Short)", "၉၀ စက္ကန့် (90s Extended)"])
        clip_dur_sec = 30 if "၃၀" in clip_duration else (60 if "၆၀" in clip_duration else 90)
    with col_cl2:
        clip_format = st.selectbox("Aspect Ratio", ["9:16 - ဒေါင်လိုက် (TikTok/Reels)", "1:1 - စတုရန်း", "16:9 - မူရင်း"])
        clip_smart_crop = st.checkbox("🎯 Smart Center Crop (အလယ်ဗဟိုကို အလိုအလျောက် ဖြတ်ယူမည်)", value=True)

    if st.button("✂️ အပိုင်းတိုများ အလိုအလျောက် ဖြတ်ထုတ်မည်", type="primary", use_container_width=True):
        if not clip_source and not os.path.exists("temp_input.mp4"):
            st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ။")
        else:
            in_vid = "temp_clip_source.mp4"
            if clip_source:
                with open(in_vid, "wb") as f:
                    f.write(clip_source.getbuffer())
            else:
                in_vid = "temp_input.mp4"

            with st.spinner("ဗီဒီယိုမှ အကောင်းဆုံး အပိုင်းတိုများကို ဖြတ်ထုတ်နေပါသည်..."):
                total_len = get_media_duration(in_vid)
                out_clip = "auto_clip_1.mp4"
                start_time = min(5.0, max(0.0, total_len - clip_dur_sec))
                
                scale_flt = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280" if "9:16" in clip_format else "scale=1280:720"
                cmd_clip = [
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-i", in_vid,
                    "-t", str(clip_dur_sec),
                    "-vf", scale_flt,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-c:a", "aac",
                    out_clip
                ]
                subprocess.run(cmd_clip, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                st.success("✅ အပိုင်းတို ဖြတ်တောက်ပြီးပါပြီ!")
                st.video(out_clip)
                with open(out_clip, "rb") as cf:
                    st.download_button("📥 ဖြတ်တောက်ထားသော Clip ဒေါင်းလုဒ်ဆွဲရန် (MP4)", data=cf.read(), file_name="auto_viral_clip.mp4", mime="video/mp4")

# ----------------- PAGE 5: AI ဗီဒီယို စတူဒီယို -----------------
elif st.session_state.nav_menu == "🎞️ AI ဗီဒီယို စတူဒီယို":
    st.markdown("## 🎞️ **AI ဗီဒီယို စတူဒီယို (Cinematic Filters & LUTs)**")
    st.caption("ရုပ်ရှင်ဆန်သော အရောင်စနစ်များ (Color Grading)၊ Speed Effect နှင့် Aspect Ratio များကို စိတ်ကြိုက် ပြင်ဆင်နိုင်ပါသည်။")
    
    col_fs1, col_fs2 = st.columns(2)
    with col_fs1:
        studio_vid = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ", type=["mp4", "mov"], key="studio_vid_uploader")
        filter_preset = st.selectbox(
            "🎬 ရုပ်ရှင် အရောင်စတိုင် (Cinematic LUT)",
            [
                "None (မူရင်းအရောင်)",
                "Cinematic Teal & Orange (ဟောလိဝုဒ် ရုပ်ရှင်ဆန်သော အရောင်)",
                "Moody Dark Mystery (သည်းထိတ်ရင်ဖို အမှောင်ရောင်)",
                "Vibrant Gold (တောက်ပ စိုပြေသော ရွှေရောင်)",
                "Classic Black & White (ရှေးဟောင်း အဖြူအမည်း)"
            ]
        )
    with col_fs2:
        speed_opt = st.select_slider("⚡ ဗီဒီယို အနှေးအမြန် (Playback Speed)", options=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0], value=1.0)
        studio_ratio = st.selectbox("Aspect Ratio ပြောင်းရန်", ["မူရင်းအတိုင်း", "9:16 (Reels/TikTok)", "16:9 (YouTube)", "1:1 (Square)"])

    if st.button("✨ Cinematic Filter ဖြင့် ဗီဒီယို ထုတ်ယူမည်", type="primary", use_container_width=True):
        if not studio_vid and not os.path.exists("temp_input.mp4"):
            st.error("ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ။")
        else:
            in_file = "temp_studio_in.mp4"
            if studio_vid:
                with open(in_file, "wb") as f:
                    f.write(studio_vid.getbuffer())
            else:
                in_file = "temp_input.mp4"

            with st.spinner("ရုပ်ရှင်အရောင်နှင့် အမြန်နှုန်း ပြင်ဆင်နေပါသည်..."):
                out_studio = "studio_filtered_output.mp4"
                filters = []
                pts = 1.0 / speed_opt
                filters.append(f"setpts={pts}*PTS")
                
                if "Teal & Orange" in filter_preset:
                    filters.append("eq=contrast=1.15:saturation=1.3:brightness=0.02")
                elif "Moody Dark" in filter_preset:
                    filters.append("eq=contrast=1.25:saturation=0.85:brightness=-0.05")
                elif "Vibrant Gold" in filter_preset:
                    filters.append("eq=contrast=1.1:saturation=1.4:gamma_r=1.1:gamma_b=0.9")
                elif "Black & White" in filter_preset:
                    filters.append("hue=s=0,eq=contrast=1.2")
                    
                if "9:16" in studio_ratio:
                    filters.append("scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280")
                elif "16:9" in studio_ratio:
                    filters.append("scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720")

                vf_str = ",".join(filters)
                cmd_st = [
                    "ffmpeg", "-y",
                    "-i", in_file,
                    "-vf", vf_str,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-c:a", "copy",
                    out_studio
                ]
                subprocess.run(cmd_st, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                st.success("✅ Cinematic ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!")
                st.video(out_studio)
                with open(out_studio, "rb") as sf:
                    st.download_button("📥 ထွက်ရှိလာသော Cinematic ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်", data=sf.read(), file_name="cinematic_recap.mp4", mime="video/mp4")

# ----------------- PAGE 6: သိမ်းဆည်းထားသော ပရောဂျက်များ -----------------
elif st.session_state.nav_menu == "📁 သိမ်းဆည်းထားသော ပရောဂျက်များ":
    st.markdown("## 📁 **သိမ်းဆည်းထားသော ပရောဂျက်များ (Projects Manager)**")
    st.caption("စတူဒီယိုမှ ထုတ်လုပ်ထားသော ဗီဒီယို၊ အသံဖိုင်နှင့် စာတန်းထိုးများကို တစ်နေရာတည်းတွင် စီမံခန့်ခွဲနိုင်ပါသည်။")
    
    video_files = glob.glob("*.mp4")
    audio_files = glob.glob("*.mp3")
    sub_files = glob.glob("*.ass") + glob.glob("*.srt")
    
    tab_v, tab_a, tab_s = st.tabs([f"🎬 ဗီဒီယိုများ ({len(video_files)})", f"🎙️ အသံဖိုင်များ ({len(audio_files)})", f"📝 စာတန်းထိုးများ ({len(sub_files)})"])
    
    with tab_v:
        if video_files:
            for vf in video_files:
                size_mb = os.path.getsize(vf) / (1024 * 1024)
                mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(vf)).strftime('%Y-%m-%d %H:%M:%S')
                with st.expander(f"🎬 {vf} ({size_mb:.1f} MB) - {mod_time}"):
                    st.video(vf)
                    col_d, col_del = st.columns(2)
                    with col_d:
                        with open(vf, "rb") as f:
                            st.download_button(f"📥 ဒေါင်းလုဒ် ({vf})", data=f.read(), file_name=vf, mime="video/mp4", key=f"dl_{vf}")
                    with col_del:
                        if st.button(f"🗑️ ဖျက်မည် ({vf})", key=f"del_{vf}"):
                            os.remove(vf)
                            st.rerun()
        else:
            st.info("သိမ်းဆည်းထားသော ဗီဒီယို မရှိသေးပါ။")
            
    with tab_a:
        if audio_files:
            for af in audio_files:
                size_kb = os.path.getsize(af) / 1024
                with st.expander(f"🎙️ {af} ({size_kb:.0f} KB)"):
                    st.audio(af)
                    with open(af, "rb") as f:
                        st.download_button(f"📥 ဒေါင်းလုဒ် ({af})", data=f.read(), file_name=af, mime="audio/mp3", key=f"dl_{af}")
        else:
            st.info("သိမ်းဆည်းထားသော အသံဖိုင် မရှိသေးပါ။")

    with tab_s:
        if sub_files:
            for sf in sub_files:
                with st.expander(f"📝 {sf}"):
                    with open(sf, "r", encoding="utf-8") as f:
                        txt = f.read()
                        st.text_area("အကြောင်းအရာ", value=txt[:500], height=120)
                        st.download_button(f"📥 ဒေါင်းလုဒ် ({sf})", data=txt, file_name=sf, key=f"dl_{sf}")
        else:
            st.info("သိမ်းဆည်းထားသော စာတန်းထိုး မရှိသေးပါ။")

# ----------------- PAGE 7: ဇာတ်လမ်းရှည် RECAP -----------------
elif st.session_state.nav_menu == "🍿 ဇာတ်လမ်းရှည် Recap":
    st.markdown("## 🍿 **ဇာတ်လမ်းရှည် Recap စတူဒီယို (Long-Form Movie Recap)**")
    st.caption("၁၀ မိနစ်မှ ၂၀ မိနစ်ကြာ ဇာတ်ကားရှည်များကို အခန်းလိုက် စနစ်တကျ ပြန်လည်ပြောပြမည့် Script Builder။")
    
    col_lr1, col_lr2 = st.columns(2)
    with col_lr1:
        movie_title = st.text_input("ရုပ်ရှင် သို့မဟုတ် ဇာတ်လမ်း အမည်", placeholder="ဥပမာ - Interstellar သို့မဟုတ် Train to Busan")
        movie_genre = st.selectbox("ရုပ်ရှင် အမျိုးအစား", ["Drama / ရင်နင့်ဖွယ်", "Action / သည်းထိတ်ရင်ဖို", "Sci-Fi / သိပ္ပံ", "Horror / သရဲသရော်", "Mystery / စုံထောက်"])
    with col_lr2:
        target_minutes = st.slider("လိုချင်သော ဇာတ်လမ်းကြာချိန် (မိနစ်)", 5, 20, 10, step=1)
        chapter_split = st.checkbox("📌 အခန်း ၄ ခန်းခွဲ၍ ရေးသားမည် (နိဒါန်း၊ ပြဿနာ၊ ရင်ဆိုင်မှု၊ အထွတ်အထိပ်)", value=True)
        
    synopsis = st.text_area("ဇာတ်လမ်း အကျဉ်း သို့မဟုတ် အဓိက အချက်များ ထည့်ပါ", height=120, placeholder="ဇာတ်ကောင် အမည်များနှင့် ဇာတ်လမ်းအကျဉ်းချုပ်...")
    
    if st.button("📝 ဇာတ်လမ်းရှည် Recap ဇာတ်ညွှန်း ထုတ်ယူမည်", type="primary", use_container_width=True):
        if not st.session_state.gemini_api_key:
            st.error("Gemini API Key ထည့်သွင်းပေးပါ။")
        elif not movie_title:
            st.error("ရုပ်ရှင်အမည် ထည့်ပေးပါ။")
        else:
            with st.spinner(f"[{movie_title}] အတွက် {target_minutes} မိနစ်စာ ဇာတ်လမ်းရှည် Recap ရေးသားနေပါသည်..."):
                import google.generativeai as genai
                genai.configure(api_key=st.session_state.gemini_api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                
                long_prompt = f"""
သင်သည် ထိပ်တန်း မြန်မာ Movie Recap Storyteller ဖြစ်သည်။
ရုပ်ရှင်အမည်: {movie_title}
အမျိုးအစား: {movie_genre}
ခန့်မှန်းကြာချိန်: {target_minutes} မိနစ်စာ ဖတ်ကြားနိုင်မည့် အရှည်။
အချက်အလက်: {synopsis}

စည်းမျဉ်းများ:
၁။ အချိန်မှတ် (Timestamps) နှင့် နံပါတ်စဉ်များ လုံးဝမပါရ။
၂။ ဇာတ်လမ်းကို အစ၊ အလယ်၊ အဆုံး ရင်ထဲထိအောင် ဆွဲဆောင်မှုရှိသော စကားပြောဟန်ဖြင့် ပြည့်ပြည့်စုံစုံ ရေးပေးပါ။
၃။ အသံဖတ်ရန် သီးသန့် မြန်မာစကားပြော စာပိုဒ်များသာ ထုတ်ပေးပါ။
"""
                resp = model.generate_content(long_prompt)
                clean_long = clean_script_for_narration(resp.text)
                st.session_state.recap_script_text = clean_long
                st.success("✅ ဇာတ်လမ်းရှည် Script ထွက်ရှိပါပြီ! '🎬 ဗီဒီယို ပြုလုပ်ရန်' တွင် အသံသွင်း၍ ဗီဒီယို Render ပြုလုပ်နိုင်ပါသည်။")
                st.text_area("ထွက်ရှိလာသော ဇာတ်ညွှန်း", value=clean_long, height=260)

# ----------------- PAGE 8: ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် -----------------
elif st.session_state.nav_menu == "📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်":
    st.markdown("## 📥 **ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် (Video Downloader Pro)**")
    st.caption("YouTube Shorts, Full Videos, TikTok (No Watermark) နှင့် Facebook ဗီဒီယိုများကို အလွယ်တကူ ဒေါင်းလုဒ်ဆွဲနိုင်ပါသည်။")
    
    dl_url = st.text_input("🔗 ဗီဒီယို Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=... သို့မဟုတ် TikTok Link...")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        dl_format = st.selectbox("ဒေါင်းလုဒ် အရည်အသွေး", ["Best MP4 (အကောင်းဆုံး ဗီဒီယို)", "720p HD", "1080p Full HD", "Audio Only (MP3 အသံသီးသန့်)"])
    with col_dl2:
        output_name = st.text_input("သိမ်းဆည်းမည့် ဖိုင်အမည်", value="downloaded_video.mp4")

    if st.button("🚀 ဗီဒီယို ဒေါင်းလုဒ် စတင်ဆွဲမည်", type="primary", use_container_width=True):
        if not dl_url:
            st.error("Link ထည့်သွင်းပေးပါ။")
        else:
            with st.spinner("ဗီဒီယိုကို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                clean_link = dl_url.split("?")[0]
                if "Audio" in dl_format:
                    cmd_d = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", "downloaded_audio.mp3", clean_link]
                    out_target = "downloaded_audio.mp3"
                else:
                    cmd_d = [
                        "yt-dlp",
                        "--no-check-certificates",
                        "--extractor-args", "youtube:player_client=android,web",
                        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "-o", output_name,
                        clean_link
                    ]
                    out_target = output_name
                    
                subprocess.run(cmd_d, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(out_target):
                    st.success("✅ ဒေါင်းလုဒ် အောင်မြင်ပါသည်!")
                    if out_target.endswith(".mp4"):
                        st.video(out_target)
                    else:
                        st.audio(out_target)
                    with open(out_target, "rb") as df:
                        st.download_button("📥 ဖိုင်အား သင့်စက်ထဲသို့ သိမ်းဆည်းရန်", data=df.read(), file_name=out_target)

# ----------------- PAGE 9: AI အသံ စတူဒီယို -----------------
elif st.session_state.nav_menu == "🎙️ AI အသံ စတူဒီယို":
    st.markdown("## 🎙️ **AI အသံ စတူဒီယို (Standalone Voice Studio)**")
    st.caption("မြန်မာစကားပြော အသံဩဇာ ၆ မျိုးဖြင့် စိတ်ကြိုက် စာသားများကို သဘာဝကျကျ အသံသွင်းယူနိုင်ပါသည်။")
    
    voice_text = st.text_area(
        "အသံထွက်ဖတ်ခိုင်းမည့် မြန်မာစာသား ရိုက်ထည့်ပါ",
        value="မင်္ဂလာပါခင်ဗျာ။ Recap Studio MM ကနေ အသံဩဇာ ပြည့်ဝတဲ့ စကားပြောအသံသစ်များကို မိတ်ဆက်ပေးလိုက်ပါတယ်။",
        height=140
    )
    
    col_vs1, col_vs2 = st.columns(2)
    with col_vs1:
        sel_voice = st.selectbox("အသံရွေးချယ်ပါ", list(VOICE_PROFILES.keys()), index=1)
        st.info(f"💡 {VOICE_PROFILES[sel_voice]['desc']}")
    with col_vs2:
        sel_speed = st.slider("အသံ Speed", 0.7, 2.0, 1.0, step=0.05)
        sel_pitch = st.select_slider("Pitch (အသံ အနိမ့်အမြင့်)", options=["-12Hz", "-9Hz", "-6Hz", "-3Hz", "+0Hz", "+3Hz", "+6Hz", "+9Hz"], value=VOICE_PROFILES[sel_voice]["pitch"])

    if st.button("🎙️ အသံဖိုင် ဖန်တီးမည် (Generate MP3)", type="primary", use_container_width=True):
        if not voice_text.strip():
            st.error("စာသား ရိုက်ထည့်ပေးပါ။")
        else:
            with st.spinner("AI အသံ ထုတ်ယူနေပါသည်..."):
                pron_dict = load_replacements("pronunciation.txt")
                cleaned = clean_script_for_narration(voice_text)
                applied = apply_pronunciation(cleaned, pron_dict)
                out_aud = "standalone_voice.mp3"
                generate_voice_file(applied, sel_voice, out_aud, speed_multiplier=sel_speed, custom_pitch=sel_pitch)
                st.success("✅ အသံဖိုင် အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!")
                st.audio(out_aud)
                with open(out_aud, "rb") as af:
                    st.download_button("📥 MP3 အသံဖိုင် ဒေါင်းလုဒ်ဆွဲရန်", data=af.read(), file_name="ai_burmese_voice.mp3", mime="audio/mp3")

# ----------------- PAGE 10: အသံ ပြောင်းစနစ် -----------------
elif st.session_state.nav_menu == "🔄 အသံ ပြောင်းစနစ်":
    st.markdown("## 🔄 **အသံ ပြောင်းစနစ်နှင့် Tools (Audio Converter)**")
    st.caption("ဗီဒီယိုမှ MP3 ထုတ်ယူခြင်း၊ Audio Pitch Shifter (အသံနက်/အသံစူး) နှင့် Tempo ချိန်ညှိခြင်း။")
    
    col_ac1, col_ac2 = st.columns(2)
    with col_ac1:
        aud_source = st.file_uploader("အသံ သို့မဟုတ် ဗီဒီယိုဖိုင် တင်ပါ", type=["mp3", "wav", "mp4", "m4a"])
        tool_mode = st.selectbox("လုပ်ဆောင်ချက်", ["ဗီဒီယိုမှ MP3 သီးသန့် ထုတ်ယူမည်", "Pitch ပြောင်းမည် (Deep Voice / High Voice)", "Tempo (အသံ အနှေးအမြန်) ချိန်မည်"])
    with col_ac2:
        pitch_shift = st.slider("Pitch Semi-tones (အသံ အနိမ့်အမြင့်)", -12, 12, 0, step=1)
        tempo_val = st.slider("Tempo Multiplier", 0.5, 2.0, 1.0, step=0.1)

    if st.button("⚙️ အသံ စနစ် ပြောင်းလဲမည်", type="primary", use_container_width=True):
        if not aud_source and not os.path.exists("temp_voice.mp3"):
            st.error("ဖိုင် အရင်တင်ပေးပါ။")
        else:
            in_media = "temp_audio_tool_in"
            if aud_source:
                ext = aud_source.name.split(".")[-1]
                in_media = f"temp_audio_tool_in.{ext}"
                with open(in_media, "wb") as f:
                    f.write(aud_source.getbuffer())
            else:
                in_media = "temp_voice.mp3"

            with st.spinner("အသံကို ပြုပြင်ပြောင်းလဲနေပါသည်..."):
                out_audio = "converted_audio_result.mp3"
                if "ဗီဒီယိုမှ MP3" in tool_mode:
                    cmd_c = ["ffmpeg", "-y", "-i", in_media, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", out_audio]
                elif "Pitch" in tool_mode:
                    scale = 2 ** (pitch_shift / 12.0)
                    cmd_c = ["ffmpeg", "-y", "-i", in_media, "-af", f"asetrate=44100*{scale},aresample=44100", out_audio]
                else:
                    cmd_c = ["ffmpeg", "-y", "-i", in_media, "-af", f"atempo={tempo_val}", out_audio]
                    
                subprocess.run(cmd_c, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                st.success("✅ အသံဖိုင် အောင်မြင်စွာ ပြောင်းလဲပြီးပါပြီ!")
                st.audio(out_audio)
                with open(out_audio, "rb") as oaf:
                    st.download_button("📥 ရလဒ် အသံဖိုင် ဒေါင်းလုဒ်ဆွဲရန်", data=oaf.read(), file_name="converted_audio.mp3")

# ----------------- PAGE 11: အသံထွက်နှင့် ဝေါဟာရ စီမံရန် -----------------
elif st.session_state.nav_menu == "📖 အသံထွက်နှင့် ဝေါဟာရ စီမံရန်":
    st.markdown("## 📖 **အသံထွက်နှင့် ဝေါဟာရ စီမံခန့်ခွဲရန် (Pronunciation Manager)**")
    st.caption("TTS အသံထွက်ရာတွင် အင်္ဂလိပ်စကားလုံးများနှင့် ဇာတ်ကောင်အမည်များကို မြန်မာလို အသံထွက်မှန်စေရန် ပြင်ဆင်နိုင်ပါသည်။")
    
    pron_file = "pronunciation.txt"
    existing_content = ""
    if os.path.exists(pron_file):
        try:
            with open(pron_file, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except Exception:
            existing_content = ""
            
    new_content = st.text_area(
        "ဖိုင်အကြောင်းအရာ (တစ်ကြောင်းလျှင် စကားလုံးတစ်ခု = အသံထွက် ပုံစံဖြင့် ရေးပါ)",
        value=existing_content,
        height=320,
        placeholder="Iron Man = အိုင်းရွန်းမန်း\nSpider-Man = စပိုက်ဒါမန်း\nThanos = သာနို့စ်"
    )
    
    if st.button("💾 အသံထွက် ပြင်ဆင်ချက်များကို သိမ်းဆည်းမည်", type="primary"):
        try:
            with open(pron_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            st.success("✅ `pronunciation.txt` ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ!")
        except Exception as err:
            st.error(f"ဖိုင်သိမ်းဆည်းရာတွင် အမှားဖြစ်ပေါ်ပါသည်: {err}")

# ----------------- PAGE 12: API & SETTINGS -----------------
elif st.session_state.nav_menu == "⚙️ API & Settings":
    st.markdown("## ⚙️ **စနစ် ဆက်တင်များနှင့် API Keys**")
    st.caption("Recap Studio MM ၏ API Key များကို ဆာဗာ refresh ဖြစ်သော်လည်း မပျောက်စေရန် အပြီးအပိုင် သိမ်းဆည်းထားနိုင်ပါသည်။")
    
    api_key_input = st.text_input("Google Gemini API Key", value=st.session_state.gemini_api_key, type="password", placeholder="AIzaSy...")
    ayr_input = st.text_input("Ayrshare API Key (Social Media Auto-Poster)", value=st.session_state.ayrshare_api_key, type="password", placeholder="Ayrshare Key...")
    
    if st.button("💾 API Keys များ အပြီးအပိုင် သိမ်းဆည်းမည်", type="primary"):
        st.session_state.gemini_api_key = api_key_input
        save_config("gemini_api_key", api_key_input)
        st.session_state.ayrshare_api_key = ayr_input
        save_config("ayrshare_api_key", ayr_input)
        st.success("✅ API Keys များကို အပြီးအပိုင် မှတ်သားပြီးပါပြီ! (Website refresh လုပ်သော်လည်း ပျောက်မသွားတော့ပါ)")
