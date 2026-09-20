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
# 1. fonts.conf ထုတ်ပေးခြင်းဖြင့် fontconfig ကို လက်ရှိ directory အား ဖတ်ရှုစေခြင်း
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
</fontconfig>""")
    except Exception:
        pass

os.environ["FONTCONFIG_PATH"] = "."

# 2. တရားဝင် Padauk / Pyidaungsu Unicode Font ကို အလိုအလျောက် ရယူခြင်း
FONT_FILE = "Padauk-Regular.ttf"
def ensure_myanmar_font():
    if not os.path.exists(FONT_FILE) or os.path.getsize(FONT_FILE) < 50000:
        urls = [
            "https://raw.githubusercontent.com/googlefonts/padauk/main/fonts/ttf/Padauk-Regular.ttf",
            "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf"
        ]
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as resp, open(FONT_FILE, "wb") as out_f:
                    out_f.write(resp.read())
                if os.path.exists(FONT_FILE) and os.path.getsize(FONT_FILE) > 50000:
                    break
            except Exception:
                pass
ensure_myanmar_font()

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
သင်သည် ထူးချွန်သော မြန်မာ Movie Recap Storyteller ဖြစ်သည်။
ပေးထားသော ဗီဒီယို၏ မြင်ကွင်းများ (Visual scenes, actions, characters movements) ကို အစအဆုံး အတိအကျ သေချာကြည့်ရှုလေ့လာပါ။
အဓိက စည်းမျဉ်းများ:
၁။ ဗီဒီယိုထဲတွင် တကယ်ဖြစ်ပျက်နေသော ရုပ်ထွက်မြင်ကွင်းများနှင့် အချိန်ကိုက် တစ်ထပ်တည်း လိုက်ပြောပြမည့် မြန်မာဇာတ်ညွှန်းကို ရေးပေးပါ။ (မြင်ကွင်းနှင့် မဆိုင်သော စိတ်ကူးယဉ် အပိုစကားများ မထည့်ပါနှင့်)။
၂။ ပထမ ၃ စက္ကန့်တွင် ပရိတ်သတ်ကို ဆွဲဆောင်မည့် Hook တစ်ခုဖြင့် စတင်ပါ။
၃။ အသံဖတ်ပြမည့် မြန်မာစာသား သက်သက်ကိုသာ ထုတ်ပေးပါ။
၄။ ဝါကျများကို ပုဒ်မ (။) သို့မဟုတ် ပုဒ်ကလေး (၊) သေချာခွဲပေးပါ။
ညွှန်ကြားချက်: {custom_instructions if custom_instructions else 'ရုပ်ရှင်မြင်ကွင်းများနှင့် အသံဖတ်ပြချက် ကွက်တိကိုက်ညီအောင် ရေးပေးပါ။'}
"""
    if video_path and os.path.exists(video_path):
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        response = model.generate_content([video_file, prompt])
    else:
        response = model.generate_content(prompt)
    return response.text

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

def create_srt_subtitles(script_text, total_duration, srt_path, max_chars=30):
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
                    if current:
                        chunks.append(current)
                    current = w
            if current:
                chunks.append(current)
                
    if not chunks:
        chunks = [script_text]
        
    chunk_time = total_duration / len(chunks)
    
    def format_time(seconds):
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"
        
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(chunks):
            start = idx * chunk_time
            end = min((idx + 1) * chunk_time, total_duration)
            f.write(f"{idx + 1}\n")
            f.write(f"{format_time(start)} --> {format_time(end)}\n")
            f.write(f"{chunk}\n\n")

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
    srt_path,
    output_video_path,
    aspect_format,
    video_speed=1.0,
    enable_subtitles=True,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
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
    
    color_map = {
        "Yellow (ရွှေဝါရောင်)": "&H00FFFF",
        "White (အဖြူရောင်)": "&HFFFFFF",
        "Green (စိမ်းဖန့်ရောင်)": "&H00FF00",
        "Cyan (မိုးပြာရောင်)": "&HFFFF00"
    }
    primary_col = color_map.get(sub_color, "&H00FFFF")
    
    # မြန်မာ Unicode Font အဖြစ် Padauk သတ်မှတ်ခြင်း
    if "Box" in sub_bg:
        sub_style = f"FontName=Padauk,FontSize=22,PrimaryColour={primary_col},BorderStyle=3,Outline=1,Shadow=0,BackColour=&H80000000,Alignment=2,MarginV=60"
    else:
        sub_style = f"FontName=Padauk,FontSize=22,PrimaryColour={primary_col},BorderStyle=1,Outline=2,Shadow=2,BackColour=&H00000000,Alignment=2,MarginV=60"
        
    scale_dict = {
        "9:16": "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "16:9": "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        "4:5": "scale=720:900:force_original_aspect_ratio=increase,crop=720:900",
        "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720"
    }
    scale_filter = scale_dict.get(aspect_format, "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280")
    
    # ရုပ်နှင့် အသံ Duration ကွက်တိညှိခြင်း (အစက Clip ပြန်မထည့်ဘဲ ကွက်တိညှိခြင်း)
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
        
    if enable_subtitles and srt_path and os.path.exists(srt_path):
        vf_filters.append(f"subtitles={srt_path}:fontsdir=.:force_style='{sub_style}'")
        
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
        
    # FFmpeg Command Construction
    if logo_path and os.path.exists(logo_path):
        # Logo အပေါ်ထောင့် ညာဘက်ခြမ်း ထည့်သွင်းခြင်း
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
    st.caption("⚡ **Recap Studio MM v2.6 Pro**")

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
    st.caption("ရုပ်သံအလိုက် အချိန်ကိုက်ဖတ်ပြခြင်း၊ Logo ထည့်သွင်းခြင်း၊ BGM အတိုးအကျယ်နှင့် Subtitle Yes/No ရွေးချယ်မှုများ ပါဝင်ပါသည်။")
    
    # Persistent Gemini API Key Input
    if not st.session_state.gemini_api_key:
        api_input = st.text_input
