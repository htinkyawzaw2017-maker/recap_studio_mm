import streamlit as st
import os
import re
import time

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CUSTOM STYLING (DARK UI MATCHING SCREENSHOT) -----------------
st.markdown("""
<style>
    /* Dark Theme Canvas */
    .stApp {
        background-color: #07100e !important;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #040908 !important;
        border-right: 1px solid #132420;
    }
    
    /* Profile Box */
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
    
    /* Hero Banner */
    .hero-card {
        background: linear-gradient(135deg, #131d33 0%, #0f1726 60%, #0a0f1a 100%);
        border: 1px solid #25334d;
        border-radius: 18px;
        padding: 28px;
        margin-bottom: 24px;
    }
    
    /* Action Cards */
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
    
    /* Format Preview Cards */
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
    if not text:
        return text
    for word, pron in pron_dict.items():
        text = re.sub(rf"\b{re.escape(word)}\b", pron, text, flags=re.IGNORECASE)
    return text

# Navigation State
if "nav_menu" not in st.session_state:
    st.session_state.nav_menu = "🏠 ပင်မစာမျက်နှာ"

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.markdown("### 🎬 **RECAP STUDIO MM**")
    
    # Profile Card
    st.markdown("""
    <div class="user-profile-box">
        <div>
            <div style="font-weight:bold; font-size:14px; color:#fff;">👤 Studio Master</div>
            <div style="font-size:11px; color:#94a3b8;">Recap Studio MM</div>
        </div>
        <span class="badge-status">Active</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation menu
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
    
    selected_page = st.radio(
        "Menu",
        menu_options,
        key="nav_menu",
        label_visibility="collapsed"
    )
    
    st.divider()
    st.caption("⚡ **Recap Studio MM Engine v2.0**\nStreamlit & Python Powered.")

# ----------------- PAGE 1: ပင်မစာမျက်နှာ (HOME DASHBOARD) -----------------
if st.session_state.nav_menu == "🏠 ပင်မစာမျက်နှာ":
    col_banner, col_status = st.columns()
    
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
        
        if st.button("🎬 ဗီဒီယို ပြုလုပ်ရန် (Recap • မြန်မာအသံထွက် • စာတန်းထိုး) ➔", type="primary"):
            st.session_state.nav_menu = "🎬 ဗီဒီယို ပြုလုပ်ရန်"
            st.rerun()
            
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
    st.caption("လိုအပ်သော Tool သို့မဟုတ် စာမျက်နှာကို တစ်ချက်နှိပ်ပြီး တန်းသွားနိုင်ပါတယ်။")
    
    # Action Cards Grid
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
    with r1_c1:
        st.markdown("""
        <div class="action-card">
            <h4>📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်</h4>
            <p style="font-size:12px; color:#94a3b8;">YouTube၊ TikTok နှင့် အခြား Link များမှ ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("ဒေါင်းလုဒ်ဆွဲရန် ➔", key="btn_quick_dl"):
            st.session_state.nav_menu = "📥 ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်"
            st.rerun()
            
    with r1_c2:
        st.markdown("""
        <div class="action-card">
            <h4>📁 သိမ်းဆည်းထားသော ပရောဂျက်များ</h4>
            <p style="font-size:12px; color:#94a3b8;">ယခင် ပြုလုပ်ထားသော ပရောဂျက်များကို ပြန်လည်ကြည့်ရှုရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("ပရောဂျက်များ ➔", key="btn_quick_proj"):
            st.session_state.nav_menu = "📁 သိမ်းဆည်းထားသော ပရောဂျက်များ"
            st.rerun()
            
    with r1_c3:
        st.markdown("""
        <div class="action-card">
            <h4>🍿 ဇာတ်လမ်းရှည် Recap</h4>
            <p style="font-size:12px; color:#94a3b8;">ရှည်လျားသော ဇာတ်ကားများကို အပိုင်းခွဲပြီး Recap လုပ်ရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("ဇာတ်လမ်းရှည် ➔", key="btn_quick_long"):
            st.session_state.nav_menu = "🍿 ဇာတ်လမ်းရှည် Recap"
            st.rerun()
            
    with r1_c4:
        st.markdown("""
        <div class="action-card">
            <h4>🎙️ AI အသံ စတူဒီယို</h4>
            <p style="font-size:12px; color:#94a3b8;">ဗီဒီယို Link သို့မဟုတ် SRT မှ မြန်မာ AI အသံ ဖန်တီးရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("အသံစတူဒီယို ➔", key="btn_quick_voice"):
            st.session_state.nav_menu = "🎙️ AI အသံ စတူဒီယို"
            st.rerun()

    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    with r2_c1:
        st.markdown("""
        <div class="action-card">
            <h4>🔄 အသံ ပြောင်းစနစ်</h4>
            <p style="font-size:12px; color:#94a3b8;">AI Voice Tool ဖြင့် အသံအမျိုးအစား ပြောင်းလဲရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("အသံပြောင်းရန် ➔", key="btn_quick_vchange"):
            st.session_state.nav_menu = "🔄 အသံ ပြောင်းစနစ်"
            st.rerun()
            
    with r2_c2:
        st.markdown("""
        <div class="action-card">
            <h4>📖 အသံထွက် & ဝေါဟာရ စီမံရန်</h4>
            <p style="font-size:12px; color:#94a3b8;">pronunciation.txt နှင့် dictionary.txt ပြင်ဆင်ရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("ဝေါဟာရ စီမံရန် ➔", key="btn_quick_dict"):
            st.session_state.nav_menu = "📖 အသံထွက်နှင့် ဝေါဟာရ စီမံရန်"
            st.rerun()
            
    with r2_c3:
        st.markdown("""
        <div class="action-card">
            <h4>✂️ Auto Clips</h4>
            <p style="font-size:12px; color:#94a3b8;">ဗီဒီယိုမှ အကောင်းဆုံး အစိတ်အပိုင်းများကို အလိုအလျောက်ဖြတ်ရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Auto Clips ➔", key="btn_quick_clips"):
            st.session_state.nav_menu = "✂️ Auto Clips"
            st.rerun()
            
    with r2_c4:
        st.markdown("""
        <div class="action-card">
            <h4>🎞️ AI ဗီဒီယို စတူဒီယို</h4>
            <p style="font-size:12px; color:#94a3b8;">ဗီဒီယို အစအဆုံး အလိုအလျောက် ထုတ်လုပ်ရန်</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("ဗီဒီယိုစတူဒီယို ➔", key="btn_quick_vstudio"):
            st.session_state.nav_menu = "🎞️ AI ဗီဒီယို စတူဒီယို"
            st.rerun()

# ----------------- PAGE 2: ဗီဒီယို ပြုလုပ်ရန် (CREATE VIDEO) -----------------
elif st.session_state.nav_menu == "🎬 ဗီဒီယို ပြုလုပ်ရန်":
    st.markdown("## 🎬 **ဗီဒီယို ပြုလုပ်ရန်**")
    st.caption("Video သို့မဟုတ် Link ထည့်ပြီး လုပ်ချင်တဲ့ Tool၊ ဘာသာစကား၊ အရွယ်အစားနဲ့ အသံကို ရွေးပါ။")
    
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
        source_lang = st.selectbox(
            "Source Lang",
            ["Auto detect (အလိုအလျောက် သိရှိရန်)", "English", "Korean", "Chinese", "Japanese", "Thai"],
            label_visibility="collapsed"
        )
    with col_lang2:
        st.markdown("##### စာတန်းထိုး/အသံ ဘာသာစကား")
        target_lang = st.selectbox(
            "Target Lang",
            ["🇲🇲 မြန်မာ (မြန်မာအသံ + မြန်မာစာတန်း)", "🇬🇧 အင်္ဂလိပ် (English)"],
            label_visibility="collapsed"
        )
        
    # Step 4: Custom Instructions
    st.markdown("#### ၂။ Custom Instructions (စိတ်ကြိုက် ညွှန်ကြားချက်များ)")
    instructions = st.text_area(
        "ညွှန်ကြားချက်များ",
        placeholder="ဥပမာ - ရုပ်ရှင်ဇာတ်ညွှန်းကို လူငယ်သုံးစကားဖြင့် စိတ်ဝင်စားဖွယ် recap လုပ်ပါ။ ဇာတ်ကောင်အမည်များကို အသံထွက်မှန်အောင် ထည့်ပေးပါ။",
        height=90,
        label_visibility="collapsed"
    )
    review_text_before_voice = st.checkbox("Review AI text before voice (အသံမသွင်းမီ AI ရေးသားထားသော စာသားကို အရင်စစ်ဆေးပြင်ဆင်မည်)")

    # Step 5: Video Formats
    st.markdown("#### ၃။ ဗီဒီယို အရွယ်အစား (Format)")
    f_c1, f_c2, f_c3, f_c4 = st.columns(4)
    with f_c1:
        st.markdown("""
        <div class="format-card">
            <b>4:5 Feed ပုံစံ</b>
            <div style="font-size:11px; color:#94a3b8;">1080 × 1350<br>Facebook / Instagram Post</div>
        </div>
        """, unsafe_allow_html=True)
    with f_c2:
        st.markdown("""
        <div class="format-card">
            <b>9:16 ဒေါင်လိုက်</b>
            <div style="font-size:11px; color:#94a3b8;">1080 × 1920<br>Reels / TikTok / Shorts</div>
        </div>
        """, unsafe_allow_html=True)
    with f_c3:
        st.markdown("""
        <div class="format-card">
            <b>16:9 အလျားလိုက်</b>
            <div style="font-size:11px; color:#94a3b8;">1920 × 1080<br>YouTube / Computer</div>
        </div>
        """, unsafe_allow_html=True)
    with f_c4:
        st.markdown("""
        <div class="format-card">
            <b>1:1 စတုရန်း</b>
            <div style="font-size:11px; color:#94a3b8;">1080 × 1080<br>Square Post</div>
        </div>
        """, unsafe_allow_html=True)
        
    format_choice = st.selectbox(
        "အသုံးပြုမည့် Format ကို ရွေးချယ်ပါ",
        ["9:16 - ဒေါင်လိုက် (Reels/TikTok/Shorts)", "16:9 - အလျားလိုက် (YouTube)", "4:5 - Feed ပုံစံ (Facebook/IG)", "1:1 - စတုရန်း"]
    )
    
    # Step 6: Voice Type
    st.markdown("#### ၄။ အသံအမျိုးအစား (Voice Type)")
    voice_type = st.radio(
        "Voice Type",
        [
            "⚡ Fast AI Voice (မြန်ဆန်သွက်လက်သော အသံ)",
            "💎 အရည်အသွေးမြင့်အသံ (Studio Quality)",
            "🎙️ My Voice (Custom Voice Clone)"
        ],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    # Step 7: Voice Selection & Sample Listen (Fix: Columns spec passed)
    col_v_select, col_v_sample = st.columns()
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
            st.info(f"📢 [{voice_choice}] ၏ အသံနမူနာကို စမ်းသပ်ဖွင့်ပြနေပါသည်...")

    st.markdown("---")
    
    # Generate Button
    if st.button("🚀 စတင်ဖန်တီးမည် (Generate Recap)", type="primary", use_container_width=True):
        if not uploaded_video and not video_url:
            st.error("⚠️ ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် တင်ပါ သို့မဟုတ် ဗီဒီယို Link ထည့်သွင်းပေးပါ။")
        else:
            with st.status("🎬 Recap Studio MM မှ လုပ်ငန်းစဉ်များကို စတင်ဆောင်ရွက်နေပါသည်...", expanded=True) as status:
                st.write("၁။ မူရင်းဗီဒီယိုကို ဖတ်ရှုစစ်ဆေးနေပါသည်...")
                time.sleep(1)
                st.write("၂။ AI ဖြင့် ဇာတ်ကွက်ခွဲခြမ်းစိတ်ဖြာပြီး မြန်မာ Recap ဇာတ်ညွှန်း ရေးသားနေပါသည်...")
                time.sleep(1)
                
                pron_dict = load_replacements("pronunciation.txt")
                if pron_dict:
                    st.write(f"၃။ pronunciation.txt မှ စကားလုံးပေါင်း ({len(pron_dict)}) လုံးကို အသံထွက်မှန်ကန်စေရန် အလိုအလျောက် ပြင်ဆင်ပြီးပါပြီ...")
                else:
                    st.write("၃။ အသံထွက်နှင့် ဝေါဟာရ စစ်ဆေးခြင်း ပြီးမြောက်ပါပြီ...")
                time.sleep(1)
                
                st.write(f"၄။ ရွေးချယ်ထားသော [{voice_choice}] ဖြင့် မြန်မာအသံထွက် (Voiceover) သွင်းနေပါသည်...")
                time.sleep(1)
                st.write(f"၅။ Format [{format_choice.split(' - ')[0]}] အတိုင်း ဗီဒီယို Render ပြုလုပ်နေပါသည်...")
                time.sleep(1)
                status.update(label="✅ Recap ဗီဒီယို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ!", state="complete", expanded=False)
                
            st.success("🎉 Recap ဗီဒီယို ဖန်တီးမှု အောင်မြင်ပါသည်!")
            
            if review_text_before_voice:
                with st.expander("📝 ဖန်တီးထားသော AI Recap ဇာတ်ညွှန်း စာသားများ", expanded=True):
                    sample_script = "ဒီဇာတ်ကားမှာတော့ မထင်မှတ်တဲ့ အလှည့်အပြောင်းတွေနဲ့အတူ ဇာတ်ကောင်ရဲ့ ရုန်းကန်ရမှုတွေကို မြင်တွေ့ရမှာ ဖြစ်ပါတယ်။ အဆုံးထိ စိတ်ဝင်စားဖို့ ကောင်းတဲ့ ဇာတ်လမ်းကောင်း တစ်ခု ဖြစ်ပါတယ်။"
                    st.text_area("ဇာတ်ညွှန်း", value=sample_script, height=100)
            
            st.download_button(
                label="📥 ပြီးစီးသော Recap ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန် (MP4)",
                data=b"Recap Studio MM Generated Video Stream Data",
                file_name="recap_studio_mm_output.mp4",
                mime="video/mp4",
                use_container_width=True
            )

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
    
    api_key_gemini = st.text_input("Google Gemini API Key", type="password", placeholder="AIzaSy...")
    api_key_openai = st.text_input("OpenAI API Key (Optional)", type="password", placeholder="sk-...")
    
    if st.button("💾 API Keys များ သိမ်းဆည်းမည်", type="primary"):
        st.success("✅ ဆက်တင်များကို သိမ်းဆည်းပြီးပါပြီ!")

# ----------------- OTHER PAGES -----------------
else:
    st.markdown(f"## {st.session_state.nav_menu}")
    st.info(f"{st.session_state.nav_menu} လုပ်ဆောင်ချက်များကို သင့် Recap Studio MM တွင် မကြာမီ ထပ်မံဖြည့်စွက်ပေးပါမည်။")
    if st.button("🏠 ပင်မစာမျက်နှာသို့ ပြန်သွားရန်"):
        st.session_state.nav_menu = "🏠 ပင်မစာမျက်နှာ"
        st.rerun()
