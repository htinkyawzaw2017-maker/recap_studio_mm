import streamlit as st
import os
import re
import time
import json
import glob
import textwrap
import subprocess
import urllib.request
import asyncio
from PIL import Image, ImageDraw, ImageFont

# Ensures Streamlit config allows up to 1024 MB (1 GB) upload limit
os.makedirs(".streamlit", exist_ok=True)
config_toml_path = os.path.join(".streamlit", "config.toml")
try:
    with open(config_toml_path, "w", encoding="utf-8") as cfg_f:
        cfg_f.write("[server]\nmaxUploadSize = 1024\nenableXsrfProtection = false\n")
except Exception:
    pass

st.set_page_config(
    page_title="Recap Studio MM Pro - Master Suite",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Plus+Jakarta+Sans:wght@400;600;700&display=swap');

    .stApp {
        background: radial-gradient(circle at 15% 15%, #071026 0%, #030712 60%, #02040a 100%);
        color: #f1f5f9;
        font-family: 'Plus Jakarta Sans', 'Pyidaungsu', sans-serif;
    }

    /* Neon Animations */
    @keyframes neonPulse {
        0% { box-shadow: 0 0 10px rgba(0, 242, 254, 0.25), 0 0 20px rgba(0, 242, 254, 0.15); border-color: rgba(0, 242, 254, 0.6); }
        50% { box-shadow: 0 0 25px rgba(0, 242, 254, 0.45), 0 0 40px rgba(56, 189, 248, 0.25); border-color: rgba(56, 189, 248, 0.9); }
        100% { box-shadow: 0 0 10px rgba(0, 242, 254, 0.25), 0 0 20px rgba(0, 242, 254, 0.15); border-color: rgba(0, 242, 254, 0.6); }
    }

    @keyframes glowBorder {
        0% { border-color: #00f2fe; }
        50% { border-color: #a855f7; }
        100% { border-color: #00f2fe; }
    }

    /* Cyber Card Styles */
    .neo-card {
        background: linear-gradient(135deg, rgba(13, 24, 48, 0.85) 0%, rgba(5, 12, 26, 0.95) 100%);
        border: 1.5px solid rgba(0, 242, 254, 0.35);
        border-radius: 16px;
        padding: 20px 24px;
        margin-bottom: 20px;
        position: relative;
        backdrop-filter: blur(14px);
        transition: all 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
        overflow: hidden;
    }

    .neo-card:hover {
        transform: translateY(-5px);
        border-color: #00f2fe;
        box-shadow: 0 12px 35px rgba(0, 242, 254, 0.25), 0 0 15px rgba(0, 242, 254, 0.3);
    }

    .neo-card-accent {
        background: linear-gradient(135deg, rgba(18, 14, 42, 0.88) 0%, rgba(9, 6, 25, 0.96) 100%);
        border: 1.5px solid rgba(168, 85, 247, 0.4);
        border-radius: 16px;
        padding: 20px 24px;
        margin-bottom: 20px;
        transition: all 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    .neo-card-accent:hover {
        transform: translateY(-5px);
        border-color: #a855f7;
        box-shadow: 0 12px 35px rgba(168, 85, 247, 0.25), 0 0 15px rgba(168, 85, 247, 0.3);
    }

    /* Neon Badge */
    .badge-sync {
        background: rgba(0, 242, 254, 0.12);
        color: #00f2fe;
        border: 1px solid #00f2fe;
        padding: 5px 14px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 1px;
        display: inline-block;
        box-shadow: 0 0 10px rgba(0, 242, 254, 0.2);
    }

    .badge-purple {
        background: rgba(168, 85, 247, 0.15);
        color: #c084fc;
        border: 1px solid #a855f7;
        padding: 5px 14px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 1px;
        display: inline-block;
        box-shadow: 0 0 10px rgba(168, 85, 247, 0.2);
    }

    /* Main Title Styler */
    .hero-title {
        font-family: 'Orbitron', 'Plus Jakarta Sans', sans-serif;
        background: linear-gradient(90deg, #00f2fe, #38bdf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900;
        letter-spacing: 1px;
        margin: 0;
    }

    /* Streamlit Widget Polishing */
    div[data-testid="stFileUploader"] {
        background: rgba(8, 17, 36, 0.6);
        border: 1.5px dashed rgba(0, 242, 254, 0.35);
        border-radius: 12px;
        padding: 10px;
        transition: all 0.3s ease;
    }
    div[data-testid="stFileUploader"]:hover {
        border-color: #00f2fe;
        box-shadow: 0 0 15px rgba(0, 242, 254, 0.2);
    }
    .stButton>button {
        border-radius: 12px !important;
        font-weight: 700 !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 242, 254, 0.35) !important;
    }
</style>
""", unsafe_allow_html=True)

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
        if not os.path.exists(fname) or os.path.getsize(fname) < 40000:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp, open(fname, "wb") as out_f:
                    out_f.write(resp.read())
            except Exception:
                pass

ensure_myanmar_fonts()

CONFIG_FILE = ".recap_config.json"

def load_config(key, default=""):
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get(key, default)
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
        return float(json.loads(res.stdout)["format"]["duration"])
    except Exception:
        return 0.0

def format_time_str(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

PHONETICS = {
    r"\bAI\b": "အေအိုင်",
    r"\bFBI\b": "အက်ဖ်ဘီအိုင်",
    r"\bCIA\b": "စီအိုင်အေ",
    r"\bVIP\b": "ဗွီအိုင်ပီ",
    r"\bDoctor\b": "ဒေါက်တာ",
    r"\bPolice\b": "ရဲတွေ",
    r"\bTikTok\b": "တစ်တော့ခ်",
    r"\bFacebook\b": "ဖေ့စ်ဘွတ်ခ်",
    r"\bYouTube\b": "ယူကျုဘ်",
    r"\bSubscribe\b": "စဘ်စခရိုက်ဘ်",
    r"\bLike\b": "လိုက်ခ်",
    r"\bBoss\b": "သူဌေးကြီး",
    r"\bCar\b": "ကား",
    r"\bPhone\b": "ဖုန်း",
    r"\bMoney\b": "ပိုက်ဆံ"
}

def clean_script_for_tts(text):
    """
    Cleans script and normalizes punctuation for fluid human speech
    without robotic dead-silences or abrupt chopped words.
    """
    if not text:
        return ""
    # Remove timestamps and line enumerations
    t = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?", "", text)
    t = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", t)
    t = re.sub(r"[\(\[（【].*?[\)\]）】]", "", t)
    t = re.sub(r"[*#_~>`]", "", t)

    # Phonetic replacements for English words commonly in viral recaps
    for pattern, rep in PHONETICS.items():
        t = re.sub(pattern, rep, t, flags=re.IGNORECASE)

    # Convert duplicate Burmese punctuation to single soft breath pause
    t = re.sub(r"[၊,]+", " ၊ ", t)
    t = re.sub(r"[။\.\!\?]+", " ။ ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def process_user_logo(input_path, output_path):
    try:
        img = Image.open(input_path).convert("RGBA")
        # Direct RGBA pixel modification compatible with all Pillow versions
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

if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))

if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = "အံ့ဩဖွယ် လက်တွေ့စမ်းသပ်မှု"

if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = "ထွက်ပေါ်လာသည့် ရလဒ်"

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = ""

if "sub_v_pos_percent" not in st.session_state:
    st.session_state.sub_v_pos_percent = 20

if "hook_top_percent" not in st.session_state:
    st.session_state.hook_top_percent = 8

if "sub_font_size" not in st.session_state:
    st.session_state.sub_font_size = 40

if "sub_color_hex" not in st.session_state:
    st.session_state.sub_color_hex = "#FFDF00"

if "sub_bg_style" not in st.session_state:
    st.session_state.sub_bg_style = "Solid Box (အမည်းနောက်ခံ)"

if "enable_subtitles" not in st.session_state:
    st.session_state.enable_subtitles = True

if "cta_type" not in st.session_state:
    st.session_state.cta_type = "👍 Like & 🔔 Subscribe လုပ်ထားပါ ခင်ဗျာ"

if "user_watermark_file" not in st.session_state:
    st.session_state.user_watermark_file = ""

if "last_rendered_video" not in st.session_state:
    st.session_state.last_rendered_video = "recap_output.mp4" if os.path.exists("recap_output.mp4") else ""

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.08

# Optimized vocal rates for natural, continuous, broadcast-level recap narrations
VOICE_CONFIGS = {
    "မင်းသန့် (Agency - Confident Narrator - သွက်လက်တက်ကြွ)": {"voice": "my-MM-ThihaNeural", "pitch": "-1Hz", "rate": "+12%"},
    "သီဟ (Action & Dynamic Voice - အလွန်သွက်လက်)": {"voice": "my-MM-ThihaNeural", "pitch": "+1Hz", "rate": "+14%"},
    "ကိုမင်း (Deep Cinematic Specialist - အသံနက်ကြီး)": {"voice": "my-MM-ThihaNeural", "pitch": "-4Hz", "rate": "+8%"},
    "မေသူ (Drama & Mystery Female - စိတ်ခံစားမှုအပြည့်)": {"voice": "my-MM-NilarNeural", "pitch": "+1Hz", "rate": "+8%"}
}

RECAP_MODES = {
    "🔍 Auto-Detect (ဗီဒီယိုထဲပါသည့်အတိုင်း အလိုအလျောက် သုံးသပ်မည်)": "auto",
    "🔬 Science, Test & Experiment (စမ်းသပ်မှုနှင့် သိပ္ပံ / ဗဟုသုတ)": "experiment",
    "🛠️ Silent Craft & DIY (အသံမဲ့ လက်မှုပညာနှင့် ပြုပြင်ရေး)": "craft",
    "🎬 Movie & Fiction Recap (ရုပ်ရှင်နှင့် ဇာတ်လမ်းတွဲများ)": "movie"
}

def generate_vision_matched_script(raw_api_keys, video_path, target_duration, mode_key="auto"):
    """
    Multimodal Vision AI that calculates natural Burmese syllable cadence
    and supports both modern google-genai and legacy google-generativeai SDKs.
    """
    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_keys) if k.strip()]
    if not keys:
        raise ValueError("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။")

    # Natural Burmese recap pace: ~2.8 to 3.2 syllables/words per second for fluid speech
    target_words = max(26, int(target_duration * 2.85))

    mode_prompts = {
        "auto": "တင်ထားသော ဗီဒီယိုဖိုင်ကို သေချာကြည့်ပါ။ ဤဗီဒီယိုသည် စမ်းသပ်မှု၊ လက်မှုပညာ သို့မဟုတ် ရုပ်ရှင်ဇာတ်လမ်း ဖြစ်စေ မျက်မြင်အစစ်အမှန် ဖြစ်ပျက်နေသော အကြောင်းအရာကိုသာ အသေးစိတ် မပြတ်မတောက် ရှင်းပြပေးပါ။",
        "experiment": "တင်ထားသော ဗီဒီယိုဖိုင်ကို သေချာကြည့်ပါ။ ဤဗီဒီယိုသည် သိပ္ပံ/လက်တွေ့ စမ်းသပ်မှု ဖြစ်သည်။ စမ်းသပ်မှု လုပ်ဆောင်ပုံ၊ အဆင့်ဆင့် ဖြစ်ပျက်ပုံနှင့် နောက်ဆုံး ရလဒ်ထွက်ပေါ်လာပုံကို မျက်မြင်အစစ်အမှန်အတိုင်း အချက်အလက်တိကျစွာ ရှင်းပြပေးပါ။",
        "craft": "တင်ထားသော ဗီဒီယိုဖိုင်ကို သေချာကြည့်ပါ။ ဤဗီဒီယိုသည် အသံမပါသော လက်မှုပညာ/DIY ဗီဒီယို ဖြစ်သည်။ လက်ဖြင့် အဆင့်ဆင့် ပြုလုပ်နေပုံများကို အနီးကပ် လိုက်လံရှင်းပြပေးပါ။",
        "movie": "တင်ထားသော ရုပ်ရှင်ဗီဒီယိုကို ကြည့်ပြီး ဇာတ်ကွက်အလိုက် စိတ်လှုပ်ရှားဖွယ် Movie Recap အဖြစ် ပြန်လည်ပြောပြပေးပါ။"
    }

    prompt = f"""
{mode_prompts.get(mode_key, mode_prompts['auto'])}

🛑 အလွန်အရေးကြီးသော သဘာဝကျ စကားပြောစည်းကမ်းချက်များ:
၁။ ပေးပို့ထားသော ဗီဒီယိုကို အစမှ အဆုံး သေချာကြည့်ရှုပြီး အမှန်တကယ် ပါဝင်သော ပုံရိပ်များနှင့် အဆင့်ဆင့် ဖြစ်ရပ်များကိုသာ အတိအကျ ရေးသားရပါမည်။
၂။ ဗီဒီယို စုစုပေါင်း ကြာချိန်သည် အတိအကျ {target_duration:.1f} စက္ကန့် ဖြစ်သည်။
၃။ အသံဖတ်ကြားရာတွင် စကားလုံး မပြတ်မတောက်ဘဲ ချောမောသွက်လက်စွာ စီးဆင်းစေရန် "ပြီးတဲ့အခါမှာတော့"၊ "ရုတ်တရက်ဆိုသလို"၊ "ဆက်လက်ပြီးတော့"၊ "နောက်ဆုံးမှာတော့" စသည့် ဆက်စပ်စကားလုံးများ သဘာဝကျကျ အသုံးပြုပါ။
၄။ ဗီဒီယိုကြာချိန်နှင့် အတိအကျ ကိုက်ညီပြည့်မီစေရန် မြန်မာစကားလုံး အရေအတွက် {target_words - 4} မှ {target_words + 6} လုံးခန့် အသေးစိတ် ရေးပေးရပါမည်။ စာသားတိုလွန်း၍ စောပြီးသွားခြင်း လုံးဝ မဖြစ်ရပါ။
၅။ မြန်မာစကားပြော အသုံးအနှုန်း သီးသန့် ဖြစ်ရပါမည်။ အင်္ဂလိပ်စာလုံး လုံးဝမထည့်ပါနှင့်။
၆။ အောက်ပါ JSON Format သီးသန့်ဖြင့်သာ ပြန်ဖြေပါ:
{{
  "hook_line1": "ဗီဒီယိုနှင့် ကိုက်ညီသော ခေါင်းစဉ် ၁ (စကားလုံး ၃-၄ လုံး)",
  "hook_line2": "ဗီဒီယိုနှင့် ကိုက်ညီသော ခေါင်းစဉ် ၂ (စကားလုံး ၃-၄ လုံး)",
  "script": "ဗီဒီယိုထဲတွင် မြင်တွေ့ရသည့်အတိုင်း သဘာဝကျကျ မပြတ်မတောက် အသေးစိတ် မြန်မာစကားပြော ရှင်းလင်းချက်..."
}}
"""
    last_err = None

    # Check whether google-genai (new) or google.generativeai (legacy) is available
    use_new_sdk = False
    try:
        from google import genai
        use_new_sdk = True
    except ImportError:
        try:
            import google.generativeai as legacy_genai
            use_new_sdk = False
        except ImportError:
            raise ImportError("Google Gemini SDK မရှိသေးပါ။ ကျေးဇူးပြု၍ pip install google-genai သို့မဟုတ် pip install google-generativeai ပြုလုပ်ပေးပါ ခင်ဗျာ။")

    for k_idx, current_key in enumerate(keys):
        try:
            if use_new_sdk:
                from google import genai
                client = genai.Client(api_key=current_key)
                contents = []
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယိုအား AI မျက်စိဖြင့် လေ့လာနိုင်ရန် Gemini Vision API သို့ ပေးပို့နေပါသည်..."):
                        video_file = client.files.upload(file=video_path)
                        waits = 0
                        while getattr(video_file, "state", None) == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file = client.files.get(name=video_file.name)
                        contents.append(video_file)

                contents.append(prompt)
                res = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents
                )
                raw_resp = res.text.strip()
            else:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=current_key)
                video_file_obj = None
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယိုအား AI မျက်စိဖြင့် လေ့လာနိုင်ရန် Gemini Vision API သို့ ပေးပို့နေပါသည်..."):
                        video_file_obj = legacy_genai.upload_file(path=video_path)
                        waits = 0
                        while video_file_obj.state.name == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file_obj = legacy_genai.get_file(video_file_obj.name)
                        if video_file_obj.state.name != "ACTIVE":
                            video_file_obj = None

                model = legacy_genai.GenerativeModel("gemini-2.5-flash")
                if video_file_obj:
                    res = model.generate_content([video_file_obj, prompt])
                else:
                    res = model.generate_content(prompt)
                raw_resp = res.text.strip()

            match = re.search(r"\{.*\}", raw_resp, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data["script"], data["hook_line1"], data["hook_line2"]

            clean_lines = [l.strip() for l in raw_resp.split("\n") if l.strip() and not l.startswith("```")]
            h1 = clean_lines[0][:30] if clean_lines else "ထူးဆန်းသော စမ်းသပ်မှု"
            h2 = clean_lines[1][:30] if len(clean_lines) > 1 else "တွေ့ရှိချက်"
            s = " ".join(clean_lines[2:]) if len(clean_lines) > 2 else raw_resp
            return s, h1, h2

        except Exception as e:
            last_err = e
            if "429" in str(e).lower() or "quota" in str(e).lower():
                st.warning(f"⚠️ API Key (#{k_idx+1}) Limit ပြည့်သွားသဖြင့် နောက် Key သို့ ကူးပြောင်းနေပါသည်...")
                continue
            continue

    raise Exception(f"API Error: {last_err}")

def generate_natural_voice(text, voice_cfg, target_video_duration, final_output_path):
    """
    Renders high quality natural human cadence without robotic vocal breaks or pitch wobbles.
    Synchronizes tightly with target video duration.
    """
    cleaned = clean_script_for_tts(text)
    temp_raw = "temp_raw_unconformed.mp3"

    import edge_tts
    communicate = edge_tts.Communicate(
        text=cleaned,
        voice=voice_cfg["voice"],
        rate=voice_cfg["rate"],
        pitch=voice_cfg["pitch"]
    )
    asyncio.run(communicate.save(temp_raw))

    raw_dur = get_media_duration(temp_raw)
    if raw_dur <= 0.1 or target_video_duration <= 0.1:
        import shutil
        shutil.copyfile(temp_raw, final_output_path)
        return

    tempo = raw_dur / target_video_duration

    # If narration is slightly shorter, preserve human voice and pad end smoothly (no unnatural slow-motion)
    if tempo < 0.98:
        pad_dur = max(0.1, target_video_duration - raw_dur)
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_raw,
            "-af", f"apad=pad_dur={pad_dur:.3f}",
            "-t", f"{target_video_duration:.3f}",
            "-c:a", "libmp3lame", "-b:a", "192k",
            final_output_path
        ]
    elif 0.98 <= tempo <= 1.20:
        # Micro-tempo adjustment within natural vocal tolerance
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_raw,
            "-filter:a", f"atempo={tempo:.3f}",
            "-t", f"{target_video_duration:.3f}",
            "-c:a", "libmp3lame", "-b:a", "192k",
            final_output_path
        ]
    else:
        # Dual-stage atempo for high tempo preservation
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_raw,
            "-filter:a", "atempo=1.15",
            "-t", f"{target_video_duration:.3f}",
            "-c:a", "libmp3lame", "-b:a", "192k",
            final_output_path
        ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def hex_to_ass(hex_code):
    h = hex_code.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H0000FFFF&"

def create_clean_ass_subtitles(h1, h2, script, duration, ass_path, font_size, v_margin, hex_color, bg_style, cta_text):
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
        b_style, outline, shadow, back_c = "3", "1", "0", "&H40000000"
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
Style: HookStyle,Pyidaungsu,44,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,{int(1280 * (st.session_state.hook_top_percent / 100.0))},1
Style: CTAStyle,Pyidaungsu,36,&H00FFFFFF,&H000000FF,&H00000000,&H200000CC,-1,0,0,0,100,100,0,0,3,2,0,2,20,20,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if h1 or h2:
        hook_str = f"{h1}\\N{h2}" if h1 and h2 else (h1 or h2)
        ass_text += f"Dialogue: 1,0:00:00.00,{fmt_ass_time(duration)},HookStyle,,0,0,0,,{hook_str}\n"

    # Chunk by punctuation pauses and allocate duration based on character length for tight lip sync
    raw_chunks = [s.strip() for s in re.split(r"[၊။\.\?\!\n]+", script) if s.strip()]
    if not raw_chunks:
        raw_chunks = [script]

    total_chars = sum(len(c) for c in raw_chunks)
    total_chars = max(1, total_chars)
    current_time = 0.0

    for chunk in raw_chunks:
        c_dur = (len(chunk) / total_chars) * duration
        c_st = current_time
        c_en = min(c_st + c_dur, duration)
        current_time = c_en
        ass_text += f"Dialogue: 0,{fmt_ass_time(c_st)},{fmt_ass_time(c_en)},SubtitleStyle,,0,0,0,,{chunk}\n"

    if cta_text and duration > 5.0:
        ass_text += f"Dialogue: 2,{fmt_ass_time(duration - 5.0)},{fmt_ass_time(duration)},CTAStyle,,0,0,0,,{cta_text}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

def render_strict_sync_video(input_video, narration_audio, ass_path, output_video, logo_path=None, logo_pos="top_right", bgm_vol=0.08):
    exact_duration = get_media_duration(input_video)
    if exact_duration <= 0.0:
        exact_duration = 33.0

    bgm_path = "temp_bgm.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"aevalsrc=sin(86*2*PI*t)*0.02+sin(126*2*PI*t)*0.01:d={exact_duration}",
        "-c:a", "libmp3lame", bgm_path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    vf_filters = [
        "scale=720:1280:force_original_aspect_ratio=increase",
        "crop=720:1280",
        "setpts=PTS-STARTPTS",
        "eq=contrast=1.03:brightness=0.01:saturation=1.04"
    ]
    if ass_path and os.path.exists(ass_path):
        vf_filters.append(f"subtitles={ass_path}:fontsdir=.")

    pos_map = {
        "top_right": "main_w-overlay_w-24:24",
        "top_left": "24:24",
        "bottom_right": "main_w-overlay_w-24:main_h-overlay_h-24",
        "bottom_left": "24:main_h-overlay_h-24"
    }

    if logo_path and os.path.exists(logo_path):
        overlay_coords = pos_map.get(logo_pos, "main_w-overlay_w-24:24")
        filter_complex = (
            f"[0:v]{','.join(vf_filters)}[vbase];"
            f"[3:v]scale=120:-1,format=rgba[logo];"
            f"[vbase][logo]overlay={overlay_coords}[vfinal];"
            f"[1:a]volume=1.0[voice];[2:a]volume={bgm_vol:.2f}[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[afinal]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video,
            "-i", narration_audio,
            "-i", bgm_path,
            "-i", logo_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]
    else:
        filter_complex = (
            f"[0:v]{','.join(vf_filters)}[vfinal];"
            f"[1:a]volume=1.0[voice];[2:a]volume={bgm_vol:.2f}[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[afinal]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video,
            "-i", narration_audio,
            "-i", bgm_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 10px 0 16px 0;">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #00f2fe; margin-bottom: 4px; font-weight: 800;">⚡ RECAP MASTER</h2>
        <span class="badge-sync">MAX 1 GB LOCKED</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### 🔑 **Gemini API Key**")
    current_key_val = st.text_area(
        "API Key (ကော်မာခံ၍ အပိုထည့်နိုင်သည်)",
        value=st.session_state.gemini_api_key,
        placeholder="AIzaSy..., AIzaSy...",
        height=70,
        label_visibility="collapsed"
    )
    if current_key_val != st.session_state.gemini_api_key:
        st.session_state.gemini_api_key = current_key_val
        save_config("gemini_api_key", current_key_val)
        st.success("✅ API Key သိမ်းဆည်းပြီးပါပြီ!")

    st.markdown("---")
    voice_sel = st.selectbox("🎙️ Narrator Voice (ဇာတ်လမ်းပြောသံ)", list(VOICE_CONFIGS.keys()), index=0)
    bgm_val = st.slider("🎵 Background Music Volume", 0.0, 0.25, float(st.session_state.saved_bgm_vol), 0.02)
    st.session_state.saved_bgm_vol = bgm_val

tab_recap, tab_splitter, tab_settings = st.tabs([
    "🎬 All-in-One Recap Studio",
    "🍿 Multi-Part Splitter (1 GB Support)",
    "⚙️ Settings & Info"
])

# ==============================================================================
# TAB 1: ALL-IN-ONE RECAP STUDIO (UNIFIED WORKFLOW)
# ==============================================================================
with tab_recap:
    st.markdown("""
    <div class="neo-card" style="animation: neonPulse 4s infinite alternate;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <h2 class="hero-title" style="font-size: 24px;">🎬 All-in-One Viral Recap Studio Pro</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 6px; margin-bottom: 0;">
                    မပြတ်မတောက်ဘဲ သဘာဝကျသော လူအစစ် စကားပြောသံဖြင့် ဗီဒီယိုနှင့် ၁:၁ ကွက်တိကျစေမည့် စနစ်
                </p>
            </div>
            <div>
                <span class="badge-sync">1:1 EXACT SYNC</span>
                <span class="badge-purple">NATURAL CADENCE</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_up1, col_up2 = st.columns([1.2, 1.0])

    with col_up1:
        st.markdown("""
        <div class="neo-card">
            <h4 style="color: #00f2fe; margin-top: 0;">1. 📤 ဗီဒီယို တင်ပါ (Max 1 GB)</h4>
        """, unsafe_allow_html=True)
        up_file = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV, WebM - Max 1GB)", type=["mp4", "mov", "webm"])
        yt_url = st.text_input("သို့မဟုတ် Video Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=...")

        if up_file:
            with open("temp_input.mp4", "wb") as f:
                f.write(up_file.getbuffer())

        vid_len = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
        if vid_len > 0:
            st.success(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(vid_len)} ({vid_len:.2f} စက္ကန့် အတိအကျ)** | အသံမပြတ်ဘဲ သဘာဝကျစွာ အသံသွင်းပေးပါမည်။")

        selected_mode_label = st.selectbox("🎯 Recap အမျိုးအစား", list(RECAP_MODES.keys()), index=0)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_up2:
        st.markdown("""
        <div class="neo-card-accent">
            <h4 style="color: #c084fc; margin-top: 0;">2. 🏷️ Channel Logo (Auto Background Remover)</h4>
        """, unsafe_allow_html=True)
        logo_file = st.file_uploader("Logo ပုံတင်ပါ (PNG, JPG)", type=["png", "jpg", "jpeg", "webp"])
        if logo_file:
            raw_logo = "raw_user_logo.png"
            clean_logo = "processed_user_logo.png"
            with open(raw_logo, "wb") as f:
                f.write(logo_file.getbuffer())
            if process_user_logo(raw_logo, clean_logo):
                st.session_state.user_watermark_file = clean_logo
                st.success("✅ Logo Background ဖျက်ပြီး နီယွန်ကွင်း ထည့်သွင်းပြီးပါပြီ!")
                st.image(clean_logo, width=70)

        logo_pos_choice = st.selectbox("📍 Logo နေရာ", ["top_right (အပေါ် ညာဘက်)", "top_left (အပေါ် ဘယ်ဘက်)", "bottom_right (အောက် ညာဘက်)"], index=0)
        logo_pos_key = logo_pos_choice.split(" ")[0]
        st.markdown("</div>", unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1.5, 1.0])
    with col_btn1:
        one_click_btn = st.button("⚡ ONE-CLICK MAGIC RECAP (မပြတ်မတောက် သဘာဝအသံဖြင့် ၁:၁ ထုတ်လုပ်မည်)", type="primary", use_container_width=True)
    with col_btn2:
        script_only_btn = st.button("📝 Script သာ အရင်ထုတ်ယူမည်", use_container_width=True)

    if one_click_btn or script_only_btn:
        if not os.path.exists("temp_input.mp4") and not yt_url:
            st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ သို့မဟုတ် Link ထည့်ပေးပါ ခင်ဗျာ။")
        elif not st.session_state.gemini_api_key.strip():
            st.error("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ (Sidebar တွင် ထည့်နိုင်ပါသည်)။")
        else:
            if yt_url and not up_file:
                with st.spinner("ဗီဒီယို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "temp_input.mp4", yt_url.split("?")[0]], capture_output=True)

            v_duration = get_media_duration("temp_input.mp4")
            if v_duration <= 0.0:
                v_duration = 33.0

            try:
                with st.spinner(f"👁️ AI က ဗီဒီယိုကို မျက်စိဖြင့် လေ့လာပြီး {v_duration:.1f}s သဘာဝကျ စာသားအပြည့်အစုံ ရေးသားနေပါသည်..."):
                    s_text, h1, h2 = generate_vision_matched_script(
                        raw_api_keys=st.session_state.gemini_api_key,
                        video_path="temp_input.mp4" if os.path.exists("temp_input.mp4") else None,
                        target_duration=v_duration,
                        mode_key=RECAP_MODES[selected_mode_label]
                    )
                    st.session_state.recap_script_text = s_text
                    st.session_state.top_hook_text = h1
                    st.session_state.bottom_hook_text = h2

                if one_click_btn:
                    with st.spinner(f"🎙️ မပြတ်မတောက်ဘဲ သွက်လက်ချောမွေ့သော {v_duration:.2f}s အသံသွင်းနေပါသည်..."):
                        voice_cfg = VOICE_CONFIGS[voice_sel]
                        synced_audio = "final_synced_voice.mp3"
                        generate_natural_voice(s_text, voice_cfg, v_duration, synced_audio)

                    ass_file = "final_subtitles.ass"
                    if st.session_state.enable_subtitles:
                        calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                        create_clean_ass_subtitles(
                            h1=st.session_state.top_hook_text,
                            h2=st.session_state.bottom_hook_text,
                            script=s_text,
                            duration=v_duration,
                            ass_path=ass_file,
                            font_size=st.session_state.sub_font_size,
                            v_margin=calc_vm,
                            hex_color=st.session_state.sub_color_hex,
                            bg_style=st.session_state.sub_bg_style,
                            cta_text=st.session_state.cta_type
                        )
                    else:
                        ass_file = None

                    with st.spinner("🎬 ဗီဒီယိုနှင့် အသံအား ၁:၁ ကွက်တိကျအောင် Render ပြုလုပ်နေပါသည်..."):
                        final_out = "recap_output.mp4"
                        render_strict_sync_video(
                            input_video="temp_input.mp4",
                            narration_audio=synced_audio,
                            ass_path=ass_file,
                            output_video=final_out,
                            logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                            logo_pos=logo_pos_key,
                            bgm_vol=st.session_state.saved_bgm_vol
                        )
                        st.session_state.last_rendered_video = final_out
                        st.success(f"🎉 အောင်မြင်ပါပြီ! ဗီဒီယိုအစစ်အမှန်အတိုင်း သွက်လက်သော အသံဖြင့် {v_duration:.2f}s ကွက်တိကျစွာ ထွက်ရှိပါပြီ ခင်ဗျာ!")
            except Exception as ex:
                st.error(f"❌ {ex}")

    st.markdown("---")

    st.markdown("### 🎬 **Interactive Video Preview & Direct Subtitle Adjuster**")
    st.caption("Subtitle အမြင့်၊ အရောင်နှင့် စာလုံးအရွယ်အစားများကို တိုက်ရိုက် စမ်းသပ် ပြင်ဆင်ပြီး Final Video အသစ် ပြန်ထုတ်နိုင်ပါသည် ခင်ဗျာ။")

    col_preview_v, col_preview_c = st.columns([1.2, 1.2])

    with col_preview_c:
        st.markdown("""
        <div class="neo-card">
            <h4 style="color: #00f2fe; margin-top: 0;">⚙️ Subtitle & Typography Settings</h4>
        """, unsafe_allow_html=True)
        st.session_state.enable_subtitles = st.checkbox("📝 စာတန်းထိုး (Subtitles) ထည့်သွင်းမည်", value=st.session_state.enable_subtitles)

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.session_state.sub_color_hex = st.color_picker("🎨 စာတန်းထိုး အရောင်", st.session_state.sub_color_hex)
        with col_c2:
            st.session_state.sub_bg_style = st.selectbox("📦 နောက်ခံစတိုင်", ["Solid Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline Only (အနားကွပ် သီးသန့်)"], index=0)

        st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ % (Subtitle Height)", 5, 80, int(st.session_state.sub_v_pos_percent))
        st.session_state.hook_top_percent = st.slider("↕️ Hook ခေါင်းစဉ် အမြင့်နေရာ % (Top %)", 2, 25, int(st.session_state.hook_top_percent))
        st.session_state.sub_font_size = st.slider("🔤 စာလုံး အရွယ်အစား (Font Size)", 28, 56, int(st.session_state.sub_font_size))

        st.session_state.cta_type = st.selectbox(
            "🔘 Call-to-Action ခလုတ် စာသား",
            ["👍 Like & 🔔 Subscribe လုပ်ထားပါ ခင်ဗျာ", "🔔 Subscribe လုပ်ထားပေးပါ ခင်ဗျာ", "စာရင်းသွင်းပါ (Formal Burmese)"],
            index=0
        )

        ch1, ch2 = st.columns(2)
        with ch1:
            st.session_state.top_hook_text = st.text_input("Line 1 Hook Text", value=st.session_state.top_hook_text)
        with ch2:
            st.session_state.bottom_hook_text = st.text_input("Line 2 Hook Text", value=st.session_state.bottom_hook_text)

        st.markdown("##### 📄 ဇာတ်ညွှန်း စာသား တိုက်ရိုက်တည်းဖြတ်ရန် (Script):")
        st.session_state.recap_script_text = st.text_area("Script", value=st.session_state.recap_script_text, height=90, label_visibility="collapsed")

        if st.button("🚀 သတ်မှတ်ချက်အသစ်ဖြင့် Final Video ပြန်ထုတ်မည် (Re-Export MP4)", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                with st.spinner("Final Video အသစ် ပြန်လည်ထုတ်ယူနေပါသည်..."):
                    t_dur = get_media_duration("temp_input.mp4")
                    ass_f = "final_subtitles.ass"
                    if st.session_state.enable_subtitles:
                        calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                        create_clean_ass_subtitles(
                            h1=st.session_state.top_hook_text,
                            h2=st.session_state.bottom_hook_text,
                            script=st.session_state.recap_script_text,
                            duration=t_dur,
                            ass_path=ass_f,
                            font_size=st.session_state.sub_font_size,
                            v_margin=calc_vm,
                            hex_color=st.session_state.sub_color_hex,
                            bg_style=st.session_state.sub_bg_style,
                            cta_text=st.session_state.cta_type
                        )
                    else:
                        ass_f = None

                    audio_to_use = "final_synced_voice.mp3" if os.path.exists("final_synced_voice.mp3") else "temp_raw_unconformed.mp3"
                    final_out = "recap_output.mp4"
                    render_strict_sync_video(
                        input_video="temp_input.mp4",
                        narration_audio=audio_to_use,
                        ass_path=ass_f,
                        output_video=final_out,
                        logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                        logo_pos=logo_pos_key,
                        bgm_vol=st.session_state.saved_bgm_vol
                    )
                    st.session_state.last_rendered_video = final_out
                    st.success("✨ Render ပြီးပါပြီ ခင်ဗျာ!")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_preview_v:
        st.markdown("""
        <div class="neo-card">
            <h4 style="color: #00f2fe; margin-top: 0;">📱 Live Video Player</h4>
        """, unsafe_allow_html=True)
        if st.session_state.last_rendered_video and os.path.exists(st.session_state.last_rendered_video):
            st.video(st.session_state.last_rendered_video)
            with open(st.session_state.last_rendered_video, "rb") as vf:
                st.download_button(
                    label="📥 Final 1:1 Synced MP4 ဒေါင်းလုဒ်ရယူရန်",
                    data=vf.read(),
                    file_name="recap_studio_master.mp4",
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )
        elif os.path.exists("temp_input.mp4"):
            st.video("temp_input.mp4")
        else:
            st.info("ဗီဒီယို ဖိုင်တင်ပြီးပါက ဤနေရာတွင် တိုက်ရိုက် ကြည့်ရှုနိုင်မည် ဖြစ်ပါသည် ခင်ဗျာ။")
        st.markdown("</div>", unsafe_allow_html=True)

# ==============================================================================
# TAB 2: MULTI-PART SPLITTER (1 GB SUPPORT)
# ==============================================================================
with tab_splitter:
    st.markdown("""
    <div class="neo-card-accent">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #ffffff; margin: 0; font-size: 20px;">🍿 Multi-Part Auto Splitter (1 GB Support)</h2>
        <p style="color: #cbd5e1; font-size: 13px; margin-top: 6px; margin-bottom: 0;">
            မိနစ် ၃၀၊ ၁ နာရီ ဗီဒီယိုရှည်ကြီးများကို ၆၀ စက္ကန့် Shorts အပိုင်း ၁၊ ၂၊ ၃ အဖြစ် အလိုအလျောက် ခွဲထုတ်ပေးသည့် စနစ်
        </p>
    </div>
    """, unsafe_allow_html=True)

    long_file = st.file_uploader("ဗီဒီယိုရှည် တင်ပါ (အများဆုံး 1 GB အထိ ရပါသည်)", type=["mp4", "mov"], key="splitter_upload")
    if long_file:
        with open("temp_long_video.mp4", "wb") as f:
            f.write(long_file.getbuffer())

    long_dur = get_media_duration("temp_long_video.mp4") if os.path.exists("temp_long_video.mp4") else 0.0

    if long_dur > 0:
        st.info(f"⏱️ ဗီဒီယိုရှည် ကြာချိန်: **{format_time_str(long_dur)} ({long_dur:.1f} စက္ကန့်)**")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            split_slice = st.selectbox("အပိုင်းတစ်ခုစီ၏ ကြာချိန်", [30, 60, 90, 180], index=1)
        with col_s2:
            split_aspect = st.selectbox("ဗီဒီယိုပုံစံ", ["9:16 ဒေါင်လိုက် (TikTok/Reels)", "မူရင်း 16:9"])
        with col_s3:
            total_parts = max(1, int(long_dur // split_slice))
            st.markdown(f"<div style='margin-top:28px; color:#00f2fe; font-weight:bold;'>ထွက်ရှိမည့် အပိုင်း အရေအတွက်: {total_parts} ပိုင်း</div>", unsafe_allow_html=True)

        if st.button("✂️ အပိုင်းတိုများ အလိုအလျောက် ခွဲထုတ်မည် (Generate All Parts)", type="primary"):
            with st.spinner(f"ဗီဒီယိုအား {total_parts} ပိုင်း အလိုအလျောက် ဖြတ်တောက်နေပါသည်..."):
                part_files = []
                for p_idx in range(total_parts):
                    st_sec = p_idx * split_slice
                    out_part = f"part_{p_idx+1}.mp4"

                    vf_part = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280" if "9:16" in split_aspect else "scale=1280:720"
                    badge_filter = f"{vf_part},drawtext=text='PART {p_idx+1}':fontfile=Pyidaungsu.ttf:fontsize=48:fontcolor=yellow:x=(w-text_w)/2:y=100:box=1:boxcolor=black@0.8:boxborderw=10"

                    cmd_split = [
                        "ffmpeg", "-y",
                        "-ss", str(st_sec),
                        "-t", str(split_slice),
                        "-i", "temp_long_video.mp4",
                        "-vf", badge_filter,
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac",
                        out_part
                    ]
                    subprocess.run(cmd_split, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if os.path.exists(out_part):
                        part_files.append((out_part, p_idx+1))

                st.session_state.split_parts_list = part_files
                st.success(f"🎉 အပိုင်းတို {len(part_files)} ပိုင်း အောင်မြင်စွာ ခွဲထုတ်ပြီးပါပြီ ခင်ဗျာ!")

        if "split_parts_list" in st.session_state and st.session_state.split_parts_list:
            cols = st.columns(2)
            for file_name, p_num in st.session_state.split_parts_list:
                col_target = cols[(p_num - 1) % 2]
                with col_target:
                    st.markdown(f"""
                    <div class="neo-card">
                        <h4 style="color:#38bdf8; margin:0 0 10px 0;">📌 Part {p_num} ({split_slice} စက္ကန့်)</h4>
                    """, unsafe_allow_html=True)
                    st.video(file_name)
                    c_b1, c_b2 = st.columns(2)
                    with c_b1:
                        with open(file_name, "rb") as pf:
                            st.download_button(f"📥 Download Part {p_num}", data=pf.read(), file_name=file_name, mime="video/mp4", key=f"dl_p_{p_num}")
                    with c_b2:
                        if st.button(f"🚀 Recap စတူဒီယိုသို့ ပို့မည် (Part {p_num})", key=f"send_recap_{p_num}"):
                            import shutil
                            shutil.copyfile(file_name, "temp_input.mp4")
                            st.success(f"✅ Part {p_num} အား Recap Studio သို့ ပို့ဆောင်ပြီးပါပြီ! ပထမ Tab တွင် ဆက်လက်လုပ်ဆောင်နိုင်ပါသည် ခင်ဗျာ။")
                    st.markdown("</div>", unsafe_allow_html=True)

# ==============================================================================
# TAB 3: SETTINGS & INFO
# ==============================================================================
with tab_settings:
    st.markdown("""
    <div class="neo-card">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #00f2fe; margin-top: 0;">⚙️ Settings & System Info</h2>
        <ul style="color: #cbd5e1; line-height: 1.8;">
            <li><strong>အများဆုံး တင်နိုင်သော ဗီဒီယိုဖိုင် အရွယ်အစား:</strong> <span class="badge-sync">1024 MB (1 GB)</span></li>
            <li><strong>အသံထွက်ဖတ်ကြားမှု စနစ်:</strong> Natural Human Cadence + Fluid Breath Sync</li>
            <li><strong>Subtitle Engine:</strong> Pillow & Clean ASS Subtitles with Myanmar Unicode</li>
            <li><strong>Video Ratio:</strong> 9:16 Vertical Center-Crop (TikTok/Reels/Shorts)</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    key_input = st.text_area("Gemini API Key List (ကော်မာခံ၍ Key အပိုများ ထည့်သွင်းနိုင်သည်)", value=st.session_state.gemini_api_key, height=100)
    if st.button("💾 သိမ်းဆည်းမည်", type="primary"):
        save_config("gemini_api_key", key_input)
        st.session_state.gemini_api_key = key_input
        st.success("Config သိမ်းဆည်းပြီးပါပြီ ခင်ဗျာ!")
