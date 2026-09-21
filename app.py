import streamlit as st
import os
import re
import time
import json
import glob
import base64
import asyncio
import datetime
import subprocess
import urllib.request
from PIL import Image, ImageDraw

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

# ----------------- WEBSITE LOGO DETECTION -----------------
def find_website_logo():
    candidates = [
        "Gemini_Generated_Image_mx9b8emx9b8emx9b.jpg",
        "recap_studiomm_logo.png",
        "recap_studiomm.jpg",
        "website_logo.png",
        "website_logo.jpg",
        "logo.png",
        "logo.jpg"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    matches = glob.glob("*Gemini_Generated_Image*.jpg") + glob.glob("*recap*.png") + glob.glob("*recap*.jpg") + glob.glob("*logo*.png")
    if matches:
        return matches[0]
    return None

WEBSITE_LOGO_PATH = find_website_logo()

def get_base64_image(image_path):
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as img_f:
                b64 = base64.b64encode(img_f.read()).decode("utf-8")
                ext = image_path.split(".")[-1].lower()
                mime = "image/png" if ext == "png" else "image/jpeg"
                return f"data:{mime};base64,{b64}"
        except Exception:
            pass
    return ""

WEBSITE_LOGO_B64 = get_base64_image(WEBSITE_LOGO_PATH)

# ----------------- USER WATERMARK LOGO PROCESSOR (BUG FIXED) -----------------
def process_user_logo(input_img_path, output_img_path, make_circle=True, remove_white_bg=True, remove_black_bg=False, add_border=True, border_color=(255, 255, 255, 230)):
    """
    User တင်ပေးသော Video Watermark Logo ကို နောက်ခံရှင်းလင်းပြီး (Remove BG)
    ဗီဒီယိုပေါ်တွင် ကပ်ရန် အလွန်သန့်ပြန့်လှပသော အဝိုင်းပုံ badge အဖြစ် ပြောင်းလဲပေးသည်။
    """
    img = Image.open(input_img_path).convert("RGBA")
    
    # 1. Background removal (Exact tuple indexing fix)
    if remove_white_bg or remove_black_bg:
        data = list(img.getdata())
        new_data = []
        for item in data:
            r, g, b, a = item[0], item, item, item[3]
            if remove_white_bg and r > 220 and g > 220 and b > 220:
                new_data.append((255, 255, 255, 0))
            elif remove_black_bg and r < 35 and g < 35 and b < 35:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)
        
    # 2. Circular crop
    if make_circle:
        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))
        
        scale_size = (min_dim * 2, min_dim * 2)
        mask = Image.new("L", scale_size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + scale_size, fill=255)
        mask = mask.resize((min_dim, min_dim), Image.Resampling.LANCZOS)
        
        out = Image.new("RGBA", (min_dim, min_dim), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask=mask)
        if add_border:
            draw_out = ImageDraw.Draw(out)
            b_width = max(2, min_dim // 40)
            draw_out.ellipse((b_width//2, b_width//2, min_dim - b_width//2, min_dim - b_width//2), outline=border_color, width=b_width)
        img = out
        
    img.save(output_img_path, "PNG")

def get_overlay_coords(pos_name, margin=20):
    if "Top-Left" in pos_name or "အပေါ် ဘယ်" in pos_name:
        return f"{margin}:{margin}"
    elif "Bottom-Right" in pos_name or "အောက် ညာ" in pos_name:
        return f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}"
    elif "Bottom-Left" in pos_name or "အောက် ဘယ်" in pos_name:
        return f"{margin}:main_h-overlay_h-{margin}"
    else: # Top-Right default
        return f"main_w-overlay_w-{margin}:{margin}"

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

# ----------------- VOICE PROFILES (MATCHING PREMIUM RECAP) -----------------
VOICE_PROFILES = {
    "မင်းသန့် (Recommended - Agency, Confident Narrator)": {
        "voice": "my-MM-ThihaNeural",
        "pitch": "-2Hz",
        "rate_offset": 8,
        "desc": "ဆွဲဆောင်မှုရှိပြီး စကားပြောအလွန်ပီပြင်သော Movie Recap အသံ (ထိပ်တန်းရွေးချယ်မှု)"
    },
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
        "desc": "အလွန်သွက်လက်ပြီး ဆွဲဆောင်အားပြင်းသော အသံ"
    },
    "မေသူ (Soft Emotional Voice - Drama & Mystery)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+4Hz",
        "rate_offset": 2,
        "desc": "နူးညံ့ညင်သာပြီး စိတ်ခံစားမှု အပြည့်ပါသော အမျိုးသမီးအသံ"
    },
    "နဒီ (Native Female - Standard Narration)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "+0Hz",
        "rate_offset": 5,
        "desc": "ကြည်လင်ပြတ်သားသော မြန်မာအမျိုးသမီး အသံ"
    },
    "ဇင်ဇင် (Fast-Paced Storyteller Female)": {
        "voice": "my-MM-NilarNeural",
        "pitch": "-3Hz",
        "rate_offset": 9,
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

if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = "တိရစ္ဆာန်တွေကို တရားစွဲ"

if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = "ကြိုးပေးကွပ်မျက်ခဲ့"

if "saved_voice_speed" not in st.session_state:
    st.session_state.saved_voice_speed = 1.15

if "saved_video_speed" not in st.session_state:
    st.session_state.saved_video_speed = 1.0

if "saved_voice" not in st.session_state:
    st.session_state.saved_voice = "မင်းသန့် (Recommended - Agency, Confident Narrator)"

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.12

if "user_watermark_path" not in st.session_state:
    st.session_state.user_watermark_path = "circle_user_watermark.png" if os.path.exists("circle_user_watermark.png") else ""

if "saved_logo_pos" not in st.session_state:
    st.session_state.saved_logo_pos = "↗️ အပေါ် ညာဘက် (Top-Right)"

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

# ----------------- CUSTOM STYLING (DARK NEON THEME) -----------------
st.markdown("""
<style>
    .stApp {
        background-color: #070e13 !important;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    section[data-testid="stSidebar"] {
        background-color: #03080b !important;
        border-right: 1px solid #11222c;
    }
    .user-profile-box {
        background: linear-gradient(135deg, #0e1c26, #09131a);
        border: 1px solid #1b3548;
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
        background: linear-gradient(135deg, #0d2232 0%, #081622 60%, #040c13 100%);
        border: 1px solid #1c3b52;
        border-radius: 18px;
        padding: 24px;
        margin-bottom: 24px;
    }
    .action-card {
        background: #09141e;
        border: 1px solid #162b3d;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 14px;
        height: 100%;
        transition: transform 0.2s, border-color 0.2s;
    }
    .action-card:hover {
        border-color: #06b6d4;
        transform: translateY(-2px);
    }
    .tweaker-box {
        background: linear-gradient(135deg, #081722, #040c12);
        border: 2px solid #0284c7;
        border-radius: 16px;
        padding: 20px;
        margin: 18px 0;
        box-shadow: 0 0 25px rgba(2, 132, 199, 0.25);
    }
    .neon-loader-card {
        background: radial-gradient(circle, #09202e 0%, #030a10 100%);
        border: 2px solid #06b6d4;
        border-radius: 22px;
        padding: 40px 24px;
        text-align: center;
        box-shadow: 0 0 35px rgba(6, 182, 212, 0.4), inset 0 0 25px rgba(59, 130, 246, 0.25);
        animation: neonCardPulse 2.5s infinite alternate;
        margin: 20px 0;
    }
    @keyframes neonCardPulse {
        0% { box-shadow: 0 0 25px #06b6d4, inset 0 0 20px #3b82f6; border-color: #06b6d4; }
        50% { box-shadow: 0 0 45px #ec4899, inset 0 0 30px #8b5cf6; border-color: #ec4899; }
        100% { box-shadow: 0 0 25px #06b6d4, inset 0 0 20px #3b82f6; border-color: #06b6d4; }
    }
    .neon-ring-container {
        position: relative;
        width: 130px;
        height: 130px;
        margin: 0 auto 16px auto;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .neon-spinner-ring {
        position: absolute;
        width: 130px;
        height: 130px;
        border-radius: 50%;
        border: 3px solid transparent;
        border-top-color: #06b6d4;
        border-right-color: #ec4899;
        border-bottom-color: #f59e0b;
        animation: neonSpin 2s linear infinite;
        box-shadow: 0 0 20px rgba(6, 182, 212, 0.6);
    }
    @keyframes neonSpin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    .neon-logo-img {
        width: 90px;
        height: 90px;
        border-radius: 50%;
        object-fit: cover;
        box-shadow: 0 0 20px rgba(255, 255, 255, 0.3);
    }
    .recap-voice-badge {
        display: inline-block;
        background: linear-gradient(90deg, #0284c7, #2563eb);
        color: #ffffff;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 2px;
        padding: 4px 14px;
        border-radius: 20px;
        margin-bottom: 12px;
        box-shadow: 0 0 15px rgba(2, 132, 199, 0.6);
    }
    .neon-phase-text {
        color: #ffffff;
        font-size: 22px;
        font-weight: 800;
        letter-spacing: 1px;
        margin: 10px 0 4px 0;
        text-shadow: 0 0 12px #06b6d4, 0 0 24px #3b82f6;
    }
    .neon-sub-phase {
        color: #38bdf8;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 1px;
    }
    .neon-sound-waves {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 6px;
        height: 30px;
        margin: 18px 0;
    }
    .neon-bar {
        width: 5px;
        background: linear-gradient(180deg, #06b6d4, #ec4899);
        border-radius: 3px;
        animation: waveGrow 1.2s infinite ease-in-out alternate;
    }
    .neon-bar:nth-child(1) { height: 10px; animation-delay: 0.1s; }
    .neon-bar:nth-child(2) { height: 22px; animation-delay: 0.3s; }
    .neon-bar:nth-child(3) { height: 32px; animation-delay: 0.2s; }
    .neon-bar:nth-child(4) { height: 18px; animation-delay: 0.4s; }
    .neon-bar:nth-child(5) { height: 28px; animation-delay: 0.1s; }
    .neon-bar:nth-child(6) { height: 12px; animation-delay: 0.5s; }
    @keyframes waveGrow {
        0% { transform: scaleY(0.4); opacity: 0.4; }
        100% { transform: scaleY(1.4); opacity: 1; box-shadow: 0 0 10px #06b6d4; }
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
    if not raw_text:
        return ""
    t = clean_script_for_narration(raw_text)
    t = re.sub(r"\n+", " ", t)
    t = t.replace("။", " ").replace("၊", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t

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
    prof = VOICE_PROFILES.get(voice_choice, VOICE_PROFILES["မင်းသန့် (Recommended - Agency, Confident Narrator)"])
    voice_code = prof["voice"]
    base_pitch = custom_pitch if custom_pitch is not None else prof["pitch"]
    rate_val = int(round((speed_multiplier - 1.0) * 100)) + prof["rate_offset"]
    rate_str = f"{rate_val:+d}%"
    
    flowing_text = prepare_uninterrupted_narration_text(text)
    asyncio.run(run_edge_tts(flowing_text, voice_code, output_audio_path, rate=rate_str, pitch=base_pitch))

# ----------------- ASS SUBTITLE & AI HOOK GENERATOR -----------------
def create_ass_with_hook_and_subtitles(
    hook_line1,
    hook_line2,
    script_text,
    total_duration,
    ass_path,
    font_name="Padauk",
    sub_font_size=38,
    sub_margin_v=240,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
    hook_color="Yellow (ရွှေဝါရောင်)",
    enable_hook=True,
    max_chars=28
):
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
        "Gold (ရွှေရောင်)": "&H0000D7FF"
    }
    sub_col_ass = color_map.get(sub_color, "&H0000FFFF")
    hook_col_ass = color_map.get(hook_color, "&H0000FFFF")

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
        outline = "3.5"
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
Style: SubtitleStyle,{font_name},{sub_font_size},{sub_col_ass},&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,30,30,{sub_margin_v},1
Style: HookStyle,{font_name},44,{hook_col_ass},&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,130,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if enable_hook and (hook_line1 or hook_line2):
        hook_display = ""
        if hook_line1 and hook_line2:
            hook_display = f"{hook_line1}\\N{hook_line2}"
        elif hook_line1:
            hook_display = hook_line1
        else:
            hook_display = hook_line2
        ass_content += f"Dialogue: 1,0:00:00.00,{format_ass_time(total_duration)},HookStyle,,0,0,0,,{hook_display}\n"

    raw_segments = [s.strip() for s in re.split(r"[၊။\n]+", script_text) if s.strip()]
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
                    if current: chunks.append(current)
                    current = w
            if current: chunks.append(current)
    if not chunks: chunks = [script_text]
    chunk_time = total_duration / len(chunks)

    for idx, chunk in enumerate(chunks):
        start = idx * chunk_time
        end = min((idx + 1) * chunk_time, total_duration)
        ass_content += f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},SubtitleStyle,,0,0,0,,{chunk}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

def generate_simple_bgm(output_path, duration):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc=sin(90*2*PI*t)*0.035+sin(135*2*PI*t)*0.025:d={duration}",
        "-c:a", "libmp3lame",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- FFMPEG VIDEO RENDERER (AUDIO BUG & LOGO POSITION FIXED) -----------------
def render_pro_video(
    input_video_path,
    myanmar_audio_path,
    ass_path,
    output_video_path,
    aspect_format="9:16",
    video_speed=1.0,
    enable_subtitles=True,
    enable_anti_copyright=True,
    enable_mask=True,
    mask_y_percent=78,
    mask_height=140,
    mask_opacity=0.90,
    enable_bgm=True,
    bgm_volume=0.12,
    original_audio_volume=0.0,
    logo_path=None,
    logo_pos="↗️ အပေါ် ညာဘက် (Top-Right)",
    logo_size=120,
    logo_opacity=0.90,
    logo_margin=20
):
    audio_duration = get_media_duration(myanmar_audio_path)
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

    base_vf = ",".join(vf_filters)
    
    # 1. Audio handling (pure Myanmar voice + optional background music)
    final_audio_to_use = myanmar_audio_path
    temp_bgm = "temp_bgm.mp3"
    temp_mixed_audio = "temp_final_narration_mix.mp3"
    
    if enable_bgm and bgm_volume > 0.01:
        generate_simple_bgm(temp_bgm, audio_duration + 2)
        cmd_duck = [
            "ffmpeg", "-y",
            "-i", myanmar_audio_path,
            "-i", temp_bgm,
            "-filter_complex", f"[0:a]volume=1.0[v];[1:a]volume={bgm_volume:.2f}[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]",
            "-c:a", "libmp3lame",
            temp_mixed_audio
        ]
        subprocess.run(cmd_duck, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        final_audio_to_use = temp_mixed_audio

    # 2. Render Video with Logo & Subtitles (Strict Audio Mapping: -map 1:a:0)
    overlay_xy = get_overlay_coords(logo_pos, logo_margin)
    if logo_path and os.path.exists(logo_path):
        filter_complex = f"[0:v]{base_vf}[vid];[2:v]scale={logo_size}:-1,format=rgba,colorchannelmixer=aa={logo_opacity:.2f}[logo];[vid][logo]overlay={overlay_xy}[vwithlogo]"
        if enable_subtitles and ass_path and os.path.exists(ass_path):
            filter_complex += f";[vwithlogo]subtitles={ass_path}:fontsdir=.[vfinal]"
        else:
            filter_complex += ";[vwithlogo]null[vfinal]"
            
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", final_audio_to_use,
            "-i", logo_path,
            "-t", str(audio_duration),
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "25",
            "-c:a", "aac",
            "-b:a", "192k",
            "-threads", "0",
            output_video_path
        ]
    else:
        if enable_subtitles and ass_path and os.path.exists(ass_path):
            final_vf = f"{base_vf},subtitles={ass_path}:fontsdir=."
        else:
            final_vf = base_vf
            
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", final_audio_to_use,
            "-t", str(audio_duration),
            "-vf", final_vf,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "25",
            "-c:a", "aac",
            "-b:a", "192k",
            "-threads", "0",
            output_video_path
        ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- SIDEBAR -----------------
with st.sidebar:
    if WEBSITE_LOGO_PATH:
        st.image(WEBSITE_LOGO_PATH, use_container_width=True)
    else:
        st.markdown("### 🎬 **RECAP STUDIO MM**")
    
    st.markdown("""
    <div class="user-profile-box">
        <div>
            <div style="font-weight:bold; font-size:14px; color:#fff;">👤 Studio Master</div>
            <div style="font-size:11px; color:#38bdf8;">Recap Studio MM Pro v2.9</div>
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
    st.caption("⚡ **Recap Studio MM Pro**")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    with col_banner:
        st.markdown("""
        <div class="hero-card">
            <span style="color:#38bdf8; font-size:12px; font-weight:bold; letter-spacing:1px;">✨ RECAP STUDIO MM PRO</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 26px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                AI Hook Overlay၊ Subtitle Masking၊ မြန်မာ AI အသံစစ်စစ်နှင့် Circular Logo Watermark စနစ် အပြည့်အစုံ ပါဝင်ပါသည်။
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
        <div class="hero-card" style="background:#071520;">
            <div style="font-size:12px; color:#94a3b8;">သင့်စနစ်အခြေအနေ</div>
            <div style="font-size:13px; margin-top:4px;">Recap Studio MM Pro v2.9</div>
            <h3 style="color:#10b981; margin:4px 0;">Studio Ready</h3>
            <p style="font-size:11px; color:#64748b;">AI Hook, 100% Burmese Voice, Masking & Circle Logo Ready.</p>
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

# ----------------- PAGE 2: ဗီဒီယို ပြုလုပ်ရန် (CREATE & PRO EDITOR) -----------------
elif st.session_state.nav_menu == "🎬 ဗီဒီယို ပြုလုပ်ရန်":
    st.markdown("## 🎬 **ဗီဒီယို ပြုလုပ်ရန် (Recap Studio Pro)**")
    st.caption("AI Hook Overlay၊ Subtitle Masking၊ မြန်မာ AI အသံစစ်စစ် (English အသံ လုံးဝမပါ) နှင့် Circular Logo Watermark အပြည့်အစုံ။")
    
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
        st.markdown("##### ၂။ Fast AI Voice ရွေးချယ်မှု")
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
                generate_voice_file("မင်္ဂလာပါ ကျွန်တော်ကတော့ မင်းသန့်ပါ။ ရုပ်ရှင်ဇာတ်လမ်း အစအဆုံးကို အကောင်းဆုံး ပြန်လည်ပြောပြပေးသွားမှာ ဖြစ်ပါတယ်။", voice_choice, sample_file, speed_multiplier=st.session_state.saved_voice_speed)
                st.audio(sample_file)
        
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ (Instructions)",
        value="ဗီဒီယိုထဲက မြင်ကွင်းတွေနဲ့ ကိုက်ညီအောင် 'Spoiler ကြီး' စတိုင် သဘာဝကျကျ စကားပြောဟန်ဖြင့် ရေးပေးပါ။ အချိန်မှတ်နှင့် နံပါတ်များ လုံးဝမထည့်ပါနှင့်။",
        height=65
    )

    # ----------------- LOGO WATERMARK SETUP BEFORE RENDER -----------------
    st.markdown("##### ၃။ Video Watermark Logo (ဗီဒီယိုပေါ်တွင် ကပ်မည့် Logo)")
    enable_watermark = st.checkbox("🖼️ ဗီဒီယိုပေါ်တွင် Watermark Logo ထည့်သွင်းမည်", value=True)
    if enable_watermark:
        col_w1, col_w2, col_w3 = st.columns(3)
        with col_w1:
            pre_logo_file = st.file_uploader("Logo ပုံ ရွေးချယ်ပါ (PNG / JPG)", type=["png", "jpg", "jpeg"], key="pre_logo_uploader")
            if pre_logo_file is not None:
                try:
                    raw_p = "temp_user_raw_logo.png"
                    with open(raw_p, "wb") as lf:
                        lf.write(pre_logo_file.getbuffer())
                    process_user_logo(raw_p, "circle_user_watermark.png", make_circle=True, remove_white_bg=True)
                    st.session_state.user_watermark_path = "circle_user_watermark.png"
                    st.success("✅ အဝိုင်းပုံ Logo အောင်မြင်စွာ ပြင်ဆင်ပြီးပါပြီ!")
                except Exception as ex:
                    st.error(f"Logo ပြင်ဆင်ရာတွင် အမှားဖြစ်ပေါ်ပါသည်: {ex}")
        with col_w2:
            st.session_state.saved_logo_pos = st.selectbox(
                "Logo ထားရှိမည့် နေရာ (Position)",
                ["↗️ အပေါ် ညာဘက် (Top-Right)", "↖️ အပေါ် ဘယ်ဘက် (Top-Left)", "↘️ အောက် ညာဘက် (Bottom-Right)", "↙️ အောက် ဘယ်ဘက် (Bottom-Left)"],
                index=0
            )
        with col_w3:
            if st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path):
                st.image(st.session_state.user_watermark_path, width=80, caption="ပြင်ဆင်ပြီး Logo")

    st.markdown("---")
    
    # ----------------- TWO-STEP WORKFLOW -----------------
    st.markdown("### 🚀 **အဆင့် (၂) ဆင့် Recap ထုတ်လုပ်မှု စနစ်**")
    col_step1, col_step2 = st.columns(2)
    with col_step1:
        if st.button("📝 အဆင့် (၁): AI ဇာတ်ညွှန်းနှင့် Hook ခေါင်းစဉ် ထုတ်ယူမည်", type="primary", use_container_width=True):
            if not uploaded_video and not video_url:
                st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် Link ထည့်သွင်းပေးပါ။")
            elif not st.session_state.gemini_api_key:
                st.error("Gemini API Key ထည့်သွင်းပေးပါ။")
            else:
                with st.spinner("သဘာဝကျသော မြန်မာ Recap ဇာတ်ညွှန်းနှင့် Hook ခေါင်းစဉ် ထုတ်ယူနေပါသည်..."):
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
                    
                    try:
                        import google.generativeai as genai
                        genai.configure(api_key=st.session_state.gemini_api_key)
                        hook_m = genai.GenerativeModel("gemini-1.5-flash")
                        hook_prompt = f"ဒီဗီဒီယိုဇာတ်ညွှန်းအတွက် TikTok/Reels ပေါ်မှာ လူစိတ်ဝင်စားစေမယ့် စာကြောင်းတို ၂ ကြောင်းပါ ထိပ်စီး Hook Title (ဥပမာ Line 1: တိရစ္ဆာန်တွေကို တရားစွဲ, Line 2: ကြိုးပေးကွပ်မျက်ခဲ့) ကို ၂ ကြောင်းတည်း ရေးပေးပါ။ စာသားသက်သက်သာ ပေးပါ:\n{script_res[:300]}"
                        h_res = hook_m.generate_content(hook_prompt).text.strip().split("\n")
                        h_lines = [hl.strip() for hl in h_res if hl.strip() and not hl.startswith("#") and not hl.startswith("Line")]
                        if len(h_lines) >= 2:
                            st.session_state.top_hook_text = h_lines[0].replace("Line 1:", "").replace("၁။", "").strip()
                            st.session_state.bottom_hook_text = h_lines.replace("Line 2:", "").replace("၂။", "").strip()
                    except Exception:
                        pass
                        
                    st.success("✅ သဘာဝကျသော AI ဇာတ်ညွှန်းနှင့် Hook ခေါင်းစဉ် ထွက်ရှိပါပြီ!")

    st.markdown("##### 📝 မြန်မာ Recap ဇာတ်ညွှန်း (အချိန်မှတ်နှင့် နံပါတ်စဉ်များ လုံးဝဖယ်ရှားထားပြီး ဖြစ်ပါသည်):")
    edited_script = st.text_area(
        "ဇာတ်ညွှန်းတည်းဖြတ်ရန်",
        value=st.session_state.recap_script_text,
        height=140,
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

                logo_html_tag = f'<img src="{WEBSITE_LOGO_B64}" class="neon-logo-img" />' if WEBSITE_LOGO_B64 else '<span style="font-size:40px;">🎬</span>'
                
                def update_neon_phase(main_phase, sub_phase):
                    neon_container.markdown(f"""
                    <div class="neon-loader-card">
                        <div class="neon-ring-container">
                            <div class="neon-spinner-ring"></div>
                            {logo_html_tag}
                        </div>
                        <div class="recap-voice-badge">⚡ RECAP VOICE ACTIVE</div>
                        <div class="neon-phase-text">{main_phase}</div>
                        <div class="neon-sub-phase">{sub_phase}</div>
                        <div class="neon-sound-waves">
                            <div class="neon-bar"></div><div class="neon-bar"></div>
                            <div class="neon-bar"></div><div class="neon-bar"></div>
                            <div class="neon-bar"></div><div class="neon-bar"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                update_neon_phase("Uploading your video...", "Securing and uploading your video...")
                time.sleep(1.0)
                update_neon_phase("သင့် Recap ဖန်တီးနေသည်...", "Analyzing your video...")
                time.sleep(1.2)
                update_neon_phase("သင့် Recap ဖန်တီးနေသည်...", "Creating your recap script...")
                time.sleep(1.0)
                update_neon_phase("သင့် Recap ဖန်တီးနေသည်...", "Generating Myanmar Narration Voice...")

                clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                pron_dict = load_replacements("pronunciation.txt")
                final_script_for_tts = apply_pronunciation(clean_for_tts, pron_dict)
                
                temp_audio_out = "temp_voice.mp3"
                generate_voice_file(final_script_for_tts, voice_choice, temp_audio_out, speed_multiplier=st.session_state.saved_voice_speed)
                audio_dur = get_media_duration(temp_audio_out)
                st.session_state.last_voice_file = temp_audio_out

                update_neon_phase("Rendering Final Video...", "Applying Subtitle Masking & Hook Overlay...")
                
                temp_ass_path = "temp_render.ass"
                create_ass_with_hook_and_subtitles(
                    hook_line1=st.session_state.top_hook_text,
                    hook_line2=st.session_state.bottom_hook_text,
                    script_text=final_script_for_tts,
                    total_duration=audio_dur,
                    ass_path=temp_ass_path,
                    font_name="Padauk",
                    sub_font_size=38,
                    sub_margin_v=240,
                    sub_color="Yellow (ရွှေဝါရောင်)",
                    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
                    hook_color="Yellow (ရွှေဝါရောင်)",
                    enable_hook=True,
                    max_chars=28
                )

                final_video_output = "recap_output.mp4"
                
                watermark_to_use = None
                if enable_watermark and st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path):
                    watermark_to_use = st.session_state.user_watermark_path
                
                render_pro_video(
                    input_video_path=temp_in,
                    myanmar_audio_path=temp_audio_out,
                    ass_path=temp_ass_path,
                    output_video_path=final_video_output,
                    aspect_format="9:16",
                    video_speed=st.session_state.saved_video_speed,
                    enable_subtitles=True,
                    enable_anti_copyright=anti_copyright,
                    enable_mask=True,
                    mask_y_percent=78,
                    mask_height=140,
                    mask_opacity=0.90,
                    enable_bgm=(st.session_state.saved_bgm_vol > 0.01),
                    bgm_volume=st.session_state.saved_bgm_vol,
                    original_audio_volume=0.0, # 100% English audio silenced!
                    logo_path=watermark_to_use,
                    logo_pos=st.session_state.saved_logo_pos,
                    logo_size=120,
                    logo_opacity=0.90,
                    logo_margin=20
                )

                st.session_state.last_generated_video = final_video_output
                st.session_state.last_polished_video = final_video_output
                neon_container.empty()
                st.success("🎉 Recap ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ! အောက်ရှိ Editor တွင် စိတ်ကြိုက် ပြင်ဆင်နိုင်ပါသည်။")

            except Exception as e:
                neon_container.empty()
                st.error(f"❌ Error ဖြစ်ပေါ်ပါသည်: {str(e)}")

    # ----------------- PRO RECAP EDITOR TABS (MATCHING VIDEO) -----------------
    if os.path.exists("recap_output.mp4"):
        st.markdown("---")
        st.markdown("### 🎬 **Recap Pro Editor (Live Preview & Settings)**")
        
        vid_to_show = st.session_state.last_polished_video if (st.session_state.last_polished_video and os.path.exists(st.session_state.last_polished_video)) else "recap_output.mp4"
        
        col_preview, col_editor_tabs = st.columns((1.1, 1.4))
        
        with col_preview:
            st.markdown("##### 📱 9:16 Video Preview")
            st.video(vid_to_show)
            if st.session_state.last_voice_file and os.path.exists(st.session_state.last_voice_file):
                with open(st.session_state.last_voice_file, "rb") as vf:
                    st.download_button(
                        "📥 Voice အသံ ဒေါင်းလုဒ် (Download MP3)",
                        data=vf.read(),
                        file_name="recap_voice_narration.mp3",
                        mime="audio/mp3",
                        use_container_width=True
                    )
                    
        with col_editor_tabs:
            tab_sub, tab_hook, tab_aud, tab_blur, tab_logo = st.tabs([
                "📝 Subtitles",
                "⚡ AI Hook",
                "🎵 Audio",
                "👁️ Blur",
                "🖼️ Logo"
            ])
            
            # --- TAB 1: SUBTITLES ---
            with tab_sub:
                st.markdown("##### စာတန်းထိုး ချိန်ညှိချက် (Subtitles)")
                show_subs = st.checkbox("Show Subtitles (စာတန်းထိုး ပြသမည်)", value=True)
                
                col_ts1, col_ts2 = st.columns(2)
                with col_ts1:
                    sub_font_style = st.selectbox("Font Style", ["Classic", "Clean", "Bold Display", "Outline", "Poster", "Cinematic Serif"], index=0)
                    sub_col_pick = st.selectbox("Top Color", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)", "Gold (ရွှေရောင်)"], index=0)
                with col_ts2:
                    sub_bg_style = st.selectbox("Subtitle Background", ["Box (အမည်းနောက်ခံ ဘား)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)", "Semi-Box (မှန်ကြည် အမည်းနောက်ခံ)"], index=0)
                    sub_font_size_sl = st.slider("Font Size (စာလုံး အရွယ်အစား)", 24, 56, 38, step=2)
                    
                sub_v_pos = st.slider("စာတန်းထိုး အမြင့်နေရာ (Height Position)", 40, 450, 240, step=10, help="Drag or slide to place subtitle over the mask")
                sub_width_sl = st.slider("Subtitle Width (အကျယ် - အများဆုံး စာလုံးရေ)", 20, 40, 28, step=2)

            # --- TAB 2: AI HOOK ---
            with tab_hook:
                st.markdown("##### ထိပ်စီး Hook စာတန်း (AI Hook Overlay)")
                enable_hook_chk = st.checkbox("Hook Overlay ဖွင့်မည် (အပေါ်ထိပ် ခေါင်းစဉ်)", value=True)
                
                hook_l1 = st.text_input("Top Hook Text (ပထမ စာကြောင်း)", value=st.session_state.top_hook_text)
                hook_l2 = st.text_input("Bottom Hook Text (ဒုတိယ စာကြောင်း)", value=st.session_state.bottom_hook_text)
                st.session_state.top_hook_text = hook_l1
                st.session_state.bottom_hook_text = hook_l2
                
                col_hk1, col_hk2 = st.columns(2)
                with col_hk1:
                    hook_col_sel = st.selectbox("Hook Color", ["Yellow (ရွှေဝါရောင်)", "Gold (ရွှေရောင်)", "White (အဖြူရောင်)", "Cyan (မိုးပြာရောင်)"], index=0)
                with col_hk2:
                    hook_font_size = st.slider("Hook Font Size", 30, 60, 44, step=2)
                    
                st.markdown("##### 📱 Post စာသားများ (Social Media)")
                st.text_area(
                    "Facebook Reels & TikTok Caption",
                    value=f"{hook_l1} {hook_l2}!\n\n{st.session_state.recap_script_text[:140]}...\n\n#recap #movierecap #myanmar #tiktok #reels #viral",
                    height=80
                )

            # --- TAB 3: AUDIO ---
            with tab_aud:
                st.markdown("##### အသံ ချိန်ညှိချက် (Audio Settings)")
                aud_spd = st.slider("🎙️ Narration Voice Speed", 0.8, 2.0, float(st.session_state.saved_voice_speed), step=0.05)
                st.session_state.saved_voice_speed = aud_spd
                
                orig_vol_sl = st.slider("🔇 မူရင်း ဗီဒီယို အသံ (Original Audio Volume)", 0.0, 0.5, 0.0, step=0.05, help="0.0 ထားရှိပါက မူရင်း English အသံ လုံးဝ ပိတ်ထားမည်ဖြစ်သည်")
                bgm_vol_sl = st.slider("🎵 Suspense BGM Volume", 0.0, 0.5, float(st.session_state.saved_bgm_vol), step=0.02)
                st.session_state.saved_bgm_vol = bgm_vol_sl

            # --- TAB 4: BLUR / MASK ---
            with tab_blur:
                st.markdown("##### မူရင်း စာတန်းထိုး ဖုံးအုပ်ခြင်း (Original Subtitle Masking)")
                enable_blur_chk = st.checkbox("Blur / Mask Bar ဖွင့်ရန်", value=True)
                blur_y_sl = st.slider("Mask ဒေါင်လိုက်နေရာ (Vertical %)", 50, 95, 78, step=1)
                blur_h_sl = st.slider("Mask ဘား အထူ (Height px)", 60, 250, 140, step=10)
                blur_op_sl = st.slider("Mask အမည်းရောင် အကြည်/အနောက် (Opacity)", 0.4, 1.0, 0.90, step=0.05)

            # --- TAB 5: LOGO ---
            with tab_logo:
                st.markdown("##### Video Watermark Logo တင်ရန်")
                user_logo_file = st.file_uploader("User Logo ရွေးချယ်ပါ (PNG / JPG)", type=["png", "jpg", "jpeg"], key="user_logo_uploader")
                make_circle_chk = st.checkbox("✂️ အဝိုင်းပုံလှလှလေး ပြုလုပ်မည် (Auto Circular Badge)", value=True)
                remove_bg_chk = st.checkbox("🪄 နောက်ခံ အဖြူရောင် ဖယ်ရှားမည် (Remove BG)", value=True)
                
                if user_logo_file is not None:
                    try:
                        raw_path = "temp_user_raw_logo.png"
                        with open(raw_path, "wb") as lf:
                            lf.write(user_logo_file.getbuffer())
                        process_user_logo(raw_path, "circle_user_watermark.png", make_circle=make_circle_chk, remove_white_bg=remove_bg_chk)
                        st.session_state.user_watermark_path = "circle_user_watermark.png"
                        st.success("✅ အဝိုင်းပုံ Logo အောင်မြင်စွာ ပြင်ဆင်ပြီးပါပြီ!")
                        st.image("circle_user_watermark.png", width=90, caption="အဝိုင်းပုံ ပြင်ဆင်ပြီး Logo")
                    except Exception as err:
                        st.error(f"Logo ပြင်ဆင်ရာတွင် အမှားဖြစ်ပေါ်ပါသည်: {err}")
                elif st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path):
                    st.image(st.session_state.user_watermark_path, width=90, caption="လက်ရှိ သုံးနေသော Logo")
                    
                col_lg_pos, col_lg_s1, col_lg_s2 = st.columns(3)
                with col_lg_pos:
                    logo_pos_choice = st.selectbox(
                        "Logo ထားရှိမည့် နေရာ",
                        ["↗️ အပေါ် ညာဘက် (Top-Right)", "↖️ အပေါ် ဘယ်ဘက် (Top-Left)", "↘️ အောက် ညာဘက် (Bottom-Right)", "↙️ အောက် ဘယ်ဘက် (Bottom-Left)"],
                        index=0
                    )
                with col_lg_s1:
                    lg_size_sl = st.slider("Logo Size (px)", 60, 250, 120, step=10)
                with col_lg_s2:
                    lg_op_sl = st.slider("Logo Opacity", 0.3, 1.0, 0.90, step=0.05)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("⚡ ပြင်ဆင်ချက်များဖြင့် Final Video အချော ထုတ်ယူမည် (Re-Export MP4)", type="primary", use_container_width=True):
                with st.spinner("ရွေးချယ်ထားသော စတိုင်သစ်များဖြင့် Final Video အချော ထုတ်ယူနေပါသည်..."):
                    tweak_ass = "tweak_editor.ass"
                    audio_f = st.session_state.last_voice_file if (st.session_state.last_voice_file and os.path.exists(st.session_state.last_voice_file)) else "temp_voice.mp3"
                    audio_len = get_media_duration(audio_f) if os.path.exists(audio_f) else 10.0
                    
                    clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                    create_ass_with_hook_and_subtitles(
                        hook_line1=hook_l1,
                        hook_line2=hook_l2,
                        script_text=clean_for_tts,
                        total_duration=audio_len,
                        ass_path=tweak_ass,
                        font_name="Padauk",
                        sub_font_size=sub_font_size_sl,
                        sub_margin_v=sub_v_pos,
                        sub_color=sub_col_pick,
                        sub_bg=sub_bg_style,
                        hook_color=hook_col_sel,
                        enable_hook=enable_hook_chk,
                        max_chars=sub_width_sl
                    )
                    
                    final_reexport_mp4 = "recap_polished_final.mp4"
                    watermark_path = st.session_state.user_watermark_path if (st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path)) else None
                    
                    render_pro_video(
                        input_video_path="temp_input.mp4",
                        myanmar_audio_path=audio_f,
                        ass_path=tweak_ass if show_subs else None,
                        output_video_path=final_reexport_mp4,
                        aspect_format="9:16",
                        video_speed=st.session_state.saved_video_speed,
                        enable_subtitles=show_subs,
                        enable_anti_copyright=anti_copyright,
                        enable_mask=enable_blur_chk,
                        mask_y_percent=blur_y_sl,
                        mask_height=blur_h_sl,
                        mask_opacity=blur_op_sl,
                        enable_bgm=(bgm_vol_sl > 0.01),
                        bgm_volume=bgm_vol_sl,
                        original_audio_volume=orig_vol_sl,
                        logo_path=watermark_path,
                        logo_pos=logo_pos_choice,
                        logo_size=lg_size_sl,
                        logo_opacity=lg_op_sl,
                        logo_margin=20
                    )
                    st.session_state.last_polished_video = final_reexport_mp4
                    st.success("✨ Final Video အချော ပြန်လည်ထုတ်ယူပြီးပါပြီ!")
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
            value=f"{st.session_state.top_hook_text} {st.session_state.bottom_hook_text}!\n\n{st.session_state.recap_script_text[:120]}...\n\n#recap #movierecap #myanmar #shorts #reels",
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
    st.caption("မြန်မာစကားပြော အသံဩဇာ ၇ မျိုးဖြင့် စိတ်ကြိုက် စာသားများကို သဘာဝကျကျ အသံသွင်းယူနိုင်ပါသည်။")
    
    voice_text = st.text_area(
        "အသံထွက်ဖတ်ခိုင်းမည့် မြန်မာစာသား ရိုက်ထည့်ပါ",
        value="လူတွေတင်မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ သမိုင်းထဲက ထူးဆန်းတဲ့ အဖြစ်အပျက်တွေကို သင်တို့ ကြားဖူးကြရဲ့လားဗျာ။",
        height=140
    )
    
    col_vs1, col_vs2 = st.columns(2)
    with col_vs1:
        sel_voice = st.selectbox("အသံရွေးချယ်ပါ", list(VOICE_PROFILES.keys()), index=0)
        st.info(f"💡 {VOICE_PROFILES[sel_voice]['desc']}")
    with col_vs2:
        sel_speed = st.slider("အသံ Speed", 0.8, 2.0, 1.15, step=0.05)
        sel_pitch = st.select_slider("Pitch (အသံ အနိမ့်အမြင့်)", options=["-12Hz", "-8Hz", "-4Hz", "+0Hz", "+4Hz", "+8Hz"], value=VOICE_PROFILES[sel_voice]["pitch"])

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
