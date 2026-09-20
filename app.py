import streamlit as st
import os
import re
import time
import json
import asyncio
import subprocess

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# ----------------- SESSION STATE INITIALIZATION -----------------
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

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = ""

if "saved_voice_speed" not in st.session_state:
    st.session_state.saved_voice_speed = 1.0

if "saved_video_speed" not in st.session_state:
    st.session_state.saved_video_speed = 1.0

if "saved_mode" not in st.session_state:
    st.session_state.saved_mode = "🎙️ AI Recap (ဗီဒီယို အကျဉ်းချုပ် + အသံထွက်)"

if "saved_instructions" not in st.session_state:
    st.session_state.saved_instructions = ""

if "saved_sub_color" not in st.session_state:
    st.session_state.saved_sub_color = "Yellow (ရွှေဝါရောင်)"

if "saved_sub_bg" not in st.session_state:
    st.session_state.saved_sub_bg = "Box (အမည်းနောက်ခံ ဘား)"

if "saved_format" not in st.session_state:
    st.session_state.saved_format = "9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)"

if "saved_voice" not in st.session_state:
    st.session_state.saved_voice = "သီဟ (Native Burmese - Male Narration)"

if "saved_model" not in st.session_state:
    st.session_state.saved_model = "gemini-1.5-flash"

if "saved_anti_copyright" not in st.session_state:
    st.session_state.saved_anti_copyright = True

if "saved_bgm" not in st.session_state:
    st.session_state.saved_bgm = True

def navigate_to(page_name):
    st.session_state.nav_menu = page_name

# ----------------- CUSTOM STYLING (DARK UI) -----------------
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

# ----------------- PRONUNCIATION & DICTIONARY UTILS -----------------
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

# ----------------- AUDIO & VIDEO PIPELINE -----------------
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

def generate_recap_script(api_key, model_name, video_path, custom_instructions):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    
    try:
        model = genai.GenerativeModel(model_name)
    except Exception:
        model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
သင်သည် အလွန်တော်သော မြန်မာ Movie Recap Storyteller တစ်ယောက် ဖြစ်သည်။
အောက်ပါ ဗီဒီယိုကို ကြည့်ရှုပြီး ပရိတ်သတ် စိတ်ဝင်စားဖွယ် နားထောင်စေမည့် မြန်မာဘာသာ Movie Recap အသံဖတ်ပြရန် ဇာတ်ညွှန်း (Voiceover Script) တစ်ခုကို ရေးပေးပါ။
အဓိက စည်းမျဉ်းများ:
၁။ ပထမ ၃ စက္ကန့်တွင် ပရိတ်သတ်ကို ဆွဲဆောင်နိုင်မည့် Hook တစ်ခုဖြင့် စတင်ပါ။
၂။ စကားလုံးများသည် နားထောင်ရလွယ်ပြီး ဇာတ်လမ်းဆွဲဆောင်မှု ရှိရပါမည်။
၃။ မြန်မာလို အသံထွက်ဖတ်ပြမည့် စာသားသက်သက်ကိုသာ ထုတ်ပေးပါ (ဥပမာ [Scene 1], [Music] စသည့် အပိုစာသားများ မထည့်ပါနှင့်)။
၄။ ဝါကျများကို ပုဒ်မ (။) သို့မဟုတ် ပုဒ်ကလေး (၊) သေချာခွဲပေးပါ။
ညွှန်ကြားချက်: {custom_instructions if custom_instructions else 'ဇာတ်လမ်းကို စိတ်ဝင်စားဖွယ် ဆွဲဆောင်မှုရှိစွာ ပြောပြပါ။'}
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

def create_srt_subtitles(script_text, total_duration, srt_path, max_chars_per_line=30):
    # စာကြောင်းရှည်ကြီးများ မဖြစ်စေရန် စာလုံးရေ ၃၀ ဝန်းကျင်ဖြင့် အပိုင်းခွဲခြင်း
    raw_segments = [s.strip() for s in re.split(r"[၊။\n]+", script_text) if s.strip()]
    chunks = []
    for seg in raw_segments:
        if len(seg) <= max_chars_per_line:
            chunks.append(seg)
        else:
            words = seg.split(" ")
            current = ""
            for w in words:
                if len(current) + len(w) + 1 <= max_chars_per_line:
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

