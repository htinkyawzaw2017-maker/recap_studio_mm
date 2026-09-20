import streamlit as st
import os
import re
import time
import asyncio
import subprocess

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- NAVIGATION CALLBACK -----------------
def navigate_to(page_name):
    st.session_state.nav_menu = page_name

if "nav_menu" not in st.session_state:
    st.session_state.nav_menu = "🏠 ပင်မစာမျက်နှာ"
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = os.getenv("GEMINI_API_KEY", "")

# Streamlit Secrets မှ API Key ကို စစ်ဆေးခြင်း
try:
    if not st.session_state.gemini_api_key and "GEMINI_API_KEY" in st.secrets:
        st.session_state.gemini_api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

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

# ----------------- REAL BACKEND PIPELINE (AI + TTS + FFMPEG) -----------------
def generate_recap_script(api_key, video_path, custom_instructions):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
သင်သည် အလွန်တော်သော မြန်မာ Movie Recap Storyteller တစ်ယောက် ဖြစ်သည်။
အောက်ပါ ဗီဒီယိုကို ကြည့်ရှုပြီး ပရိတ်သတ် စိတ်ဝင်စားဖွယ် နားထောင်စေမည့် မြန်မာဘာသာ Movie Recap အသံဖတ်ပြရန် ဇာတ်ညွှန်း (Voiceover Script) တစ်ခုကို ရေးပေးပါ။
စည်းမျဉ်းများ:
၁။ စကားလုံးများသည် နားထောင်ရလွယ်ပြီး ဆွဲဆောင်မှု ရှိရပါမည်။
၂။ မြန်မာလို အသံထွက်ဖတ်ပြမည့် စာသားသက်သက်ကိုသာ ထုတ်ပေးပါ (ဥပမာ [Scene 1], [Music] စသည့် အပိုစာသားများ မထည့်ပါနှင့်)။
၃။ ညွှန်ကြားချက်: {custom_instructions if custom_instructions else 'ဇာတ်လမ်းကို စိတ်ဝင်စားဖွယ် ဆွဲဆောင်မှုရှိစွာ ပြောပြပါ။'}
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

async def run_edge_tts(text, voice_name, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_path)

def generate_voice_file(text, voice_choice, output_audio_path):
    voice_map = {
        "သီဟ (Native Burmese - Male Narration)": "my-MM-ThihaNeural",
        "နဒီ (Native Burmese - Female Narration)": "my-MM-NilarNeural",
        "ကိုမင်း (Deep Voice - Movie Recap Specialist)": "my-MM-ThihaNeural",
        "မေသူ (Soft Voice - Drama/Emotional)": "my-MM-NilarNeural"
    }
    voice_code = voice_map.get(voice_choice, "my-MM-ThihaNeural")
    asyncio.run(run_edge_tts(text, voice_code, output_audio_path))

