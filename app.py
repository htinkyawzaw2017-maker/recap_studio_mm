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

# ----------------- LOGO DETECTION -----------------
def find_studio_logo():
    candidates = [
        "logo.png", "logo.jpg", "logo.jpeg",
        "Gemini_Generated_Image_mx9b8emx9b8emx9b.jpg"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    matches = glob.glob("*logo*.png") + glob.glob("*logo*.jpg") + glob.glob("*Gemini_Generated_Image*.jpg")
    if matches:
        return matches[0]
    return None

STUDIO_LOGO_PATH = find_studio_logo()

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

# ----------------- VOICE PROFILES (DISTINCT TIMBRES) -----------------
VOICE_PROFILES = {
    "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "-8Hz",
        "rate_offset": 5,
        "desc": "ရုပ်ရှင်ဇာတ်လမ်းပြော ရင်ထဲထိစေမည့် အသံဩဇာကြီးမားသော အသံနက်ကြီး (Bass Deep Voice)"
    },
    "သီဟ (Native Male - Action & Dynamic)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "+1Hz",
        "rate_offset": 8,
        "desc": "သွက်လက်တက်ကြွပြီး စိတ်လှုပ်ရှားဖွယ် ဇာတ်ကွက်များအတွက် စကားပြောဟန်"
    },
    "အောင်ကျော် (Radio & Dramatic Narrator)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "+4Hz",
        "rate_offset": 10,
        "desc": "ဆွဲဆောင်မှုရှိပြီး စကားပြောအလွန်သွက်လက်သော အသံ"
    },
    "မေသူ (Soft Emotional Voice - Drama & Mystery)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+5Hz",
        "rate_offset": 2,
        "desc": "နူးညံ့ညင်သာပြီး စိတ်ခံစားမှုပေးစွမ်းနိုင်သော အသံ"
    },
    "နဒီ (Native Female - Standard Narration)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+0Hz",
        "rate_offset": 4,
        "desc": "ကြည်လင်ပြတ်သားသော မြန်မာအမျိုးသမီး အသံ"
    },
    "ဇင်ဇင် (Fast-Paced Storyteller Female)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "-3Hz",
        "rate_offset": 8,
        "desc": "ခေတ်မီဆန်းသစ်ပြီး စကားပြောဟန် သွက်လက်သော ဇာတ်လမ်းပြောသံ"
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
    st.session_state.saved_voice_speed = 1.15

if "saved_video_speed" not in st.session_state:
    st.session_state.saved_video_speed = 1.0

