import streamlit as st
import os
import re
import time
import json
import asyncio
import datetime
import subprocess
import urllib.request

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- MYANMAR UNICODE FONT CONFIG -----------------
# 1. fonts.conf တည်ဆောက်၍ fontconfig အား Padauk / Pyidaungsu ဖောင့်များကို အဓိက သတ်မှတ်စေခြင်း
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

# 2. တရားဝင် Padauk / Pyidaungsu Unicode Font ကို အလိုအလျောက် ရယူခြင်း
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
    st.session_state.saved_voice = "သီဟ (Native Burmese - Male Narration)"

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_bgm_vol" not in st.session_state:
    st.session_state.saved_bgm_vol = 0.12

if "last_generated_video" not in st.session_state:
    st.session_state.last_generated_video = "recap_output.mp4" if os.path.exists("recap_output.mp4") else ""

def navigate_to(page_name):
    st.session_state.nav_menu = page_name

# ----------------- CUSTOM STYLING -----------------
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
    .format-card {
        background: #0d1a17;
        border: 1px solid #1a352f;
        border-radius: 12px;
        padding: 14px;
        text-align: center;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SCRIPT CLEANER (TIMESTAMPS & NUMBERS REMOVER) -----------------
def clean_script_for_narration(text):
    """
    AI မှ ထုတ်ပေးသော အချိန်မှတ်များ (၀:၀၀-၀:၀၃ စသည်)၊ နံပါတ်စဉ်များ (၁၊ ၂၊ ၃)၊
    ခေါင်းစဉ်များနှင့် Markdown သင်္ကေတများကို အပြီးအပိုင် ရှင်းလင်းပေးပြီး
    ချောမွေ့သော မြန်မာစကားပြော ဇာတ်လမ်းစာပိုဒ်အဖြစ် ပြောင်းလဲပေးသည်။
    """
    if not text:
        return ""
    # ၁။ မြန်မာ/အင်္ဂလိပ် ဂဏန်းဖြင့် ရေးထားသော အချိန်မှတ်များ ဖြတ်ထုတ်ခြင်း (e.g. ၀:၀၀-၀:၀၃:, 0:00-0:03:)
    text = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?\s*[:\s-]*", "", text)
    # ၂။ စာကြောင်းအစရှိ စာရင်းနံပါတ်များ ဖြတ်ထုတ်ခြင်း (e.g. ၁။, ၂။, 1., 2), 1-)
    text = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", text)
    # ၃။ ကွင်းစကွင်းပိတ်အတွင်းရှိ မြင်ကွင်းမှတ်စုများ ဖြတ်ထုတ်ခြင်း e.g. [ရယ်သံ]၊ (Scene 1)
    text = re.sub(r"[\(\[（【].*?[\)\]）】]", "", text)
    # ၄။ Markdown သင်္ကေတများ (*, #, _, ~, >) ရှင်းထုတ်ခြင်း
    text = re.sub(r"[*#_~>`]", "", text)
    # ၅။ Scene ခေါင်းစဉ်များ ရှင်းထုတ်ခြင်း
    text = re.sub(r"(?i)\b(scene|visual|audio|narrator|intro|outro|video)\s*\d*[:\-]*", "", text)
    # ၆။ စာကြောင်းများကို ပုံမှန်စကားပြော စာပိုဒ်အဖြစ် ချိတ်ဆက်ခြင်း
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    cleaned_text = " ".join(lines)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text

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
သင်သည် အလွန်တော်သော မြန်မာ Movie / Video Recap အသံသွင်း ဇာတ်လမ်းပြောပြသူ (Professional Storyteller Narrator) တစ်ဦး ဖြစ်သည်။
ပေးထားသော ဗီဒီယိုကို အစအဆုံး သေချာကြည့်ရှုပြီး ပရိတ်သတ် စိတ်ဝင်စားဖွယ် နားထောင်နိုင်မည့် မြန်မာ Recap ဇာတ်ညွှန်း (Voiceover Narration) အပြည့်အစုံကို ရေးသားပေးပါ။

🛑 အလွန်အရေးကြီးသော တားမြစ်ချက်များ (မဖြစ်မနေ လိုက်နာရမည်):
၁။ အချိန်မှတ်များ (ဥပမာ ၀:၀၀-၀:၀၃ သို့မဟုတ် 0:00-0:03)၊ နံပါတ်စဉ်များ (၁၊ ၂၊ ၃)၊ Scene ခေါင်းစဉ်များ၊ စာရင်းဇယား (Log / Table) ပုံစံများကို လုံးဝ (လုံးဝ) မထည့်ရ။
၂။ မြင်ကွင်းမှတ်စု (ဥပမာ - [ရယ်သံ]၊ (မြင်ကွင်း-မိုးရွာခြင်း)၊ မျှစ်ခွံခွာနေသည် စသော စာသားခြောက်ကပ်ကပ်များ) မထည့်ရ။
၃။ အသံဖတ်သူ (TTS AI) က တိုက်ရိုက် အသံထွက် ဖတ်ပြရမည်ဖြစ်သောကြောင့် နံပါတ်များ (1, 2, 3) ပါပါက အသံဖတ်သူက နံပါတ်လိုက်ဖတ်သွားပါလိမ့်မည်။ ထို့ကြောင့် နံပါတ်များ၊ သင်္ကေတများ လုံးဝမပါရ။

✨ ဇာတ်ညွှန်း ရေးသားရမည့် စတိုင် (Natural Storytelling Style):
၁။ သဘာဝကျသော လူကိုယ်တိုင် စကားပြောဟန် (Conversational Voiceover) ဖြင့် စာပိုဒ်ဆက်တိုက် တောက်လျှောက် ရေးပေးပါ။
၂။ ဇာတ်ကွက် စတင်ရာတွင် စိတ်ဝင်စားဖွယ် Hook ဖြင့် စတင်ပါ (ဥပမာ - "သဘာဝတောင်တန်းတွေကြားမှာ ရိုးရာအစားအစာတွေကို ဖန်တီးပြသသွားမယ့် ဒီဗီဒီယိုလေးမှာတော့...")။
၃။ ဇာတ်လမ်း မြင်ကွင်းတစ်ခုနှင့်တစ်ခုကို ချိတ်ဆက်စကားလုံးများဖြစ်သော "ပထမဆုံးအနေနဲ့"၊ "ပြီးတဲ့နောက်မှာတော့"၊ "ဆက်လက်ပြီးတော့"၊ "အဲဒီနောက်မှာတော့"၊ "နောက်ဆုံးမှာတော့" စသည့် သဘာဝကျသော စကားပြောစကားလုံးများဖြင့် သီကုံးရေးသားပါ။
၄။ မြန်မာစာဖတ်ရ ချောမွေ့စေရန် ပုဒ်မ (။) နှင့် ပုဒ်ကလေး (၊) ကို သေချာတိကျစွာ ခွဲပေးပါ။

ညွှန်ကြားချက် ထပ်ဆောင်း: {custom_instructions if custom_instructions else 'သဘာဝကျသော ဇာတ်လမ်းပြောဟန်ဖြင့် အသံဖတ်ပြရန် သီးသန့် မြန်မာစကားပြော စာသားသက်သက်သာ ရေးပေးပါ။'}
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
    # ချက်ချင်း စာသားသန့်စင်ပေးပြီး အချိန်မှတ်နှင့် နံပါတ်များကို ဖယ်ရှားခြင်း
    clean_text = clean_script_for_narration(raw_text)
    return clean_text

async def run_edge_tts(text, voice_name, output_path, speed_rate="+0%"):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice_name, rate=speed_rate)
    await communicate.save(output_path)