def render_video_ffmpeg(input_video_path, audio_path, output_video_path, aspect_format):
    aspect_filters = {
        "9:16": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "16:9": "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
        "4:5": "scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350",
        "1:1": "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    }
    vf = aspect_filters.get(aspect_format, "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video_path,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
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
        st.success("🔑 Gemini API: ချိတ်ဆက်ထားသည်")
    else:
        st.warning("⚠️ Gemini API Key မထည့်ရသေးပါ")
    st.caption("⚡ **Recap Studio MM Engine v2.0**")

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
    st.markdown("## 🎬 **ဗီဒီယို ပြုလုပ်ရန်**")
    st.caption("Video သို့မဟုတ် Link ထည့်ပြီး လုပ်ချင်တဲ့ Tool၊ ဘာသာစကား၊ အရွယ်အစားနဲ့ အသံကို ရွေးပါ။")
    
    # API Key ထည့်သွင်းရန် လိုအပ်ပါက ပြသပေးခြင်း
    if not st.session_state.gemini_api_key:
        api_input = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ (AI Recap ဇာတ်ညွှန်း ရေးရန် လိုအပ်ပါသည်)", type="password")
        if api_input:
            st.session_state.gemini_api_key = api_input
            st.success("API Key မှတ်သားပြီးပါပြီ!")
            st.rerun()
    
    tab_upload, tab_link = st.tabs(["📤 ဗီဒီယို တင်ရန်", "🔗 ဗီဒီယို လင့်ခ်"])
    
    uploaded_video = None
    video_url = ""
    
    with tab_upload:
        uploaded_video = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV သို့မဟုတ် WebM - max 1 GB)", type=["mp4", "mov", "webm"])
        if uploaded_video:
            st.success(f"ဖိုင်တင်ပြီးပါပြီ: {uploaded_video.name}")
            
    with tab_link:
        video_url = st.text_input("ဗီဒီယို Link ထည့်ပါ (YouTube, TikTok သို့မဟုတ် Direct Video URL)", placeholder="https://...")
        if video_url:
            st.info(f"ချိတ်ဆက်ထားသော Link: {video_url}")

    st.markdown("---")
    
    # Step 1: Mode Selection
    st.markdown("#### ၁။ ဘာပုံစံ ပြုလုပ်ချင်ပါသလဲ?")
    mode = st.radio(
        "ရွေးချယ်ရန်",
        [
            "🎙️ AI Recap (ဗီဒီယို အကျဉ်းချုပ် + အသံထွက်)",
            "📝 မြန်မာ စာတန်းထိုး (Subtitles)",
            "🎬 ရုပ်ရှင် ပြန်လည်ပြောပြ (Story Narration)",
            "✨ Vision Narrator (AI ဇာတ်ကွက် ခွဲခြမ်းစိတ်ဖြာခြင်း)"
        ],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    # Step 2 & 3: Language Settings
    col_lang1, col_lang2 = st.columns(2)
    with col_lang1:
        st.markdown("##### Source language (မူရင်းဗီဒီယို ဘာသာစကား)")
        source_lang = st.selectbox("Source Lang", ["Auto detect (အလိုအလျောက် သိရှိရန်)", "English", "Korean", "Chinese", "Japanese", "Thai"], label_visibility="collapsed")
    with col_lang2:
        st.markdown("##### စာတန်းထိုး/အသံ ဘာသာစကား")
        target_lang = st.selectbox("Target Lang", ["🇲🇲 မြန်မာ (မြန်မာအသံ + မြန်မာစာတန်း)", "🇬🇧 အင်္ဂလိပ် (English)"], label_visibility="collapsed")
        
    # Step 4: Custom Instructions
    st.markdown("#### ၂။ Custom Instructions (စိတ်ကြိုက် ညွှန်ကြားချက်များ)")
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ",
        placeholder="ဥပမာ - ရုပ်ရှင်ဇာတ်ညွှန်းကို လူငယ်သုံးစကားဖြင့် စိတ်ဝင်စားဖွယ် recap လုပ်ပါ။ ဇာတ်ကောင်အမည်များကို အသံထွက်မှန်အောင် ထည့်ပေးပါ။",
        height=90,
        label_visibility="collapsed"
    )

    # Step 5: Video Formats
    st.markdown("#### ၃။ ဗီဒီယို အရွယ်အစား (Format)")
    f_c1, f_c2, f_c3, f_c4 = st.columns(4)
    with f_c1:
        st.markdown('<div class="format-card"><b>4:5 Feed ပုံစံ</b><div style="font-size:11px; color:#94a3b8;">1080 × 1350<br>Facebook / IG</div></div>', unsafe_allow_html=True)
    with f_c2:
        st.markdown('<div class="format-card"><b>9:16 ဒေါင်လိုက်</b><div style="font-size:11px; color:#94a3b8;">1080 × 1920<br>TikTok / Reels</div></div>', unsafe_allow_html=True)
    with f_c3:
        st.markdown('<div class="format-card"><b>16:9 အလျားလိုက်</b><div style="font-size:11px; color:#94a3b8;">1920 × 1080<br>YouTube</div></div>', unsafe_allow_html=True)
    with f_c4:
        st.markdown('<div class="format-card"><b>1:1 စတုရန်း</b><div style="font-size:11px; color:#94a3b8;">1080 × 1080<br>Square</div></div>', unsafe_allow_html=True)
        
    format_choice = st.selectbox(
        "အသုံးပြုမည့် Format ကို ရွေးချယ်ပါ",
        ["9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)", "16:9 - အလျားလိုက် (YouTube)", "4:5 - Feed ပုံစံ (Facebook/IG)", "1:1 - စတုရန်း"]
    )
    format_ratio = format_choice.split(" - ")[0]
    
    # Step 6: Voice Selection
    st.markdown("#### ၄။ အသံရွေးချယ်မှု")
    col_v_select, col_v_sample = st.columns(2)
    with col_v_select:
        voice_choice = st.selectbox(
            "ပုံမှန်အသံ ရွေးရန်",
            [
                "သီဟ (Native Burmese - Male Narration)",
                "နဒီ (Native Burmese - Female Narration)",
                "ကိုမင်း (Deep Voice - Movie Recap Specialist)",
                "မေသူ (Soft Voice - Drama/Emotional)"
            ]
        )
    with col_v_sample:
        st.write("")
        st.write("")
        if st.button("▶ Sample နားထောင်ရန်", use_container_width=True):
            with st.spinner("အသံနမူနာ ဖန်တီးနေပါသည်..."):
                sample_audio = "sample_voice.mp3"
                generate_voice_file("မင်္ဂလာပါ Recap Studio MM မှ ကြိုဆိုပါတယ်။", voice_choice, sample_audio)
                st.audio(sample_audio)

    st.markdown("---")
    
    # ----------------- REAL GENERATION PROCESS -----------------
    if st.button("🚀 စတင်ဖန်တီးမည် (Generate Recap)", type="primary", use_container_width=True):
        if not uploaded_video and not video_url:
            st.error("⚠️ ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် ဗီဒီယို Link ထည့်သွင်းပေးပါ။")
        elif not st.session_state.gemini_api_key:
            st.error("⚠️ ကျေးဇူးပြု၍ Gemini API Key ထည့်သွင်းပေးပါ။")
        else:
            try:
                with st.status("🎬 Recap Studio MM မှ ဗီဒီယို ဖန်တီးနေပါသည်...", expanded=True) as status:
                    # ၁။ ဗီဒီယို သိမ်းဆည်းခြင်း
                    st.write("၁။ မူရင်းဗီဒီယိုဖိုင်ကို ပြင်ဆင်နေပါသည်...")
                    temp_video_input = "temp_input.mp4"
                    if uploaded_video:
                        with open(temp_video_input, "wb") as f:
                            f.write(uploaded_video.getbuffer())
                    elif video_url:
                        st.write("Link မှ ဗီဒီယို ဒေါင်းလုဒ်ရယူနေပါသည်...")
                        cmd_dl = ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", temp_video_input, video_url]
                        subprocess.run(cmd_dl, check=True)
                        
                    # ၂။ Gemini ဖြင့် ဇာတ်ညွှန်း ရေးသားခြင်း
                    st.write("၂။ Google Gemini AI ဖြင့် မြန်မာ Recap ဇာတ်ညွှန်း ရေးသားနေပါသည်...")
                    recap_script = generate_recap_script(
                        api_key=st.session_state.gemini_api_key,
                        video_path=temp_video_input,
                        custom_instructions=instructions
                    )
                    
                    # ၃။ Pronunciation Replacement
                    pron_dict = load_replacements("pronunciation.txt")
                    if pron_dict:
                        recap_script = apply_pronunciation(recap_script, pron_dict)
                        st.write(f"၃။ pronunciation.txt မှ စကားလုံး ({len(pron_dict)}) လုံးကို အသံထွက်မှန်အောင် အစားထိုးပြီးပါပြီ...")
                    else:
                        st.write("၃။ အသံထွက်နှင့် ဝေါဟာရ စစ်ဆေးခြင်း ပြီးမြောက်ပါပြီ...")
                        
                    # ၄။ Edge-TTS ဖြင့် မြန်မာအသံဖိုင် ထုတ်ယူခြင်း
                    st.write(f"၄။ [{voice_choice}] ဖြင့် မြန်မာအသံထွက် (Voiceover) သွင်းနေပါသည်...")
                    temp_audio_output = "temp_voice.mp3"
                    generate_voice_file(recap_script, voice_choice, temp_audio_output)
                    
                    # ၅။ FFmpeg ဖြင့် ဗီဒီယို Render ပြုလုပ်ခြင်း
                    st.write(f"၅။ Format [{format_ratio}] အတိုင်း ဗီဒီယိုနှင့် အသံကို Render ပြုလုပ်နေပါသည်...")
                    final_video_output = "recap_output.mp4"
                    render_video_ffmpeg(temp_video_input, temp_audio_output, final_video_output, format_ratio)
                    
                    status.update(label="✅ Recap ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!", state="complete", expanded=False)
                    
                st.success("🎉 Recap ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!")
                
                # ဖန်တီးထားသော Script နှင့် အသံဖိုင် ပြသခြင်း
                with st.expander("📝 ဖန်တီးထားသော AI Recap ဇာတ်ညွှန်း စာသားများ", expanded=True):
                    st.text_area("ဇာတ်ညွှန်း", value=recap_script, height=120)
                    st.audio(temp_audio_output)
                
                # ဗီဒီယို Player ဖြင့် တိုက်ရိုက်ပြသခြင်းနှင့် ဒေါင်းလုဒ်ဆွဲရန် ခလုတ်
                if os.path.exists(final_video_output):
                    st.video(final_video_output)
                    with open(final_video_output, "rb") as vid_file:
                        st.download_button(
                            label="📥 ပြီးစီးသော Recap ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် (MP4)",
                            data=vid_file.read(),
                            file_name="recap_studio_mm_output.mp4",
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
    st.caption("Recap Studio MM ကို ပိုမိုမြန်ဆန်ပြီး ကန့်သတ်ချက်မရှိစေရန် သင်၏ ကိုယ်ပိုင် API Keys များကို ထည့်သွင်းနိုင်ပါသည်။")
    
    api_key_input = st.text_input("Google Gemini API Key", value=st.session_state.gemini_api_key, type="password", placeholder="AIzaSy...")
    
    if st.button("💾 API Key သိမ်းဆည်းမည်", type="primary"):
        st.session_state.gemini_api_key = api_key_input
        st.success("✅ Gemini API Key ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ!")

# ----------------- OTHER PAGES -----------------
else:
    st.markdown(f"## {st.session_state.nav_menu}")
    st.info(f"{st.session_state.nav_menu} လုပ်ဆောင်ချက်များကို သင့် Recap Studio MM တွင် မကြာမီ ထပ်မံဖြည့်စွက်ပေးပါမည်။")
    st.button("🏠 ပင်မစာမျက်နှာသို့ ပြန်သွားရန်", on_click=navigate_to, args=("🏠 ပင်မစာမျက်နှာ",), key="btn_back_home")