if "saved_voice" not in st.session_state:
    st.session_state.saved_voice = "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)"

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.15

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
        padding: 24px;
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
        background: linear-gradient(135deg, #0b1a20, #050d11);
        border: 2px solid #0284c7;
        border-radius: 16px;
        padding: 22px;
        margin: 20px 0;
        box-shadow: 0 0 25px rgba(2, 132, 199, 0.3);
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
        width: 90px;
        height: 90px;
        margin: 0 auto 15px auto;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #06b6d4, #ec4899);
        box-shadow: 0 0 25px #06b6d4, 0 0 50px #ec4899;
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

# ----------------- SCRIPT CLEANER & UNINTERRUPTED SPEECH -----------------
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

def prepare_uninterrupted_narration_text(raw_text):
    """
    အသံသွင်းရာတွင် ကြားထဲ ရပ်တန့်နေခြင်း (Awkward 1.5s Pauses) ကို အမြစ်ပြတ် ဖယ်ရှားပြီး
    YouTuber စကားပြောဟန်ကဲ့သို့ တစ်ဆက်တည်း တောက်လျှောက် ဖတ်ပြစေရန်
    ပုဒ်မ (။) နှင့် မလိုလားအပ်သော ပုဒ်ကလေး (၊) များကို ဖယ်ရှားပေးသည်။
    """
    if not raw_text:
        return ""
    t = clean_script_for_narration(raw_text)
    t = re.sub(r"\n+", " ", t)
    t = t.replace("။", " ").replace("၊", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t

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
သင်သည် TikTok နှင့် Facebook Reels ပေါ်တွင် အလွန်လူကြိုက်များသော မြန်မာ Movie / Story Recap Storyteller (ဥပမာ- Spoiler ကြီး၊ The Spoiler စတိုင်) ဖြစ်သည်။
ပေးထားသော ဗီဒီယိုကို ကြည့်ရှုပြီး ပရိတ်သတ် ရင်ခုန်စိတ်လှုပ်ရှားစေမည့် မြန်မာ Recap စကားပြော ဇာတ်ညွှန်းကို ရေးသားပေးပါ။

🛑 အလွန်အရေးကြီးသော တားမြစ်ချက်များ:
၁။ တရားဝင် စာအုပ်ကြီးဆန်သော စကားများ (ဥပမာ 'သင်ယုံကြည်နိုင်ပါ့မလား'၊ 'ခံခဲ့ရဖူးပါသည်'၊ 'တွေ့ရပါသည်' စသည်) ကို လုံးဝ (လုံးဝ) မသုံးရ။
၂။ အချိန်မှတ်များ (၀:၀၀-၀:၀၃)၊ နံပါတ်စဉ်များ (၁၊ ၂၊ ၃)၊ Scene ခေါင်းစဉ်များ၊ ကွင်းစကွင်းပိတ်များ လုံးဝမပါရ။
၃။ စကားပြောသံ မပြတ်တောက်စေရန် စာကြောင်းတိုလေးများ ခဏခဏ မဖြတ်ဘဲ အသက်ပါသော စကားပြောဝါကျရှည်များဖြင့် တောက်လျှောက် ရေးပေးပါ။

✨ မဖြစ်မနေ လိုက်နာရမည့် စကားပြောဟန် စတိုင် (Viral Colloquial Storytelling Style):
၁။ ပရိတ်သတ်ကို တိုက်ရိုက် စကားပြောသလို ရင်ဖွင့်ပြောပြဟန်ဖြင့် ရေးပါ (ဥပမာ- 'လူတွေတင် မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ သမိုင်းထဲက ထူးဆန်းတဲ့ အဖြစ်အပျက်တွေကို သင်တို့ ကြားဖူးကြရဲ့လားဗျာ...')။
၂။ စကားပြောချိတ်ဆက်စကားလုံးများ ဖြစ်သည့် 'ဟုတ်ပါတယ်ဗျ'၊ 'ဒါတင် မကသေးဘူးဗျာ'၊ 'တကယ်တော့'၊ 'အဆိုးဆုံးကတော့'၊ '...ခဲ့ကြတာပေါ့ဗျာ' စသည့် စကားပြောအသုံးအနှုန်းများကို တွင်တွင်ကျယ်ကျယ် သုံးပါ။
၃။ အသံဖတ်သူက တစ်ဆက်တည်း သဘာဝကျကျ အသက်ပါပါ ဖတ်ပြနိုင်စေရန် သာမန် စကားပြောစာပိုဒ်သက်သက်သာ ထုတ်ပေးပါ။

ညွှန်ကြားချက် ထပ်ဆောင်း: {custom_instructions if custom_instructions else 'သဘာဝကျသော ရုပ်ရှင်ပြန်ပြောပြသည့် စကားပြောဟန်စစ်စစ်ဖြင့် ရေးပေးပါ။'}
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

def generate_voice_file(text, voice_choice, output_audio_path, speed_multiplier=1.15, custom_pitch=None):
    prof = VOICE_PROFILES.get(voice_choice, VOICE_PROFILES["ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)"])
    voice_code = prof["voice"]
    base_pitch = custom_pitch if custom_pitch is not None else prof["pitch"]
    rate_val = int(round((speed_multiplier - 1.0) * 100)) + prof["rate_offset"]
    rate_str = f"{rate_val:+d}%"
    
    flowing_text = prepare_uninterrupted_narration_text(text)
    asyncio.run(run_edge_tts(flowing_text, voice_code, output_audio_path, rate=rate_str, pitch=base_pitch))

# ----------------- ADVANCED SUBTITLES (ASS FORMAT) -----------------
def create_ass_subtitles(
    script_text,
    total_duration,
    ass_path,
    font_name="Padauk",
    font_size=36,
    margin_v=260,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
    max_chars=28
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
        outline = "3"
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
        "-i", f"aevalsrc=sin(90*2*PI*t)*0.035+sin(135*2*PI*t)*0.025:d={duration}",
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
    enable_mask=True,
    mask_y_percent=78,
    mask_height=140,
    mask_opacity=0.90,
    enable_bgm=True,
    bgm_volume=0.15,
    logo_path=None,
    logo_size=120,
    logo_opacity=0.90,
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
        
    # SUBTITLE MASKING: Cover old English subtitles
    if enable_mask:
        y_calc = f"ih*{mask_y_percent/100.0}-({mask_height}/2)"
        vf_filters.append(f"drawbox=y={y_calc}:w=iw:h={mask_height}:color=black@{mask_opacity:.2f}:t=fill")

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
    if STUDIO_LOGO_PATH:
        st.image(STUDIO_LOGO_PATH, use_container_width=True)
    else:
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
    st.caption("⚡ **Recap Studio MM v2.9 Pro**")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    with col_banner:
        st.markdown("""
        <div class="hero-card">
            <span style="color:#a78bfa; font-size:12px; font-weight:bold; letter-spacing:1px;">✨ RECAP STUDIO MM PRO</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 26px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                Subtitle Masking (မူရင်းစာတန်းထိုး ဖုံးအုပ်ခြင်း)၊ ဆက်တိုက် စကားပြောသံ၊ Logo Watermark နှင့် Live Tweaker အားလုံး ပါဝင်ပါသည်။
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
            <div style="font-size:13px; margin-top:4px;">Recap Studio MM Pro v2.9</div>
            <h3 style="color:#10b981; margin:4px 0;">Studio Ready</h3>
            <p style="font-size:11px; color:#64748b;">Subtitle Masking, Uninterrupted Voice & Logo Ready.</p>
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
    st.caption("Subtitle Masking (မူရင်းစာတန်းထိုး ဖုံးအုပ်ခြင်း)၊ ဆက်တိုက် စကားပြောသံ၊ Logo Watermark နှင့် Live Tweaker အပြည့်အစုံ။")
    
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
        st.markdown("##### ၂။ အသံ ရွေးချယ်မှု (ဆက်တိုက် စကားပြောသံ)")
        voice_choice = st.selectbox(
            "အသံရွေးချယ်ပါ",
            list(VOICE_PROFILES.keys()),
            index=0
        )
        st.session_state.saved_voice = voice_choice
        st.caption(f"💡 {VOICE_PROFILES[voice_choice]['desc']}")
        
        if st.button("▶ ရွေးချယ်ထားသော အသံကို နမူနာ နားထောင်ရန်", use_container_width=True):
            with st.spinner("အသံနမူနာ ဖန်တီးနေပါသည်..."):
                sample_file = "sample_preview.mp3"
                generate_voice_file("လူတွေတင်မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ သမိုင်းထဲက အဖြစ်အပျက်တွေကို သင်တို့ ကြားဖူးကြရဲ့လားဗျာ။", voice_choice, sample_file, speed_multiplier=st.session_state.saved_voice_speed)
                st.audio(sample_file)
        
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ (Instructions)",
        value="ဗီဒီယိုထဲက မြင်ကွင်းတွေနဲ့ ကိုက်ညီအောင် 'Spoiler ကြီး' စတိုင် သဘာဝကျကျ စကားပြောဟန်ဖြင့် ရေးပေးပါ။ အချိန်မှတ်နှင့် နံပါတ်များ လုံးဝမထည့်ပါနှင့်။",
        height=65
    )

    # ----------------- SUBTITLE MASKING SETTINGS -----------------
    st.markdown("#### ၃။ မူရင်း စာတန်းထိုး ဖုံးအုပ်ခြင်း (Subtitle Masking)")
    st.caption("မူရင်း ဗီဒီယိုထဲတွင် အင်္ဂလိပ်စာတန်းထိုး ပါပြီးသားဖြစ်နေပါက ၎င်းနေရာကို အမည်းရောင်ဘားဖြင့် ဖုံးအုပ်ပြီး မြန်မာစာလုံး ပေါ်လွင်အောင် ထားနိုင်ပါသည်။")
    
    enable_mask = st.checkbox("🛡️ မူရင်း စာတန်းထိုး ဖုံးအုပ်မည့် Mask Bar ထည့်မည် (Masking Enable)", value=True)
    mask_y_percent = 78
    mask_height = 140
    mask_opacity = 0.90
    
    if enable_height = 140
    mask_opacity = 0.90
    
    if enable_mask:
        col_mk1, col_mk2, col_mk3 = st.columns(3)
        with col_mk1:
            mask_y_percent = st.slider("Mask ဒေါင်လိုက်နေရာ (Vertical %)", 50, 95, 78, step=1, help="78% သည် မူရင်းစာတန်းထိုး နေရာဖြစ်ပါသည်")
        with col_mk2:
            mask_height = st.slider("Mask ဘား အထူ/အမြင့် (Height px)", 60, 250, 140, step=10)
        with col_mk3:
            mask_opacity = st.slider("Mask အမည်းရောင် အကြည်/အနောက် (Opacity)", 0.4, 1.0, 0.90, step=0.05)

    # ----------------- SUBTITLES & SPEED SETTINGS -----------------
    st.markdown("#### ၄။ မြန်မာစာတန်းထိုးနှင့် Speed ချိန်ညှိချက်")
    col_sub_btn, col_sub_style1, col_sub_font = st.columns(3)
    with col_sub_btn:
        sub_option = st.radio("မြန်မာ စာတန်းထိုး ထည့်သွင်းမည်လား?", ["✅ ထည့်သွင်းမည် (Yes)", "❌ မထည့်ပါ (No)"], horizontal=True)
        enable_subtitles = (sub_option == "✅ ထည့်သွင်းမည် (Yes)")
    with col_sub_style1:
        sub_color = st.selectbox("စာလုံး အရောင်", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)", "Gold (ရွှေရောင်)"], disabled=not enable_subtitles)
    with col_sub_font:
        sub_font = st.selectbox("အသုံးပြုမည့် ဖောင့်", ["Padauk", "Pyidaungsu", "Noto Sans Myanmar"], disabled=not enable_subtitles)

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        voice_speed = st.slider("🎙️ စကားပြော Speed (1.15x အကြံပြုပါသည်)", min_value=0.8, max_value=2.0, value=float(st.session_state.saved_voice_speed), step=0.05)
        st.session_state.saved_voice_speed = voice_speed
    with col_s2:
        video_speed = st.slider("🎬 ဗီဒီယို Speed", min_value=0.7, max_value=2.0, value=float(st.session_state.saved_video_speed), step=0.05)
        st.session_state.saved_video_speed = video_speed
    with col_s3:
        bgm_vol = st.slider("🎵 Suspense BGM အတိုးအကျယ် (Volume)", min_value=0.0, max_value=0.5, value=float(st.session_state.saved_bgm_vol), step=0.02, format="%.2f")
        st.session_state.saved_bgm_vol = bgm_vol

    # ----------------- LOGO WATERMARK SETTINGS -----------------
    st.markdown("#### ၅။ ဗီဒီယို Format နှင့် Studio Logo Watermark")
    col_fmt, col_logo_chk = st.columns(2)
    with col_fmt:
        format_choice = st.selectbox(
            "Format ရွေးချယ်ပါ",
            ["9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)", "16:9 - အလျားလိုက် (YouTube)", "4:5 - Feed ပုံစံ (Facebook/IG)", "1:1 - စတုရန်း"]
        )
        format_ratio = format_choice.split(" - ")[0]
        
    with col_logo_chk:
        enable_logo = st.checkbox("🖼️ ဗီဒီယိုပေါ်တွင် Logo ထည့်သွင်းမည် (အပေါ်ထောင့် ညာဘက်)", value=True)
        
    logo_file_path = STUDIO_LOGO_PATH
    logo_size = 130
    logo_opacity = 0.90
    logo_margin = 20
    
    if enable_logo:
        uploaded_logo = st.file_uploader("Logo ပုံ ရွေးချယ်ပါ (မရွေးပါက သင့်မူရင်း Logo ကို သုံးပါမည်)", type=["png", "jpg", "jpeg"])
        if uploaded_logo:
            logo_file_path = "temp_custom_logo.png"
            with open(logo_file_path, "wb") as f:
                f.write(uploaded_logo.getbuffer())
                
        col