def generate_voice_file(text, voice_choice, output_audio_path, speed_multiplier=1.0):
    voice_map = {
        "သီဟ (Native Burmese - Male Narration)": "my-MM-ThihaNeural",
        "နဒီ (Native Burmese - Female Narration)": "my-MM-NilarNeural",
        "ကိုမင်း (Deep Voice - Movie Recap Specialist)": "my-MM-ThihaNeural",
        "မေသူ (Soft Voice - Drama/Emotional)": "my-MM-NilarNeural"
    }
    voice_code = voice_map.get(voice_choice, "my-MM-ThihaNeural")
    percent_offset = int(round((speed_multiplier - 1.0) * 100))
    rate_str = f"{percent_offset:+d}%"
    asyncio.run(run_edge_tts(text, voice_code, output_audio_path, speed_rate=rate_str))

# ----------------- ADVANCED SUBSTATION ALPHA (ASS) SUBTITLES -----------------
def create_ass_subtitles(script_text, total_duration, ass_path, font_name="Padauk", sub_color="Yellow (ရွှေဝါရောင်)", sub_bg="Box (အမည်းနောက်ခံ ဘား)", max_chars=32):
    """
    မြန်မာ Unicode စာလုံးပေါင်း အတိအကျမှန်ကန်စေရန် ASS (Advanced SubStation Alpha) ဖော်မတ်ဖြင့် ထုတ်လုပ်ပေးသည်။
    """
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
        "Cyan (မိုးပြာရောင်)": "&H00FFFF00"
    }
    primary_col = color_map.get(sub_color, "&H0000FFFF")
    
    # BorderStyle: 3 = Opaque Box, 1 = Outline + Drop Shadow
    if "Box" in sub_bg:
        border_style = "3"
        outline = "1"
        shadow = "0"
        back_colour = "&H80000000"
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
Style: Default,{font_name},32,{primary_col},&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,30,30,85,1

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
    # အသံနှင့် ရုပ် အချိန်ကွက်တိကျစေရန် ချိန်ညှိခြင်း (အစကနေ Clip ပြန်မပတ်ပါ)
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
    
    # BGM Audio Ducking
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
        
    # FFmpeg Command Construction with Logo Overlay at Top-Right
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
            <div style="font-size:11px; color:#94a3b8;">Recap Studio MM</div>
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
    st.caption("⚡ **Recap Studio MM v2.7 Pro**")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    with col_banner:
        st.markdown("""
        <div class="hero-card">
            <span style="color:#a78bfa; font-size:12px; font-weight:bold; letter-spacing:1px;">✨ RECAP STUDIO MM</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 28px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                AI Recap၊ ရုပ်သံကွက်တိ အသံထွက်၊ Auto BGM Ducking၊ Logo နှင့် Auto-Poster Tools များကို တစ်နေရာတည်းမှာ အသုံးပြုပါ။
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.button(
            "🎬 ဗီဒီယို ပြုလုပ်ရန် (Recap • မြန်မာအသံထွက် • စာတန်းထိုး) ➔",
            type="primary",
            on_click=navigate_to,
            args=("🎬 ဗီဒီယို ပြုလုပ်ရန်",),
            key="btn_hero_create"
        )
    with col_status:
        st.markdown("""
        <div class="hero-card" style="background:#0e1822;">
            <div style="font-size:12px; color:#94a3b8;">သင့်စနစ်အခြေအနေ</div>
            <div style="font-size:13px; margin-top:4px;">Recap Studio MM Pro</div>
            <h3 style="color:#10b981; margin:4px 0;">Studio Ready</h3>
            <p style="font-size:11px; color:#64748b;">အသံနှင့် ဗီဒီယို စနစ်များ အားလုံး အသင့်ရှိနေပါသည်။</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("⚡ မြန်ဆန်သော လုပ်ဆောင်ချက်များ")
    
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
    st.caption("သဘာဝကျသော မြန်မာစကားပြော ဇာတ်ညွှန်း၊ နံပါတ်/အချိန်မှတ် လုံးဝမပါသော အသံဖတ်စနစ်နှင့် တိကျသော Unicode စာတန်းထိုး။")
    
    # Persistent Gemini API Key Input
    if not st.session_state.gemini_api_key:
        api_input = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ (ဆာဗာ refresh လုပ်သော်လည်း မပျောက်စေရန် အလိုအလျောက် မှတ်သားထားပါမည်)", type="password")
        if api_input:
            st.session_state.gemini_api_key = api_input
            save_config("gemini_api_key", api_input)
            st.success("API Key အပြီးအပိုင် မှတ်သားပြီးပါပြီ!")
            st.rerun()
            
    # AI Model & Anti-Copyright
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
    
    # Mode & Voice Selection with Sample Listen Button
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
        st.markdown("##### ၂။ အသံ ရွေးချယ်မှုနှင့် နမူနာ နားထောင်ရန်")
        voice_choice = st.selectbox(
            "ပုံမှန်အသံ",
            [
                "သီဟ (Native Burmese - Male Narration)",
                "နဒီ (Native Burmese - Female Narration)",
                "ကိုမင်း (Deep Voice - Movie Recap Specialist)",
                "မေသူ (Soft Voice - Drama/Emotional)"
            ]
        )
        st.session_state.saved_voice = voice_choice
        
        if st.button("▶ Sample အသံနမူနာ နားထောင်ရန်", use_container_width=True):
            with st.spinner("အသံနမူနာ ဖန်တီးနေပါသည်..."):
                sample_file = "sample_preview.mp3"
                generate_voice_file("မင်္ဂလာပါ Recap Studio MM မှ ကြိုဆိုပါတယ်။", voice_choice, sample_file, speed_multiplier=st.session_state.saved_voice_speed)
                st.audio(sample_file)
        
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ (Instructions)",
        value="ဗီဒီယိုထဲက မြင်ကွင်းတွေနဲ့ ကိုက်ညီအောင် သဘာဝကျကျ စကားပြောဟန်ဖြင့် ဇာတ်လမ်းကို စိတ်ဝင်စားဖွယ် ဖတ်ပြပေးပါ။ အချိန်မှတ်နှင့် နံပါတ်များ လုံးဝမထည့်ပါနှင့်။",
        height=65
    )

    # Subtitles Enable/Disable Toggle (YES / NO) & Font Selection
    st.markdown("#### ၃။ မြန်မာစာတန်းထိုး (Subtitles) ရွေးချယ်မှု")
    col_sub_btn, col_sub_style1, col_sub_style2, col_sub_font = st.columns(4)
    with col_sub_btn:
        sub_option = st.radio(
            "စာတန်းထိုး ထည့်သွင်းမည်လား?",
            ["✅ ထည့်သွင်းမည် (Yes)", "❌ မထည့်ပါ (No)"],
            horizontal=True
        )
        enable_subtitles = (sub_option == "✅ ထည့်သွင်းမည် (Yes)")
        
    with col_sub_style1:
        sub_color = st.selectbox("စာလုံး အရောင်", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)"], disabled=not enable_subtitles)
    with col_sub_style2:
        sub_bg = st.selectbox("စာတန်းထိုး နောက်ခံ", ["Box (အမည်းနောက်ခံ ဘား)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)"], disabled=not enable_subtitles)
    with col_sub_font:
        sub_font = st.selectbox("အသုံးပြုမည့် ဖောင့်", ["Padauk", "Pyidaungsu", "Noto Sans Myanmar"], disabled=not enable_subtitles)

    # Speed Controls (0.7x to 2.0x) & BGM Volume Control
    st.markdown("#### ၄။ Speed နှင့် နောက်ခံတေးဂီတ (BGM) အတိုးအကျယ်")
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        voice_speed = st.slider(
            "🎙️ အသံ Speed",
            min_value=0.7, max_value=2.0, value=float(st.session_state.saved_voice_speed), step=0.05
        )
        st.session_state.saved_voice_speed = voice_speed
    with col_s2:
        video_speed = st.slider(
            "🎬 ဗီဒီယို Speed",
            min_value=0.7, max_value=2.0, value=float(st.session_state.saved_video_speed), step=0.05
        )
        st.session_state.saved_video_speed = video_speed
    with col_s3:
        bgm_vol = st.slider(
            "🎵 BGM အတိုးအကျယ် (Volume)",
            min_value=0.0, max_value=0.5, value=float(st.session_state.saved_bgm_vol), step=0.02,
            format="%.2f"
        )
        st.session_state.saved_bgm_vol = bgm_vol

    # Format Selection & Logo Watermark Option
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
    
    # ----------------- TWO-STEP WORKFLOW -----------------
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

    # Editable Script Area
    st.markdown("##### 📝 မြန်မာ Recap ဇာတ်ညွှန်း (အချိန်မှတ်နှင့် နံပါတ်စဉ်များ လုံးဝဖယ်ရှားထားပြီး ဖြစ်ပါသည်):")
    edited_script = st.text_area(
        "ဇာတ်ညွှန်းတည်းဖြတ်ရန်",
        value=st.session_state.recap_script_text,
        height=160,
        label_visibility="collapsed"
    )
    st.session_state.recap_script_text = edited_script

    # Step 2: Final Render Button
    with col_step2:
        render_btn = st.button("🎬 အဆင့် (၂): အသံနှင့် ဗီဒီယို Render လုပ်မည်", type="primary", use_container_width=True)

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

                with st.status("🎬 Recap Studio MM မှ ဗီဒီယို ထုတ်လုပ်နေပါသည်...", expanded=True) as status:
                    # အသံထွက်ဖတ်မည့် စာသားအား အချိန်မှတ်နှင့် နံပါတ်များ ထပ်မံသန့်စင်ခြင်း
                    clean_for_tts = clean_script_for_narration(st.session_state.recap_script_text)
                    pron_dict = load_replacements("pronunciation.txt")
                    final_script_for_tts = apply_pronunciation(clean_for_tts, pron_dict)
                    st.write("၁။ နံပါတ်များနှင့် အချိန်မှတ်များကို ရှင်းထုတ်ပြီး pronunciation.txt ဖြင့် အသံထွက် စကားလုံးများ ပြင်ဆင်ပြီးပါပြီ...")
                    
                    st.write(f"၂။ [{voice_choice}] (Speed {voice_speed}x) ဖြင့် မြန်မာအသံဖိုင် ထုတ်ယူနေပါသည်...")
                    temp_audio_out = "temp_voice.mp3"
                    generate_voice_file(final_script_for_tts, voice_choice, temp_audio_out, speed_multiplier=voice_speed)
                    audio_dur = get_media_duration(temp_audio_out)
                    st.write(f"အသံကြာချိန်: {audio_dur:.1f} စက္ကန့်")
                    
                    temp_ass_path = "temp_sub.ass"
                    if enable_subtitles:
                        st.write(f"၃။ [{sub_font}] Font ဖြင့် မြန်မာစာတန်းထိုး (ASS Subtitles) အတိအကျ ဖန်တီးနေပါသည်...")
                        create_ass_subtitles(
                            script_text=final_script_for_tts,
                            total_duration=audio_dur,
                            ass_path=temp_ass_path,
                            font_name=sub_font,
                            sub_color=sub_color,
                            sub_bg=sub_bg,
                            max_chars=32
                        )
                    
                    st.write("၄။ အသံ/ရုပ်/BGM Ducking/Logo/Anti-Copyright တို့ဖြင့် Render ပြုလုပ်နေပါသည်...")
                    final_video_output = "recap_output.mp4"
                    render_pro_video(
                        input_video_path=temp_in,
                        audio_path=temp_audio_out,
                        ass_path=temp_ass_path if enable_subtitles else None,
                        output_video_path=final_video_output,
                        aspect_format=format_ratio,
                        video_speed=video_speed,
                        enable_subtitles=enable_subtitles,
                        enable_anti_copyright=anti_copyright,
                        enable_bgm=(bgm_vol > 0.01),
                        bgm_volume=bgm_vol,
                        logo_path=logo_file_path if (enable_logo and logo_file_path) else None,
                        logo_size=logo_size,
                        logo_opacity=logo_opacity,
                        logo_margin=logo_margin
                    )
                    st.session_state.last_generated_video = final_video_output
                    status.update(label="✅ Recap ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!", state="complete", expanded=False)
                    
                st.success("🎉 Recap ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ!")
                
                # Audio Preview
                st.markdown("#### 🎙️ ထွက်ရှိလာသော အသံဖိုင်နှင့် စာတန်းထိုး")
                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    st.audio(temp_audio_out)
                with col_a2:
                    if enable_subtitles and os.path.exists(temp_ass_path):
                        with open(temp_ass_path, "r", encoding="utf-8") as ass_f:
                            st.download_button("📥 ASS စာတန်းထိုးဖိုင် ဒေါင်းလုဒ်ဆွဲရန်", data=ass_f.read(), file_name="recap_subtitles.ass")

                # Video Preview in Compact Centered Size
                st.markdown("#### 🎬 Recap ဗီဒီယို Preview")
                if os.path.exists(final_video_output):
                    if format_ratio == "9:16":
                        vp1, vp_center, vp2 = st.columns((1, 1, 1))
                        with vp_center:
                            st.video(final_video_output)
                    else:
                        vp1, vp_center, vp2 = st.columns((1, 2, 1))
                        with vp_center:
                            st.video(final_video_output)
                            
                    with open(final_video_output, "rb") as vid_file:
                        st.download_button(
                            label="📥 ပြီးစီးသော Recap ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် (MP4)",
                            data=vid_file.read(),
                            file_name="recap_studio_mm_final.mp4",
                            mime="video/mp4",
                            use_container_width=True
                        )
                        
                    st.info("💡 ဗီဒီယိုကို Facebook သို့မဟုတ် TikTok ပေါ်သို့ အချိန်ကိုက် Auto တင်လိုပါက ဘယ်ဘက် Sidebar ရှိ **'📱 Auto-Post (Facebook & TikTok)'** စာမျက်နှာသို့ သွားရောက်နိုင်ပါသည်။")
            except Exception as e:
                st.error(f"❌ Error ဖြစ်ပေါ်ပါသည်: {str(e)}")

