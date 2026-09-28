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

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM Pro - Master Suite",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CYBERPUNK NEON GLOW CSS -----------------
st.markdown("""
<style>
    .stApp {
        background-color: #030712;
        color: #f1f5f9;
    }
    @keyframes neonGlow {
        0% { box-shadow: 0 0 5px #00f2fe, 0 0 10px #00f2fe; }
        50% { box-shadow: 0 0 20px #00f2fe, 0 0 30px #38bdf8; }
        100% { box-shadow: 0 0 5px #00f2fe, 0 0 10px #00f2fe; }
    }
    .neon-panel {
        background: linear-gradient(135deg, rgba(8, 25, 44, 0.92), rgba(3, 10, 20, 0.98));
        border: 1.5px solid #00f2fe;
        border-radius: 14px;
        padding: 18px 24px;
        animation: neonGlow 3s infinite alternate;
        margin-bottom: 20px;
    }
    .badge-sync {
        background: rgba(0, 242, 254, 0.15);
        color: #00f2fe;
        border: 1px solid #00f2fe;
        padding: 4px 12px;
        border-radius: 14px;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.5px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- MYANMAR FONT ENGINE -----------------
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

# ----------------- CONFIG PERSISTENCE -----------------
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

# ----------------- MEDIA DURATION HELPERS -----------------
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

# ----------------- PHONETIC BURMESE TRANSLITERATION -----------------
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
    if not text:
        return ""
    t = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?", "", text)
    t = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", t)
    t = re.sub(r"[\(\[（【].*?[\)\]）】]", "", t)
    t = re.sub(r"[*#_~>`]", "", t)
    for pattern, rep in PHONETICS.items():
        t = re.sub(pattern, rep, t, flags=re.IGNORECASE)
    t = t.replace("\n", " ").replace("  ", " ").strip()
    return t

# ----------------- USER LOGO BACKGROUND REMOVER -----------------
def process_user_logo(input_path, output_path):
    try:
        img = Image.open(input_path).convert("RGBA")
        data = list(img.getdata())
        new_data = []
        for item in data:
            r, g, b, a = item
            if r > 215 and g > 215 and b > 215:
                new_data.append((255, 255, 255, 0))
            elif r < 30 and g < 30 and b < 30:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)

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

# ----------------- SESSION STATE -----------------
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

if "active_nav_tab" not in st.session_state:
    st.session_state.active_nav_tab = "🎬 Movie Recap Studio"

VOICE_CONFIGS = {
    "မင်းသန့် (Agency - Confident Narrator)": {"voice": "my-MM-ThihaNeural", "pitch": "-2Hz", "rate": "+3%"},
    "ကိုမင်း (Deep Cinematic Specialist)": {"voice": "my-MM-ThihaNeural", "pitch": "-6Hz", "rate": "+2%"},
    "သီဟ (Action & Dynamic Voice)": {"voice": "my-MM-ThihaNeural", "pitch": "+1Hz", "rate": "+5%"},
    "မေသူ (Drama & Mystery Female)": {"voice": "my-MM-NilarNeural", "pitch": "+2Hz", "rate": "+2%"}
}

# ----------------- TRUE MULTIMODAL VISION AI SCRIPT ENGINE -----------------
def generate_vision_matched_script(raw_api_keys, video_path, target_duration, mode_prompt_type="movie"):
    import google.generativeai as genai

    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_keys) if k.strip()]
    if not keys:
        raise ValueError("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။")

    # Strict Formula: 1.65 spoken words per second for 1:1 duration lock
    exact_words = max(18, int(target_duration * 1.65))

    if mode_prompt_type == "craft":
        mode_instruction = """
တင်ထားသော ဗီဒီယိုဖိုင်ကို မျက်စိဖြင့် သေချာကြည့်ပါ။ ဤဗီဒီယိုသည် အသံမပါသော လက်မှုပညာ (Woodworking/DIY/Restoration/စမ်းသပ်မှု) ဗီဒီယို ဖြစ်သည်။
လက်ဖြင့် အဆင့်ဆင့် ပြုလုပ်နေပုံများကို မျက်မြင်အစစ်အမှန်အတိုင်း "ပထမဦးဆုံးအနေနဲ့...", "ဒီနေရာမှာတော့...", "သေသပ်သွားအောင် အချောကိုင်ပေးနေတာ ဖြစ်ပါတယ်..." စသည်ဖြင့် ပရိသတ် စွဲဆောင်သွားအောင် အနီးကပ် ရှင်းပြပေးပါ။ စိတ်ကူးယဉ် ဇာတ်လမ်းများ လုံးဝမထည့်ပါနှင့်။
"""
    else:
        mode_instruction = """
တင်ထားသော ရုပ်ရှင်/ဇာတ်လမ်း ဗီဒီယိုဖိုင်ကို မျက်စိဖြင့် သေချာကြည့်ပါ။ ဗီဒီယိုထဲတွင် အမှန်တကယ် ပါဝင်သော ဇာတ်ကွက်များနှင့် အဖြစ်အပျက်ကို အခြေခံပြီး "ဒီအချိန်မှာပဲ...", "ရုတ်တရက်...", "တကယ်တော့ သူဟာ..." စသည့် အချိတ်အဆက်များ ထည့်သွင်းကာ စိတ်လှုပ်ရှားဖွယ် Movie Recap အဖြစ် ပြန်လည်ပြောပြပေးပါ။
"""

    prompt = f"""
{mode_instruction}

🛑 အလွန်အရေးကြီးသော စည်းကမ်းချက်များ:
၁။ ပေးပို့ထားသော ဗီဒီယိုကို မျက်စိဖြင့် သေချာကြည့်ရှုပါ။ ဗီဒီယိုထဲတွင် အမှန်တကယ် ပါဝင်သော ပုံရိပ်များနှင့် အကြောင်းအရာကိုသာ အတိအကျ ရေးသားရပါမည်။ ဗီဒီယိုထဲမပါသော အခြားစိတ်ကူးယဉ် ဇာတ်လမ်းများကို လုံးဝ (လုံးဝ) မထည့်ရပါ။
၂။ ဗီဒီယို ကြာချိန်သည် အတိအကျ {target_duration:.1f} စက္ကန့် ဖြစ်သည်။
၃။ စကားပြောနှုန်း ၁:၁ ကွက်တိကျစေရန် စကားလုံး အရေအတွက်ကို အတိအကျ {exact_words} လုံးခန့် ({exact_words-3} မှ {exact_words+3} လုံးအတွင်းသာ) ရေးပေးရပါမည်။
၄။ မြန်မာစကားပြော သီးသန့် ဖြစ်ရပါမည်။ အင်္ဂလိပ်စာလုံး လုံးဝမထည့်ပါနှင့်။
၅။ အောက်ပါ JSON Format သီးသန့်ဖြင့်သာ ပြန်ဖြေပါ:
{{
  "hook_line1": "ဗီဒီယိုနှင့် ကိုက်ညီသော ခေါင်းစဉ် ၁ (စကားလုံး ၃-၄ လုံး)",
  "hook_line2": "ဗီဒီယိုနှင့် ကိုက်ညီသော ခေါင်းစဉ် ၂ (စကားလုံး ၃-၄ လုံး)",
  "script": "ဗီဒီယိုထဲတွင် မြင်တွေ့ရသည့်အတိုင်း မြန်မာစကားပြော ရှင်းလင်းချက် အပြည့်အစုံ..."
}}
"""
    last_err = None
    for k_idx, current_key in enumerate(keys):
        genai.configure(api_key=current_key)
        
        # 1. Upload Video File to Gemini Multimodal Vision API
        video_file_obj = None
        if video_path and os.path.exists(video_path):
            try:
                with st.spinner("📤 ဗီဒီယိုအား AI မျက်စိဖြင့် လေ့လာနိုင်ရန် Gemini Vision API သို့ ပေးပို့နေပါသည်..."):
                    video_file_obj = genai.upload_file(path=video_path)
                    waits = 0
                    while video_file_obj.state.name == "PROCESSING" and waits < 30:
                        time.sleep(1.5)
                        waits += 1
                        video_file_obj = genai.get_file(video_file_obj.name)
                    if video_file_obj.state.name != "ACTIVE":
                        video_file_obj = None
            except Exception:
                video_file_obj = None

        # 2. Query Gemini with the actual Video File
        for m_name in ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(m_name)
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
                    st.warning(f"⚠️ API Key (#{k_idx+1}) Limit ပြည့်သွားသဖြင့် နောက် Key သို့ ပြောင်းနေပါသည်...")
                    break
                continue
    raise Exception(f"API Error: {last_err}")

# ----------------- MILLISECOND AUDIO CONFORMING ENGINE -----------------
def generate_and_conform_voice(text, voice_cfg, target_video_duration, final_output_path):
    cleaned = clean_script_for_tts(text)
    temp_raw = "temp_raw_unconformed.mp3"
    
    import edge_tts
    communicate = edge_tts.Communicate(text=cleaned, voice=voice_cfg["voice"], rate=voice_cfg["rate"], pitch=voice_cfg["pitch"])
    asyncio.run(communicate.save(temp_raw))

    raw_dur = get_media_duration(temp_raw)
    if raw_dur <= 0.1 or target_video_duration <= 0.1:
        import shutil
        shutil.copyfile(temp_raw, final_output_path)
        return

    tempo = raw_dur / target_video_duration
    filters = []
    t = tempo
    while t > 2.0:
        filters.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        filters.append("atempo=0.5")
        t /= 0.5
    filters.append(f"atempo={t:.4f}")
    filter_chain = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", temp_raw,
        "-filter:a", filter_chain,
        "-t", f"{target_video_duration:.3f}",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        final_output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- CAPCUT STYLE ANIMATED SUBTITLES ENGINE -----------------
def hex_to_ass(hex_code):
    h = hex_code.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H0000FFFF&"

def create_capcut_animated_subtitles(h1, h2, script, duration, ass_path, font_size, v_margin, hex_color, bg_style, cta_text, is_capcut_animated=True):
    def fmt_ass_time(s):
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        centis = int((s - int(s)) * 100)
        return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"

    col_primary = hex_to_ass(hex_color)
    col_active_word = "&H0000FFFF&"

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

    chunks = [s.strip() for s in re.split(r"[၊။\.\?\!\n]+", script) if s.strip()]
    if not chunks:
        chunks = [script]
    chunk_time = duration / len(chunks)

    for i, chunk in enumerate(chunks):
        c_st = i * chunk_time
        c_en = min((i + 1) * chunk_time, duration)

        if is_capcut_animated:
            words = chunk.split(" ")
            w_count = max(1, len(words))
            w_time = (c_en - c_st) / w_count

            for w_idx, word in enumerate(words):
                w_st = c_st + (w_idx * w_time)
                w_en = min(w_st + w_time, c_en)

                active_line = []
                for idx, w in enumerate(words):
                    if idx == w_idx:
                        active_line.append(f"{{\\c{col_active_word}\\fscx112\\fscy112}}{w}{{\\r}}")
                    else:
                        active_line.append(w)
                rendered_chunk = " ".join(active_line)
                ass_text += f"Dialogue: 0,{fmt_ass_time(w_st)},{fmt_ass_time(w_en)},SubtitleStyle,,0,0,0,,{rendered_chunk}\n"
        else:
            ass_text += f"Dialogue: 0,{fmt_ass_time(c_st)},{fmt_ass_time(c_en)},SubtitleStyle,,0,0,0,,{chunk}\n"

    if cta_text and duration > 5.0:
        ass_text += f"Dialogue: 2,{fmt_ass_time(duration - 5.0)},{fmt_ass_time(duration)},CTAStyle,,0,0,0,,{cta_text}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

# ----------------- STRICT 1:1 HARDWARE-LOCKED RENDER PIPELINE -----------------
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

# ----------------- SIDEBAR NAVIGATION -----------------
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; margin-bottom: 12px;">
        <h2 style="color: #00f2fe; margin-bottom: 0px;">⚡ RECAP MASTER</h2>
        <span class="badge-sync">PRO SUITE EDITION</span>
    </div>
    """, unsafe_allow_html=True)

    menu_tabs = [
        "🎬 Movie Recap Studio",
        "🛠️ Silent Craft & DIY Studio",
        "🍿 Multi-Part Auto Splitter",
        "🎨 CapCut Subtitle Studio",
        "⚙️ API & Global Settings"
    ]
    st.session_state.active_nav_tab = st.radio("Navigation Menu", menu_tabs, label_visibility="collapsed")

    st.markdown("---")
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
    voice_sel = st.selectbox("🎙️ Narrator Voice", list(VOICE_CONFIGS.keys()), index=0)
    bgm_val = st.slider("🎵 BGM Volume", 0.0, 0.25, float(st.session_state.saved_bgm_vol), 0.02)
    st.session_state.saved_bgm_vol = bgm_val

