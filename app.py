import streamlit as st
import os
import re
import time
import json
import glob
import subprocess
import urllib.request
import asyncio
import shutil
from PIL import Image, ImageDraw, ImageFont

# ----------------- 1 GB FILE UPLOAD CONFIG AUTOMATION -----------------
os.makedirs(".streamlit", exist_ok=True)
config_toml_path = os.path.join(".streamlit", "config.toml")
try:
    with open(config_toml_path, "w", encoding="utf-8") as cfg_f:
        cfg_f.write("[server]\nmaxUploadSize = 1024\nenableXsrfProtection = false\n")
except Exception:
    pass

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Recap Studio MM Pro - Strict Sync",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- NEON CYBERPUNK STYLING -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Plus+Jakarta+Sans:wght@400;600;700&display=swap');

    .stApp {
        background: radial-gradient(circle at 15% 15%, #071026 0%, #030712 60%, #02040a 100%);
        color: #f1f5f9;
        font-family: 'Plus Jakarta Sans', sans-serif;
    }

    @keyframes neonPulse {
        0% { box-shadow: 0 0 10px rgba(0, 242, 254, 0.25), 0 0 20px rgba(0, 242, 254, 0.15); border-color: rgba(0, 242, 254, 0.6); }
        50% { box-shadow: 0 0 25px rgba(0, 242, 254, 0.45), 0 0 40px rgba(56, 189, 248, 0.25); border-color: rgba(56, 189, 248, 0.9); }
        100% { box-shadow: 0 0 10px rgba(0, 242, 254, 0.25), 0 0 20px rgba(0, 242, 254, 0.15); border-color: rgba(0, 242, 254, 0.6); }
    }

    .neo-card {
        background: linear-gradient(135deg, rgba(13, 24, 48, 0.85) 0%, rgba(5, 12, 26, 0.95) 100%);
        border: 1.5px solid rgba(0, 242, 254, 0.35);
        border-radius: 16px;
        padding: 20px 24px;
        margin-bottom: 20px;
        position: relative;
        backdrop-filter: blur(14px);
        transition: all 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .neo-card:hover {
        transform: translateY(-4px);
        border-color: #00f2fe;
        box-shadow: 0 12px 35px rgba(0, 242, 254, 0.25);
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
        transform: translateY(-4px);
        border-color: #a855f7;
        box-shadow: 0 12px 35px rgba(168, 85, 247, 0.25);
    }

    .badge-sync {
        background: rgba(0, 242, 254, 0.12);
        color: #00f2fe;
        border: 1px solid #00f2fe;
        padding: 5px 14px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 800;
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
        display: inline-block;
        box-shadow: 0 0 10px rgba(168, 85, 247, 0.2);
    }

    .hero-title {
        font-family: 'Orbitron', 'Plus Jakarta Sans', sans-serif;
        background: linear-gradient(90deg, #00f2fe, #38bdf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900;
        letter-spacing: 1px;
        margin: 0;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SDK AUTO-DETECTOR -----------------
use_new_sdk = False
try:
    from google import genai
    from google.genai import types
    use_new_sdk = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
        use_new_sdk = False
    except ImportError:
        pass

# ----------------- MYANMAR FONT CONFIG -----------------
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
        "Pyidaungsu.ttf": "https://github.com/googlefonts/pyidaungsu/raw/main/fonts/ttf/Pyidaungsu-Regular.ttf"
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

# ----------------- CONFIG & CLEANUP -----------------
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

def cleanup_workspace():
    """SAFE CLEANUP: Only removes intermediate audio/subtitle files."""
    patterns = ["silence_*.mp3", "raw_seg_*.mp3", "*.ass", "temp_bgm.mp3", "concat_segments.txt", "raw_frame.png"]
    count = 0
    for p in patterns:
        for f in glob.glob(p):
            try:
                os.remove(f)
                count += 1
            except Exception:
                pass
    return count

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

# ----------------- SCRIPT CLEANER -----------------
PHONETICS_MM = {
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
    r"\bLike\b": "လိုက်ခ်"
}

def clean_script_line(text, lang="my"):
    if not text:
        return ""
    t = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?", "", text)
    t = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", t)
    t = re.sub(r"[\(\[（【].*?[\)\]）】]", "", t)
    t = re.sub(r"[*#_~>`]", "", t)
    
    if lang == "my":
        for pattern, rep in PHONETICS_MM.items():
            t = re.sub(pattern, rep, t, flags=re.IGNORECASE)
        t = re.sub(r"[၊,]+", " ", t)
        t = re.sub(r"[။\.\!\?]+", " ။ ", t)
        
    t = re.sub(r"\s+", " ", t).strip()
    return t

def process_user_logo(input_path, output_path):
    try:
        img = Image.open(input_path).convert("RGBA")
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

# ----------------- SESSION STATES -----------------
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))
if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = "စိတ်ဝင်စားဖွယ်ရာ"
if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = "ဇာတ်ကွက်များ"
if "target_language" not in st.session_state:
    st.session_state.target_language = "🇲🇲 Burmese (မြန်မာစကားပြောသံ)"
if "dialogues_timeline" not in st.session_state:
    st.session_state.dialogues_timeline = []
if "sub_v_pos_percent" not in st.session_state:
    st.session_state.sub_v_pos_percent = 22
if "hook_top_percent" not in st.session_state:
    st.session_state.hook_top_percent = 7
if "sub_font_size" not in st.session_state:
    st.session_state.sub_font_size = 40
if "sub_color_hex" not in st.session_state:
    st.session_state.sub_color_hex = "#00F2FE"
if "sub_bg_style" not in st.session_state:
    st.session_state.sub_bg_style = "Solid Box (အမည်းနောက်ခံ)"
if "enable_subtitles" not in st.session_state:
    st.session_state.enable_subtitles = True
if "mute_original_audio" not in st.session_state:
    st.session_state.mute_original_audio = False
if "user_watermark_file" not in st.session_state:
    st.session_state.user_watermark_file = ""
if "last_rendered_video" not in st.session_state:
    st.session_state.last_rendered_video = ""
if "video_reframe_style" not in st.session_state:
    st.session_state.video_reframe_style = "Smart Blur Background (မူရင်းအပြည့် + ဘေးဘက်ဝါး)"
if "last_uploaded_file_id" not in st.session_state:
    st.session_state.last_uploaded_file_id = None
if "selected_ai_model" not in st.session_state:
    st.session_state.selected_ai_model = "gemini-2.5-flash"

VOICE_CATALOG = {
    "🇲🇲 Burmese (မြန်မာစကားပြောသံ)": {
        "မင်းသန့် (Action & Dynamic Narrator)": {"voice": "my-MM-ThihaNeural", "rate": "+0%", "pitch": "-1Hz", "lang": "my"},
        "မေသူ (Drama & Expressive Female)": {"voice": "my-MM-NilarNeural", "rate": "+0%", "pitch": "+1Hz", "lang": "my"}
    },
    "🇬🇧 English (English Dubbing)": {
        "Christopher (Deep Cinematic)": {"voice": "en-US-ChristopherNeural", "rate": "+0%", "pitch": "-1Hz", "lang": "en"},
        "Jenny (Energetic Female)": {"voice": "en-US-JennyNeural", "rate": "+0%", "pitch": "+1Hz", "lang": "en"}
    }
}

RECAP_MODES = {
    "🔍 Auto-Detect (အလိုအလျောက် သုံးသပ်မည်)": "auto",
    "🔬 Science, Test & Experiment (စမ်းသပ်မှုနှင့် သိပ္ပံ)": "experiment",
    "🛠️ Silent Craft & DIY (အသံမဲ့ လက်မှုပညာ)": "craft",
    "🎬 Movie & Fiction Recap (ရုပ်ရှင်နှင့် ဇာတ်လမ်းတွဲများ)": "movie"
}

def extract_timeline_dialogues(raw_api_keys, video_path, target_language="my", mode_key="auto", selected_model="gemini-2.5-flash"):
    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_keys) if k.strip()]
    if not keys:
        raise ValueError("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။")

    lang_instruction = "Burmese language (မြန်မာစကားပြော အသုံးအနှုန်းသီးသန့်)" if target_language == "my" else "English language"

    mode_prompts = {
        "auto": "Observe this video very carefully. Focus ONLY on exact speaking moments.",
        "experiment": "This is an Experiment video. Only dub exactly when someone is actively explaining.",
        "craft": "This is a DIY video. If silent, only dub briefly during prominent actions.",
        "movie": "This is a Movie/Animation. Act as an expert dubbing director."
    }
    context = mode_prompts.get(mode_key, mode_prompts["auto"])

    prompt = f"""
{context}

CRITICAL TIMELINE RULES FOR STRICT DUBBING:
1. ONLY identify timestamps where characters or narrators are ACTUALLY SPEAKING in the video.
2. If there is NO speech (e.g. background music, silent walking, fighting), DO NOT create any dialogue entry for that gap.
3. Make sure the translated text is VERY CONCISE. It must fit within the given start/end timeframe at normal speaking speed.
4. For each active dialogue segment, output:
   - "start": exact start timestamp in seconds (float, e.g. 3.2)
   - "end": exact end timestamp in seconds (float, e.g. 6.8)
   - "speaker": character name or gender
   - "text": natural, concise dubbed speech in {lang_instruction}.

Return STRICTLY JSON format:
{{
  "hook_line1": "Catchy Hook Line 1",
  "hook_line2": "Catchy Hook Line 2",
  "dialogues": [
    {{
      "start": 2.5,
      "end": 5.4,
      "speaker": "Hero",
      "text": "Short translated dialogue..."
    }}
  ]
}}
"""
    models_to_try = [selected_model]
    last_err = None
    
    for k_idx, current_key in enumerate(keys):
        try:
            # ဗီဒီယိုဖိုင်အား Google Server သို့ (၁) ခါသာ ပို့ရန် (Upload Once)
            uploaded_file_ref = None
            if use_new_sdk:
                client = genai.Client(api_key=current_key)
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယိုကို AI မျက်စိဖြင့် လေ့လာရန် ပေးပို့နေပါသည်..."):
                        video_file = client.files.upload(file=video_path)
                        waits = 0
                        while getattr(video_file, "state", None) == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file = client.files.get(name=video_file.name)
                        uploaded_file_ref = video_file
            else:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=current_key)
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယိုကို AI မျက်စိဖြင့် လေ့လာရန် ပေးပို့နေပါသည်..."):
                        video_file_obj = legacy_genai.upload_file(path=video_path)
                        waits = 0
                        while video_file_obj.state.name == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file_obj = legacy_genai.get_file(video_file_obj.name)
                        if video_file_obj.state.name == "ACTIVE":
                            uploaded_file_ref = video_file_obj

            # 503 Server Error အတွက် Model များပြောင်းလဲခြင်း နှင့် Retry လုပ်ခြင်း
            for model_name in models_to_try:
                for attempt in range(2):
                    try:
                        raw_resp = ""
                        if use_new_sdk:
                            contents = [uploaded_file_ref, prompt] if uploaded_file_ref else [prompt]
                            with st.spinner(f"🧠 AI စဉ်းစားနေပါသည် ({model_name})..."):
                                res = client.models.generate_content(model=model_name, contents=contents)
                            raw_resp = res.text.strip()
                        else:
                            model = legacy_genai.GenerativeModel(model_name)
                            contents = [uploaded_file_ref, prompt] if uploaded_file_ref else prompt
                            with st.spinner(f"🧠 AI စဉ်းစားနေပါသည် ({model_name})..."):
                                res = model.generate_content(contents)
                            raw_resp = res.text.strip()

                        match = re.search(r"\{.*\}", raw_resp, re.DOTALL)
                        if match:
                            data = json.loads(match.group(0))
                            return data
                        raise ValueError("AI JSON ပြန်ကြားချက် မမှန်ကန်ပါ။")
                        
                    except Exception as e:
                        last_err = e
                        err_str = str(e).lower()
                        if "503" in err_str or "unavailable" in err_str or "overloaded" in err_str:
                            if attempt == 0:
                                st.warning(f"⚠️ Google Server ယာယီ ကြပ်နေပါသည် (503 Error)။ ၅ စက္ကန့်စောင့်ပြီး အလိုအလျောက် ထပ်မံကြိုးစားပါမည်...")
                                time.sleep(5)
                                continue 
                            else:
                                st.warning(f"⚠️ {model_name} ဆက်တိုက် ကြပ်နေသဖြင့် အခြား Model သို့ ပြောင်းလဲနေပါသည်...")
                                break
                        elif "429" in err_str or "quota" in err_str:
                            raise e 
                        else:
                            raise e
                            
        except Exception as e:
            last_err = e
            if "429" in str(e).lower() or "quota" in str(e).lower():
                st.warning(f"⚠️ API Key (#{k_idx+1}) Limit ပြည့်သွားသဖြင့် နောက် Key သို့ ကူးပြောင်းနေပါသည်...")
                continue
            continue
            
    raise Exception(f"AI Extraction Error: {last_err}")