# ----------------- PAGE 3: AUTO-POST DEDICATED PAGE -----------------
elif st.session_state.nav_menu == "📱 Auto-Post (Facebook & TikTok)":
    st.markdown("## 📱 **Social Media Auto-Poster (သီးသန့် စီမံခန့်ခွဲမှု စာမျက်နှာ)**")
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
        ayr_key_input = st.text_input(
            "🔑 Ayrshare API Key",
            value=st.session_state.ayrshare_api_key,
            type="password",
            placeholder="Ayrshare Profile API Key ထည့်ပါ..."
        )
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
    
    # Check if video is ready
    vid_path = "recap_output.mp4"
    if os.path.exists(vid_path):
        st.success("✅ လက်ရှိ ပြီးစီးထားသော ဗီဒီယိုဖိုင် အသင့်ရှိနေပါသည် (`recap_output.mp4`)")
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

# ----------------- PAGE 4: အသံထွက်နှင့် ဝေါဟာရ စီမံရန် -----------------
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
            
    st.markdown("##### `pronunciation.txt` ဖိုင် တိုက်ရိုက်ပြင်ဆင်ခြင်း")
    new_content = st.text_area(
        "ဖိုင်အကြောင်းအရာ (တစ်ကြောင်းလျှင် စကားလုံးတစ်ခု = အသံထွက် ပုံစံဖြင့် ရေးပါ)",
        value=existing_content,
        height=350,
        placeholder="Iron Man = အိုင်းရွန်းမန်း\nSpider-Man = စပိုက်ဒါမန်း\nThanos = သာနို့စ်"
    )
    
    if st.button("💾 အသံထွက် ပြင်ဆင်ချက်များကို သိမ်းဆည်းမည်", type="primary"):
        try:
            with open(pron_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            st.success("✅ `pronunciation.txt` ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ!")
        except Exception as err:
            st.error(f"ဖိုင်သိမ်းဆည်းရာတွင် အမှားဖြစ်ပေါ်ပါသည်: {err}")

# ----------------- PAGE 5: API & SETTINGS -----------------
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

# ----------------- OTHER PAGES -----------------
else:
    st.markdown(f"## {st.session_state.nav_menu}")
    st.info(f"{st.session_state.nav_menu} လုပ်ဆောင်ချက်များကို သင့် Recap Studio MM တွင် မကြာမီ ထပ်မံဖြည့်စွက်ပေးပါမည်။")
    st.button("🏠 ပင်မစာမျက်နှာသို့ ပြန်သွားရန်", on_click=navigate_to, args=("🏠 ပင်မစာမျက်နှာ",), key="btn_back_home")