def render_final_video(
    input_video_path,
    audio_path,
    srt_path,
    output_video_path,
    aspect_format,
    video_speed=1.0,
    sub_color="Yellow (ရွှေဝါရောင်)",
    sub_bg="Box (အမည်းနောက်ခံ ဘား)",
    enable_anti_copyright=True,
    enable_bgm=True
):
    # ၁။ အသံကြာချိန်နှင့် ဗီဒီယိုကြာချိန်ကို တိုင်းတာခြင်း
    audio_duration = get_media_duration(audio_path)
    video_duration = get_media_duration(input_video_path)
    
    # ၂။ စာတန်းထိုး စတိုင်
    color_map = {
        "Yellow (ရွှေဝါရောင်)": "&H00FFFF",
        "White (အဖြူရောင်)": "&HFFFFFF",
        "Green (စိမ်းဖန့်ရောင်)": "&H00FF00",
        "Cyan (မိုးပြာရောင်)": "&HFFFF00"
    }
    primary_col = color_map.get(sub_color, "&H00FFFF")
    
    if "Box" in sub_bg:
        sub_style = f"FontSize=22,PrimaryColour={primary_col},BorderStyle=3,Outline=1,Shadow=0,BackColour=&H80000000,Alignment=2,MarginV=60"
    else:
        sub_style = f"FontSize=22,PrimaryColour={primary_col},BorderStyle=1,Outline=2,Shadow=2,BackColour=&H00000000,Alignment=2,MarginV=60"
        
    # ၃။ 720p Optimized Aspect Filters
    scale_dict = {
        "9:16": "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "16:9": "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        "4:5": "scale=720:900:force_original_aspect_ratio=increase,crop=720:900",
        "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720"
    }
    scale_filter = scale_dict.get(aspect_format, "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280")
    
    # ၄။ ရုပ်နှင့် အသံ ကွက်တိညှိခြင်း (အစက Clip ပြန်မထည့်ဘဲ Duration အတိအကျ ချိန်ညှိခြင်း)
    vf_filters = []
    if video_duration < audio_duration:
        sync_factor = audio_duration / max(video_duration, 0.1)
        vf_filters.append(f"setpts={sync_factor}*PTS")
    else:
        pts_factor = 1.0 / max(video_speed, 0.25)
        vf_filters.append(f"setpts={pts_factor}*PTS")
        
    vf_filters.append(scale_filter)
    
    # ၅။ Anti-Copyright Filter (Micro-zoom 1.05x, Color Shift)
    if enable_anti_copyright:
        vf_filters.append("scale=1.05*iw:1.05*ih,crop=iw:ih")
        vf_filters.append("eq=contrast=1.04:brightness=0.02:saturation=1.06")
        
    # ၆။ စာတန်းထိုး Hardsub ပေါင်းထည့်ခြင်း
    if srt_path and os.path.exists(srt_path):
        vf_filters.append(f"subtitles={srt_path}:force_style='{sub_style}'")
        
    full_vf = ",".join(vf_filters)
    
    # ၇။ BGM & Audio Ducking (စကားပြောချိန် သီချင်းတိုးစေမည့် စနစ်)
    final_audio_to_use = audio_path
    temp_bgm_file = "temp_bgm.mp3"
    temp_ducked_audio = "temp_ducked.mp3"
    
    if enable_bgm:
        generate_simple_bgm(temp_bgm_file, audio_duration + 2)
        cmd_duck = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-i", temp_bgm_file,
            "-filter_complex", "[0:a]volume=1.0[v];[1:a]volume=0.12[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]",
            "-c:a", "libmp3lame",
            temp_ducked_audio
        ]
        subprocess.run(cmd_duck, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        final_audio_to_use = temp_ducked_audio
        
    # ၈။ FFmpeg Rendering
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video_path,
        "-i", final_audio_to_use,
        "-t", str(audio_duration),
        "-vf", full_vf,
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
    st.caption("⚡ **Recap Studio MM v2.5 Pro**")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns(2)
    
    with col_banner:
        st.markdown("""
        <div class="hero-card">
            <span style="color:#a78bfa; font-size:12px; font-weight:bold; letter-spacing:1px;">✨ RECAP STUDIO MM</span>
            <h1 style="color:#ffffff; margin: 10px 0 6px 0; font-size: 28px;">ဒီနေ့ဘာပြုလုပ်ချင်ပါသလဲ?</h1>
            <p style="color:#cbd5e1; font-size:14px; margin-bottom: 20px;">
                AI Recap၊ မြန်မာစာတန်းထိုး၊ ဇာတ်လမ်းရှည် Recap၊ ဒေါင်းလုဒ်နှင့် အသံ Tools များကို တစ်နေရာတည်းမှာ အသုံးပြုပါ။
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
            <div style="font-size:13px; margin-top:4px;">Recap Studio MM</div>
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
        st.markdown('<div class="action-card"><h4>📁 ပရောဂျက်များ</h4><p style="font-size:12px; color:#94a3b8;">ယခင် ပြုလုပ်ထားသော ဖိုင်များ</p></div>', unsafe_allow_html=True)
        st.button("ပရောဂျက်များ ➔", on_click=navigate_to, args=("📁 သိမ်းဆည်းထားသော ပရောဂျက်များ",), key="btn_quick_proj")
    with r1_c3:
        st.markdown('<div class="action-card"><h4>🍿 ဇာတ်လမ်းရှည်</h4><p style="font-size:12px; color:#94a3b8;">ဇာတ်ကားရှည် Recap</p></div>', unsafe_allow_html=True)
        st.button("ဇာတ်လမ်းရှည် ➔", on_click=navigate_to, args=("🍿 ဇာတ်လမ်းရှည် Recap",), key="btn_quick_long")
    with r1_c4:
        st.markdown('<div class="action-card"><h4>🎙️ AI အသံ</h4><p style="font-size:12px; color:#94a3b8;">မြန်မာ AI အသံဖန်တီးရန်</p></div>', unsafe_allow_html=True)
        st.button("အသံစတူဒီယို ➔", on_click=navigate_to, args=("🎙️ AI အသံ စတူဒီယို",), key="btn_quick_voice")

    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    with r2_c1:
        st.markdown('<div class="action-card"><h4>🔄 အသံ ပြောင်းစနစ်</h4><p style="font-size:12px; color:#94a3b8;">Voice Tool</p></div>', unsafe_allow_html=True)
        st.button("အသံပြောင်းရန် ➔", on_click=navigate_to, args=("🔄 အသံ ပြောင်းစနစ်",), key="btn_quick_vchange")
    with r2_c2:
        st.markdown('<div class="action-card"><h4>📖 အသံထွက် စီမံရန်</h4><p style="font-size:12px; color:#94a3b8;">pronunciation.txt</p></div>', unsafe_allow_html=True)
        st.button("ဝေါဟာရ စီမံရန် ➔", on_click=navigate_to, args=("📖 အသံထွက်နှင့် ဝေါဟာရ စီမံရန်",), key="btn_quick_dict")
    with r2_c3:
        st.markdown('<div class="action-card"><h4>✂️ Auto Clips</h4><p style="font-size:12px; color:#94a3b8;">အပိုင်းဖြတ်ရန်</p></div>', unsafe_allow_html=True)
        st.button("Auto Clips ➔", on_click=navigate_to, args=("✂️ Auto Clips",), key="btn_quick_clips")
    with r2_c4:
        st.markdown('<div class="action-card"><h4>🎞️ ဗီဒီယို စတူဒီယို</h4><p style="font-size:12px; color:#94a3b8;">AI Video Studio</p></div>', unsafe_allow_html=True)
        st.button("ဗီဒီယိုစတူဒီယို ➔", on_click=navigate_to, args=("🎞️ AI ဗီဒီယို စတူဒီယို",), key="btn_quick_vstudio")

# ----------------- PAGE 2: ဗီဒီယို ပြုလုပ်ရန် (CREATE VIDEO) -----------------
elif st.session_state.nav_menu == "🎬 ဗီဒီယို ပြုလုပ်ရန်":
    st.markdown("## 🎬 **ဗီဒီယို ပြုလုပ်ရန် (Recap Studio Pro)**")
    st.caption("Anti-Copyright၊ BGM Ducking၊ Two-Step Script Editing နှင့် A/V Sync အပြည့်အစုံ ပါဝင်ပါသည်။")
    
    # API Key Checking & Persistent Storage
    if not st.session_state.gemini_api_key:
        api_input = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ (ဆာဗာ refresh လုပ်သော်လည်း မပျောက်စေရန် အလိုအလျောက် မှတ်သားထားပါမည်)", type="password")
        if api_input:
            st.session_state.gemini_api_key = api_input
            save_config("gemini_api_key", api_input)
            st.success("API Key အပြီးအပိုင် မှတ်သားပြီးပါပြီ!")
            st.rerun()
            
    # Model Selection (Gemini 1.5 Flash / Gemini 2.5 Flash)
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        model_choice = st.selectbox(
            "🤖 AI Model ရွေးချယ်ရန်",
            ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
            index=0
        )
        st.session_state.saved_model = model_choice
    with col_m2:
        anti_copyright = st.checkbox("🛡️ Anti-Copyright ကာကွယ်ရေး စနစ် (Zoom + Color Shift)", value=st.session_state.saved_anti_copyright)
        st.session_state.saved_anti_copyright = anti_copyright
        bgm_choice = st.checkbox("🎵 Auto BGM ပေါင်းစပ်မှု + Audio Ducking (စကားပြောချိန် သီချင်းတိုးစေရန်)", value=st.session_state.saved_bgm)
        st.session_state.saved_bgm = bgm_choice
        
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
    
    # Mode & Voice Selection
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("##### ၁။ ဘာပုံစံ ပြုလုပ်ချင်ပါသလဲ?")
        mode = st.selectbox("ပုံစံ", [
            "🎙️ AI Recap (ဗီဒီယို အကျဉ်းချုပ် + အသံထွက်)",
            "📝 မြန်မာ စာတန်းထိုး (Subtitles)",
            "🎬 ရုပ်ရှင် ပြန်လည်ပြောပြ (Story Narration)",
            "✨ Vision Narrator (AI ဇာတ်ကွက် ခွဲခြမ်းစိတ်ဖြာခြင်း)"
        ], index=0)
        st.session_state.saved_mode = mode
    with col_c2:
        st.markdown("##### ၂။ အသံ ရွေးချယ်မှု")
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
        
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ (Instructions)",
        value=st.session_state.saved_instructions,
        placeholder="ဥပမာ - ရုပ်ရှင်ဇာတ်ညွှန်းကို လူငယ်သုံးစကားဖြင့် စိတ်ဝင်စားဖွယ် recap လုပ်ပါ။ ဇာတ်ကောင်အမည်များကို အသံထွက်မှန်အောင် ထည့်ပေးပါ။",
        height=70
    )
    st.session_state.saved_instructions = instructions

    # Speed Controls (0.7x to 2.0x Bar)
    st.markdown("#### ၃။ အသံနှင့် ဗီဒီယို Speed အလျော့အတင်း (၀.၇x မှ ၂.၀x အထိ)")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        voice_speed = st.slider(
            "🎙️ အသံ Speed (Voice Speed)",
            min_value=0.7,
            max_value=2.0,
            value=float(st.session_state.saved_voice_speed),
            step=0.05
        )
        st.session_state.saved_voice_speed = voice_speed
    with col_s2:
        video_speed = st.slider(
            "🎬 ဗီဒီယို Speed (Video Speed)",
            min_value=0.7,
            max_value=2.0,
            value=float(st.session_state.saved_video_speed),
            step=0.05
        )
        st.session_state.saved_video_speed = video_speed

    # Subtitle Styling & Format
    col_st1, col_st2 = st.columns(2)
    with col_st1:
        st.markdown("##### ၄။ မြန်မာစာတန်းထိုး (Subtitles) စတိုင်")
        sub_color = st.selectbox("စာလုံး အရောင်", ["Yellow (ရွှေဝါရောင်)", "White (အဖြူရောင်)", "Green (စိမ်းဖန့်ရောင်)", "Cyan (မိုးပြာရောင်)"])
        sub_bg = st.selectbox("စာတန်းထိုး နောက်ခံ", ["Box (အမည်းနောက်ခံ ဘား)", "Outline & Shadow (အနားကွပ်နှင့် အရိပ်)"])
        st.session_state.saved_sub_color = sub_color
        st.session_state.saved_sub_bg = sub_bg
    with col_st2:
        st.markdown("##### ၅။ ဗီဒီယို အရွယ်အစား (Format)")
        format_choice = st.selectbox(
            "Format ရွေးချယ်ပါ",
            ["9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)", "16:9 - အလျားလိုက် (YouTube)", "4:5 - Feed ပုံစံ (Facebook/IG)", "1:1 - စတုရန်း"]
        )
        format_ratio = format_choice.split(" - ")[0]
        st.session_state.saved_format = format_choice

    st.markdown("---")
    
    # ----------------- TWO-STEP WORKFLOW -----------------
    st.markdown("### 🚀 **အဆင့် (၂) ဆင့် Recap ထုတ်လုပ်မှု စနစ်**")
    
    # Step 1: Script Generation
    col_step1, col_step2 = st.columns(2)
    with col_step1:
        if st.button("📝 အဆင့် (၁): AI ဇာတ်ညွှန်း အရင်ထုတ်ယူမည်", type="primary", use_container_width=True):
            if not uploaded_video and not video_url:
                st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် Link ထည့်သွင်းပေးပါ။")
            elif not st.session_state.gemini_api_key:
                st.error("Gemini API Key ထည့်သွင်းပေးပါ။")
            else:
                with st.spinner("Google Gemini AI ဖြင့် မြန်မာ Recap ဇာတ်ညွှန်း ရေးသားနေပါသည်..."):
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
                        res = subprocess.run(cmd_dl, capture_output=True, text=True)
                        if res.returncode != 0:
                            st.warning("YouTube မှ Server IP ကို ပိတ်ထားပါသဖြင့် Upload Tab ဖြင့် ဗီဒီယိုတင်ပေးပါခင်ဗျာ။")
                            
                    script_res = generate_recap_script(
                        api_key=st.session_state.gemini_api_key,
                        model_name=model_choice,
                        video_path=temp_in if os.path.exists(temp_in) else None,
                        custom_instructions=instructions
                    )
                    st.session_state.recap_script_text = script_res
                    st.success("AI ဇာတ်ညွှန်း ထွက်ရှိပါပြီ! အောက်တွင် ဖတ်ရှုပြင်ဆင်နိုင်ပါသည်။")

    # Editable Script Area
    st.markdown("##### 📝 မြန်မာ Recap ဇာတ်ညွှန်း (မိမိစိတ်ကြိုက် စာလုံးများ ဖြည့်စွက်/ပြင်ဆင်နိုင်ပါသည်):")
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
                    # ၁။ Pronunciation Dictionary
                    pron_dict = load_replacements("pronunciation.txt")
                    final_script_for_tts = apply_pronunciation(st.session_state.recap_script_text, pron_dict)
                    st.write("၁။ pronunciation.txt ဖြင့် အသံထွက် စကားလုံးများ ပြင်ဆင်ပြီးပါပြီ...")
                    
                    # ၂။ Voiceover Generation (Speed multiplier applied)
                    st.write(f"၂။ [{voice_choice}] (Speed {voice_speed}x) ဖြင့် မြန်မာအသံဖိုင် ထုတ်ယူနေပါသည်...")
                    temp_audio_out = "temp_voice.mp3"
                    generate_voice_file(final_script_for_tts, voice_choice, temp_audio_out, speed_multiplier=voice_speed)
                    audio_dur = get_media_duration(temp_audio_out)
                    st.write(f"အသံကြာချိန်: {audio_dur:.1f} စက္ကန့်")
                    
                    # ၃။ Subtitle Generation (Max 30 chars per line)
                    st.write("၃။ စာလုံးရေ ၃၀ နှုန်းဖြင့် မြန်မာစာတန်းထိုး (SRT) ဖန်တီးနေပါသည်...")
                    temp_srt_path = "temp_sub.srt"
                    create_srt_subtitles(final_script_for_tts, audio_dur, temp_srt_path, max_chars_per_line=30)
                    
                    # ၄။ Final Render (A/V Sync, Speed, BGM Ducking, Anti-Copyright)
                    st.write("၄။ အသံ/ရုပ်/BGM Ducking/Anti-Copyright တို့ဖြင့် Render ပြုလုပ်နေပါသည်...")
                    final_video_output = "recap_output.mp4"
                    render_final_video(
                        input_video_path=temp_in,
                        audio_path=temp_audio_out,
                        srt_path=temp_srt_path,
                        output_video_path=final_video_output,
                        aspect_format=format_ratio,
                        video_speed=video_speed,
                        sub_color=sub_color,
                        sub_bg=sub_bg,
                        enable_anti_copyright=anti_copyright,
                        enable_bgm=bgm_choice
                    )
                    status.update(label="✅ Recap ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!", state="complete", expanded=False)
                    
                st.success("🎉 Recap ဗီဒီယို အောင်မြင်စွာ ထွက်ရှိပါပြီ!")
                
                # Audio Preview
                st.markdown("#### 🎙️ ထွက်ရှိလာသော အသံဖိုင်နှင့် စာတန်းထိုး")
                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    st.audio(temp_audio_out)
                with col_a2:
                    with open(temp_srt_path, "r", encoding="utf-8") as srt_f:
                        st.download_button("📥 SRT စာတန်းထိုးဖိုင် ဒေါင်းလုဒ်ဆွဲရန်", data=srt_f.read(), file_name="recap_subtitles.srt")

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
                else:
                    st.error("ဗီဒီယိုဖိုင် ထွက်ပေါ်မလာပါ။")
                    
            except Exception as e:
                st.error(f"❌ Error ဖြစ်ပေါ်ပါသည်: {str(e)}")

# ----------------- PAGE 3: အသံထွက်နှင့် ဝေါဟာရ စီမံရန် -----------------
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

# ----------------- PAGE 4: API & SETTINGS -----------------
elif st.session_state.nav_menu == "⚙️ API & Settings":
    st.markdown("## ⚙️ **စနစ် ဆက်တင်များနှင့် API Keys**")
    st.caption("Recap Studio MM ၏ API Key များကို ဆာဗာ refresh ဖြစ်သော်လည်း မပျောက်စေရန် အပြီးအပိုင် သိမ်းဆည်းထားနိုင်ပါသည်။")
    
    api_key_input = st.text_input("Google Gemini API Key", value=st.session_state.gemini_api_key, type="password", placeholder="AIzaSy...")
    
    if st.button("💾 API Key အပြီးအပိုင် သိမ်းဆည်းမည်", type="primary"):
        st.session_state.gemini_api_key = api_key_input
        save_config("gemini_api_key", api_key_input)
        st.success("✅ Gemini API Key ကို အပြီးအပိုင် မှတ်သားပြီးပါပြီ! (Website refresh လုပ်သော်လည်း ပျောက်မသွားတော့ပါ)")

# ----------------- OTHER PAGES -----------------
else:
    st.markdown(f"## {st.session_state.nav_menu}")
    st.info(f"{st.session_state.nav_menu} လုပ်ဆောင်ချက်များကို သင့် Recap Studio MM တွင် မကြာမီ ထပ်မံဖြည့်စွက်ပေးပါမည်။")
    st.button("🏠 ပင်မစာမျက်နှာသို့ ပြန်သွားရန်", on_click=navigate_to, args=("🏠 ပင်မစာမျက်နှာ",), key="btn_back_home")
