"""Recap Studio MM: a Burmese-first video recap, voice-over and subtitle app."""

import importlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import edge_tts
import google.generativeai as genai
import requests
import streamlit as st
import whisper
import yt_dlp
from google.cloud import texttospeech
from google.oauth2 import service_account

APP_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = APP_DIR / "user_sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Single-user local persistence (no database). These plain files live next to
# app.py on the running server so a page refresh (new browser session) does
# not wipe the saved Gemini key / Google credentials. NOTE: on Streamlit
# Community Cloud this survives refreshes and sleep/wake, but a fresh
# redeploy from GitHub resets the container disk — that is expected without
# a real database.
CONFIG_PATH = APP_DIR / "local_config.json"
GOOGLE_CREDS_PATH = APP_DIR / "local_google_creds.json"

st.set_page_config(page_title="Recap Studio MM", page_icon="🎞️", layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
SESSION_DIR = SESSIONS_DIR / st.session_state.session_id
SESSION_DIR.mkdir(parents=True, exist_ok=True)

PATHS = {
    "source": SESSION_DIR / "source.mp4",
    "audio": SESSION_DIR / "source_audio.wav",
    "voice": SESSION_DIR / "recap_voice.mp3",
    "bgm": SESSION_DIR / "background_music.mp3",
    "caption_source": SESSION_DIR / "caption_source.mp4",
    "caption_audio": SESSION_DIR / "caption_audio.wav",
    "caption_ass": SESSION_DIR / "captions.ass",
    "caption_srt": SESSION_DIR / "captions.srt",
    "caption_video": SESSION_DIR / "captioned_video.mp4",
    "dub_audio": SESSION_DIR / "dubbed_audio.mp3",
    "cookies": SESSION_DIR / "cookies.txt",
}

# Two ways a video can reach Subtitle Studio:
#  1. It has real speech -> transcribe the audio directly.
#  2. It is silent footage that Recap Builder's "AI ကြည့်ပြီးရေးမည်" mode
#     already turned into a finished script -> that script must be time
#     aligned to the video's visuals instead of transcribing (there is no
#     audio to transcribe). Putting this option first and auto-selecting it
#     when a silent-video script is handed over avoids the previous mistake
#     of users landing on the audio-transcription mode and getting a
#     confusing "no speech found" error.
SUBTITLE_MODE_SCRIPT_ALIGN = "Recap Builder ရဲ့ AI script ကို timing ချိန်ညှိမည် (အသံမပါသော ဗီဒီယိုအတွက် — အကြံပြု)"
SUBTITLE_MODE_AUDIO = "ဗီဒီယို အသံမှ တိုက်ရိုက်ထုတ်မည် (video မှာ မူရင်းအသံပါလျှင်)"
SUBTITLE_MODE_OPTIONS = [SUBTITLE_MODE_SCRIPT_ALIGN, SUBTITLE_MODE_AUDIO]

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800;900&family=Noto+Sans+Myanmar:wght@400;500;600;700&display=swap');
      :root { --ink:#eef1f8; --muted:#97a3ba; --line:rgba(193,207,232,.13); --aqua:#30d5c8; --violet:#8e7dff; }
      * { box-sizing:border-box; }
      .stApp { background:radial-gradient(circle at 12% -10%,rgba(48,213,200,.16),transparent 30rem),radial-gradient(circle at 94% 0%,rgba(142,125,255,.15),transparent 30rem),#0a0e1a; color:var(--ink); font-family:"Noto Sans Myanmar","DM Sans",sans-serif; }
      [data-testid="stSidebar"] { background:#0e1524; border-right:1px solid var(--line); }
      [data-testid="stSidebar"] * { color:var(--ink); }
      [data-testid="stSidebar"] .block-container { padding-top:1.4rem; }
      .block-container { max-width:1360px; padding-top:2rem; padding-bottom:4rem; }
      h1,h2,h3,h4,p,label,.stMarkdown { color:var(--ink) !important; }
      ::-webkit-scrollbar { width:10px; height:10px; }
      ::-webkit-scrollbar-thumb { background:rgba(48,213,200,.35); border-radius:8px; }

      .hero { position:relative; overflow:hidden; padding:2rem 2.2rem; margin:0 0 1.6rem; border:1px solid rgba(96,225,216,.24); border-radius:24px; background:linear-gradient(125deg,rgba(19,38,54,.96),rgba(28,29,60,.9)); box-shadow:0 20px 60px rgba(0,0,0,.28); }
      .hero::after { content:""; position:absolute; inset:0; background:linear-gradient(120deg,transparent,rgba(142,125,255,.08),transparent); pointer-events:none; }
      .eyebrow { display:inline-flex; align-items:center; gap:.4rem; color:var(--aqua) !important; font-size:.72rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; margin:0 0 .7rem; padding:.3rem .7rem; border:1px solid rgba(48,213,200,.3); border-radius:999px; background:rgba(48,213,200,.08); }
      .hero h1 { font-family:"DM Sans","Noto Sans Myanmar",sans-serif; font-size:2.3rem; margin:0; font-weight:900; letter-spacing:-.02em; background:linear-gradient(100deg,#eef1f8,#bfeee8 60%,#eef1f8); -webkit-background-clip:text; background-clip:text; }
      .hero p { color:#c4cee0 !important; margin:.6rem 0 0; font-size:1.02rem; max-width:52rem; line-height:1.6; }
      .hero-badges { display:flex; gap:.5rem; flex-wrap:wrap; margin-top:1rem; }
      .hero-badge { font-size:.74rem; font-weight:600; color:#bcd8ff !important; padding:.28rem .65rem; border-radius:999px; background:rgba(142,125,255,.12); border:1px solid rgba(142,125,255,.28); }

      .step-card { display:flex; gap:.85rem; align-items:flex-start; padding:1rem 1.05rem; min-height:5.4rem; border-radius:16px; border:1px solid var(--line); background:rgba(18,26,42,.78); transition:transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
      .step-card:hover { transform:translateY(-2px); border-color:rgba(48,213,200,.4); box-shadow:0 12px 30px rgba(0,0,0,.25); }
      .step-icon { font-size:1.35rem; line-height:1.4rem; }
      .step-num { font:800 .72rem "DM Sans"; color:var(--aqua); letter-spacing:.08em; }
      .step-label { color:#d6dded !important; font-size:.87rem; margin-top:.15rem; line-height:1.35; }

      .label,.section-lead,.small-note { color:var(--muted) !important; font-size:.86rem; margin-top:.35rem; }
      .section-title { font:800 1.2rem "DM Sans","Noto Sans Myanmar",sans-serif; margin:.2rem 0; display:flex; align-items:center; gap:.5rem; letter-spacing:-.01em; }
      .section-lead { margin:0 0 1.1rem; font-size:.92rem; line-height:1.55; }

      .stButton > button,.stDownloadButton > button { border:0; border-radius:12px; color:#06161a !important; font-weight:700; letter-spacing:.01em; background:linear-gradient(100deg,var(--aqua),#7ce6d5); min-height:2.75rem; box-shadow:0 8px 20px rgba(48,213,200,.16); transition:filter .15s ease, transform .15s ease, box-shadow .15s ease; }
      .stButton > button:hover,.stDownloadButton > button:hover { filter:brightness(1.08); transform:translateY(-1px); box-shadow:0 12px 26px rgba(48,213,200,.26); }
      .stButton > button:focus,.stDownloadButton > button:focus { outline:2px solid rgba(48,213,200,.55) !important; outline-offset:2px; }
      .stTextInput input,.stTextArea textarea,[data-baseweb="select"] > div,[data-testid="stFileUploader"] { background:#111a2a !important; color:var(--ink) !important; border-color:rgba(193,207,232,.18) !important; border-radius:12px !important; }
      .stTextArea textarea { line-height:1.9; }
      [data-testid="stFileUploader"] { padding:.4rem; }
      .stRadio label p, .stSelectbox label p, .stTextInput label p, .stTextArea label p, .stSlider label p, .stFileUploader label p, .stCheckbox label p { color:#cdd8e9 !important; font-weight:600 !important; font-size:.86rem !important; }

      [data-baseweb="tab-list"] { gap:.5rem; border-bottom:1px solid var(--line); }
      button[data-baseweb="tab"] { color:var(--muted); font-weight:700; padding:.8rem 1.1rem; border-radius:10px 10px 0 0; }
      button[data-baseweb="tab"]:hover { color:#cdd8e9; background:rgba(48,213,200,.05); }
      button[data-baseweb="tab"][aria-selected="true"] { color:var(--aqua); border-bottom-color:var(--aqua); }

      [data-baseweb="slider"] div[role="slider"] { background:var(--aqua) !important; box-shadow:0 0 0 5px rgba(48,213,200,.16) !important; }
      [data-baseweb="slider"] > div > div { background:rgba(48,213,200,.4) !important; }

      [data-testid="stExpander"] { border:1px solid var(--line) !important; border-radius:14px !important; background:rgba(15,22,36,.6) !important; overflow:hidden; }
      .stAlert { border-radius:14px !important; border:1px solid var(--line) !important; }

      .callout { padding:1rem 1.15rem; margin:.7rem 0 1.1rem; border-left:3px solid var(--aqua); border-radius:0 12px 12px 0; background:rgba(48,213,200,.07); color:#cdd8e9; font-size:.9rem; line-height:1.6; }
      .callout.warn { border-left-color:#ffb454; background:rgba(255,180,84,.08); }
      hr { border-color:var(--line) !important; margin:1.6rem 0 !important; }
      .footer-note { text-align:center; color:var(--muted); font-size:.8rem; margin-top:2rem; }
      details { border:1px solid var(--line); border-radius:12px; padding:.2rem .3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_local_config():
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return data.get("gemini_keys", ""), data.get("model_name", "gemini-2.5-flash")
        except (json.JSONDecodeError, OSError):
            return "", "gemini-2.5-flash"
    return "", "gemini-2.5-flash"


def save_local_config(raw_keys, model_name):
    try:
        CONFIG_PATH.write_text(json.dumps({"gemini_keys": raw_keys, "model_name": model_name}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_local_google_creds():
    if GOOGLE_CREDS_PATH.exists():
        try:
            return json.loads(GOOGLE_CREDS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_local_google_creds(info):
    try:
        GOOGLE_CREDS_PATH.write_text(json.dumps(info), encoding="utf-8")
    except OSError:
        pass


def init_state():
    saved_raw, saved_model = load_local_config()
    for key, value in {
        "api_keys": [key.strip() for key in saved_raw.split(",") if key.strip()],
        "model_name_value": saved_model,
        "google_creds": None, "raw_transcript": "", "final_script": "",
        "script_editor": "", "processed_video": None, "processed_audio": None,
        "caption_video": None, "srt_path": None, "publish_kit": "",
        "segments": None, "dub_language": None, "dubbed_video": None,
        "last_download_url": "", "script_language": "မြန်မာ", "script_video_is_silent": False,
        "subtitle_mode": SUBTITLE_MODE_AUDIO, "has_cookies": False,
    }.items():
        st.session_state.setdefault(key, value)
    if st.session_state.google_creds is None:
        saved_info = load_local_google_creds()
        if saved_info:
            try:
                st.session_state.google_creds = service_account.Credentials.from_service_account_info(saved_info)
            except (ValueError, TypeError):
                pass


init_state()


@st.cache_resource(ttl=24 * 3600, show_spinner=False)
def ensure_ytdlp_fresh():
    """YouTube changes what it serves to yt-dlp every few weeks, and the
    single highest-success mitigation is simply always running the newest
    yt-dlp release (the project usually ships a counter-fix within days).
    This runs at most once per day per server process — cheap, silent, and
    means users do not have to remember to click the manual update button
    in the sidebar for downloads to keep working."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "--no-cache-dir", "yt-dlp"],
            capture_output=True, text=True, check=False, timeout=90,
        )
        importlib.reload(yt_dlp)
    except Exception:
        pass
    return True


ensure_ytdlp_fresh()


def load_dictionary():
    path = APP_DIR / "dictionary.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def pronunciation_dictionary():
    path = APP_DIR / "pronunciation.txt"
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() and value.strip():
                result[key.strip()] = value.strip()
    return result


def require_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    st.error("FFmpeg မတွေ့ပါ။")
    return False


def run_media(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        return False, str(error)
    return (True, "") if result.returncode == 0 else (False, (result.stderr or "Media processing failed.")[-900:])


def duration_of(path):
    if not require_ffmpeg():
        return 0
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=False)
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def atempo_filter_chain(factor):
    """ffmpeg's atempo filter is documented as safe within 0.5x-2.0x per
    instance, so factors outside that range (needed for the 0.4x-3.0x
    narration-speed slider) are decomposed into a chain of atempo stages
    that multiply out to the exact requested factor."""
    factor = max(0.1, min(factor, 20.0))
    remaining = factor
    stages = []
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)
    return ",".join(f"atempo={stage:.6f}" for stage in stages)


def save_upload(upload, destination):
    destination.write_bytes(upload.getbuffer())


def transcribe(video, audio, language=None):
    """Render Free Tier RAM (512MB) သက်သာစေရန် Gemini API ဖြင့် တိုက်ရိုက် transcribe လုပ်ခြင်း"""
    if not require_ffmpeg():
        return None, None
    ok, details = run_media(["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "libmp3lame", "-b:a", "64k", str(SESSION_DIR / "audio_small.mp3")])
    if not ok:
        st.error(f"အသံထုတ်မရပါ — {details}")
        return None, None

    if st.session_state.api_keys:
        try:
            genai.configure(api_key=st.session_state.api_keys[0])
            small_audio = SESSION_DIR / "audio_small.mp3"
            audio_file = genai.upload_file(path=str(small_audio))
            while audio_file.state.name == "PROCESSING":
                time.sleep(1)
                audio_file = genai.get_file(audio_file.name)

            prompt = "Transcribe the spoken audio into plain text accurately without timestamps or commentary."
            if language:
                prompt += f" The language is {language}."

            model = genai.GenerativeModel(st.session_state.model_name)
            response = model.generate_content([audio_file, prompt])
            genai.delete_file(audio_file.name)
            text = response.text.strip() if response.text else ""
            return text, []
        except Exception as api_err:
            st.warning(f"Cloud transcription error, falling back to local: {api_err}")

    # Fallback to tiny whisper if Gemini fails
    try:
        model = whisper.load_model("tiny")
        options = {"task": "transcribe"}
        if language:
            options["language"] = language
        data = model.transcribe(str(SESSION_DIR / "audio_small.mp3"), **options)
        return data.get("text", "").strip(), data.get("segments", [])
    except Exception as error:
        st.error(f"Speech recognition မအောင်မြင်ပါ — {error}")
        return None, None


def _clear_destination(destination):
    if destination.exists():
        try:
            destination.unlink()
        except OSError:
            pass
    for leftover in destination.parent.glob(destination.stem + ".*"):
        try:
            leftover.unlink()
        except OSError:
            pass


def installed_ytdlp_version():
    return getattr(yt_dlp, "version", None) and getattr(yt_dlp.version, "__version__", "unknown") or "unknown"


def update_ytdlp():
    """Manual, on-demand version of ensure_ytdlp_fresh() for the sidebar
    button — useful right after YouTube ships a breaking change and a user
    does not want to wait for the daily automatic refresh."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "--no-cache-dir", "yt-dlp"],
            capture_output=True, text=True, check=False, timeout=120,
        )
        if result.returncode != 0:
            return False, (result.stderr or "pip install မအောင်မြင်ပါ။")[-600:]
        importlib.reload(yt_dlp)
        ensure_ytdlp_fresh.clear()
        return True, installed_ytdlp_version()
    except Exception as error:
        return False, str(error)


def download_video(url, destination, cookies_path=None):
    """Robust YouTube / public-video download that always lands on `destination`.

    YouTube regularly changes what it serves to yt-dlp's default player
    client, which causes "Requested format is not available" / HTTP 403
    even though the video plays fine in a browser. The mitigations applied
    here, in order of real-world effectiveness, are: (1) always run the
    freshest yt-dlp (see `ensure_ytdlp_fresh`, which runs automatically once
    a day, plus the sidebar's manual update button), (2) retry extraction
    with several different player clients — starting with the ones that
    currently need no proof-of-origin token for most public videos — before
    falling back to ones that do, (3) prefer IPv4 egress, which YouTube's
    bot-detection trusts more than many hosting providers' IPv6 ranges, and
    (4) accept browser-exported cookies for videos that require a
    logged-in session.
    """
    _clear_destination(destination)
    cookies_path = cookies_path if cookies_path and Path(cookies_path).exists() else None

    attempts = [
        {"player_client": ["tv_embedded"], "ipv4": True},
        {"player_client": ["tv"], "ipv4": True},
        {"player_client": ["mweb"], "ipv4": True},
        {"player_client": ["ios"], "ipv4": True},
        {"player_client": ["android"], "ipv4": True},
        {"player_client": ["web_embedded"], "ipv4": True},
        {"player_client": ["web_safari"], "ipv4": True},
        {"player_client": ["default", "-android_sdkless"], "ipv4": True},
        {"player_client": ["web", "tv_embedded"], "ipv4": True},
        {"format": "b", "ipv4": False},  # best single progressive stream, no client override
        {"ipv4": False},  # yt-dlp default behaviour as a last resort
    ]
    last_error = ""
    for attempt_index, extra_args in enumerate(attempts):
        _clear_destination(destination)
        if attempt_index > 0:
            time.sleep(1.2)  # avoid tight retry loops, which make bot-detection worse, not better
        player_client = extra_args.get("player_client")
        options = {
            "format": extra_args.get("format", "bestvideo*+bestaudio/best"),
            "outtmpl": str(destination),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            "extractor_retries": 3,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        }
        if extra_args.get("ipv4"):
            options["source_address"] = "0.0.0.0"
        if cookies_path:
            options["cookiefile"] = str(cookies_path)
        if player_client:
            options["extractor_args"] = {"youtube": {"player_client": player_client, "formats": ["missing_pot"]}}
        try:
            with yt_dlp.YoutubeDL(options) as client:
                client.download([url])
            if destination.exists() and destination.stat().st_size > 10_000:
                return True, ""
        except Exception as error:
            last_error = str(error)

    _clear_destination(destination)
    if last_error:
        lowered = last_error.lower()
        if "sign in" in lowered or "bot" in lowered or "confirm" in lowered:
            return False, "ဒီဗီဒီယိုကို YouTube က bot-check / login လိုအပ်အောင် ကန့်သတ်ထားပါတယ်။ Sidebar ရဲ့ 'YouTube cookies.txt' ကိုတင်ပြီး ပြန်စမ်းကြည့်ပါ (Chrome/Firefox extension ဖြင့် youtube.com ကို login ဝင်ထားစဉ် export လုပ်ပါ)။"
        if "private" in lowered or "unavailable" in lowered:
            return False, "ဒီဗီဒီယိုကို ဒေါင်းလုဒ်လုပ်ခွင့်မရှိပါ (private/unavailable)။"
        if "format is not available" in lowered or "requested format" in lowered or "403" in lowered:
            return False, "YouTube ဘက်က format ချထားမှု ပြောင်းသွားလို့ ဒေါင်းလုဒ်မရပါ။ App က yt-dlp ကို တစ်နေ့ တစ်ခါ အလိုအလျောက် update လုပ်ပေးထားပေမယ့်၊ YouTube ပြောင်းလိုက်ပြီး မကြာသေးရင် Sidebar ရဲ့ '🔄 yt-dlp update' ခလုတ်ကို နှိပ်ပြီး ချက်ချင်း update ဆွဲကြည့်ပါ။ ဆက်မရပါက cookies.txt တင်ပြီးထပ်စမ်းပါ။"
    return False, last_error or "ဗီဒီယိုကို ဒေါင်းလုဒ်လုပ်၍မရပါ။ Link ကိုပြန်စစ်ပါ။"


BURMESE_RULES = """
သင်သည် မြန်မာပရိသတ်အတွက် အတွေ့အကြုံရှိသော recap narrator ဖြစ်သည်။
အောက်က transcript ကို အဓိပ္ပာယ်မပျက်စေဘဲ စကားပြောသဘာဝကျသော မြန်မာ recap narration အဖြစ် ပြန်ရေးပါ။

မဖြစ်မနေလိုက်နာရမည့် စည်းကမ်းများ
1. စဖွင့်ချိတ်ဆက်ချက် → အခြေအနေ/နောက်ခံ → ပြဿနာ → အလှည့်အပြောင်း → ရလဒ် → အဆုံးသတ်အနှစ်ချုပ် အစဉ်လိုက်စီးဆင်းအောင်ရေးပါ။
2. မြင်ကွင်းဖော်ပြချက်၊ shot, scene, camera, timestamp၊ ခေါင်းစဉ်၊ bullet list နှင့် meta စာသားများ လုံးဝမထည့်ပါနှင့်။
3. လူအမည်၊ နေရာအမည်၊ ငွေပမာဏ၊ အစဉ်လိုက်ဖြစ်ရပ်ကို transcript ထဲကအတိုင်း တိတိကျကျထိန်းပါ။ ခန့်မှန်းချက် မရေးပါနှင့်။ ဘာသာပြန်သော်လည်း အချက်အလက်ကို အပိုထည့်ခြင်း၊ ချန်လှပ်ချန်ခြင်း လုံးဝမပြုလုပ်ရ — မူရင်းအဓိပ္ပာယ်နှင့် အတိအကျကိုက်ညီရမည်။
4. စာပေဆန်၊ ရေးဟန်ကျသော မြန်မာစာအရေးအသား (ဥပမာ - ၍၊ ဖြစ်ပေသည်၊ ထိုအခါ၊ ၏) ကို လုံးဝမသုံးပါနှင့်။ မြန်မာလူမျိုးများ နေ့စဉ်ပြောဆိုနေကျ၊ သဘာဝကျသော အပြောစကား (colloquial spoken Burmese) ကိုသာသုံးပါ။ ဝါကျတစ်ကြောင်းလျှင် အဓိပ္ပာယ်တစ်ခုသာပါအောင် ရှင်းလင်းအောင်ရေးပါ။
5. အသံပြောအရှိန်ပြောင်းရန်လိုမှသာ [action], [sad], [happy], [whisper], [normal] tag ကို ဝါကျမတိုင်မီ ထည့်နိုင်သည်။
6. Output တွင် recap narration စာသားသီးသန့်သာ ပြန်ပေးပါ။
""".strip()


def recap_prompt(transcript, tone, language):
    if language == "မြန်မာ":
        return f"{BURMESE_RULES}\n\nNarration tone: {tone}\n\nTranscript:\n{transcript}"
    return f"""
You are a professional recap narrator. Rewrite this transcript as a natural {language} voice-over.
Use this order: hook, context, conflict, turning point, outcome, takeaway.
Preserve facts only — do not add or drop information. Do not output headings, scene directions, timestamps, bullets, or translation notes.
Return only the finished narration.

Tone: {tone}
Transcript: {transcript}
""".strip()


def visual_prompt(tone, language):
    if language == "မြန်မာ":
        return f"{BURMESE_RULES}\n\nဤဗီဒီယိုကိုသာအခြေခံ၍ {tone} tone ဖြင့် recap narration ရေးပါ။ မြင်/ကြားရသည့် အချက်များသာထည့်ပြီး နားထောင်သူလိုက်လံနားလည်နိုင်မည့် ဇာတ်ကြောင်းပုံစံဖြင့်ရေးပါ။"
    return f"Write a professional {tone} recap narration in {language} from this video. Use only verifiable events. Do not include scene directions, timestamps, headings, bullets, or unsupported details. Return only the finished narration."


def clean_ai_text(text):
    text = text.strip()
    return re.sub(r"^(?:final script|recap narration|narration)\s*[:：]\s*", "", text, flags=re.I).strip()


def extract_json_array(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.I).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    match = re.search(r"\[.*\]", text, flags=re.S)
    return match.group(0) if match else text


def align_script_to_video(video_path, script_text, language):
    """For videos that have no usable speech (e.g. silent footage that the
    Recap Builder already turned into a script via 'AI ကြည့်ပြီးရေးမည်' mode),
    ask Gemini to split that finished script into short lines and time-align
    each line to the video's visuals, so Subtitle Studio can turn it into
    accurately-timed captions and dubbing without needing original audio."""
    if not st.session_state.api_keys:
        return None, "Gemini API key ကို sidebar မှာ ထည့်ပါ။"
    if not script_text.strip():
        return None, "Recap Builder ကနေ script မရှိသေးပါ။"
    duration = duration_of(video_path)
    try:
        genai.configure(api_key=st.session_state.api_keys[0])
        remote = genai.upload_file(path=str(video_path))
        while remote.state.name == "PROCESSING":
            time.sleep(2)
            remote = genai.get_file(remote.name)
        if remote.state.name == "FAILED":
            return None, "Gemini video processing မအောင်မြင်ပါ။"
        prompt = f"""
ဤအောက်ပါစာသားသည် ဒီဗီဒီယို (မူရင်းအသံမပါ) အတွက် ရေးထားပြီးသား {language} recap narration ဖြစ်သည်။
Video ၏ စက္ကန့်ပေါင်း {duration:.1f} sec ရှိသည်။
Narration စာသားကို အဓိပ္ပာယ်၊ စကားလုံး၊ အစီအစဉ် လုံးဝမပြောင်းလဲစေဘဲ တိုတောင်းသော caption လိုင်းများအဖြစ် ပိုင်းခြားပြီး၊ video ထဲက မြင်ကွင်းအစီအစဉ်နှင့် ကိုက်ညီအောင် timestamp ချိတ်ဆက်ပါ။

စည်းကမ်းများ
1. Narration ရှိ စကားလုံးအားလုံးကို အစဉ်လိုက်၊ ချန်လှပ်မထားဘဲ၊ ထပ်မထည့်ဘဲ အကုန်သုံးပါ။
2. line တစ်ကြောင်းစီသည် စကားလုံး ၄-၁၄ လုံးခန့်၊ (တစ်ထွက်ရှူငင်ချိန်) အရှည်ရှိရမည်။
3. start/end timestamp များသည် စက္ကန့်ဖြင့် ဂဏန်းဖြစ်ရမည်၊ တဖြည်းဖြည်းများလာရမည်၊ 0 နှင့် {duration:.1f} ကြားတွင်ရှိရမည်၊ line တစ်ခုနှင့်တစ်ခု overlap မဖြစ်ရ။
4. Video ၏ visual pacing (ပြောင်းလဲမှု၊ အရေးကြီးသည့်မြင်ကွင်း) နှင့် ကိုက်ညီအောင် timing ချထားပါ။
5. JSON array တစ်ခုတည်းသာ ပြန်ပေးပါ — [{{"start": 0.0, "end": 3.2, "text": "..."}}, ...] ပုံစံ။ အခြားစာသား၊ ရှင်းလင်းချက် လုံးဝမထည့်ပါနှင့်။

Narration script:
{script_text}
""".strip()
        model = genai.GenerativeModel(st.session_state.model_name)
        response = model.generate_content([remote, prompt])
        genai.delete_file(remote.name)
        raw = extract_json_array(response.text or "")
        data = json.loads(raw)
    except Exception as error:
        return None, str(error)

    segments = []
    for item in data if isinstance(data, list) else []:
        try:
            start, end = float(item["start"]), float(item["end"])
            text = str(item["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and end > start:
            segments.append({"start": max(start, 0.0), "end": end, "text": text})
    segments.sort(key=lambda seg: seg["start"])
    if not segments:
        return None, "AI ကနေ timing ချထားမှုမရပါ။ ထပ်စမ်းကြည့်ပါ။"
    return segments, None


def generate(prompt):
    if not st.session_state.api_keys:
        return None, "Gemini API key ကို sidebar မှာ ထည့်ပါ။"
    dictionary = load_dictionary()
    if dictionary:
        prompt = f"အသုံးအနှုန်းနှင့်အမည်များအတွက် ဒီ dictionary ကို ဦးစားပေးလိုက်နာပါ။\n{dictionary}\n\n{prompt}"
    errors = []
    for key in st.session_state.api_keys:
        try:
            genai.configure(api_key=key)
            response = genai.GenerativeModel(st.session_state.model_name).generate_content(prompt)
            text = getattr(response, "text", "").strip()
            if text:
                return clean_ai_text(text), None
            errors.append("AI response မှာစာသားမပါရှိပါ။")
        except Exception as error:
            errors.append(str(error))
    return None, errors[-1] if errors else "AI response မရပါ။"


# Edge TTS defaults intentionally use the "standard" Neural voices (Jenny /
# Guy) instead of the newer expressive ones (Aria / Christopher). The
# expressive voices apply more dynamic internal prosody, which is what was
# causing short function words like "the" to occasionally come out as a
# clipped "tee" — the standard voices read English with a clearer, more
# neutral international accent and stay stable across rate/pitch changes.
VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-ThihaNeural", "မ": "my-MM-NilarNeural"},
    "English": {"ကျား": "en-US-GuyNeural", "မ": "en-US-JennyNeural"},
}
GOOGLE_VOICE_MAP = {
    "မြန်မာ": {"ကျား": "my-MM-Standard-A", "မ": "my-MM-Standard-A"},
    "English": {"ကျား": "en-US-Neural2-D", "မ": "en-US-Neural2-C"},
}
VOICE_MODES = {
    "Recap — ပြတ်သားမြန်ဆန်": ("+6%", "+0Hz"),
    "Documentary — တည်ငြိမ်": ("-4%", "-2Hz"),
    "Story — ဇာတ်လမ်းဆန်": ("-7%", "-2Hz"),
    "Energy — စိတ်လှုပ်ရှား": ("+12%", "+2Hz"),
}
EMOTIONS = {
    "[normal]": ("+0%", "+0Hz"), "[sad]": ("-14%", "-12Hz"),
    "[happy]": ("+8%", "+9Hz"), "[action]": ("+20%", "+2Hz"),
    "[whisper]": ("-10%", "-16Hz"),
}


def int_value(value):
    return int(value.replace("%", "").replace("Hz", "").replace("+", ""))


def spoken_number(number):
    try:
        if "." in number:
            whole, fraction = number.split(".", 1)
            return f"{spoken_number(whole)} ဒသမ {spoken_number(fraction)}"
        n = int(number.replace(",", ""))
        if n == 0:
            return "သုည"
        digits = ["", "တစ်", "နှစ်", "သုံး", "လေး", "ငါး", "ခြောက်", "ခုနစ်", "ရှစ်", "ကိုး"]
        units = ((10_000_000, "ကုဋေ"), (1_000_000, "သန်း"), (100_000, "သိန်း"), (10_000, "သောင်း"), (1_000, "ထောင်"), (100, "ရာ"), (10, "ဆယ်"))
        result = []
        for unit, label in units:
            if n >= unit:
                upper, n = divmod(n, unit)
                result.append(spoken_number(str(upper)) + label)
        if n:
            result.append(digits[n])
        spoken = "".join(result).replace("ထောင်", "ထောင့်").replace("ရာ", "ရာ့").replace("ဆယ်", "ဆယ့်")
        return spoken[:-1] + "င်" if spoken.endswith("ထောင့်") else spoken.rstrip("့")
    except (ValueError, IndexError):
        return number


def normalize_tts(text, language):
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"[*#]", "", text).replace('"', "").replace("'", "")
    for source, spoken in sorted(pronunciation_dictionary().items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(source), spoken, text, flags=re.I)
    if language == "မြန်မာ":
        text = re.sub(r"\b\d+(?:\.\d+)?\b", lambda match: spoken_number(match.group()), text)
    return re.sub(r"\s+", " ", text.replace("၊", ", ").replace("။", ". ")).strip()


def edge_chunk(text, language, gender, rate, pitch, output):
    try:
        result = subprocess.run(["edge-tts", "--voice", VOICE_MAP[language][gender], "--text", text, f"--rate={rate}", f"--pitch={pitch}", "--write-media", str(output)], capture_output=True, text=True, check=False)
        return result.returncode == 0 and output.exists() and output.stat().st_size > 0
    except OSError:
        return False


def google_chunk(text, language, gender, rate, pitch, output):
    credentials = st.session_state.google_creds
    if credentials is None:
        return False
    try:
        client = texttospeech.TextToSpeechClient(credentials=credentials)
        result = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code="my-MM" if language == "မြန်မာ" else "en-US", name=GOOGLE_VOICE_MAP[language][gender]),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=max(.25, min(4, 1 + rate / 100)), pitch=max(-20, min(20, pitch / 10))),
        )
        output.write_bytes(result.audio_content)
        return output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def create_voice(script, language, gender, delivery, speed, engine):
    if not require_ffmpeg():
        return False, "FFmpeg မရှိပါ။"
    base_rate, base_pitch = VOICE_MODES[delivery]
    # TTS engines only sound natural within roughly 0.7x-1.4x of their
    # default rate; anything more aggressive is applied afterwards as a
    # precise ffmpeg atempo pass so the 0.4x-3.0x slider is always accurate
    # without ever sending a distorted rate string to the voice engine.
    engine_speed = max(0.7, min(1.4, speed))
    residual_speed = speed / engine_speed
    current_rate = int_value(base_rate) + round((engine_speed - 1) * 100)
    current_pitch = int_value(base_pitch)
    chunks, index = [], 0
    for item in re.split(r"(\[.*?\])", script):
        item = item.strip()
        if not item:
            continue
        tag = item.lower()
        if tag in EMOTIONS:
            rate, pitch = EMOTIONS[tag]
            current_rate = int_value(base_rate) + round((engine_speed - 1) * 100) + int_value(rate)
            current_pitch = int_value(base_pitch) + int_value(pitch)
            continue
        if tag == "[p]":
            pause = SESSION_DIR / f"pause_{index}.mp3"
            ok, _ = run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", ".65", "-q:a", "9", str(pause)])
            if ok:
                chunks.append(pause)
                index += 1
            continue
        if item.startswith("[") and item.endswith("]"):
            continue
        text = normalize_tts(item, language)
        output = SESSION_DIR / f"voice_part_{index}.mp3"
        ok = google_chunk(text, language, gender, current_rate, current_pitch, output) if engine == "Google Cloud TTS" else edge_chunk(text, language, gender, f"{current_rate:+d}%", f"{current_pitch:+d}Hz", output)
        if not ok:
            return False, "အသံတစ်ပိုင်းဖန်တီးမရပါ။ Voice setting သို့မဟုတ် network ကို စစ်ပါ။"
        chunks.append(output)
        index += 1
    if not chunks:
        return False, "အသံဖန်တီးရန် စာသားမရှိပါ။"
    listing = SESSION_DIR / "voice_list.txt"
    listing.write_text("".join(f"file '{chunk}'\n" for chunk in chunks), encoding="utf-8")
    ok, error = run_media(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "libmp3lame", "-q:a", "2", str(PATHS["voice"])])
    if not (ok and PATHS["voice"].exists()):
        return False, error
    if abs(residual_speed - 1.0) > 0.02:
        adjusted = SESSION_DIR / "voice_speed_adjusted.mp3"
        ok, error = run_media(["ffmpeg", "-y", "-i", str(PATHS["voice"]), "-filter:a", atempo_filter_chain(residual_speed), "-c:a", "libmp3lame", "-q:a", "2", str(adjusted)])
        if not (ok and adjusted.exists()):
            return False, error or "Narration speed ချိန်ညှိ၍မရပါ။"
        shutil.copyfile(adjusted, PATHS["voice"])
    return True, ""


def parse_points(raw, source_duration):
    values = []
    for item in raw.split(","):
        try:
            point = float(item.strip())
            if 1 < point < source_duration - 1 and point not in values:
                values.append(point)
        except ValueError:
            pass
    return sorted(values)


def make_freeze_edit(source, points):
    if not points:
        return source, ""
    clips, start = [], 0
    for index, point in enumerate(points):
        clip, image, hold = SESSION_DIR / f"clip_{index}.mp4", SESSION_DIR / f"freeze_{index}.jpg", SESSION_DIR / f"hold_{index}.mp4"
        tasks = [
            ["ffmpeg", "-y", "-ss", str(start), "-to", str(point), "-i", str(source), "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)],
            ["ffmpeg", "-y", "-ss", str(point), "-i", str(source), "-frames:v", "1", "-q:v", "2", str(image)],
            ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", "2", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(hold)],
        ]
        for task in tasks:
            ok, error = run_media(task)
            if not ok:
                return None, error
        clips.extend([clip, hold])
        start = point
    tail = SESSION_DIR / "tail.mp4"
    ok, error = run_media(["ffmpeg", "-y", "-ss", str(start), "-i", str(source), "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(tail)])
    if not ok:
        return None, error
    clips.append(tail)
    listing = SESSION_DIR / "freeze_list.txt"
    listing.write_text("".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    output = SESSION_DIR / f"freeze_edit_{int(time.time())}.mp4"
    ok, error = run_media(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)])
    return (output, "") if ok else (None, error)


def make_video(source, bgm, bgm_volume, speed, points):
    stage, error = make_freeze_edit(source, points)
    if stage is None:
        return None, error
    output = SESSION_DIR / f"recap_{int(time.time())}.mp4"
    video_filter = f"[0:v]setpts={1 / speed:.5f}*PTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v]"
    command, maps = ["ffmpeg", "-y", "-i", str(stage), "-i", str(PATHS["voice"])], ["-map", "[v]"]
    if bgm and bgm.exists():
        command.extend(["-stream_loop", "-1", "-i", str(bgm)])
        audio_filter = f";[2:a]volume={bgm_volume:.2f}[bgm];[1:a][bgm]amix=inputs=2:duration=first:normalize=0[a]"
        maps.extend(["-map", "[a]"])
    else:
        audio_filter = ""
        maps.extend(["-map", "1:a"])
    ok, error = run_media(command + ["-filter_complex", video_filter + audio_filter] + maps + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output)])
    return (output, "") if ok and output.exists() else (None, error)


def padauk_font():
    folder = APP_DIR / "fonts_cache"
    folder.mkdir(exist_ok=True)
    font = folder / "Padauk-Bold.ttf"
    if font.exists() and font.stat().st_size > 50_000:
        return font
    try:
        response = requests.get("https://github.com/googlefonts/padauk/raw/main/fonts/ttf/Padauk-Bold.ttf", timeout=20)
        response.raise_for_status()
        font.write_bytes(response.content)
        return font
    except requests.RequestException:
        return None


def ass_time(seconds):
    return f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}.{int(seconds % 1 * 100):02d}"


def srt_time(seconds):
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d},{int(seconds % 1 * 1000):03d}"


def write_subtitles(segments):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Recap,Padauk-Bold,42,&H00FFFFFF,&H0000FFFF,&H0010181E,&H60000000,1,0,0,0,100,100,0,0,1,3.2,0.8,2,90,90,62,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    with PATHS["caption_ass"].open("w", encoding="utf-8") as ass, PATHS["caption_srt"].open("w", encoding="utf-8") as srt:
        ass.write(header)
        for number, item in enumerate(segments, 1):
            start, end, text = float(item["start"]), float(item["end"]), item["text"].strip()
            words = text.replace("{", "(").replace("}", ")").replace("\\", "").split()
            display = text if len(words) <= 8 else "\\N".join(textwrap.wrap(" ".join(words), width=32, break_long_words=False))
            ass.write(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Recap,,0,0,0,,{display}\n")
            srt.write(f"{number}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")


def translate_segments(segments):
    """Translate each subtitle line into natural, dubbing-friendly spoken
    Burmese (not a stiff literal/literary translation) while keeping facts,
    names and numbers exactly intact. Never aborts the whole batch — a
    single failed line falls back to the original text so subtitle/dubbing
    generation can still complete."""
    output = []
    failed = 0
    for item in segments:
        prompt = (
            "အောက်ပါ subtitle line ကို ရိုးရိုးရှင်းရှင်း literal (တိုက်ရိုက်) ဘာသာပြန်မဟုတ်ဘဲ၊ "
            "မြန်မာလူမျိုးများ နေ့စဉ်ပြောဆိုနေကျ၊ သဘာဝကျသော အပြောစကား (colloquial spoken Burmese) ဖြင့် ပြန်ဆိုပါ။\n"
            "- မူရင်းစာသား၏ အဓိပ္ပာယ်၊ အချက်အလက်၊ နာမည်၊ နေရာအမည်၊ ဂဏန်းများကို အတိအကျ ထိန်းသိမ်းပါ — ဖြည့်စွက်ခြင်း၊ "
            "ချန်လှပ်ခြင်း (extra သို့မဟုတ် ချန်ချွင်းမှု) လုံးဝမပြုလုပ်ပါနှင့်။\n"
            "- Dubbing တွင်တွဲသုံးရန်ဖြစ်၍ စာကြောင်းအရှည်ကို မူရင်းနှင့်နီးစပ်အောင်ထိန်းပါ။\n"
            "- စာပေဆန်၊ ရေးဟန်ကျသော မြန်မာစာအသုံးအနှုန်း (ဥပမာ - ၍၊ ဖြစ်ပေသည်၊ ထိုအခါ၊ ၏) များကို လုံးဝရှောင်ပါ။\n"
            "- ရှင်းလင်းချက်၊ ခေါင်းစဉ်၊ မှတ်ချက် လုံးဝမထည့်ပါနှင့်— ဘာသာပြန်ထားသော line တစ်ကြောင်းတည်းသာ ပြန်ပေးပါ။\n\n"
            f"Subtitle: {item['text'].strip()}"
        )
        translated, _ = generate(prompt)
        if translated:
            output.append({"start": item["start"], "end": item["end"], "text": translated.replace("\n", " ").strip()})
        else:
            failed += 1
            output.append({"start": item["start"], "end": item["end"], "text": item["text"].strip()})
    warning = f"{failed} subtitle line(s) ဘာသာပြန်မရသဖြင့် မူရင်းစာသားကို အစားထိုးထားပါသည်။" if failed else None
    return output, warning


def silence_file(duration, output):
    duration = max(duration, 0.05)
    ok, _ = run_media(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{duration:.3f}", "-q:a", "9", str(output)])
    return ok


def build_dubbed_audio(segments, language, gender, engine):
    """Turn caption segments into a single audio track whose timing matches
    the video exactly: each line is spoken, then stretched/trimmed/padded so
    it starts and ends at the same second as the original subtitle."""
    if not require_ffmpeg():
        return None, "FFmpeg မရှိပါ။"
    chunks = []
    cursor = 0.0
    for index, segment in enumerate(segments):
        start = max(float(segment["start"]), 0.0)
        end = max(float(segment["end"]), start + 0.2)
        text = normalize_tts(segment["text"].strip(), language)
        if not text:
            cursor = max(cursor, end)
            continue
        gap = start - cursor
        if gap > 0.06:
            silence = SESSION_DIR / f"dub_gap_{index}.mp3"
            if silence_file(gap, silence):
                chunks.append(silence)
        raw = SESSION_DIR / f"dub_raw_{index}.mp3"
        ok = google_chunk(text, language, gender, 0, 0, raw) if engine == "Google Cloud TTS" else edge_chunk(text, language, gender, "+0%", "+0Hz", raw)
        if not ok:
            return None, f"Line {index + 1} ရဲ့ အသံမထုတ်နိုင်ပါ။"
        raw_duration = duration_of(raw)
        target = max(end - start, 0.2)
        fitted = raw
        if raw_duration > 0.05:
            tempo = max(0.5, min(2.0, raw_duration / target))
            if abs(tempo - 1.0) > 0.03:
                candidate = SESSION_DIR / f"dub_fit_{index}.mp3"
                ok, _ = run_media(["ffmpeg", "-y", "-i", str(raw), "-filter:a", f"atempo={tempo:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(candidate)])
                if ok:
                    fitted = candidate
        fitted_duration = duration_of(fitted)
        if fitted_duration < target - 0.05:
            pad = SESSION_DIR / f"dub_pad_{index}.mp3"
            chunks.append(fitted)
            if silence_file(target - fitted_duration, pad):
                chunks.append(pad)
        elif fitted_duration > target + 0.05:
            trimmed = SESSION_DIR / f"dub_trim_{index}.mp3"
            ok, _ = run_media(["ffmpeg", "-y", "-i", str(fitted), "-t", f"{target:.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(trimmed)])
            chunks.append(trimmed if ok else fitted)
        else:
            chunks.append(fitted)
        cursor = end
    if not chunks:
        return None, "Dubbing အတွက် အသံစာသားမတွေ့ပါ။"
    listing = SESSION_DIR / "dub_list.txt"
    listing.write_text("".join(f"file '{chunk}'\n" for chunk in chunks), encoding="utf-8")
    ok, error = run_media(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "libmp3lame", "-q:a", "2", str(PATHS["dub_audio"])])
    return (PATHS["dub_audio"], "") if ok and PATHS["dub_audio"].exists() else (None, error)


def mux_dubbed_video(video_path, audio_path, output_path):
    ok, error = run_media(["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path)])
    return (True, "") if ok and output_path.exists() else (False, error)


with st.sidebar:
    st.markdown("## 🎞️ Recap Studio MM")
    st.caption("Burmese-first creator workspace")
    st.divider()
    with st.expander("🔐 AI settings", expanded=True):
        saved_raw, saved_model = load_local_config()
        if "api_key_input" not in st.session_state:
            st.session_state.api_key_input = saved_raw
        raw_keys = st.text_input("Gemini API key", type="password", key="api_key_input", help="Key ကို ဒီ server ပေါ်မှာသာသိမ်းထားပြီး browser refresh လုပ်လည်း မပျောက်ပါ။ Multiple key များကို comma ဖြင့်ခွဲနိုင်သည်။")
        st.session_state.api_keys = [key.strip() for key in raw_keys.split(",") if key.strip()]
        model_options = ["gemini-2.5-flash", "gemini-2.5-pro"]
        default_index = model_options.index(saved_model) if saved_model in model_options else 0
        st.session_state.model_name = st.selectbox("Model", model_options, index=default_index)
        save_local_config(raw_keys, st.session_state.model_name)
        st.caption("AI rewrite၊ direct video recap၊ subtitle ဘာသာပြန်နှင့် dubbing အတွက်သာလိုသည်။")
        if CONFIG_PATH.exists() and st.button("🗑️ Saved key ဖျက်မည်", use_container_width=True):
            CONFIG_PATH.unlink(missing_ok=True)
            st.session_state.api_key_input = ""
            st.session_state.api_keys = []
            st.rerun()
    with st.expander("🔊 Google Cloud TTS (optional)"):
        credentials = st.file_uploader("service_account.json", type=["json"], key="credentials")
        if credentials:
            try:
                info = json.load(credentials)
                st.session_state.google_creds = service_account.Credentials.from_service_account_info(info)
                save_local_google_creds(info)
                st.success("Google Cloud TTS ချိတ်ဆက်ပြီး refresh လုပ်လည်း မပျောက်အောင် သိမ်းထားပါပြီ။")
            except (ValueError, TypeError, json.JSONDecodeError):
                st.error("service account JSON ဖိုင်မမှန်ပါ။")
        elif st.session_state.google_creds is not None:
            st.success("Google Cloud TTS သိမ်းထားသည့် credential ဖြင့် ချိတ်ဆက်ထားပါသည်။")
            if st.button("🗑️ Google credential ဖျက်မည်", use_container_width=True):
                GOOGLE_CREDS_PATH.unlink(missing_ok=True)
                st.session_state.google_creds = None
                st.rerun()
    with st.expander("📥 Video link import", expanded=True):
        link = st.text_input("YouTube / public video URL")
        cookies_upload = st.file_uploader(
            "YouTube cookies.txt (optional)", type=["txt"], key="cookies_upload",
            help="'Sign in to confirm you're not a bot' သို့မဟုတ် 'Requested format is not available' error ဆက်တက်နေရင် browser extension (ဥပမာ - Get cookies.txt LOCALLY) နဲ့ youtube.com ကနေ login ဝင်ထားစဉ် cookies.txt ကို export လုပ်ပြီး ဒီနေရာမှာတင်ပါ။",
        )
        if cookies_upload:
            save_upload(cookies_upload, PATHS["cookies"])
            st.session_state.has_cookies = True
            st.success("cookies.txt ကို ဒေါင်းလုဒ်တွေအတွက် အသုံးပြုပါမည်။")
        elif PATHS["cookies"].exists():
            st.caption("✅ cookies.txt လက်ရှိအသုံးပြုနေသည်")
            if st.button("🗑️ cookies.txt ဖျက်မည်", use_container_width=True):
                PATHS["cookies"].unlink(missing_ok=True)
                st.session_state.has_cookies = False
                st.rerun()
        version_col, update_col = st.columns([1.3, 1])
        with version_col:
            st.caption(f"yt-dlp ဗားရှင်း — {installed_ytdlp_version()} · daily auto-update ✅")
        with update_col:
            if st.button("🔄 yt-dlp update", use_container_width=True, help="App က yt-dlp ကို တစ်နေ့တစ်ခါ အလိုအလျောက် update လုပ်ပေးနေပေမယ့်၊ YouTube ပြောင်းလိုက်ပြီး ချက်ချင်း update ဆွဲချင်ရင် ဒီခလုတ်ကိုနှိပ်ပါ။"):
                with st.spinner("yt-dlp ကို နောက်ဆုံးဗားရှင်းသို့ update လုပ်နေသည်…"):
                    ok, info = update_ytdlp()
                if ok:
                    st.success(f"yt-dlp ကို v{info} အဖြစ် update လုပ်ပြီးပါပြီ။")
                else:
                    st.error(f"Update မအောင်မြင်ပါ — {info}")
        if st.button("ဗီဒီယိုဒေါင်းလုဒ်", use_container_width=True):
            if not link.strip():
                st.warning("Video URL ထည့်ပါ။")
            else:
                with st.spinner("ဗီဒီယို ရယူနေသည်… (ဗီဒီယိုအရွယ်အစားပေါ်မူတည်၍ အချိန်ယူနိုင်သည်)"):
                    ok, error = download_video(link.strip(), PATHS["source"], PATHS["cookies"] if PATHS["cookies"].exists() else None)
                if ok:
                    st.session_state.last_download_url = link.strip()
                    st.success("ဗီဒီယိုရပြီ — 'Recap Builder' tab ရဲ့ ဗီဒီယိုနေရာမှာ အလိုအလျောက်ပါသွားပါပြီ။")
                    st.rerun()
                else:
                    st.error(f"ရယူမရပါ — {error}")
        if PATHS["source"].exists():
            st.caption(f"လက်ရှိ source ဗီဒီယို အသင့်ရှိပါသည် ({duration_of(PATHS['source']):.0f} sec)")
    st.divider()
    if st.button("🔄 Session အသစ်ပြန်စ", use_container_width=True):
        saved_id = st.session_state.session_id
        saved_keys = st.session_state.api_keys
        saved_model_name = st.session_state.get("model_name")
        st.session_state.clear()
        st.session_state.session_id = saved_id
        st.session_state.api_keys = saved_keys
        if saved_model_name:
            st.session_state.model_name = saved_model_name
        st.rerun()
    st.markdown('<p class="small-note">အသုံးပြုခွင့်ရှိသော ဗီဒီယိုများကိုသာ upload / import လုပ်ပါ။</p>', unsafe_allow_html=True)


st.markdown(
    """
    <div class="hero">
      <span class="eyebrow">✦ Burmese video storytelling workflow</span>
      <h1>Recap Studio MM</h1>
      <p>ဗီဒီယိုတစ်ခုကို ရှင်းလင်းတိကျသော မြန်မာ recap narration၊ voice-over၊ subtitle နှင့် timing-ကိုက်ညီသော dubbing အဖြစ် စနစ်တကျထုတ်လုပ်ပါ။</p>
      <div class="hero-badges">
        <span class="hero-badge">🎯 Fact-safe Burmese narration</span>
        <span class="hero-badge">🗣️ Natural colloquial translation</span>
        <span class="hero-badge">⬇️ Self-updating YouTube import</span>
        <span class="hero-badge">🎚️ 0.4x–3.0x speed control</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
step_cols = st.columns(3)
for column, icon, number, label in zip(
    step_cols,
    ["📥", "✍️", "📤"],
    ["STEP 01", "STEP 02", "STEP 03"],
    ["ဗီဒီယိုထည့်ပြီး transcript ယူပါ", "fact-safe recap ကို AI ဖြင့် ပြင်ပါ", "အသံ၊ MP4၊ subtitle နှင့် dubbed video ကို export လုပ်ပါ"],
):
    with column:
        st.markdown(f'<div class="step-card"><div class="step-icon">{icon}</div><div><div class="step-num">{number}</div><div class="step-label">{label}</div></div></div>', unsafe_allow_html=True)

recap_tab, subtitle_tab, publish_tab = st.tabs(["✦ Recap Builder", "▣ Subtitle Studio", "↗ Publish Kit"])


with recap_tab:
    st.markdown('<p class="section-title">✦ Recap Builder</p><p class="section-lead">အသံမှရေးမည် mode က transcript ကိုအခြေခံ၍ အချက်အလက်မပျက်သော recap ရေးပေးသည်။</p>', unsafe_allow_html=True)
    left, right = st.columns([1.35, 1])
    with left:
        uploaded = st.file_uploader("ဗီဒီယိုဖိုင်ထည့်ပါ", type=["mp4", "mov", "mkv", "webm"], key="recap_source")
        if uploaded:
            save_upload(uploaded, PATHS["source"])
            st.success(f"{uploaded.name} ကို ready လုပ်ပြီးပါပြီ။")
        if PATHS["source"].exists():
            seconds = duration_of(PATHS["source"])
            st.info(f"✅ Source ready · {seconds:.0f} sec (link import / upload နှစ်မျိုးလုံးက ဒီနေရာကိုပဲ ဝင်သွားပါသည်)" if seconds else "✅ Source ready")
            with st.expander("ပြန်ကြည့်ရန်"):
                st.video(str(PATHS["source"]))
    with right:
        recap_mode = st.radio("Recap ရေးနည်း", ["ဗီဒီယိုကို AI ကြည့်ပြီးရေးမည် (Render RAM လွတ် - အကြံပြု)", "အသံမှရေးမည်"])
        narration_language = st.selectbox("Narration language", ["မြန်မာ", "English"])
        tone = st.selectbox("Narration tone", ["Movie recap — တင်းကျပ်ပြီးစီးဆင်း", "Documentary — ရှင်းလင်းတည်ငြိမ်", "News recap — အချက်အလက်ဦးစားပေး", "High energy — မြန်ပြီးထိရောက်"])
        source_language = st.selectbox("မူရင်းအသံဘာသာ", ["Auto detect", "မြန်မာ", "English", "Japanese", "Chinese", "Thai"])
    with st.expander("မြန်မာ recap narration ကို ဘယ်လိုတိကျအောင်ပြင်ထားလဲ"):
        st.markdown('<div class="callout">AI ကို စဖွင့်ချိတ်ဆက်ချက် → နောက်ခံ → ပြဿနာ → အလှည့်အပြောင်း → ရလဒ် → အနှစ်ချုပ် အစဉ်လိုက်ရေးရန် ညွှန်ကြားထားပါတယ်။ လူအမည်၊ နေရာအမည်၊ ဂဏန်းနှင့်ဖြစ်ရပ်ကို မူရင်း transcript ထဲကအတိုင်းသာ ထိန်းရပြီး scene, camera, timestamp တို့ကို ထည့်မရေးနိုင်အောင် ကန့်သတ်ထားပါတယ်။ ဘာသာပြန်တဲ့အခါလည်း စာပေဆန်တဲ့ ရေးဟန်မဟုတ်ဘဲ လူတွေနေ့စဉ်ပြောနေကျ သဘာဝကျတဲ့ အပြောစကားနဲ့ တိတိကျကျ (အပို၊ အလို မရှိအောင်) ရေးရန် သီးသန့်ညွှန်ကြားထားပါတယ်။</div>', unsafe_allow_html=True)
    if st.button("Recap script ဖန်တီးပါ", type="primary", use_container_width=True):
        if not PATHS["source"].exists():
            st.warning("အရင်ဆုံး ဗီဒီယိုဖိုင် upload လုပ်ပါ သို့မဟုတ် sidebar က link import လုပ်ပါ။")
        elif not st.session_state.api_keys:
            st.warning("AI narration ဖန်တီးရန် sidebar မှာ Gemini API key ထည့်ပါ။")
        elif recap_mode.startswith("ဗီဒီယိုကို AI ကြည့်ပြီးရေးမည်"):
            with st.spinner("ဗီဒီယိုကိုစိစစ်ပြီး recap ရေးနေသည်…"):
                try:
                    genai.configure(api_key=st.session_state.api_keys[0])
                    remote = genai.upload_file(path=str(PATHS["source"]))
                    while remote.state.name == "PROCESSING":
                        time.sleep(2)
                        remote = genai.get_file(remote.name)
                    if remote.state.name == "FAILED":
                        raise RuntimeError("Gemini video processing မအောင်မြင်ပါ။")
                    response = genai.GenerativeModel(st.session_state.model_name).generate_content([remote, visual_prompt(tone, narration_language)])
                    script, error = clean_ai_text(response.text), None
                    genai.delete_file(remote.name)
                except Exception as failure:
                    script, error = None, str(failure)
            if script:
                st.session_state.final_script = script
                st.session_state.script_editor = script
                st.session_state.script_language = narration_language
                st.session_state.script_video_is_silent = True
                st.success("Recap narration ready ဖြစ်ပါပြီ — ဒီ script ကို 'Subtitle Studio' tab ရဲ့ 'Recap Builder script ကို timing ချိန်ညှိမည်' mode မှာ ဆက်သုံးနိုင်ပါတယ်။")
            else:
                st.error(f"Recap မဖန်တီးနိုင်ပါ — {error}")
        else:
            codes = {"မြန်မာ": "my", "English": "en", "Japanese": "ja", "Chinese": "zh", "Thai": "th"}
            code = None if source_language == "Auto detect" else codes[source_language]
            with st.spinner("အသံကိုနားထောင်ပြီး recap ရေးနေသည်…"):
                transcript, _ = transcribe(PATHS["source"], PATHS["audio"], code)
                script, error = generate(recap_prompt(transcript, tone, narration_language)) if transcript else (None, "Transcript မရပါ။")
            if script:
                st.session_state.raw_transcript = transcript
                st.session_state.final_script = script
                st.session_state.script_editor = script
                st.session_state.script_language = narration_language
                st.session_state.script_video_is_silent = False
                st.success("Recap narration ready ဖြစ်ပါပြီ။")
            else:
                st.error(f"Recap မဖန်တီးနိုင်ပါ — {error}")

    if st.session_state.raw_transcript:
        with st.expander("မူရင်း transcript ကိုကြည့်ရန်"):
            st.write(st.session_state.raw_transcript)

    st.markdown("---")
    st.markdown('<p class="section-title">🎙️ Narration editor & export</p><p class="section-lead">စကားလုံးနှင့်အမည်များကိုစစ်ပြီး export လုပ်ပါ။ [action], [sad], [happy], [whisper] ကိုလိုအပ်မှသာ ထည့်ပါ။</p>', unsafe_allow_html=True)
    script_text = st.text_area("Final recap narration", key="script_editor", height=310, placeholder="Recap script ကို ဒီနေရာမှာ တိုက်ရိုက်ရေးနိုင်ပါတယ်။")
    st.session_state.final_script = script_text
    if st.button("➜ ဒီ script နဲ့ ဗီဒီယိုကို Subtitle Studio ကို ပို့ပါ", use_container_width=True, disabled=not (script_text.strip() and PATHS["source"].exists())):
        shutil.copyfile(PATHS["source"], PATHS["caption_source"])
        st.session_state.segments = None
        st.session_state.caption_video = None
        st.session_state.dubbed_video = None
        # This is the fix for the hand-off ordering: when the video came from
        # the silent "AI ကြည့်ပြီးရေးမည်" mode there is no audio track to
        # transcribe, so Subtitle Studio must default straight into the
        # script-timing-alignment mode instead of the audio-transcription
        # mode (which would otherwise fail with "no speech found").
        st.session_state.subtitle_mode = SUBTITLE_MODE_SCRIPT_ALIGN if st.session_state.script_video_is_silent else SUBTITLE_MODE_AUDIO
        st.success("Script နှင့် ဗီဒီယိုကို 'Subtitle Studio' tab ဆီ ပို့ပြီးပါပြီ — ဒီနေရာက tab ကိုသွားလိုက်ရုံပါပဲ၊ မှန်ကန်တဲ့ mode ကို အလိုအလျောက် ရွေးပေးထားပါပြီ။")
    st.caption("မှတ်ချက် — ဗီဒီယိုမှာ မူရင်းအသံမပါလျှင် (AI ကြည့်ပြီးရေးထားသော script ဖြစ်လျှင်) ဒီ button ကို သုံးပြီး Subtitle Studio ထဲ တိုက်ရိုက်ပို့နိုင်ပါတယ်။ ဗီဒီယို-အသံ-စာတန်း timing ချိန်ညှိပေးတဲ့ logic အားလုံးက ဒီ Recap Builder flow ထဲမှာသာ ရှိပါတယ်။")
    voice_column, export_column = st.columns([1.1, 1])
    with voice_column:
        voice_engine = st.radio("Voice engine", ["Edge TTS (free)", "Google Cloud TTS"], horizontal=True)
        voice_language = st.selectbox("Voice language", list(VOICE_MAP))
        if voice_language == "English":
            st.caption("English voice ကို international, ရှင်းလင်းပီသတဲ့ standard neural voice (Jenny/Guy) ဖြင့် default သုံးထားပါတယ် — 'the' ကဲ့သို့ short word အသံထွက်မှားမှု လျော့ချရန်ဖြစ်ပါတယ်။")
        gender = st.selectbox("Voice", ["ကျား", "မ"], index=1)
        delivery = st.selectbox("Delivery", list(VOICE_MODES))
        voice_speed = st.slider("Narration speed", 0.4, 3.0, 1.0, 0.05, help="0.4x (အလွန်နှေး) မှ 3.0x (အလွန်မြန်) အထိ တိကျစွာ ချိန်ညှိနိုင်သည်။")
    with export_column:
        export = st.radio("Export", ["🎬 Recap video (MP4)", "🎧 Voice-over only (MP3)"], horizontal=True)
        video_speed = st.slider("Video speed", 0.4, 3.0, 1.0, 0.05, help="0.4x (အလွန်နှေး) မှ 3.0x (အလွန်မြန်) အထိ တိကျစွာ ချိန်ညှိနိုင်သည်။")
        freeze = st.text_input("Freeze-frame emphasis (seconds, optional)", placeholder="ဥပမာ 30, 65")
        bgm = st.file_uploader("Background music (optional)", type=["mp3", "wav", "m4a"], key="bgm")
        if bgm:
            save_upload(bgm, PATHS["bgm"])
        bgm_volume = st.slider("BGM volume", 0.0, .5, .12, .01)
    if st.button("Voice-over / video ထုတ်ပါ", type="primary", use_container_width=True):
        if not script_text.strip():
            st.warning("Final recap narration မှာ စာသားထည့်ပါ။")
        elif voice_engine == "Google Cloud TTS" and st.session_state.google_creds is None:
            st.warning("Google Cloud TTS ကိုရွေးထားလျှင် sidebar မှာ service_account.json တင်ပါ။")
        elif export.startswith("🎬") and not PATHS["source"].exists():
            st.warning("MP4 ထုတ်ရန် source video လိုအပ်ပါတယ်။")
        else:
            with st.spinner("အသံဖန်တီးနေသည်…"):
                ok, error = create_voice(script_text, voice_language, gender, delivery, voice_speed, "Google Cloud TTS" if voice_engine == "Google Cloud TTS" else "Edge TTS")
            if not ok:
                st.error(f"Voice-over မထုတ်နိုင်ပါ — {error}")
            elif export.startswith("🎧"):
                st.session_state.processed_audio = str(PATHS["voice"])
                st.success("Voice-over MP3 ပြီးပါပြီ။")
            else:
                with st.spinner("ဗီဒီယိုနှင့်အသံကို ပေါင်းစပ်နေသည်…"):
                    points = parse_points(freeze, duration_of(PATHS["source"]))
                    video, error = make_video(PATHS["source"], PATHS["bgm"] if PATHS["bgm"].exists() else None, bgm_volume, video_speed, points)
                if video:
                    st.session_state.processed_audio = str(PATHS["voice"])
                    st.session_state.processed_video = str(video)
                    st.success("Recap video ပြီးပါပြီ။")
                else:
                    st.error(f"Video မထုတ်နိုင်ပါ — {error}")
    if st.session_state.processed_audio and Path(st.session_state.processed_audio).exists():
        audio = Path(st.session_state.processed_audio)
        st.markdown("#### Voice-over output")
        st.audio(str(audio), format="audio/mpeg")
        st.download_button("MP3 ဒေါင်းလုဒ်", audio.read_bytes(), "recap_voiceover.mp3", "audio/mpeg", use_container_width=True)
    if st.session_state.processed_video and Path(st.session_state.processed_video).exists():
        video = Path(st.session_state.processed_video)
        st.markdown("#### Recap video output")
        st.video(str(video))
        st.download_button("MP4 ဒေါင်းလုဒ်", video.read_bytes(), "recap_studio_mm.mp4", "video/mp4", use_container_width=True)


with subtitle_tab:
    st.markdown('<p class="section-title">▣ Subtitle Studio</p><p class="section-lead">ဗီဒီယိုအသံကို timestamp တိကျစွာဖြင့် subtitle အဖြစ်ထုတ်ပြီး SRT၊ burned-in MP4 နှင့် timing-ကိုက်ညီသော dubbed voice video ထုတ်နိုင်သည်။</p>', unsafe_allow_html=True)

    subtitle_mode = st.radio(
        "Subtitle စာသားရင်းမြစ်",
        SUBTITLE_MODE_OPTIONS,
        key="subtitle_mode",
        help="User တင်ပေးသော ဗီဒီယိုမှာ မူရင်းအသံမပါဘဲ Recap Builder က AI ကြည့်ပြီးရေးထားသော script ကိုသာသုံးထားလျှင် ပထမရွေးစရာ (script timing ချိန်ညှိမည်) ကိုသုံးပါ — ဒါသည် 'Recap Builder' tab ရဲ့ 'ပို့ပါ' ခလုတ်ကိုနှိပ်ချိန်တွင် အလိုအလျောက် ရွေးပေးပါလိမ့်မည်။",
    )
    is_script_mode = subtitle_mode == SUBTITLE_MODE_SCRIPT_ALIGN

    caption_upload = st.file_uploader("Caption လိုချင်သောဗီဒီယို", type=["mp4", "mov", "mkv", "webm"], key="caption_upload")
    if caption_upload:
        save_upload(caption_upload, PATHS["caption_source"])
        st.session_state.segments = None
        st.session_state.caption_video = None
        st.session_state.dubbed_video = None
        st.success(f"{caption_upload.name} ကို ready လုပ်ပြီးပါပြီ။")

    if not is_script_mode:
        subtitle_language = st.selectbox("Subtitle language", ["မူရင်းအသံအတိုင်း", "မြန်မာ (တိကျသောဘာသာပြန်)"])
        subtitle_source = st.selectbox("မူရင်းအသံဘာသာ", ["Auto detect", "မြန်မာ", "English", "Japanese", "Chinese", "Thai"], key="subtitle_source")
        if st.button("Subtitle ဖန်တီးပါ", type="primary", use_container_width=True):
            if not PATHS["caption_source"].exists():
                st.warning("ဗီဒီယိုဖိုင်ကို အရင်ထည့်ပါ။")
            elif subtitle_language.startswith("မြန်မာ") and not st.session_state.api_keys:
                st.warning("မြန်မာဘာသာပြန် subtitle အတွက် sidebar မှာ Gemini API key ထည့်ပါ။")
            else:
                codes = {"မြန်မာ": "my", "English": "en", "Japanese": "ja", "Chinese": "zh", "Thai": "th"}
                code = None if subtitle_source == "Auto detect" else codes[subtitle_source]
                with st.spinner("အသံကို subtitle အဖြစ်ပြောင်းနေသည်…"):
                    _, segments = transcribe(PATHS["caption_source"], PATHS["caption_audio"], code)
                if not segments:
                    st.error("Subtitle မထုတ်နိုင်ပါ — အသံစာသားမတွေ့ပါ (ဗီဒီယိုမှာ မူရင်းအသံမပါလျှင် အပေါ်က 'Recap Builder ရဲ့ AI script ကို timing ချိန်ညှိမည်' ကိုရွေးပါ)။")
                else:
                    if subtitle_language.startswith("မြန်မာ"):
                        with st.spinner("မိနစ်၊ စက္ကန့်အတိုင်း သဘာဝကျသော မြန်မာအပြောစကားသို့ တစ်ကြောင်းချင်း ပြန်ဆိုနေသည်…"):
                            segments, warn_msg = translate_segments(segments)
                        if warn_msg:
                            st.warning(warn_msg)
                    font = padauk_font()
                    if not font:
                        st.error("မြန်မာ subtitle font ကိုရယူမရပါ။ Network ကိုစစ်ပြီး ပြန်စမ်းပါ။")
                    else:
                        write_subtitles(segments)
                        ok, error = run_media(["ffmpeg", "-y", "-i", str(PATHS["caption_source"]), "-vf", f"ass={PATHS['caption_ass']}:fontsdir={font.parent}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "copy", str(PATHS["caption_video"])])
                        if ok:
                            st.session_state.caption_video = str(PATHS["caption_video"])
                            st.session_state.srt_path = str(PATHS["caption_srt"])
                            st.session_state.segments = segments
                            st.session_state.dub_language = "မြန်မာ" if subtitle_language.startswith("မြန်မာ") else (subtitle_source if subtitle_source in ("မြန်မာ", "English") else None)
                            st.session_state.dubbed_video = None
                            st.success("Subtitle MP4 နှင့် SRT ပြီးပါပြီ။ အောက်မှာ dubbing ကိုလည်း ဆက်လုပ်နိုင်ပါတယ်။")
                        else:
                            st.error(f"Caption video မထုတ်နိုင်ပါ — {error}")
    else:
        if not st.session_state.final_script.strip():
            st.markdown('<div class="callout warn">Recap Builder tab မှာ script တစ်ခု အရင်ဖန်တီးပါ၊ ပြီးရင် "ဒီ script နဲ့ ဗီဒီယိုကို Subtitle Studio ကို ပို့ပါ" ခလုတ်ကို နှိပ်ပါ။</div>', unsafe_allow_html=True)
        else:
            script_language_for_align = st.selectbox(
                "ဒီ script က ဘယ်ဘာသာနဲ့ ရေးထားလဲ",
                ["မြန်မာ", "English"],
                index=0 if st.session_state.get("script_language", "မြန်မာ") == "မြန်မာ" else 1,
                key="align_script_language",
            )
            translate_to_burmese = script_language_for_align == "English" and st.checkbox("Caption ကို မြန်မာဘာသာသို့ ထပ်ပြန်ဆိုမည်", value=True)
            with st.expander("Script preview", expanded=False):
                st.write(st.session_state.final_script)
            if st.button("Script ကို Video timing နဲ့ချိန်ညှိပြီး Subtitle ဖန်တီးပါ", type="primary", use_container_width=True):
                if not PATHS["caption_source"].exists():
                    st.warning("ဗီဒီယိုဖိုင်ကို အရင်ထည့်ပါ (Recap Builder ကနေ 'ပို့ပါ' ခလုတ်နဲ့လည်း ရနိုင်ပါတယ်)။")
                elif not st.session_state.api_keys:
                    st.warning("Sidebar မှာ Gemini API key ထည့်ပါ။")
                else:
                    with st.spinner("Video ရဲ့ မြင်ကွင်းအစီအစဉ်နဲ့ script ကို timing ချိန်ညှိနေသည် (အနည်းငယ်အချိန်ယူနိုင်သည်)…"):
                        segments, error = align_script_to_video(PATHS["caption_source"], st.session_state.final_script, script_language_for_align)
                    if not segments:
                        st.error(f"Timing ချိန်ညှိမရပါ — {error}")
                    else:
                        if translate_to_burmese:
                            with st.spinner("သဘာဝကျသော မြန်မာအပြောစကားသို့ တစ်ကြောင်းချင်း ပြန်ဆိုနေသည်…"):
                                segments, warn_msg = translate_segments(segments)
                            if warn_msg:
                                st.warning(warn_msg)
                        font = padauk_font()
                        if not font:
                            st.error("မြန်မာ subtitle font ကိုရယူမရပါ။ Network ကိုစစ်ပြီး ပြန်စမ်းပါ။")
                        else:
                            write_subtitles(segments)
                            burn_command = ["ffmpeg", "-y", "-i", str(PATHS["caption_source"]), "-vf", f"ass={PATHS['caption_ass']}:fontsdir={font.parent}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
                            burn_command += ["-an"] if st.session_state.get("script_video_is_silent") else ["-c:a", "copy"]
                            ok, error = run_media(burn_command + [str(PATHS["caption_video"])])
                            if ok:
                                st.session_state.caption_video = str(PATHS["caption_video"])
                                st.session_state.srt_path = str(PATHS["caption_srt"])
                                st.session_state.segments = segments
                                st.session_state.dub_language = "မြန်မာ" if (translate_to_burmese or script_language_for_align == "မြန်မာ") else "English"
                                st.session_state.dubbed_video = None
                                st.success("Video timing နဲ့ ကိုက်ညီသော Subtitle MP4 နှင့် SRT ပြီးပါပြီ။ အောက်မှာ dubbing ကိုလည်း ဆက်လုပ်နိုင်ပါတယ်။")
                            else:
                                st.error(f"Caption video မထုတ်နိုင်ပါ — {error}")
    if st.session_state.caption_video and Path(st.session_state.caption_video).exists():
        caption_video, srt = Path(st.session_state.caption_video), Path(st.session_state.srt_path)
        st.video(str(caption_video))
        first, second = st.columns(2)
        with first:
            st.download_button("Captioned MP4 ဒေါင်းလုဒ်", caption_video.read_bytes(), "recap_captions.mp4", "video/mp4", use_container_width=True)
        with second:
            st.download_button("SRT ဒေါင်းလုဒ်", srt.read_bytes(), "recap_captions.srt", "text/plain", use_container_width=True)

    st.markdown("---")
    st.markdown('<p class="section-title">🗣️ Voice Dubbing</p><p class="section-lead">အထက်က caption စာသားအတိုင်း ကွက်တိ — video ရဲ့ မိနစ်၊ စက္ကန့်နဲ့ အတိအကျကိုက်ညီအောင် အသံအသစ်ကို အလိုအလျောက် ဆွဲရှည်/ဆွဲတို/ခံနားချိန်ညှိပြီး ထည့်ပေးပါသည်။</p>', unsafe_allow_html=True)
    if not st.session_state.get("segments"):
        st.markdown('<div class="callout warn">Dubbing မလုပ်ခင် အပေါ်က "Subtitle ဖန်တီးပါ" ကို အရင်နှိပ်ပါ။</div>', unsafe_allow_html=True)
    else:
        dub_language_auto = st.session_state.get("dub_language")
        if not dub_language_auto:
            st.markdown('<div class="callout warn">Dubbing ကို လောလောဆယ် "မြန်မာ (တိကျသောဘာသာပြန်)" caption သို့မဟုတ် "English" မူရင်းအသံအတွက်သာ ပံ့ပိုးထားပါသည်။ Subtitle language ကို "မြန်မာ (တိကျသောဘာသာပြန်)" ရွေးပြီး ပြန်စလုပ်ကြည့်ပါ။</div>', unsafe_allow_html=True)
        else:
            d1, d2, d3 = st.columns(3)
            with d1:
                dub_gender = st.selectbox("အသံအမျိုးအစား", ["မ", "ကျား"], key="dub_gender")
            with d2:
                dub_engine = st.radio("Voice engine", ["Edge TTS (free)", "Google Cloud TTS"], horizontal=True, key="dub_engine")
            with d3:
                burn_captions = st.checkbox("စာတန်းထိုးပါ (Burn subtitle)", value=True, key="dub_burn")
            if dub_language_auto == "English":
                st.caption("English dubbing အတွက်လည်း international ရှင်းလင်းပီသတဲ့ Jenny/Guy standard voice ကို default သုံးထားပါတယ်။")
            if st.button("🎙️ Dubbed video ထုတ်ပါ", type="primary", use_container_width=True):
                if dub_engine == "Google Cloud TTS" and st.session_state.google_creds is None:
                    st.warning("Google Cloud TTS အတွက် service_account.json ကို sidebar တွင်တင်ပါ။")
                else:
                    engine_name = "Google Cloud TTS" if dub_engine == "Google Cloud TTS" else "Edge TTS"
                    with st.spinner("Timing ကိုက်အောင် အသံသွင်းနေသည် (မိနစ်များပါက အချိန်ယူနိုင်သည်)…"):
                        dub_audio, err = build_dubbed_audio(st.session_state.segments, dub_language_auto, dub_gender, engine_name)
                    if not dub_audio:
                        st.error(f"Dub အသံမထုတ်နိုင်ပါ — {err}")
                    else:
                        with st.spinner("ဗီဒီယိုထဲ အသံအသစ်ထည့်နေသည်…"):
                            output_path = SESSION_DIR / f"dubbed_{int(time.time())}.mp4"
                            if burn_captions and PATHS["caption_ass"].exists():
                                font = padauk_font()
                                fontsdir = font.parent if font else APP_DIR
                                ok2, err2 = run_media(["ffmpeg", "-y", "-i", str(PATHS["caption_source"]), "-i", str(dub_audio), "-filter_complex", f"[0:v]ass={PATHS['caption_ass']}:fontsdir={fontsdir}[v]", "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output_path)])
                            else:
                                ok2, err2 = mux_dubbed_video(PATHS["caption_source"], dub_audio, output_path)
                        if ok2:
                            st.session_state.dubbed_video = str(output_path)
                            st.success("Dubbed video ပြီးပါပြီ — video ရဲ့ timing အတိုင်း ကွက်တိ အသံသွင်းပြီးပါပြီ။")
                        else:
                            st.error(f"Dubbed video မထုတ်နိုင်ပါ — {err2}")
    if st.session_state.get("dubbed_video") and Path(st.session_state.dubbed_video).exists():
        dubbed = Path(st.session_state.dubbed_video)
        st.markdown("#### Dubbed video output")
        st.video(str(dubbed))
        st.download_button("Dubbed MP4 ဒေါင်းလုဒ်", dubbed.read_bytes(), "recap_dubbed.mp4", "video/mp4", use_container_width=True)


with publish_tab:
    st.markdown('<p class="section-title">↗ Publish Kit</p><p class="section-lead">Recap script ကနေ publish-ready title, description နှင့် hashtags ကို ထုတ်ပါ။</p>', unsafe_allow_html=True)
    if st.button("Title နှင့် caption idea ဖန်တီးပါ", type="primary", use_container_width=True):
        if not st.session_state.final_script.strip():
            st.warning("Recap Builder မှာ script တစ်ခုဖန်တီး သို့မဟုတ် ရေးထားပါ။")
        elif not st.session_state.api_keys:
            st.warning("Sidebar မှာ Gemini API key ထည့်ပါ။")
        else:
            prompt = f"Based only on this Burmese recap narration, create a concise social publishing kit in Burmese. Return exactly these sections: TITLE IDEAS (5 short, factual, non-clickbait titles), DESCRIPTION (one 2–3 sentence description), HASHTAGS (8 relevant hashtags). Do not invent facts.\n\nNarration:\n{st.session_state.final_script}"
            with st.spinner("Publish kit ပြင်ဆင်နေသည်…"):
                kit, error = generate(prompt)
            if kit:
                st.session_state.publish_kit = kit
            else:
                st.error(f"Publish kit မဖန်တီးနိုင်ပါ — {error}")
    if st.session_state.publish_kit:
        st.code(st.session_state.publish_kit, language=None)

st.markdown('<p class="footer-note">Recap Studio MM · single-user local session · API key & credentials သိမ်းထားမှုသည် ဒီ server disk ပေါ်တွင်သာ ရှိပါသည်</p>', unsafe_allow_html=True)
