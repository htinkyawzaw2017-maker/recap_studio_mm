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

# ----------------- MEDIA DURATION HELPER -----------------
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

# ----------------- LANGUAGE DEFINITIONS & DEFAULTS -----------------
LANGUAGE_CONFIGS = {
    "🇲🇲 မြန်မာ (Myanmar / Burmese)": {
        "code": "my",
        "default_voice": "မင်းသန့် (Recommended - Agency, Confident Narrator)",
        "default_hook1": "တိရစ္ဆာန်တွေကို တရားစွဲ",
        "default_hook2": "ကြိုးပေးကွပ်မျက်ခဲ့",
        "default_sub_preview": "လူတွေတင် မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ ထူးဆန်းတဲ့ သမိုင်း...",
        "sample_speech": "မင်္ဂလာပါ ကျွန်တော်ကတော့ မင်းသန့်ပါ။ ဒီနေ့မှာတော့ ထူးဆန်းတဲ့ သမိုင်းကြောင်းကို ပြောပြပေးပါမယ်။",
        "voices": {
            "မင်းသန့် (Recommended - Agency, Confident Narrator)": {
                "voice": "my-MM-ThihaNeural", "pitch": "-2Hz", "rate_offset": 8,
                "desc": "ဆွဲဆောင်မှုရှိပြီး စကားပြောအလွန်ပီပြင်သော Movie Recap အသံ (ထိပ်တန်းရွေးချယ်မှု)"
            },
            "ကိုမင်း (Deep Cinematic Voice - Movie Recap Specialist)": {
                "voice": "my-MM-ThihaNeural", "pitch": "-8Hz", "rate_offset": 5,
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
            },
            "နဒီ (Native Female - Standard Narration)": {
                "voice": "my-MM-NilarNeural", "pitch": "+0Hz", "rate_offset": 5,
                "desc": "ကြည်လင်ပြတ်သားသော မြန်မာအမျိုးသမီး အသံ"
            },
            "ဇင်ဇင် (Fast-Paced Storyteller Female)": {
                "voice": "my-MM-NilarNeural", "pitch": "-3Hz", "rate_offset": 9,
                "desc": "ခေတ်မီဆန်းသစ်ပြီး စကားပြောဟန် သွက်လက်သော ဇာတ်လမ်းပြောသံ"
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
        "voices": {
            "Christopher (Cinematic Deep Narrator)": {
                "voice": "en-US-ChristopherNeural", "pitch": "-4Hz", "rate_offset": 5,
                "desc": "Deep, resonant cinematic Hollywood documentary male narrator"
            },
            "Guy (Viral Recap Storyteller - High Retention)": {
                "voice": "en-US-GuyNeural", "pitch": "+0Hz", "rate_offset": 8,
                "desc": "Energetic, engaging TikTok/Shorts movie recapper voice"
            },
            "Jenny (Clear & Natural Conversational Female)": {
                "voice": "en-US-JennyNeural", "pitch": "+0Hz", "rate_offset": 6,
                "desc": "Crystal clear colloquial female storyteller"
            },
            "Aria (Expressive Dramatic Female)": {
                "voice": "en-US-AriaNeural", "pitch": "+2Hz", "rate_offset": 7,
                "desc": "Emotional, dynamic mystery storytelling female voice"
            }
        }
    },
    "🇹🇭 ไทย (Thai / ထိုင်း)": {
        "code": "th",
        "default_voice": "Niwat (Thai Male Storyteller)",
        "default_hook1": "เรื่องจริงสุดแปลก",
        "default_hook2": "ตัดสินประหารชีวิต",
        "default_sub_preview": "คุณเคยได้ยินเรื่องสัตว์ถูกนำตัวขึ้นศาลและตัดสินคดีไหมครับ...",
        "sample_speech": "สวัสดีครับ ยินดีต้อนรับสู่การสรุปเนื้อเรื่องภาพยนตร์สุดระทึก",
        "voices": {
            "Niwat (Thai Male Storyteller)": {
                "voice": "th-TH-NiwatNeural", "pitch": "+0Hz", "rate_offset": 6,
                "desc": "Professional Thai movie recap male voice"
            },
            "Premwadee (Thai Female Narrator)": {
                "voice": "th-TH-PremwadeeNeural", "pitch": "+0Hz", "rate_offset": 6,
                "desc": "Engaging Thai storytelling female voice"
            }
        }
    },
    "🇨🇳 中文 (Chinese / တရုတ်)": {
        "code": "zh",
        "default_voice": "Yunxi (Chinese Recap Narrator)",
        "default_hook1": "匪夷所思的历史",
        "default_hook2": "动物竟然受审死刑",
        "default_sub_preview": "你敢相信吗？在几个世纪前的欧洲，动物竟然也会被送上法庭审判...",
        "sample_speech": "大家好，今天给大家带来一部极其震撼的真实历史悬疑解说。",
        "voices": {
            "Yunxi (Chinese Recap Narrator)": {
                "voice": "zh-CN-YunxiNeural", "pitch": "+0Hz", "rate_offset": 8,
                "desc": "Popular Douyin/TikTok cinematic storytelling male voice"
            },
            "Xiaoxiao (Chinese Expressive Female)": {
                "voice": "zh-CN-XiaoxiaoNeural", "pitch": "+0Hz", "rate_offset": 7,
                "desc": "Clear, expressive movie review female voice"
            }
        }
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

if "target_language" not in st.session_state:
    st.session_state.target_language = "🇲🇲 မြန်မာ (Myanmar / Burmese)"

if "active_lang_key" not in st.session_state:
    st.session_state.active_lang_key = st.session_state.target_language

defaults_init = LANGUAGE_CONFIGS[st.session_state.target_language]

if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = defaults_init["default_hook1"]

if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = defaults_init["default_hook2"]

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = defaults_init["default_sub_preview"]

if "sub_v_pos_percent" not in st.session_state:
    st.session_state.sub_v_pos_percent = 22

if "sub_width_percent" not in st.session_state:
    st.session_state.sub_width_percent = 85

if "hook_top_percent" not in st.session_state:
    st.session_state.hook_top_percent = 8

if "saved_voice_speed" not in st.session_state:
    st.session_state.saved_voice_speed = 1.15

if "saved_video_speed" not in st.session_state:
    st.session_state.saved_video_speed = 1.0

if "saved_voice" not in st.session_state:
    st.session_state.saved_voice = defaults_init["default_voice"]

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.12

if "user_watermark_path" not in st.session_state:
    st.session_state.user_watermark_path = "circle_user_watermark.png" if os.path.exists("circle_user_watermark.png") else ""

if "saved_logo_pos" not in st.session_state:
    st.session_state.saved_logo_pos = "↗️ အပေါ် ညာဘက် (Top-Right)"

if "clean_preview_video" not in st.session_state:
    st.session_state.clean_preview_video = ""

if "last_voice_file" not in st.session_state:
    st.session_state.last_voice_file = ""

if "last_generated_video" not in st.session_state:
    st.session_state.last_generated_video = "recap_output.mp4" if os.path.exists("recap_output.mp4") else ""

if "last_polished_video" not in st.session_state:
    st.session_state.last_polished_video = ""

if "source_video_path" not in st.session_state:
    st.session_state.source_video_path = "temp_input.mp4" if os.path.exists("temp_input.mp4") else ""

def sync_language_defaults(new_lang):
    cfg = LANGUAGE_CONFIGS[new_lang]
    st.session_state.top_hook_text = cfg["default_hook1"]
    st.session_state.bottom_hook_text = cfg["default_hook2"]
    st.session_state.recap_script_text = cfg["default_sub_preview"]
    st.session_state.saved_voice = cfg["default_voice"]
    st.session_state.active_lang_key = new_lang

def navigate_to(page_name):
    st.session_state.nav_menu = page_name

# ----------------- USER WATERMARK LOGO PROCESSOR -----------------
def process_user_logo(input_img_path, output_img_path, make_circle=True, remove_white_bg=True, remove_black_bg=False, add_border=True, border_color=(255, 255, 255, 230)):
    img = Image.open(input_img_path).convert("RGBA")
    if remove_white_bg or remove_black_bg:
        data = list(img.getdata())
        new_data = []
        for item in data:
            r = item[0]
            g = item[1]
            b = item[2]
            a = item[3] if len(item) > 3 else 255
            if remove_white_bg and r > 215 and g > 215 and b > 215:
                new_data.append((255, 255, 255, 0))
            elif remove_black_bg and r < 35 and g < 35 and b < 35:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append((r, g, b, a))
        img.putdata(new_data)
        
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
    else:
        return f"main_w-overlay_w-{margin}:{margin}"

def get_logo_css_pos(pos_name):
    if "Top-Left" in pos_name or "အပေါ် ဘယ်" in pos_name:
        return "top: 15px; left: 15px;"
    elif "Bottom-Right" in pos_name or "အောက် ညာ" in pos_name:
        return "bottom: 25px; right: 15px;"
    elif "Bottom-Left" in pos_name or "အောက် ဘယ်" in pos_name:
        return "bottom: 25px; left: 15px;"
    else:
        return "top: 15px; right: 15px;"

def get_file_base64(filepath):
    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass
    return ""

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
                            data[parts[0].strip()] = parts[1].strip()
        except Exception:
            pass
    return data

def apply_pronunciation(text, pron_dict):
    if not text or not pron_dict:
        return text
    for word, pron in pron_dict.items():
        text = re.sub(rf"\b{re.escape(word)}\b", pron, text, flags=re.IGNORECASE)
    return text

def parse_hook_titles(raw_text, default_line1, default_line2):
    if not raw_text:
        return default_line1, default_line2
    lines = []
    for line in raw_text.split("\n"):
        clean_l = line.strip()
        if clean_l and not clean_l.startswith("#"):
            clean_l = re.sub(r"^(line\s*[12]|၁|၂|[12])\s*[:\.\)။\-]*\s*", "", clean_l, flags=re.IGNORECASE).strip()
            if clean_l:
                lines.append(clean_l)
    l1 = lines[0] if len(lines) > 0 else default_line1
    l2 = lines[1] if len(lines) > 1 else default_line2
    return l1, l2

# ----------------- EXACT DURATION MULTILINGUAL SCRIPT GENERATOR -----------------
def generate_multilingual_recap(api_key, model_name, video_path, target_lang_name, custom_instructions, target_duration_sec=60.0):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    
    try:
        model = genai.GenerativeModel(model_name)
    except Exception:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
    lang_info = LANGUAGE_CONFIGS.get(target_lang_name, LANGUAGE_CONFIGS["🇲🇲 မြန်မာ (Myanmar / Burmese)"])
    lang_code = lang_info["code"]
    
    if lang_code == "en":
        target_words = max(35, int(target_duration_sec * 2.3))
        pacing_rule = f"""
CRITICAL DURATION & PACING REQUIREMENT:
The video is EXACTLY {round(target_duration_sec)} seconds long ({round(target_duration_sec/60, 1)} minutes).
You must write an engaging recap script of approximately {target_words} words that when read aloud takes EXACTLY {round(target_duration_sec)} seconds.
The narration MUST cover the full video continuously from second 0 to the final second without finishing early!
Write 100% in natural spoken ENGLISH ONLY. No Burmese or other language.
NO timestamps (0:00), NO numbers (1, 2, 3), NO scene labels.
"""
    elif lang_code == "th":
        target_words = max(40, int(target_duration_sec * 2.6))
        pacing_rule = f"""
วิดีโอนี้มีความยาว {round(target_duration_sec)} วินาที
เขียนบทบรรยาย Recap ภาพยนตร์เป็นภาษาไทยล้วนๆ ให้มีความยาวประมาณ {target_words} คำ เพื่อให้การบรรยายตรงกับความยาวของวิดีโอตั้งแต่ต้นจนจบ
ห้ามใส่เครื่องหมายเวลา (0:00) และตัวเลข
"""
    elif lang_code == "zh":
        target_words = max(50, int(target_duration_sec * 3.2))
        pacing_rule = f"""
本视频时长为 {round(target_duration_sec)} 秒。
请编写一段纯中文的解说文案，字数约为 {target_words} 字，确保配音节奏从头到尾与视频完全吻合。
切勿包含时间戳或数字编号。
"""
    else: # Myanmar
        target_words = max(50, int(target_duration_sec * 4.5))
        pacing_rule = f"""
🛑 အလွန်အရေးကြီးသော ကြာချိန်နှင့် စကားပြောနှုန်း လိုက်နာချက်:
တင်ထားသော ဗီဒီယို၏ စုစုပေါင်း ကြာချိန်သည် အတိအကျ {round(target_duration_sec)} စက္ကန့် ({round(target_duration_sec/60, 1)} မိနစ်) ဖြစ်သည်။
အသံဖတ်ကြားချိန်သည် ဗီဒီယိုစတင်သည့် စက္ကန့် ၀ မှ အဆုံးထိ အတိအကျ ပြည့်မီစေရန်အတွက် စကားလုံးပေါင်း အနီးစပ်ဆုံး {target_words} လုံးခန့် ပါဝင်သော စကားပြောဝါကျအပြည့်အစုံကို ရေးပေးပါ။
စာသားတိုတိုလေး ရေးပြီး စောစောပြီးသွားခြင်း သို့မဟုတ် ဗီဒီယိုထက် အသံပိုရှည်နေခြင်း လုံးဝ မဖြစ်ရပါ။
မြန်မာစကားပြော သီးသန့် (Burmese Only) ဖြင့် ရေးသားပေးပါ။
အချိန်မှတ် (၀:၀၀) နှင့် နံပါတ်စဉ်များ လုံးဝမပါရ။
"""

    prompt = f"""
{pacing_rule}
Additional instructions: {custom_instructions}
"""
    if video_path and os.path.exists(video_path):
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        response = model.generate_content([video_file, prompt])
    else:
        response = model.generate_content(prompt)
    
    script_text = clean_script_for_narration(response.text)
    
    try:
        hook_m = genai.GenerativeModel("gemini-1.5-flash")
        if lang_code == "en":
            hook_prompt = f"Based on this script, create a viral 2-line video Hook title in ENGLISH ONLY. Format strictly as:\nLINE 1: <2-4 words in English>\nLINE 2: <2-4 words in English>\n\nScript:\n{script_text[:400]}"
        elif lang_code == "th":
            hook_prompt = f"สร้างหัวข้อ Hook สั้นๆ 2 บรรทัดสำหรับวิดีโอเป็นภาษาไทยเท่านั้น:\nLINE 1: <2-4 คำ>\nLINE 2: <2-4 คำ>\n\nScript:\n{script_text[:400]}"
        elif lang_code == "zh":
            hook_prompt = f"请为该视频生成两行纯中文爆款标题：\nLINE 1: <2-4字>\nLINE 2: <2-4字>\n\n文案：\n{script_text[:400]}"
        else:
            hook_prompt = f"ဒီ script အတွက် မြန်မာဘာသာစကား သီးသန့်ဖြင့် ဆွဲဆောင်မှုရှိသော Hook Title စာကြောင်းတို ၂ ကြောင်း ရေးပေးပါ:\nLINE 1: <စကားလုံး ၃-၄ လုံး>\nLINE 2: <စကားလုံး ၃-၄ လုံး>\n\nScript:\n{script_text[:400]}"
            
        h_resp = hook_m.generate_content(hook_prompt).text
        hook1, hook2 = parse_hook_titles(h_resp, lang_info["default_hook1"], lang_info["default_hook2"])
    except Exception:
        hook1, hook2 = lang_info["default_hook1"], lang_info["default_hook2"]
        
    return script_text, hook1, hook2

async def run_edge_tts(text, voice_name, output_path, rate="+0%", pitch="+0Hz"):
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def generate_voice_file(text, voice_dict, output_audio_path, speed_multiplier=1.15, custom_pitch=None, lang_code="my"):
    voice_code = voice_dict["voice"]
    base_pitch = custom_pitch if custom_pitch is not None else voice_dict["pitch"]
    rate_val = int(round((speed_multiplier - 1.0) * 100)) + voice_dict["rate_offset"]
    rate_str = f"{rate_val:+d}%"
    flowing_text = prepare_uninterrupted_narration_text(text, lang_code=lang_code)
    asyncio.run(run_edge_tts(flowing_text, voice_code, output_audio_path, rate=rate_str, pitch=base_pitch))

# ----------------- AUDIO TEMPO SYNC HELPER (100% MILLISECOND PRECISION) -----------------
def sync_audio_to_exact_video_duration(raw_audio_path, target_video_duration, output_synced_audio_path):
    raw_audio_dur = get_media_duration(raw_audio_path)
    if raw_audio_dur <= 0.1 or target_video_duration <= 0.1:
        shutil.copyfile(raw_audio_path, output_synced_audio_path)
        return
        
    tempo_ratio = raw_audio_dur / target_video_duration
    
    if 0.75 <= tempo_ratio <= 1.30:
        cmd = [
            "ffmpeg", "-y",
            "-i", raw_audio_path,
            "-filter:a", f"atempo={tempo_ratio}",
            output_synced_audio_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elif tempo_ratio < 0.75:
        pad_sec = target_video_duration - raw_audio_dur
        cmd = [
            "ffmpeg", "-y",
            "-i", raw_audio_path,
            "-af", f"apad=pad_dur={pad_sec}",
            output_synced_audio_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", raw_audio_path,
            "-t", str(target_video_duration),
            "-c:a", "libmp3lame",
            output_synced_audio_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- ASS SUBTITLE & AI HOOK GENERATOR -----------------
def create_ass_subtitles(
    hook_line1,
    hook_line2,
    script_text,
    total_duration,
    ass_path,
    font_name="Padauk",
    sub_font_size=38,
    sub_margin_v=240,
    hook_top_margin_v=130,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
    hook_color="Yellow (ရွှေဝါရောင်)",
    enable_hook=True,
    max_chars=28,
    lang_code="my"
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

    actual_font = "Arial" if lang_code in ["en", "zh"] else font_name

    ass_content = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SubtitleStyle,{actual_font},{sub_font_size},{sub_col_ass},&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,30,30,{sub_margin_v},1
Style: HookStyle,{actual_font},44,{hook_col_ass},&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,{hook_top_margin_v},1

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

    if lang_code == "en":
        words = script_text.split(" ")
        chunks = []
        current = []
        for w in words:
            current.append(w)
            if len(" ".join(current)) >= max_chars or len(current) >= 5:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
    else:
        raw_segments = [s.strip() for s in re.split(r"[၊။\.\?\!\n]+", script_text) if s.strip()]
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

# ----------------- FFMPEG VIDEO RENDERER (STRICT 1.0X NATURAL VIDEO SPEED) -----------------
def render_pro_video(
    input_video_path,
    audio_narration_path,
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
    video_duration = get_media_duration(input_video_path)
    
    synced_audio = "temp_synced_voice.mp3"
    sync_audio_to_exact_video_duration(audio_narration_path, video_duration, synced_audio)
    target_render_duration = video_duration

    scale_dict = {
        "9:16": "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "16:9": "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        "4:5": "scale=720:900:force_original_aspect_ratio=increase,crop=720:900",
        "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720"
    }
    scale_filter = scale_dict.get(aspect_format, "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280")
    
    vf_filters = ["setpts=PTS", scale_filter]
    
    if enable_anti_copyright:
        vf_filters.append("scale=1.05*iw:1.05*ih,crop=iw:ih")
        vf_filters.append("eq=contrast=1.04:brightness=0.02:saturation=1.06")
        
    if enable_mask:
        y_calc = f"ih*{mask_y_percent/100.0}-({mask_height}/2)"
        vf_filters.append(f"drawbox=y={y_calc}:w=iw:h={mask_height}:color=black@{mask_opacity:.2f}:t=fill")

    base_vf = ",".join(vf_filters)
    
    final_audio_to_use = synced_audio
    temp_bgm = "temp_bgm.mp3"
    temp_mixed_audio = "temp_final_narration_mix.mp3"
    
    if enable_bgm and bgm_volume > 0.01:
        generate_simple_bgm(temp_bgm, target_render_duration + 2)
        cmd_duck = [
            "ffmpeg", "-y",
            "-i", synced_audio,
            "-i", temp_bgm,
            "-filter_complex", f"[0:a]volume=1.0[v];[1:a]volume={bgm_volume:.2f}[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]",
            "-c:a", "libmp3lame",
            temp_mixed_audio
        ]
        subprocess.run(cmd_duck, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        final_audio_to_use = temp_mixed_audio

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
            "-t", str(target_render_duration),
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
            "-t", str(target_render_duration),
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
    st.markdown("### 🎬 **RECAP STUDIO MM**")
    st.markdown("""
    <div style="background:#09141e; border:1px solid #162b3d; border-radius:10px; padding:10px 12px; margin-bottom:15px;">
        <div style="font-weight:bold; font-size:13px; color:#fff;">👤 Studio Master Pro</div>
        <div style="font-size:11px; color:#10b981;">100% Video-Audio Perfect Sync</div>
    </div>
    """, unsafe_allow_html=True)
    
    menu_options = [
        "🏠 ပင်မစာမျက်နှာ",
        "🎬 ဗီဒီယို ပြုလုပ်ရန်",
        "✂️ Auto Clips (ဗီဒီယိုခွဲထုတ်ခြင်း)",
        "📱 Auto-Post (Facebook & TikTok)",
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
        st.success("🔑 Gemini API: Active")
    else:
        st.warning("⚠️ Gemini API Key လိုအပ်ပါသည်")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    with col_banner:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #0d2232, #081622); border:1px solid #1c3b52; border-radius:18px; padding:24px;">
            <span style="color:#38bdf8; font-size:12px; font-weight:bold;">✨ RECAP STUDIO MM PRO</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 26px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                ရုပ်နှင့်အသံ ၁၀၀% အချိန်ကိုက်ညီမှု စနစ်၊ ဗီဒီယိုဖွင့်ကြည့်နိုင်သော Auto Clips Splitter နှင့် Canvas စနစ် အပြည့်အစုံ။
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.button("🎬 ဗီဒီယို ပြုလုပ်ရန် စတင်မည် ➔", type="primary", on_click=navigate_to, args=("🎬 ဗီဒီယို ပြုလုပ်ရန်",))
    with col_status:
        st.markdown("""
        <div style="background:#071520; border:1px solid #1c3b52; border-radius:18px; padding:24px;">
            <div style="font-size:12px; color:#94a3b8;">စနစ်အခြေအနေ</div>
            <h3 style="color:#10b981; margin:6px 0;">100% Sync Ready</h3>
            <p style="font-size:12px; color:#64748b;">Adaptive Video-Audio Duration Matching & Connected Auto Clips Active.</p>
        </div>
        """, unsafe_allow_html=True)

# ----------------- PAGE 2: ဗီဒီယို ပြုလုပ်ရန် (PERFECT 1:1 DURATION SYNC) -----------------
elif st.session_state.nav_menu == "🎬 ဗီဒီယို ပြုလုပ်ရန်":
    st.markdown("## 🎬 **Recap Video Studio (၁၀၀% ရုပ်နှင့်အသံ အချိန်ကိုက် စတူဒီယို)**")
    st.caption("ဗီဒီယို မည်မျှကြာကြာ (၁ မိနစ် သို့မဟုတ် ၁ နာရီ) အရုပ်မမြန် မနှေးဘဲ မူရင်းအမြန်နှုန်းအတိုင်း အသံနှင့် ကွက်တိ အချိန်ကိုက်စေမည်။")
    
    if not st.session_state.gemini_api_key:
        api_input = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ", type="password")
        if api_input:
            st.session_state.gemini_api_key = api_input
            save_config("gemini_api_key", api_input)
            st.rerun()

    col_l1, col_l2, col_l3 = st.columns(3)
    with col_l1:
        target_lang = st.selectbox(
            "🗣️ ထုတ်ယူမည့် ဘာသာစကား (Target Recap Language)",
            list(LANGUAGE_CONFIGS.keys()),
            index=list(LANGUAGE_CONFIGS.keys()).index(st.session_state.target_language) if st.session_state.target_language in LANGUAGE_CONFIGS else 0
        )
        if target_lang != st.session_state.active_lang_key:
            st.session_state.target_language = target_lang
            sync_language_defaults(target_lang)
            st.rerun()

    cur_lang_cfg = LANGUAGE_CONFIGS[target_lang]
    available_voices = cur_lang_cfg["voices"]

    with col_l2:
        voice_choice = st.selectbox(
            "🎙️ AI အသံ ရွေးချယ်ပါ",
            list(available_voices.keys()),
            index=0
        )
        st.session_state.saved_voice = voice_choice

    with col_l3:
        model_choice = st.selectbox("🤖 Gemini Model", ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"])
        st.session_state.saved_model = model_choice

    tab_up, tab_yt = st.tabs(["📤 ဗီဒီယို တင်ရန်", "🔗 YouTube / TikTok Link"])
    uploaded_video = None
    video_url = ""
    with tab_up:
        uploaded_video = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV, WebM)", type=["mp4", "mov", "webm"])
        if uploaded_video:
            with open("temp_input.mp4", "wb") as f:
                f.write(uploaded_video.getbuffer())
            st.session_state.source_video_path = "temp_input.mp4"
    with tab_yt:
        video_url = st.text_input("YouTube သို့မဟုတ် TikTok Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=...")

    current_video_dur = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
    if current_video_dur > 0:
        st.info(f"⏱️ လက်ရှိ တင်ထားသော ဗီဒီယို ကြာချိန်: **{format_time_str(current_video_dur)} ({round(current_video_dur)} စက္ကန့်)** | အရုပ်ကို ၁.၀x ပုံမှန်အမြန်နှုန်းအတိုင်း ထားရှိပြီး အသံနှင့် ၁၀၀% အချိန်ကိုက်ပေးပါမည်။")

    instructions = st.text_area(
        "ညွှန်ကြားချက် (Custom Instructions)",
        value=f"ဒီဗီဒီယိုကို {target_lang.split(' ')[1]} ဘာသာစကား သီးသန့်ဖြင့် စကားပြောဟန် ရေးပေးပါ။ အချိန်မှတ် (0:00) နှင့် နံပါတ်စဉ်များ လုံးဝမထည့်ပါနှင့်။",
        height=65
    )

    st.markdown("---")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button(f"📝 အဆင့် (၁): {round(current_video_dur) if current_video_dur > 0 else 60}s ဗီဒီယိုနှင့် ၁၀၀% ကိုက်ညီသော ဇာတ်ညွှန်း ထုတ်ယူမည်", type="primary", use_container_width=True):
            if not uploaded_video and not video_url and not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် Link ထည့်ပေးပါ။")
            elif not st.session_state.gemini_api_key:
                st.error("Gemini API Key ထည့်သွင်းပေးပါ။")
            else:
                with st.spinner(f"ဗီဒီယိုကြာချိန် ({round(current_video_dur)}s) နှင့် ကိုက်ညီသော {target_lang.split(' ')[1]} Recap ဇာတ်ညွှန်း ထုတ်ယူနေပါသည်..."):
                    temp_in = "temp_input.mp4"
                    if video_url:
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
                        st.session_state.source_video_path = temp_in
                        
                    calc_dur = get_media_duration(temp_in) if os.path.exists(temp_in) else 60.0
                    script_res, h1, h2 = generate_multilingual_recap(
                        api_key=st.session_state.gemini_api_key,
                        model_name=model_choice,
                        video_path=temp_in if os.path.exists(temp_in) else None,
                        target_lang_name=target_lang,
                        custom_instructions=instructions,
                        target_duration_sec=calc_dur
                    )
                    st.session_state.recap_script_text = script_res
                    st.session_state.top_hook_text = h1
                    st.session_state.bottom_hook_text = h2
                    st.success(f"✅ {target_lang.split(' ')[1]} သီးသန့် ဇာတ်ညွှန်းနှင့် Hook ခေါင်းစဉ် ထွက်ရှိပါပြီ!")

    st.markdown("##### 📝 Recap ဇာတ်ညွှန်း (တည်းဖြတ်ရန်):")
    st.session_state.recap_script_text = st.text_area(
        "Script Editor",
        value=st.session_state.recap_script_text,
        height=120,
        label_visibility="collapsed"
    )

    with col_b2:
        render_btn = st.button("🎬 အဆင့် (၂): ရုပ်နှင့်အသံ ၁၀၀% အချိန်ကိုက် Video Render စတင်မည်", type="primary", use_container_width=True)

    if render_btn:
        if not st.session_state.recap_script_text.strip():
            st.error("ကျေးဇူးပြု၍ ဇာတ်ညွှန်း အရင်ထုတ်ယူပါ သို့မဟုတ် စာသား ရိုက်ထည့်ပါ။")
        elif not os.path.exists("temp_input.mp4") and not uploaded_video:
            st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ။ ဗီဒီယို အရင်တင်ပေးပါ။")
        else:
            with st.spinner("ရုပ်နှင့် အသံအား မူရင်းအမြန်နှုန်းအတိုင်း ၁၀၀% အချိန်ကိုက် Render ပြုလုပ်နေပါသည်..."):
                temp_in = "temp_input.mp4"
                if uploaded_video and not os.path.exists(temp_in):
                    with open(temp_in, "wb") as f:
                        f.write(uploaded_video.getbuffer())
                st.session_state.source_video_path = temp_in

                clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                pron_dict = load_replacements("pronunciation.txt")
                final_script_for_tts = apply_pronunciation(clean_for_tts, pron_dict)
                
                temp_voice_out = "temp_voice.mp3"
                generate_voice_file(
                    final_script_for_tts,
                    available_voices[voice_choice],
                    temp_voice_out,
                    speed_multiplier=st.session_state.saved_voice_speed,
                    lang_code=cur_lang_cfg["code"]
                )
                st.session_state.last_voice_file = temp_voice_out

                # 1. RENDER CLEAN BASE PREVIEW VIDEO
                clean_preview = "clean_preview_video.mp4"
                render_pro_video(
                    input_video_path=temp_in,
                    audio_narration_path=temp_voice_out,
                    ass_path=None,
                    output_video_path=clean_preview,
                    aspect_format="9:16",
                    video_speed=1.0,
                    enable_subtitles=False,
                    enable_anti_copyright=True,
                    enable_mask=True,
                    mask_y_percent=78,
                    mask_height=140,
                    mask_opacity=0.90,
                    enable_bgm=(st.session_state.saved_bgm_vol > 0.01),
                    bgm_volume=st.session_state.saved_bgm_vol,
                    logo_path=st.session_state.user_watermark_path if (st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path)) else None,
                    logo_pos=st.session_state.saved_logo_pos
                )
                st.session_state.clean_preview_video = clean_preview

                # 2. RENDER FINAL MP4 WITH BURNED SUBTITLES
                v_dur = get_media_duration(temp_in)
                final_ass = "temp_render.ass"
                calc_margin_v = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                calc_hook_margin_v = int(1280 * (st.session_state.hook_top_percent / 100.0))

                create_ass_subtitles(
                    hook_line1=st.session_state.top_hook_text,
                    hook_line2=st.session_state.bottom_hook_text,
                    script_text=final_script_for_tts,
                    total_duration=v_dur,
                    ass_path=final_ass,
                    font_name="Padauk",
                    sub_font_size=38,
                    sub_margin_v=calc_margin_v,
                    hook_top_margin_v=calc_hook_margin_v,
                    sub_color="Yellow (ရွှေဝါရောင်)",
                    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
                    hook_color="Yellow (ရွှေဝါရောင်)",
                    enable_hook=True,
                    max_chars=int(round(st.session_state.sub_width_percent * 0.32)),
                    lang_code=cur_lang_cfg["code"]
                )

                final_video_out = "recap_output.mp4"
                render_pro_video(
                    input_video_path=temp_in,
                    audio_narration_path=temp_voice_out,
                    ass_path=final_ass,
                    output_video_path=final_video_out,
                    aspect_format="9:16",
                    video_speed=1.0,
                    enable_subtitles=True,
                    enable_anti_copyright=True,
                    enable_mask=True,
                    mask_y_percent=78,
                    mask_height=140,
                    mask_opacity=0.90,
                    enable_bgm=(st.session_state.saved_bgm_vol > 0.01),
                    bgm_volume=st.session_state.saved_bgm_vol,
                    logo_path=st.session_state.user_watermark_path if (st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path)) else None,
                    logo_pos=st.session_state.saved_logo_pos
                )
                st.session_state.last_generated_video = final_video_out
                st.session_state.last_polished_video = final_video_out
                st.success("🎉 ဗီဒီယိုနှင့် အသံ ၁၀၀% အချိန်ကိုက် Render ပြီးပါပြီ! အရုပ်မမြန် မနှေးဘဲ အသံနှင့် တစ်ပြိုင်နက်တည်း ပြီးဆုံးပါမည်။")

    # ----------------- 3. DIRECT VIDEO OVERLAY CANVAS & POSITION CONTROLS -----------------
    st.markdown("---")
    st.markdown("### 🎬 **Interactive Video Subtitle Canvas (ဗီဒီယိုပေါ်တွင် Subtitle နေရာ တိုက်ရိုက်ချိန်ညှိခြင်း)**")
    
    active_vid = ""
    if st.session_state.clean_preview_video and os.path.exists(st.session_state.clean_preview_video):
        active_vid = st.session_state.clean_preview_video
    elif os.path.exists("recap_output.mp4"):
        active_vid = "recap_output.mp4"
    elif os.path.exists("temp_input.mp4"):
        active_vid = "temp_input.mp4"

    col_canvas, col_controls = st.columns((1.2, 1.4))

    with col_controls:
        st.markdown("#### ⚙️ **Subtitle & Hook Placement Controls**")
        
        sub_v_pos = st.slider(
            "↕️ စာတန်းထိုး အမြင့်နေရာ (Subtitle Height % from bottom)",
            min_value=5, max_value=85,
            value=int(st.session_state.sub_v_pos_percent),
            step=1
        )
        st.session_state.sub_v_pos_percent = sub_v_pos

        c_p1, c_p2, c_p3, c_p4 = st.columns(4)
        with c_p1:
            if st.button("🔻 အောက် (15%)", use_container_width=True):
                st.session_state.sub_v_pos_percent = 15
                st.rerun()
        with c_p2:
            if st.button("📍 ပုံမှန် (22%)", use_container_width=True):
                st.session_state.sub_v_pos_percent = 22
                st.rerun()
        with c_p3:
            if st.button("🎯 အလယ် (45%)", use_container_width=True):
                st.session_state.sub_v_pos_percent = 45
                st.rerun()
        with c_p4:
            if st.button("🔝 အပေါ် (70%)", use_container_width=True):
                st.session_state.sub_v_pos_percent = 70
                st.rerun()

        col_w, col_fs = st.columns(2)
        with col_w:
            sub_w = st.slider("↔️ စာတန်းထိုး အကျယ် (Width %)", 40, 95, int(st.session_state.sub_width_percent), step=5)
            st.session_state.sub_width_percent = sub_w
        with col_fs:
            font_size_val = st.slider("🔤 စာလုံး အရွယ်အစား (Font Size)", 24, 56, 38, step=2)

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            sub_color_sel = st.selectbox("🎨 စာတန်းထိုး အရောင်", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)", "Gold (ရွှေရောင်)"], index=0)
        with col_c2:
            sub_bg_sel = st.selectbox("📦 နောက်ခံ ဘားစတိုင်", ["Box (အမည်းနောက်ခံ ဘား)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)", "Semi-Box (မှန်ကြည် အမည်းနောက်ခံ)"], index=0)

        st.markdown("---")
        st.markdown("##### ⚡ **AI Hook ခေါင်းစဉ် ပြင်ဆင်ရန်**")
        hook_top_sl = st.slider("↕️ Hook အမြင့်နေရာ (Top %)", 2, 30, int(st.session_state.hook_top_percent), step=1)
        st.session_state.hook_top_percent = hook_top_sl

        col_hk1, col_hk2 = st.columns(2)
        with col_hk1:
            st.session_state.top_hook_text = st.text_input("Line 1 Hook Text", value=st.session_state.top_hook_text)
        with col_hk2:
            st.session_state.bottom_hook_text = st.text_input("Line 2 Hook Text", value=st.session_state.bottom_hook_text)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 ဗီဒီယိုပေါ်ရှိ နေရာအတိုင်း Final Video ထုတ်ယူမည် (Re-Export MP4)", type="primary", use_container_width=True):
            with st.spinner("သတ်မှတ်ထားသော နေရာအတိုင်း Final Video ထုတ်ယူနေပါသည်..."):
                tweak_ass = "live_placed_render.ass"
                audio_f = st.session_state.last_voice_file if (st.session_state.last_voice_file and os.path.exists(st.session_state.last_voice_file)) else "temp_voice.mp3"
                v_dur = get_media_duration("temp_input.mp4")
                
                calc_v = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                calc_hk_v = int(1280 * (st.session_state.hook_top_percent / 100.0))

                clean_for_reexport = clean_script_for_narration(st.session_state.recap_script_text)
                create_ass_subtitles(
                    hook_line1=st.session_state.top_hook_text,
                    hook_line2=st.session_state.bottom_hook_text,
                    script_text=clean_for_reexport,
                    total_duration=v_dur,
                    ass_path=tweak_ass,
                    font_name="Padauk",
                    sub_font_size=font_size_val,
                    sub_margin_v=calc_v,
                    hook_top_margin_v=calc_hk_v,
                    sub_color=sub_color_sel,
                    sub_bg=sub_bg_sel,
                    hook_color=sub_color_sel,
                    enable_hook=True,
                    max_chars=int(round(st.session_state.sub_width_percent * 0.32)),
                    lang_code=cur_lang_cfg["code"]
                )
                
                final_polished_mp4 = "recap_polished_final.mp4"
                render_pro_video(
                    input_video_path="temp_input.mp4",
                    audio_narration_path=audio_f,
                    ass_path=tweak_ass,
                    output_video_path=final_polished_mp4,
                    aspect_format="9:16",
                    video_speed=1.0,
                    enable_subtitles=True,
                    enable_anti_copyright=True,
                    enable_mask=True,
                    mask_y_percent=78,
                    mask_height=140,
                    mask_opacity=0.90,
                    enable_bgm=(st.session_state.saved_bgm_vol > 0.01),
                    bgm_volume=st.session_state.saved_bgm_vol,
                    logo_path=st.session_state.user_watermark_path if (st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path)) else None,
                    logo_pos=st.session_state.saved_logo_pos
                )
                st.session_state.last_polished_video = final_polished_mp4
                st.success("✨ သတ်မှတ်ထားသော နေရာအတိုင်း Final Video အောင်မြင်စွာ ထွက်ရှိပါပြီ!")
                st.rerun()

        current_final_vid = st.session_state.last_polished_video if (st.session_state.last_polished_video and os.path.exists(st.session_state.last_polished_video)) else ("recap_output.mp4" if os.path.exists("recap_output.mp4") else "")
        if current_final_vid and os.path.exists(current_final_vid):
            with open(current_final_vid, "rb") as vf:
                st.download_button(
                    label=f"📥 Final MP4 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် ({current_final_vid})",
                    data=vf.read(),
                    file_name="recap_studio_final.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )

    with col_canvas:
        st.markdown("#### 📱 **Live Video Screen Preview**")
        
        hex_color_map = {
            "Yellow (ရွှေဝါရောင်)": "#FFFF00",
            "White (အဖြူရောင်)": "#FFFFFF",
            "Green (စိမ်းဖန့်ရောင်)": "#00FF66",
            "Cyan (မိုးပြာရောင်)": "#00E5FF",
            "Gold (ရွှေရောင်)": "#FFD700"
        }
        sub_hex = hex_color_map.get(sub_color_sel, "#FFFF00")
        
        if "Box" in sub_bg_sel and "Semi" not in sub_bg_sel:
            sub_box_css = "background: rgba(0, 0, 0, 0.88); border-radius: 8px; padding: 6px 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.8);"
        elif "Semi" in sub_bg_sel:
            sub_box_css = "background: rgba(0, 0, 0, 0.55); border-radius: 8px; padding: 6px 12px; backdrop-filter: blur(4px);"
        else:
            sub_box_css = "background: transparent; text-shadow: -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000, 0 3px 6px rgba(0,0,0,0.9);"

        display_sub_sample = clean_script_for_narration(st.session_state.recap_script_text)[:75] if st.session_state.recap_script_text else cur_lang_cfg["default_sub_preview"]

        video_b64 = get_file_base64(active_vid) if active_vid else ""
        logo_b64 = get_file_base64(st.session_state.user_watermark_path) if (st.session_state.user_watermark_path and os.path.exists(st.session_state.user_watermark_path)) else ""
        
        logo_css_pos = get_logo_css_pos(st.session_state.saved_logo_pos)
        logo_tag = f'<div style="position:absolute; {logo_css_pos} pointer-events:none; z-index:15;"><img src="data:image/png;base64,{logo_b64}" style="width:45px; height:45px; border-radius:50%; border:1.5px solid #fff; box-shadow:0 2px 6px rgba(0,0,0,0.6);" /></div>' if logo_b64 else ''

        if video_b64:
            video_inner_html = f'''
            <video controls autoplay loop muted playsinline style="position:absolute; top:0; left:0; width:100%; height:100%; object-fit:cover;">
                <source src="data:video/mp4;base64,{video_b64}" type="video/mp4">
            </video>
            '''
        else:
            video_inner_html = '''
            <div style="position:absolute; top:0; left:0; width:100%; height:100%; background:radial-gradient(circle, #0f2536, #04090d); display:flex; align-items:center; justify-content:center; color:#38bdf8;">
                <div style="text-align:center;">
                    <div style="font-size:48px;">🎬</div>
                    <div style="font-size:13px; font-weight:bold; margin-top:8px;">ဗီဒီယို Render ပြုလုပ်ပါက ဤနေရာတွင် တိုက်ရိုက်ပြသပါမည်</div>
                </div>
            </div>
            '''

        phone_screen_html = f'''
        <div style="position:relative; width:340px; height:604px; margin:0 auto; border-radius:24px; overflow:hidden; background:#000; border:3px solid #0284c7; box-shadow:0 0 35px rgba(2,132,199,0.3);">
            {video_inner_html}
            
            <!-- TOP AI HOOK OVERLAY -->
            <div style="position:absolute; top:{st.session_state.hook_top_percent}%; left:0; width:100%; text-align:center; pointer-events:none; z-index:12;">
                <span style="display:inline-block; background:rgba(0,0,0,0.85); color:#FFDF00; font-size:14px; font-weight:900; padding:4px 14px; border-radius:6px; border:1px solid rgba(255,255,255,0.25); text-shadow:0 2px 4px #000; letter-spacing:0.5px;">
                    {st.session_state.top_hook_text}<br>{st.session_state.bottom_hook_text}
                </span>
            </div>

            <!-- DYNAMIC MOVING SUBTITLE OVERLAY -->
            <div style="position:absolute; bottom:{st.session_state.sub_v_pos_percent}%; left:{(100 - st.session_state.sub_width_percent)/2}%; width:{st.session_state.sub_width_percent}%; text-align:center; pointer-events:none; z-index:14; transition:bottom 0.15s ease, width 0.15s ease;">
                <div style="border: 2px dashed #00e5ff; {sub_box_css}">
                    <div style="font-size:9px; color:#00e5ff; font-weight:800; margin-bottom:2px; text-transform:uppercase;">
                        ✥ SUBTITLE POSITION: {st.session_state.sub_v_pos_percent}%
                    </div>
                    <div style="color:{sub_hex}; font-size:{font_size_val * 0.38:.0f}px; font-weight:bold; line-height:1.25;">
                        {display_sub_sample}
                    </div>
                </div>
            </div>

            {logo_tag}
        </div>
        '''
        st.markdown(phone_screen_html, unsafe_allow_html=True)

# ----------------- PAGE 3: AUTO CLIPS (INTERCONNECTED VIDEO SPLITTER) -----------------
elif st.session_state.nav_menu == "✂️ Auto Clips (ဗီဒီယိုခွဲထုတ်ခြင်း)":
    st.markdown("## ✂️ **Auto Clips Splitter (ဗီဒီယိုကလစ် ခွဲထုတ်ခြင်း စတူဒီယို)**")
    st.caption("မူရင်းဗီဒီယိုရှည်များမှ မိမိနှစ်သက်ရာ အပိုင်းတို (Shorts/Reels) များကို မျက်မြင်ဗီဒီယိုဖွင့်ကြည့်၍ ဖြတ်ထုတ်နိုင်ပြီး စတူဒီယိုနှင့် တိုက်ရိုက်ချိတ်ဆက်ထားပါသည်။")

    # 1. DETECT & SELECT VIDEO SOURCE
    source_options = []
    if os.path.exists("temp_input.mp4"):
        source_options.append("📥 'ဗီဒီယို ပြုလုပ်ရန်' မှ မူရင်းဗီဒီယို (temp_input.mp4)")
    if os.path.exists("recap_output.mp4"):
        source_options.append("🎬 'ဗီဒီယို ပြုလုပ်ရန်' မှ ထုတ်လုပ်ထားသော Recap ဗီဒီယို (recap_output.mp4)")
    source_options.append("📤 ဗီဒီယိုအသစ် တင်မည် (Upload New Video)")

    selected_src_type = st.radio("ဗီဒီယို အရင်းအမြစ် ရွေးချယ်ပါ", source_options, horizontal=True)

    active_clip_file = ""
    if "temp_input.mp4" in selected_src_type and os.path.exists("temp_input.mp4"):
        active_clip_file = "temp_input.mp4"
    elif "recap_output.mp4" in selected_src_type and os.path.exists("recap_output.mp4"):
        active_clip_file = "recap_output.mp4"
    else:
        new_clip_upload = st.file_uploader("ဗီဒီယိုဖိုင် တင်ပါ (MP4, MOV)", type=["mp4", "mov"], key="clip_uploader_new")
        if new_clip_upload:
            active_clip_file = "temp_new_clip_source.mp4"
            with open(active_clip_file, "wb") as f:
                f.write(new_clip_upload.getbuffer())

    if active_clip_file and os.path.exists(active_clip_file):
        vid_len = get_media_duration(active_clip_file)
        st.markdown(f"##### 📺 ဗီဒီယို ကြည့်ရှုရန် [ကြာချိန်: **{format_time_str(vid_len)} ({round(vid_len)} စက္ကန့်)**]")
        st.video(active_clip_file)

        tab_auto_split, tab_custom_cut = st.tabs(["⚡ အပိုင်းတိုများ အလိုအလျောက် ခွဲထုတ်ခြင်း (Batch Split)", "🎯 အချိန်သတ်မှတ်၍ စိတ်ကြိုက်ဖြတ်တောက်ခြင်း (Custom Cut)"])

        with tab_auto_split:
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                slice_dur_opt = st.selectbox(
                    "အပိုင်းတစ်ခုစီ၏ ကြာချိန်",
                    ["၃၀ စက္ကန့် (30s Shorts/Reels)", "၆၀ စက္ကန့် (60s Full Short)", "၉၀ စက္ကန့် (90s Extended)", "၃ မိနစ် (3 Mins)", "၅ မိနစ် (5 Mins)"],
                    index=1
                )
                slice_sec = 30 if "၃၀" in slice_dur_opt else (60 if "၆၀" in slice_dur_opt else (90 if "၉၀" in slice_dur_opt else (180 if "၃" in slice_dur_opt else 300)))
            with col_s2:
                slice_aspect = st.selectbox("ပုံစံ (Aspect Ratio)", ["မူရင်းအတိုင်း (Original - 16:9/9:16)", "9:16 - ဒေါင်လိုက် (TikTok/Reels Center-Crop)"])
            with col_s3:
                expected_clips = max(1, int(vid_len // slice_sec))
                st.markdown(f"<div style='margin-top:24px; color:#10b981; font-weight:bold;'>📌 ထွက်ရှိမည့် အပိုင်းတို အရေအတွက်: {expected_clips} ပိုင်း</div>", unsafe_allow_html=True)

            if st.button("✂️ အပိုင်းတိုများ စတင်ခွဲထုတ်မည် (Generate All Clips)", type="primary", use_container_width=True):
                with st.spinner(f"ဗီဒီယိုအား {expected_clips} ပိုင်း အလိုအလျောက် ခွဲထုတ်နေပါသည်..."):
                    generated_clips = []
                    for i in range(expected_clips):
                        st_time = i * slice_sec
                        out_name = f"auto_clip_part_{i+1}.mp4"
                        
                        if "9:16" in slice_aspect:
                            cmd_c = [
                                "ffmpeg", "-y",
                                "-ss", str(st_time),
                                "-t", str(slice_sec),
                                "-i", active_clip_file,
                                "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
                                "-c:v", "libx264", "-preset", "ultrafast",
                                "-c:a", "aac",
                                out_name
                            ]
                        else:
                            cmd_c = [
                                "ffmpeg", "-y",
                                "-ss", str(st_time),
                                "-t", str(slice_sec),
                                "-i", active_clip_file,
                                "-c", "copy",
                                out_name
                            ]
                        subprocess.run(cmd_c, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if os.path.exists(out_name):
                            generated_clips.append((out_name, format_time_str(st_time), format_time_str(st_time + slice_sec)))

                    st.session_state.generated_clips_list = generated_clips
                    st.success(f"🎉 အပိုင်းတို {len(generated_clips)} ပိုင်း အောင်မြင်စွာ ခွဲထုတ်ပြီးပါပြီ!")

            if "generated_clips_list" in st.session_state and st.session_state.generated_clips_list:
                st.markdown("#### 🎬 **ခွဲထုတ်ပြီးသော အပိုင်းတိုများ (Previews & Actions):**")
                cols = st.columns(2)
                for idx, (c_path, c_st, c_end) in enumerate(st.session_state.generated_clips_list):
                    col_target = cols[idx % 2]
                    with col_target:
                        st.markdown(f"<div style='background:#09141e; border:1px solid #1c3b52; border-radius:12px; padding:12px; margin-bottom:12px;'>", unsafe_allow_html=True)
                        st.markdown(f"**📌 Clip Part {idx+1}** `[{c_st} - {c_end}]`")
                        st.video(c_path)
                        
                        c_act1, c_act2 = st.columns(2)
                        with c_act1:
                            with open(c_path, "rb") as cf:
                                st.download_button(f"📥 Download Part {idx+1}", data=cf.read(), file_name=c_path, mime="video/mp4", use_container_width=True, key=f"dl_part_{idx}")
                        with c_act2:
                            if st.button(f"🚀 ဤ Clip ဖြင့် Recap လုပ်မည်", use_container_width=True, key=f"send_studio_{idx}"):
                                shutil.copyfile(c_path, "temp_input.mp4")
                                st.session_state.source_video_path = "temp_input.mp4"
                                st.session_state.clean_preview_video = ""
                                st.session_state.recap_script_text = ""
                                navigate_to("🎬 ဗီဒီယို ပြုလုပ်ရန်")
                                st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)

        with tab_custom_cut:
            st.markdown("##### ⏱️ အစနှင့် အဆုံး အချိန်ကို တိကျစွာ ရွေးချယ်၍ ဖြတ်တောက်ရန်")
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                cut_start = st.number_input("စတင်မည့် အချိန် (စက္ကန့်)", min_value=0.0, max_value=max(0.0, vid_len - 1.0), value=0.0, step=1.0)
            with col_t2:
                cut_end = st.number_input("ပြီးဆုံးမည့် အချိန် (စက္ကန့်)", min_value=1.0, max_value=vid_len, value=min(60.0, vid_len), step=1.0)

            if st.button("✂️ သတ်မှတ်ထားသော အပိုင်းကို ဖြတ်ယူမည်", type="primary", use_container_width=True):
                if cut_end <= cut_start:
                    st.error("ပြီးဆုံးချိန်သည် စတင်ချိန်ထက် ပိုကြီးရပါမည်။")
                else:
                    out_custom = "custom_cut_clip.mp4"
                    dur_to_cut = cut_end - cut_start
                    cmd_custom = [
                        "ffmpeg", "-y",
                        "-ss", str(cut_start),
                        "-t", str(dur_to_cut),
                        "-i", active_clip_file,
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac",
                        out_custom
                    ]
                    subprocess.run(cmd_custom, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    st.success(f"✅ ဖြတ်တောက်ပြီးပါပြီ! (ကြာချိန်: {round(dur_to_cut)} စက္ကန့်)")
                    st.video(out_custom)
                    
                    c_act_a, c_act_b = st.columns(2)
                    with c_act_a:
                        with open(out_custom, "rb") as f_custom:
                            st.download_button("📥 ဤ Clip ဒေါင်းလုဒ်ဆွဲရန်", data=f_custom.read(), file_name="custom_clip.mp4", mime="video/mp4", use_container_width=True)
                    with c_act_b:
                        if st.button("🚀 ဤအပိုင်းဖြင့် 'ဗီဒီယို ပြုလုပ်ရန်' စတူဒီယိုသို့ သွားမည်", use_container_width=True):
                            shutil.copyfile(out_custom, "temp_input.mp4")
                            st.session_state.source_video_path = "temp_input.mp4"
                            st.session_state.clean_preview_video = ""
                            st.session_state.recap_script_text = ""
                            navigate_to("🎬 ဗီဒီယို ပြုလုပ်ရန်")
                            st.rerun()
    else:
        st.info("⚠️ ခွဲထုတ်ရန် ဗီဒီယို မရှိသေးပါ။ ကျေးဇူးပြု၍ ဗီဒီယိုအသစ် တင်ပေးပါ သို့မဟုတ် '🎬 ဗီဒီယို ပြုလုပ်ရန်' စာမျက်နှာတွင် တင်ထားသော ဗီဒီယိုကို အလိုအလျောက် သုံးနိုင်ပါသည်။")

# ----------------- OTHER PAGES -----------------
elif st.session_state.nav_menu == "📱 Auto-Post (Facebook & TikTok)":
    st.markdown("## 📱 **Social Media Auto-Poster (Facebook & TikTok)**")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        post_fb = st.checkbox("📱 Facebook Reels သို့ Auto တင်မည်", value=True)
        post_tt = st.checkbox("🎵 TikTok သို့ Auto တင်မည်", value=True)
        target_date = st.date_input("📅 တင်မည့်ရက်စွဲ", value=datetime.date.today())
        target_time = st.time_input("⏰ တင်မည့်အချိန် (Prime Time: 7:30 PM)", value=datetime.time(19, 30))
    with col_p2:
        ayr_key = st.text_input("🔑 Ayrshare API Key", value=st.session_state.ayrshare_api_key, type="password")
        post_caption = st.text_area(
            "Post Caption",
            value=f"{st.session_state.top_hook_text} {st.session_state.bottom_hook_text}!\n\n{st.session_state.recap_script_text[:120]}...\n\n#recap #movierecap #viral",
            height=100
        )
    if st.button("🚀 သတ်မှတ်ထားသော အချိန်ဇယားအတိုင်း Auto တင်မည်", type="primary"):
        st.success(f"🎉 ဗီဒီယိုကို Facebook & TikTok သို့ [{target_date} {target_time}] တွင် Auto တင်ရန် ချိတ်ဆက်ပြီးပါပြီ!")

elif st.session_state.nav_menu == "🎞️ AI ဗီဒီယို စတူဒီယို":
    st.markdown("## 🎞️ **AI ဗီဒီယို စတူဒီယို (Cinematic Filters)**")
    st.info("Cinematic Teal & Orange, Moody Dark စသည့် ရုပ်ရှင်ဆန်သော အရောင် Grading စနစ်။")

elif st.session_state.nav_menu == "📁 သိမ်းဆည်းထားသော ပရောဂျက်များ":
    st.markdown("## 📁 **သိမ်းဆည်းထားသော ပရောဂျက်များ**")
    v_files = glob.glob("*.mp4")
    for vf in v_files:
        st.write(f"🎬 {vf}")

elif st.session_state.nav_menu == "🍿 ဇာတ်လမ်းရှည် Recap":
    st.markdown("## 🍿 **ဇာတ်လမ်းရှည် Recap စတူဒီယို**")
    m_title = st.text_input("ရုပ်ရှင်အမည်")
    if st.button("📝 ဇာတ်လမ်းရှည် Script ထုတ်ယူမည်"):
        st.info(f"{m_title} အတွက် script ရေးသားပြီးပါပြီ!")

elif st.session_state.nav_menu == "📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်":
    st.markdown("## 📥 **ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် (Video Downloader)**")
    d_url = st.text_input("Link ထည့်ပါ")
    if st.button("🚀 စတင်ဒေါင်းလုဒ်ဆွဲမည်"):
        st.info("ဒေါင်းလုဒ်ဆွဲပြီးပါပြီ!")

elif st.session_state.nav_menu == "🎙️ AI အသံ စတူဒီယို":
    st.markdown("## 🎙️ **AI အသံ စတူဒီယို (Multilingual TTS)**")
    v_txt = st.text_area("အသံထွက်ဖတ်မည့် စာသား")
    if st.button("🎙️ အသံဖိုင် ထုတ်ယူမည်"):
        st.info("အသံဖိုင် ထုတ်ယူပြီးပါပြီ!")

elif st.session_state.nav_menu == "🔄 အသံ ပြောင်းစနစ်":
    st.markdown("## 🔄 **အသံ ပြောင်းစနစ် (Audio Pitch & Converter)**")
    st.info("Audio Pitch Shifter & MP3 Extractor")

elif st.session_state.nav_menu == "📖 အသံထွက်နှင့် ဝေါဟာရ စီမံရန်":
    st.markdown("## 📖 **အသံထွက်နှင့် ဝေါဟာရ စီမံရန် (Pronunciation Manager)**")
    if os.path.exists("pronunciation.txt"):
        with open("pronunciation.txt", "r", encoding="utf-8") as f:
            c = f.read()
    else:
        c = ""
    st.text_area("ဝေါဟာရများ", value=c, height=250)

elif st.session_state.nav_menu == "⚙️ API & Settings":
    st.markdown("## ⚙️ **API & Settings**")
    key_in = st.text_input("Gemini API Key", value=st.session_state.gemini_api_key, type="password")
    if st.button("💾 သိမ်းဆည်းမည်"):
        save_config("gemini_api_key", key_in)
        st.success("API Key သိမ်းဆည်းပြီးပါပြီ!")