# ==============================================================================
# TAB 1: MOVIE RECAP STUDIO
# ==============================================================================
if st.session_state.active_nav_tab == "🎬 Movie Recap Studio":
    st.markdown("""
    <div class="neon-panel">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h2 style="color: #ffffff; margin: 0; font-size: 22px;">🎬 Movie & Series Recap Studio</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 4px; margin-bottom: 0;">
                    ရုပ်ရှင်၊ Series နှင့် Anime များကို AI Vision ဖြင့် ကြည့်ပြီး စက္ကန့်မလွဲ ၁:၁ ရုပ်သံကွက်တိကျ အသံသွင်းပေးမည့် စနစ်
                </p>
            </div>
            <div class="badge-sync">1:1 EXACT DURATION LOCKED</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1.2, 1.0])
    with col1:
        st.markdown("#### 1. 📤 ဗီဒီယို ဖိုင်တင်ပါ (သို့မဟုတ် YouTube Link)")
        up_file = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV)", type=["mp4", "mov", "webm"], key="movie_uploader")
        yt_url = st.text_input("သို့မဟုတ် Link ထည့်ပါ", placeholder="[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=)...", key="movie_yt")

        if up_file:
            with open("temp_input.mp4", "wb") as f:
                f.write(up_file.getbuffer())

        vid_len = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
        if vid_len > 0:
            st.success(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(vid_len)} ({vid_len:.2f} စက္ကန့် အတိအကျ)**")

    with col2:
        st.markdown("#### 2. 🏷️ Channel Logo (Auto Background Remover)")
        logo_file = st.file_uploader("Logo ပုံတင်ပါ", type=["png", "jpg", "jpeg", "webp"], key="movie_logo")
        if logo_file:
            raw_logo = "raw_user_logo.png"
            clean_logo = "processed_user_logo.png"
            with open(raw_logo, "wb") as f:
                f.write(logo_file.getbuffer())
            if process_user_logo(raw_logo, clean_logo):
                st.session_state.user_watermark_file = clean_logo
                st.success("✅ Logo Background ဖျက်ပြီး နီယွန်ကွင်း ထည့်သွင်းပြီးပါပြီ!")
                st.image(clean_logo, width=70)

        logo_pos_choice = st.selectbox("📍 Logo နေရာ", ["top_right (အပေါ် ညာဘက်)", "top_left (အပေါ် ဘယ်ဘက်)", "bottom_right (အောက် ညာဘက်)"], index=0, key="movie_logo_pos")
        logo_pos_key = logo_pos_choice.split(" ")[0]

    st.markdown("---")
    col_b1, col_b2 = st.columns([1.5, 1.0])
    with col_b1:
        one_click_btn = st.button("⚡ ONE-CLICK MOVIE RECAP (ဇာတ်ညွှန်း၊ အသံနှင့် ဗီဒီယို ၁:၁ ထုတ်လုပ်မည်)", type="primary", use_container_width=True)
    with col_b2:
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
            if v_duration <= 0.0: v_duration = 33.0

            try:
                with st.spinner(f"👁️ AI က ဗီဒီယိုကို မျက်စိဖြင့် လေ့လာပြီး {v_duration:.1f}s Movie Recap ရေးသားနေပါသည်..."):
                    s_text, h1, h2 = generate_vision_matched_script(
                        raw_api_keys=st.session_state.gemini_api_key,
                        video_path="temp_input.mp4" if os.path.exists("temp_input.mp4") else None,
                        target_duration=v_duration,
                        mode_prompt_type="movie"
                    )
                    st.session_state.recap_script_text = s_text
                    st.session_state.top_hook_text = h1
                    st.session_state.bottom_hook_text = h2

                if one_click_btn:
                    with st.spinner(f"🎙️ အသံအား {v_duration:.2f}s သို့ မီလီစက္ကန့်မလွဲ Conforming ညှိယူနေပါသည်..."):
                        voice_cfg = VOICE_CONFIGS[voice_sel]
                        synced_audio = "final_synced_voice.mp3"
                        generate_and_conform_voice(s_text, voice_cfg, v_duration, synced_audio)

                    ass_file = "final_subtitles.ass"
                    calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                    create_capcut_animated_subtitles(
                        h1=st.session_state.top_hook_text,
                        h2=st.session_state.bottom_hook_text,
                        script=s_text,
                        duration=v_duration,
                        ass_path=ass_file,
                        font_size=st.session_state.sub_font_size,
                        v_margin=calc_vm,
                        hex_color=st.session_state.sub_color_hex,
                        bg_style=st.session_state.sub_bg_style,
                        cta_text=st.session_state.cta_type,
                        is_capcut_animated=True
                    )

                    with st.spinner("🎬 Final MP4 ဗီဒီယို Render ပြုလုပ်နေပါသည်..."):
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
                        st.success(f"🎉 အောင်မြင်ပါပြီ! ဗီဒီယိုနှင့် အသံ {v_duration:.2f}s အတိအကျ ကွက်တိကျစွာ ထွက်ရှိပါပြီ ခင်ဗျာ!")
            except Exception as ex:
                st.error(f"❌ {ex}")

    st.markdown("---")
    st.markdown("#### 📱 Video Player & Live Placement")
    if st.session_state.last_rendered_video and os.path.exists(st.session_state.last_rendered_video):
        col_v1, col_v2 = st.columns([1.2, 1.0])
        with col_v1:
            st.video(st.session_state.last_rendered_video)
        with col_v2:
            with open(st.session_state.last_rendered_video, "rb") as vf:
                st.download_button(
                    label="📥 Final 1:1 Synced MP4 ဒေါင်းလုဒ်ဆွဲရန်",
                    data=vf.read(),
                    file_name="movie_recap_final.mp4",
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )

# ==============================================================================
# TAB 2: SILENT CRAFT & DIY EXPLAINER STUDIO
# ==============================================================================
elif st.session_state.active_nav_tab == "🛠️ Silent Craft & DIY Studio":
    st.markdown("""
    <div class="neon-panel">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h2 style="color: #ffffff; margin: 0; font-size: 22px;">🛠️ Silent Craft & DIY Visual Explainer</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 4px; margin-bottom: 0;">
                    အသံမဲ့ လက်မှုပညာ၊ DIY၊ ဟင်းချက်နည်းနှင့် သန့်ရှင်းရေး/စမ်းသပ်မှု ဗီဒီယိုများကို AI က လိုက်ကြည့်ပြီး Step-by-Step အသံသွင်းပေးသည့် စနစ်
                </p>
            </div>
            <div class="badge-sync">AI MULTIMODAL VISION</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_c1, col_c2 = st.columns([1.2, 1.0])
    with col_c1:
        st.markdown("#### 📤 အသံမပါသော လက်မှုပညာ/စမ်းသပ်မှု ဗီဒီယို တင်ပါ")
        craft_file = st.file_uploader("လက်မှုပညာ ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV)", type=["mp4", "mov"], key="craft_uploader")
        craft_url = st.text_input("သို့မဟုတ် YouTube Link", placeholder="[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=)...", key="craft_yt")

        if craft_file:
            with open("temp_craft.mp4", "wb") as f:
                f.write(craft_file.getbuffer())

        c_dur = get_media_duration("temp_craft.mp4") if os.path.exists("temp_craft.mp4") else 0.0
        if c_dur > 0:
            st.info(f"⏱️ လက်မှုပညာ ဗီဒီယို ကြာချိန်: **{format_time_str(c_dur)} ({c_dur:.2f} စက္ကန့်)**")

    with col_c2:
        craft_category = st.selectbox(
            "📌 ပညာရပ် အမျိုးအစား",
            ["သစ်သားပရိဘောဂ & သစ်ထွင်း (Woodworking/Carpentry)", "ပစ္စည်းဟောင်း ပြန်လည်ပြုပြင်ခြင်း (Restoration)", "သိပ္ပံနှင့် လက်တွေ့စမ်းသပ်မှု (Science & Experiment)", "အိမ်သုံး DIY & လက်မှုပစ္စည်း (DIY Crafting)", "ဟင်းချက်နည်း & မုန့်လုပ်နည်း (Cooking/Baking)"]
        )
        st.caption("AI သည် မျက်စိရှေ့တွင် လက်ဖြင့် အဆင့်ဆင့် လုပ်ဆောင်ပြသနေသည့် လှုပ်ရှားမှုများကို အနီးကပ် လိုက်လံရှင်းပြပေးမည် ဖြစ်ပါသည်။")

    if st.button("⚡ ONE-CLICK CRAFT EXPLAINER (လက်မှုပညာ သီးသန့် အသံသွင်းမည်)", type="primary", use_container_width=True):
        if not os.path.exists("temp_craft.mp4") and not craft_url:
            st.error("ဗီဒီယို အရင်တင်ပေးပါ ခင်ဗျာ။")
        else:
            if craft_url and not craft_file:
                with st.spinner("ဗီဒီယို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "temp_craft.mp4", craft_url.split("?")[0]], capture_output=True)

            c_dur = get_media_duration("temp_craft.mp4")
            with st.spinner(f"👁️ ဗီဒီယို လက်လှုပ်ရှားမှုများကို AI ဖြင့် လေ့လာပြီး {c_dur:.1f}s အသံသွင်း ဇာတ်ညွှန်း ရေးသားနေပါသည်..."):
                s_text, h1, h2 = generate_vision_matched_script(
                    raw_api_keys=st.session_state.gemini_api_key,
                    video_path="temp_craft.mp4" if os.path.exists("temp_craft.mp4") else None,
                    target_duration=c_dur,
                    mode_prompt_type="craft"
                )

            with st.spinner("🎙️ ရှင်းလင်းချက် အသံအား စက္ကန့်မလွဲ Conforming ညှိယူနေပါသည်..."):
                voice_cfg = VOICE_CONFIGS[voice_sel]
                synced_audio = "craft_synced_voice.mp3"
                generate_and_conform_voice(s_text, voice_cfg, c_dur, synced_audio)

            with st.spinner("🎬 Final Craft Explainer ဗီဒီယို Render ပြုလုပ်နေပါသည်..."):
                ass_file = "craft_subtitles.ass"
                create_capcut_animated_subtitles(h1, h2, s_text, c_dur, ass_file, 38, 240, "#00f2fe", "Solid Box", "🔔 Follow လုပ်ထားပါ ခင်ဗျာ", True)
                final_craft_out = "craft_recap_output.mp4"
                render_strict_sync_video("temp_craft.mp4", synced_audio, ass_file, final_craft_out, None, "top_right", 0.08)
                st.success("🎉 အသံမဲ့ လက်မှုပညာ Explainer ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ ခင်ဗျာ!")
                st.video(final_craft_out)

# ==============================================================================
# TAB 3: MULTI-PART AUTO SPLITTER
# ==============================================================================
elif st.session_state.active_nav_tab == "🍿 Multi-Part Auto Splitter":
    st.markdown("""
    <div class="neon-panel">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h2 style="color: #ffffff; margin: 0; font-size: 22px;">🍿 ဇာတ်လမ်းရှည် Multi-Part Auto Splitter</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 4px; margin-bottom: 0;">
                    မိနစ် ၃၀ ဗီဒီယိုရှည်ကြီးများကို ၆၀ စက္ကန့် Shorts အပိုင်း ၁၊ ၂၊ ၃ အဖြစ် Part တပ်ပြီး အလိုအလျောက် ခွဲပေးသည့် စနစ်
                </p>
            </div>
            <div class="badge-sync">BATCH VIRAL CUTTER</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    long_file = st.file_uploader("ဗီဒီယိုရှည် တင်ပါ (MP4, MOV)", type=["mp4", "mov"], key="splitter_upload")
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
                    st.markdown(f"**📌 Part {p_num} ({split_slice} စက္ကန့်)**")
                    st.video(file_name)
                    c_b1, c_b2 = st.columns(2)
                    with c_b1:
                        with open(file_name, "rb") as pf:
                            st.download_button(f"📥 Download Part {p_num}", data=pf.read(), file_name=file_name, mime="video/mp4", key=f"dl_p_{p_num}")
                    with c_b2:
                        if st.button(f"🚀 Recap လုပ်မည် (Part {p_num})", key=f"send_recap_{p_num}"):
                            import shutil
                            shutil.copyfile(file_name, "temp_input.mp4")
                            st.session_state.active_nav_tab = "🎬 Movie Recap Studio"
                            st.rerun()

# ==============================================================================
# TAB 4: CAPCUT STYLE ANIMATED SUBTITLES STUDIO
# ==============================================================================
elif st.session_state.active_nav_tab == "🎨 CapCut Subtitle Studio":
    st.markdown("""
    <div class="neon-panel">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h2 style="color: #ffffff; margin: 0; font-size: 22px;">🎨 CapCut Style Animated Subtitles Studio</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 4px; margin-bottom: 0;">
                    စကားလုံးထွက်လာတိုင်း စာလုံးလေးများ အဝါရောင် လင်းလက်ခုန်တက်လာစေမည့် Kinetic ASS Engine
                </p>
            </div>
            <div class="badge-sync">ACTIVE WORD POP HIGHLIGHT</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_sub_v, col_sub_c = st.columns([1.2, 1.2])

    with col_sub_c:
        st.markdown("#### ⚙️ Typography & Highlight Controls")
        st.session_state.enable_subtitles = st.checkbox("📝 စာတန်းထိုး ဖွင့်မည်", value=st.session_state.enable_subtitles)
        st.session_state.sub_custom_anim = st.checkbox("✨ CapCut Active Word Pop Highlight ဖွင့်မည်", value=True)

        col_sc1, col_sc2 = st.columns(2)
        with col_sc1:
            st.session_state.sub_color_hex = st.color_picker("🎨 အခြေခံ စာတန်းထိုး အရောင်", st.session_state.sub_color_hex)
        with col_sc2:
            st.session_state.sub_bg_style = st.selectbox("📦 နောက်ခံစတိုင်", ["Solid Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline Only (အနားကွပ် သီးသန့်)"], index=0)

        st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ %", 5, 80, int(st.session_state.sub_v_pos_percent))
        st.session_state.hook_top_percent = st.slider("↕️ Hook ခေါင်းစဉ် အမြင့်နေရာ %", 2, 25, int(st.session_state.hook_top_percent))
        st.session_state.sub_font_size = st.slider("🔤 စာလုံး အရွယ်အစား", 28, 56, int(st.session_state.sub_font_size))

        ch1, ch2 = st.columns(2)
        with ch1:
            st.session_state.top_hook_text = st.text_input("Line 1 Hook", value=st.session_state.top_hook_text, key="cap_h1")
        with ch2:
            st.session_state.bottom_hook_text = st.text_input("Line 2 Hook", value=st.session_state.bottom_hook_text, key="cap_h2")

        st.session_state.recap_script_text = st.text_area("Script Preview Editor", value=st.session_state.recap_script_text, height=90, key="cap_script")

        if st.button("🚀 CapCut စာတန်းထိုးဖြင့် Final Video ပြန်ထုတ်မည်", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                with st.spinner("CapCut Animated Subtitles တပ်ဆင်နေပါသည်..."):
                    t_dur = get_media_duration("temp_input.mp4")
                    ass_f = "final_subtitles.ass"
                    calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                    create_capcut_animated_subtitles(
                        h1=st.session_state.top_hook_text,
                        h2=st.session_state.bottom_hook_text,
                        script=st.session_state.recap_script_text,
                        duration=t_dur,
                        ass_path=ass_f,
                        font_size=st.session_state.sub_font_size,
                        v_margin=calc_vm,
                        hex_color=st.session_state.sub_color_hex,
                        bg_style=st.session_state.sub_bg_style,
                        cta_text=st.session_state.cta_type,
                        is_capcut_animated=st.session_state.sub_custom_anim
                    )
                    audio_to_use = "final_synced_voice.mp3" if os.path.exists("final_synced_voice.mp3") else "temp_raw_unconformed.mp3"
                    final_out = "recap_output.mp4"
                    render_strict_sync_video(
                        input_video="temp_input.mp4",
                        narration_audio=audio_to_use,
                        ass_path=ass_f,
                        output_video=final_out,
                        logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                        logo_pos="top_right",
                        bgm_vol=st.session_state.saved_bgm_vol
                    )
                    st.session_state.last_rendered_video = final_out
                    st.success("✨ CapCut စတိုင် စာတန်းထိုး တပ်ဆင်ပြီးပါပြီ ခင်ဗျာ!")
                    st.rerun()

    with col_sub_v:
        st.markdown("#### 📱 Live Subtitle Mockup")
        box_css = "background: rgba(0,0,0,0.85); border-radius: 6px; padding: 4px 10px;" if "Solid" in st.session_state.sub_bg_style else "background: rgba(0,0,0,0.45); border-radius: 6px; padding: 4px 10px;"
        phone_mockup_html = textwrap.dedent(f"""
        <div style="width: 100%; max-width: 310px; height: 490px; margin: 10px auto; background: radial-gradient(circle, #0e1e2d, #04090e); border: 2.5px solid #00f2fe; border-radius: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 25px rgba(0,242,254,0.3);">
            <div style="position: absolute; top: {st.session_state.hook_top_percent}%; left: 0; width: 100%; text-align: center; padding: 0 10px;">
                <span style="display: inline-block; background: rgba(0,0,0,0.9); border: 1.5px solid #FFD700; color: #FFDF00; font-size: 12px; font-weight: 800; padding: 3px 8px; border-radius: 5px;">
                    {st.session_state.top_hook_text}<br>{st.session_state.bottom_hook_text}
                </span>
            </div>
            <div style="position: absolute; bottom: {st.session_state.sub_v_pos_percent}%; left: 8%; width: 84%; text-align: center;">
                <div style="border: 1.5px dashed #00f2fe; {box_css}">
                    <span style="color: #ffffff; font-size: {int(st.session_state.sub_font_size * 0.32)}px; font-weight: bold;">
                        လူတွေတင်မကဘဲ <span style="color:#00f2fe; font-size:{int(st.session_state.sub_font_size * 0.36)}px; text-shadow:0 0 8px #00f2fe;">တိရစ္ဆာန်တွေကိုပါ</span> တရားရုံးတင်ခဲ့တဲ့...
                    </span>
                </div>
            </div>
        </div>
        """)
        st.markdown(phone_mockup_html, unsafe_allow_html=True)

# ==============================================================================
# TAB 5: API & GLOBAL SETTINGS
# ==============================================================================
elif st.session_state.active_nav_tab == "⚙️ API & Global Settings":
    st.markdown("## ⚙️ **API & Global Settings Manager**")
    st.caption("စနစ်တစ်ခုလုံး၏ အရေးကြီး Config များနှင့် Gemini API Key Backup များကို စီမံခန့်ခွဲနိုင်ပါသည် ခင်ဗျာ။")

    key_input = st.text_area("Gemini API Key List (ကော်မာခံ၍ Key ၃ ခုထိ ထည့်နိုင်သည်)", value=st.session_state.gemini_api_key, height=100)
    if st.button("💾 သိမ်းဆည်းမည်", type="primary"):
        save_config("gemini_api_key", key_input)
        st.session_state.gemini_api_key = key_input
        st.success("Config သိမ်းဆည်းပြီးပါပြီ ခင်ဗျာ!")