def render_strict_1x_timeline_narration(dialogues, voice_cfg, total_video_duration, final_audio_path):
    """
    CRITICAL FIX: NO ATEMPO USED. Audio runs at pure 1x normal speed.
    Places audio strictly at the start timestamp by padding with silence before it.
    """
    import edge_tts
    sorted_dialogues = sorted(dialogues, key=lambda d: float(d.get("start", 0)))
    concat_list_file = "concat_segments.txt"
    segment_files = []
    current_time = 0.0

    with st.spinner("🎙️ အမြန်နှုန်းကို လုံးဝမပြောင်းလဲဘဲ Normal 1x အတိုင်း အချိန်ဇယားတိတိကျကျ ချထားနေပါသည်..."):
        for idx, item in enumerate(sorted_dialogues):
            d_start = max(0.0, float(item.get("start", 0.0)))
            d_text = clean_script_line(item.get("text", ""), voice_cfg.get("lang", "my"))

            if not d_text:
                continue

            # 1. Fill exact silence gap before this dialogue begins
            gap = d_start - current_time
            if gap > 0.05:
                silence_gap = f"silence_gap_{idx}.mp3"
                cmd_sil = [
                    "ffmpeg", "-y", "-threads", "1", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", f"{gap:.3f}",
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    silence_gap
                ]
                subprocess.run(cmd_sil, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                segment_files.append(silence_gap)
                current_time += gap
            elif gap < 0:
                # If previous audio was slightly longer, we just start immediately without silence gap.
                pass 

            # 2. Render normal 1x speed dialogue TTS
            raw_seg = f"raw_seg_{idx}.mp3"
            comm = edge_tts.Communicate(
                text=d_text,
                voice=voice_cfg["voice"],
                rate=voice_cfg["rate"],
                pitch=voice_cfg["pitch"]
            )
            asyncio.run(comm.save(raw_seg))

            raw_dur = get_media_duration(raw_seg)
            if raw_dur > 0:
                segment_files.append(raw_seg)
                current_time += raw_dur

        # 3. Final silence tail to guarantee audio length perfectly matches video length
        if total_video_duration > current_time + 0.05:
            tail_gap = total_video_duration - current_time
            tail_file = "silence_tail.mp3"
            cmd_tail = [
                "ffmpeg", "-y", "-threads", "1", "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{tail_gap:.3f}",
                "-c:a", "libmp3lame", "-b:a", "192k",
                tail_file
            ]
            subprocess.run(cmd_tail, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            segment_files.append(tail_file)

    # 4. Concatenate all segments into a master track
    if not segment_files:
        # Fallback empty audio if no dialogues found
        cmd_empty = [
            "ffmpeg", "-y", "-threads", "1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{total_video_duration:.3f}", "-c:a", "libmp3lame", "-b:a", "192k", final_audio_path
        ]
        subprocess.run(cmd_empty, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return

    with open(concat_list_file, "w", encoding="utf-8") as cf:
        for sf in segment_files:
            cf.write(f"file '{sf}'\n")

    cmd_concat = [
        "ffmpeg", "-y", "-threads", "2", "-f", "concat", "-safe", "0",
        "-i", concat_list_file,
        "-c:a", "libmp3lame", "-b:a", "192k",
        final_audio_path
    ]
    subprocess.run(cmd_concat, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def hex_to_ass(hex_code):
    h = hex_code.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H0000FFFF&"

def create_timeline_ass_subtitles(h1, h2, dialogues, duration, ass_path, font_size, v_margin, hex_color, bg_style):
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

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if h1 or h2:
        hook_str = f"{h1}\\N{h2}" if h1 and h2 else (h1 or h2)
        ass_text += f"Dialogue: 1,0:00:00.00,{fmt_ass_time(duration)},HookStyle,,0,0,0,,{{\\t(0,200,\\fscx105\\fscy105)\\t(200,350,\\fscx100\\fscy100)}}{hook_str}\n"

    for d in dialogues:
        st_sec = max(0.0, float(d.get("start", 0.0)))
        en_sec = min(duration, float(d.get("end", st_sec + 3.0)))
        line = d.get("text", "").strip()
        if line:
            # CapCut Style pop-in subtitle effect
            pop_fx = "{\\t(0,120,\\fscx112\\fscy112)\\t(120,240,\\fscx100\\fscy100)}"
            ass_text += f"Dialogue: 0,{fmt_ass_time(st_sec)},{fmt_ass_time(en_sec)},SubtitleStyle,,0,0,0,,{pop_fx}{line}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

def has_audio_stream(file_path):
    try:
        cmd = ["ffprobe", "-i", file_path, "-show_streams", "-select_streams", "a", "-loglevel", "error"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return len(res.stdout.strip()) > 0
    except:
        return False

def render_dialogue_synced_video(input_video, narration_audio, ass_path, output_video, logo_path=None, logo_pos="top_right", reframe_mode="Smart Blur Background", mute_original=False):
    exact_duration = get_media_duration(input_video)
    if exact_duration <= 0.0:
        exact_duration = 30.0

    # Smart Auto-Reframe (Blur Background vs Center Crop)
    if "Blur" in reframe_mode:
        base_vfilter = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=25:10,eq=brightness=-0.15[bg];"
            "[0:v]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[vreframed]"
        )
        v_stream_name = "[vreframed]"
    else:
        base_vfilter = "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280[vreframed]"
        v_stream_name = "[vreframed]"

    sub_filter = f"{v_stream_name}subtitles={ass_path}:fontsdir=.[vsub]" if (ass_path and os.path.exists(ass_path)) else f"{v_stream_name}copy[vsub]"

    pos_map = {
        "top_right": "main_w-overlay_w-24:24",
        "top_left": "24:24",
        "bottom_right": "main_w-overlay_w-24:main_h-overlay_h-24"
    }

    # Audio Logic: Mute or Ducking
    has_orig_audio = has_audio_stream(input_video)
    
    if not has_orig_audio or mute_original:
        # Strictly muted or silent video
        audio_filter = "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.2,apad[afinal]"
    else:
        # Advanced Audio Ducking (Original volume lowered when AI speaks)
        audio_filter = (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.3[orig_sfx];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.2,apad[ai_dub];"
            "[ai_dub]asplit[ai_final][ai_sc];"
            "[orig_sfx][ai_sc]sidechaincompress=threshold=0.03:ratio=10.0:attack=10:release=500[ducked_sfx];"
            "[ducked_sfx][ai_final]amix=inputs=2:duration=longest:dropout_transition=0[afinal]"
        )

    if logo_path and os.path.exists(logo_path):
        overlay_coords = pos_map.get(logo_pos, "main_w-overlay_w-24:24")
        full_complex = (
            f"{base_vfilter};"
            f"{sub_filter};"
            f"[2:v]scale=120:-1,format=rgba[logo];"
            f"[vsub][logo]overlay={overlay_coords}[vfinal];"
            f"{audio_filter}"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "2",
            "-i", input_video,
            "-i", narration_audio,
            "-i", logo_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "24",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]
    else:
        full_complex = (
            f"{base_vfilter};"
            f"{sub_filter};"
            f"[vsub]copy[vfinal];"
            f"{audio_filter}"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "2",
            "-i", input_video,
            "-i", narration_audio,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "24",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 10px 0 16px 0;">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #00f2fe; margin-bottom: 4px; font-weight: 800;">⚡ RECAP STUDIO PRO</h2>
        <span class="badge-sync">STRICT 1:1 TIMELINE</span>
    </div>
    """, unsafe_allow_html=True)

    if not use_new_sdk:
         st.warning("Running in Fallback SDK Mode (google.generativeai).")

    st.markdown("#### 🔑 **Gemini API Key**")
    current_key_val = st.text_area(
        "API Key",
        value=st.session_state.gemini_api_key,
        placeholder="AIzaSy...",
        height=70,
        label_visibility="collapsed"
    )
    if current_key_val != st.session_state.gemini_api_key:
        st.session_state.gemini_api_key = current_key_val
        save_config("gemini_api_key", current_key_val)
        st.success("✅ API Key သိမ်းဆည်းပြီးပါပြီ!")

    st.markdown("---")
    st.markdown("#### 🤖 **AI Model Selection**")
    st.session_state.selected_ai_model = st.selectbox(
        "Gemini Model ရွေးချယ်ပါ (503 Error တက်ပါက ပြောင်းသုံးရန်)",
        ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"],
        index=["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"].index(st.session_state.selected_ai_model) if st.session_state.selected_ai_model in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"] else 0
    )

    st.markdown("---")
    st.markdown("#### 🌐 **Language & Narrator**")
    st.session_state.target_language = st.selectbox(
        "ဘာသာစကား ရွေးချယ်ပါ (Dub Language)",
        ["🇲🇲 Burmese (မြန်မာစကားပြောသံ)", "🇬🇧 English (English Dubbing)"],
        index=0 if "Burmese" in st.session_state.target_language else 1
    )

    available_voices = VOICE_CATALOG[st.session_state.target_language]
    voice_sel = st.selectbox("🎙️ Narrator Voice (အသံရွေးချယ်ပါ)", list(available_voices.keys()), index=0)

    st.markdown("---")
    if st.button("🧹 Storage ရှင်းလင်းမည် (Safe Cleanup)", use_container_width=True):
        cleaned_cnt = cleanup_workspace()
        st.success(f"🧹 ယာယီအသံဖိုင်ပေါင်း {cleaned_cnt} ခုအား ရှင်းလင်းပြီးပါပြီ!")

tab_dub, tab_thumb, tab_splitter, tab_settings = st.tabs([
    "🎬 Master Studio (Strict Sync)",
    "🖼️ Viral Thumbnail",
    "🍿 1 GB Shorts Splitter",
    "⚙️ System Settings"
])

with tab_dub:
    st.markdown("""
    <div class="neo-card" style="animation: neonPulse 4s infinite alternate;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <h2 class="hero-title" style="font-size: 24px;">🎬 Normal 1x Speed Locked Dubbing</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 6px; margin-bottom: 0;">
                    ဇာတ်ကောင် စကားပြောချိန်တွင်သာ AI မှ အမြန်နှုန်းမပြောင်းဘဲ (1x အတိုင်း) အတိအကျဝင်ရောက်ပြောဆိုပေးမည့်စနစ်
                </p>
            </div>
            <div>
                <span class="badge-sync">NO SPEED DISTORTION</span>
                <span class="badge-purple">AUDIO DUCKING</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_up1, col_up2 = st.columns([1.2, 1.0])

    with col_up1:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">1. 📤 ဗီဒီယို တင်ပါ</h4>""", unsafe_allow_html=True)
        up_file = st.file_uploader("ဗီဒီယိုဖိုင် တင်ပါ (MP4, MOV, WebM - Max 1GB)", type=["mp4", "mov", "webm"])
        
        if up_file and up_file.file_id != st.session_state.last_uploaded_file_id:
            with open("temp_input.mp4", "wb") as f:
                f.write(up_file.getbuffer())
            st.session_state.last_uploaded_file_id = up_file.file_id

        yt_url = st.text_input("သို့မဟုတ် Video Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=...")

        vid_len = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
        if vid_len > 0:
            st.success(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(vid_len)} ({vid_len:.2f} စက္ကန့်)**")

        selected_mode_label = st.selectbox("🎯 Recap အမျိုးအစား (Context Analysis)", list(RECAP_MODES.keys()), index=0)
        mode_key = RECAP_MODES[selected_mode_label]

        st.session_state.video_reframe_style = st.selectbox(
            "📐 မျက်နှာပြင် အချိုးအစား (Smart Reframe)",
            ["Smart Blur Background (မူရင်းအပြည့် + ဘေးဘက်ဝါး)", "Center Crop (အလယ်ကိုသာ ဖြတ်ယူမည်)"],
            index=0
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_up2:
        st.markdown("""<div class="neo-card-accent"><h4 style="color: #c084fc; margin-top: 0;">2. 🏷️ Logo & Audio Control</h4>""", unsafe_allow_html=True)
        logo_file = st.file_uploader("Channel Logo တင်ပါ (Auto Remove BG)", type=["png", "jpg", "jpeg", "webp"])
        if logo_file:
            raw_logo = "raw_user_logo.png"
            clean_logo = "processed_user_logo.png"
            with open(raw_logo, "wb") as f:
                f.write(logo_file.getbuffer())
            if process_user_logo(raw_logo, clean_logo):
                st.session_state.user_watermark_file = clean_logo
                st.success("✅ Logo Background ဖျက်ပြီးပါပြီ!")
                st.image(clean_logo, width=70)

        logo_pos_choice = st.selectbox("📍 Logo နေရာ", ["top_right", "top_left", "bottom_right"], index=0)
        
        st.markdown("---")
        st.session_state.mute_original_audio = st.checkbox(
            "🔇 မူရင်းဗီဒီယိုအသံကို အပြည့်အဝ ပိတ်မည် (Mute Original Audio)", 
            value=st.session_state.mute_original_audio
        )
        st.caption("အမှတ်ခြစ်ထားပါက မူရင်းအသံ (သီချင်း၊ ဆူညံသံများ) လုံးဝပျောက်သွားပါမည်။")

        st.markdown("</div>", unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1.5, 1.0])
    with col_btn1:
        start_magic_btn = st.button("⚡ ONE-CLICK STRICT SYNC DUB (အသံမမြန်စေဘဲ အတိအကျထည့်မည်)", type="primary", use_container_width=True)
    with col_btn2:
        extract_only_btn = st.button("🔍 Timeline သာ အရင်စစ်ဆေးမည်", use_container_width=True)

    if start_magic_btn or extract_only_btn:
        cleanup_workspace() # Safe clean before run
        if not os.path.exists("temp_input.mp4") and not yt_url:
            st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ (သို့) အောက်ဘက် Splitter မှ ပို့ပေးပါ ခင်ဗျာ။")
        elif not st.session_state.gemini_api_key.strip():
            st.error("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ (Sidebar တွင် ထည့်နိုင်ပါသည်)။")
        else:
            if yt_url and not os.path.exists("temp_input.mp4"):
                with st.spinner("ဗီဒီယို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "temp_input.mp4", yt_url.split("?")[0]], capture_output=True)

            v_duration = get_media_duration("temp_input.mp4")
            if v_duration <= 0.0:
                v_duration = 30.0

            try:
                lang_code = "my" if "Burmese" in st.session_state.target_language else "en"
                with st.spinner(f"👁️ AI ဖြင့် ဇာတ်ကောင် စကားပြောချိန်ကို စက္ကန့်မလွဲ ရှာဖွေနေပါသည်..."):
                    res_data = extract_timeline_dialogues(
                        raw_api_keys=st.session_state.gemini_api_key,
                        video_path="temp_input.mp4",
                        target_language=lang_code,
                        mode_key=mode_key,
                        selected_model=st.session_state.selected_ai_model
                    )
                    st.session_state.dialogues_timeline = res_data.get("dialogues", [])
                    st.session_state.top_hook_text = res_data.get("hook_line1", "စိတ်လှုပ်ရှားဖွယ်ရာ")
                    st.session_state.bottom_hook_text = res_data.get("hook_line2", "ဇာတ်ကွက်")

                st.success(f"🎯 စကားပြောခန်းပေါင်း {len(st.session_state.dialogues_timeline)} ခုကို အချိန်အတိအကျဖြင့် ရှာဖွေတွေ့ရှိပါပြီ!")

                if start_magic_btn:
                    voice_cfg = available_voices[voice_sel]
                    synced_audio = "final_dialogue_strict_1x.mp3"
                    
                    render_strict_1x_timeline_narration(
                        dialogues=st.session_state.dialogues_timeline,
                        voice_cfg=voice_cfg,
                        total_video_duration=v_duration,
                        final_audio_path=synced_audio
                    )

                    ass_file = "timeline_subtitles.ass"
                    if st.session_state.enable_subtitles:
                        calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                        create_timeline_ass_subtitles(
                            h1=st.session_state.top_hook_text,
                            h2=st.session_state.bottom_hook_text,
                            dialogues=st.session_state.dialogues_timeline,
                            duration=v_duration,
                            ass_path=ass_file,
                            font_size=st.session_state.sub_font_size,
                            v_margin=calc_vm,
                            hex_color=st.session_state.sub_color_hex,
                            bg_style=st.session_state.sub_bg_style
                        )
                    else:
                        ass_file = None

                    with st.spinner("🎬 Final Video ပြုလုပ်နေပါသည် (အစအဆုံး တိကျစွာ လိုက်ပြောပါမည်)..."):
                        final_out = "recap_output.mp4"
                        render_dialogue_synced_video(
                            input_video="temp_input.mp4",
                            narration_audio=synced_audio,
                            ass_path=ass_file,
                            output_video=final_out,
                            logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                            logo_pos=logo_pos_choice.split(" ")[0],
                            reframe_mode=st.session_state.video_reframe_style,
                            mute_original=st.session_state.mute_original_audio
                        )
                        st.session_state.last_rendered_video = final_out
                        st.success("🎉 အောင်မြင်ပါပြီ! ဗီဒီယိုအမြန်နှုန်း ၁ဆ (1x) အတိုင်း စကားပြောချိန်တွင်သာ ကွက်တိလိုက်ပြောသော ဗီဒီယို ထွက်ရှိပါပြီ!")
            except Exception as ex:
                st.error(f"❌ Error: {ex}")

    st.markdown("---")
    
    col_p_vid, col_p_ctrl = st.columns([1.2, 1.2])

    with col_p_ctrl:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">⏱️ Timeline Editor (Manual Fixes)</h4>""", unsafe_allow_html=True)
        if st.session_state.dialogues_timeline:
            new_dialogues = []
            for d_idx, d_item in enumerate(st.session_state.dialogues_timeline):
                c_t1, c_t2, c_txt = st.columns([1, 1, 2.5])
                with c_t1:
                    new_st = st.number_input(f"Start ({d_idx+1})", value=float(d_item.get("start", 0.0)), step=0.1, key=f"st_{d_idx}")
                with c_t2:
                    new_en = st.number_input(f"End ({d_idx+1})", value=float(d_item.get("end", 0.0)), step=0.1, key=f"en_{d_idx}")
                with c_txt:
                    new_text = st.text_input(f"Line ({d_idx+1})", value=d_item.get("text", ""), key=f"tx_{d_idx}")
                new_dialogues.append({"start": new_st, "end": new_en, "speaker": d_item.get("speaker", ""), "text": new_text})

            st.session_state.dialogues_timeline = new_dialogues
        else:
            st.info("ဗီဒီယိုကို AI စတင်ခိုင်းပြီးပါက ဤနေရာတွင် Timeline များ ပေါ်လာမည် ဖြစ်ပါသည်။")

        st.markdown("#### ⚙️ Typography & Subtitles")
        st.session_state.enable_subtitles = st.checkbox("📝 Pop-up စာတန်းထိုး ထည့်သွင်းမည်", value=st.session_state.enable_subtitles)
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.session_state.sub_color_hex = st.color_picker("🎨 စာတန်းထိုး အရောင်", st.session_state.sub_color_hex)
        with col_s2:
            st.session_state.sub_bg_style = st.selectbox("📦 နောက်ခံစတိုင်", ["Solid Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline Only (အနားကွပ် သီးသန့်)"], index=0)

        st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ %", 5, 80, int(st.session_state.sub_v_pos_percent))
        
        if st.button("🚀 ပြင်ဆင်ချက်များဖြင့် Final Video ပြန်ထုတ်မည်", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                with st.spinner("Timeline အသစ်ဖြင့် ဗီဒီယို ပြန်လည်ထုတ်ယူနေပါသည်..."):
                    v_dur = get_media_duration("temp_input.mp4")
                    voice_cfg = available_voices[voice_sel]
                    synced_audio = "final_dialogue_strict_1x.mp3"
                    render_strict_1x_timeline_narration(
                        dialogues=st.session_state.dialogues_timeline,
                        voice_cfg=voice_cfg,
                        total_video_duration=v_dur,
                        final_audio_path=synced_audio
                    )
                    ass_file = "timeline_subtitles.ass"
                    calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                    create_timeline_ass_subtitles(
                        h1=st.session_state.top_hook_text,
                        h2=st.session_state.bottom_hook_text,
                        dialogues=st.session_state.dialogues_timeline,
                        duration=v_dur,
                        ass_path=ass_file,
                        font_size=st.session_state.sub_font_size,
                        v_margin=calc_vm,
                        hex_color=st.session_state.sub_color_hex,
                        bg_style=st.session_state.sub_bg_style
                    )
                    final_out = "recap_output.mp4"
                    render_dialogue_synced_video(
                        input_video="temp_input.mp4",
                        narration_audio=synced_audio,
                        ass_path=ass_file if st.session_state.enable_subtitles else None,
                        output_video=final_out,
                        logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                        logo_pos="top_right",
                        reframe_mode=st.session_state.video_reframe_style,
                        mute_original=st.session_state.mute_original_audio
                    )
                    st.session_state.last_rendered_video = final_out
                    st.success("✨ Re-Export အောင်မြင်ပါပြီ ခင်ဗျာ!")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_p_vid:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">📱 Live Video Player</h4>""", unsafe_allow_html=True)
        if st.session_state.last_rendered_video and os.path.exists(st.session_state.last_rendered_video):
            st.video(st.session_state.last_rendered_video)
            with open(st.session_state.last_rendered_video, "rb") as vf:
                st.download_button(
                    label="📥 Final Master MP4 ဒေါင်းလုဒ်ရယူရန်",
                    data=vf.read(),
                    file_name="dialogue_strict_1x_master.mp4",
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )
        elif os.path.exists("temp_input.mp4"):
            st.video("temp_input.mp4")
        else:
            st.info("ဗီဒီယိုဖိုင် တင်ပြီးပါက ဤနေရာတွင် တိုက်ရိုက် ကြည့်ရှုနိုင်ပါမည်။")
        st.markdown("</div>", unsafe_allow_html=True)

with tab_thumb:
    st.markdown("""
    <div class="neo-card-accent">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #ffffff; margin: 0; font-size: 20px;">🖼️ 1-Click Viral Thumbnail</h2>
    </div>
    """, unsafe_allow_html=True)

    col_th1, col_th2 = st.columns([1.2, 1.2])

    with col_th1:
        st.markdown("""<div class="neo-card"><h4 style="color: #c084fc; margin-top: 0;">📸 Cover Snapshot</h4>""", unsafe_allow_html=True)
        v_d_max = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 10.0
        thumb_sec = st.slider("📍 ဖမ်းယူမည့် စက္ကန့်", 0.0, float(v_d_max), float(min(2.5, v_d_max)), 0.1)

        t_h1 = st.text_input("Cover Line 1", value=st.session_state.top_hook_text)
        t_h2 = st.text_input("Cover Line 2", value=st.session_state.bottom_hook_text)

        if st.button("✨ Thumbnail ဖန်တီးမည်", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                temp_frame = "raw_frame.png"
                subprocess.run(["ffmpeg", "-y", "-threads", "1", "-ss", str(thumb_sec), "-i", "temp_input.mp4", "-vframes", "1", "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280", temp_frame], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(temp_frame):
                    try:
                        base = Image.open(temp_frame).convert("RGBA")
                        shade = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
                        s_draw = ImageDraw.Draw(shade)
                        s_draw.rectangle([0, 0, 720, 300], fill=(0, 0, 0, 180))
                        base = Image.alpha_composite(base, shade)
                        draw = ImageDraw.Draw(base)
                        font_path = "Pyidaungsu.ttf" if os.path.exists("Pyidaungsu.ttf") else None
                        font = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default()
                        draw.text((360, 100), t_h1, fill=(255, 235, 59, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))
                        draw.text((360, 180), t_h2, fill=(0, 242, 254, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))
                        
                        out_thumb = "viral_thumbnail.jpg"
                        base.convert("RGB").save(out_thumb, "JPEG", quality=95)
                        st.session_state.latest_thumbnail = out_thumb
                        st.success("🎉 Cover ပုံ ဖန်တီးပြီးပါပြီ ခင်ဗျာ!")
                    except Exception:
                        pass
        if "latest_thumbnail" in st.session_state and os.path.exists(st.session_state.latest_thumbnail):
            st.image(st.session_state.latest_thumbnail, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with tab_splitter:
    st.markdown("""
    <div class="neo-card-accent">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #ffffff; margin: 0; font-size: 20px;">🍿 Multi-Part Auto Splitter (1 GB Support)</h2>
    </div>
    """, unsafe_allow_html=True)

    long_file = st.file_uploader("ဗီဒီယိုရှည် တင်ပါ", type=["mp4", "mov"], key="splitter_upload")
    if long_file:
        with open("temp_long_video.mp4", "wb") as f:
            f.write(long_file.getbuffer())

    long_dur = get_media_duration("temp_long_video.mp4") if os.path.exists("temp_long_video.mp4") else 0.0

    if long_dur > 0:
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            split_slice = st.selectbox("အပိုင်းတစ်ခုစီ၏ ကြာချိန်", [30, 60, 90, 180], index=1)
        with col_s2:
            split_aspect = st.selectbox("ဗီဒီယိုပုံစံ", ["9:16 ဒေါင်လိုက်", "မူရင်း 16:9"])
        with col_s3:
            total_parts = max(1, int(long_dur // split_slice))
            
        if st.button("✂️️ အပိုင်းတိုများ ခွဲထုတ်မည်", type="primary"):
            with st.spinner(f"ဗီဒီယိုအား {total_parts} ပိုင်း ဖြတ်တောက်နေပါသည်..."):
                part_files = []
                for p_idx in range(total_parts):
                    st_sec = p_idx * split_slice
                    out_part = f"part_{p_idx+1}.mp4"
                    vf_part = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280" if "9:16" in split_aspect else "scale=1280:720"
                    cmd_split = [
                        "ffmpeg", "-y", "-threads", "2", "-ss", str(st_sec), "-t", str(split_slice),
                        "-i", "temp_long_video.mp4", "-vf", vf_part,
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_part
                    ]
                    subprocess.run(cmd_split, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if os.path.exists(out_part):
                        part_files.append((out_part, p_idx+1))
                st.session_state.split_parts_list = part_files
                st.success("အောင်မြင်စွာ ခွဲထုတ်ပြီးပါပြီ!")

        if "split_parts_list" in st.session_state and st.session_state.split_parts_list:
            cols = st.columns(2)
            for file_name, p_num in st.session_state.split_parts_list:
                with cols[(p_num - 1) % 2]:
                    st.markdown(f"**📌 Part {p_num}**")
                    st.video(file_name)
                    if st.button(f"🚀 Master Studio သို့ ပို့မည် (Part {p_num})", key=f"send_recap_{p_num}"):
                        shutil.copyfile(file_name, "temp_input.mp4")
                        st.session_state.last_uploaded_file_id = None
                        st.success(f"✅ Part {p_num} ကို Master Studio သို့ ပို့ပြီးပါပြီ! ပထမ Tab ကို သွားပါ။")

with tab_settings:
    st.markdown("""
    <div class="neo-card">
        <h2 style="color: #00f2fe; margin-top: 0;">⚙️ System Architecture </h2>
        <ul>
            <li><span class="badge-sync">STRICT 1X SPEED</span> လုံးဝ အသံမပြောင်းလဲဘဲ Normal 1x အတိုင်း အံဝင်ခွင်ကျ အလုပ်လုပ်ပါသည်။ (atempo ကို လုံးဝ ဖြုတ်ပစ်ထားပါသည်)</li>
            <li><span class="badge-purple">FULL DURATION LOCK</span> အသံကို ဗီဒီယိုအဆုံးထိ တိတိကျကျ Padding ဖြင့် ဖြည့်သွင်းထားပါသည်။</li>
            <li><span class="badge-sync">MUTE TOGGLE</span> မူရင်းအသံကို အပြည့်အဝ ပိတ်ပစ်နိုင်သည့် Option ကို UI တွင် ထည့်သွင်းထားပါသည်။</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
