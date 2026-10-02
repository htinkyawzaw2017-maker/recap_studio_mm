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
import shutil
from PIL import Image, ImageDraw, ImageFont

# ----------------- HYBRID GEMINI SDK DETECTOR -----------------
# Automatically handles Streamlit Cloud environments regardless of which SDK is installed
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

# ----------------- 1 GB FILE UPLOAD CONFIG AUTOMATION -----------------
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
    .badge-green {
        background: rgba(34, 197, 94, 0.15);
        color: #4ade80;
        border: 1px solid #4ade80;
        padding: 5px 14px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 800;
        display: inline-block;
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

def cleanup_workspace():
    """SAFE CLEANUP: Only removes intermediate audio/subtitle files. 
    Does NOT delete temp_input.mp4 or part_*.mp4 to prevent FileNotFoundError."""
    patterns = ["silence_*.mp3", "raw_seg_*.mp3", "conf_seg_*.mp3", "*.ass", "temp_bgm.mp3", "concat_segments.txt", "raw_frame.png"]
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
    r"\bLike\b": "လိုက်ခ်",
    r"\bBoss\b": "သူဌေးကြီး",
    r"\bCar\b": "ကား"
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

if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))
if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = "ဇာတ်ကွက် စိတ်ဝင်စားဖွယ်ရာ"
if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = "ကြည့်ရှုလိုက်ပါ"
if "target_language" not in st.session_state:
    st.session_state.target_language = "🇲🇲 Burmese (မြန်မာစကားပြောသံ)"
if "dialogues_timeline" not in st.session_state:
    st.session_state.dialogues_timeline = []
if "seo_description" not in st.session_state:
    st.session_state.seo_description = ""
if "seo_hashtags" not in st.session_state:
    st.session_state.seo_hashtags = "#recap #movie #myanmar #animation #shorts"
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
if "user_watermark_file" not in st.session_state:
    st.session_state.user_watermark_file = ""
if "last_rendered_video" not in st.session_state:
    st.session_state.last_rendered_video = ""
if "video_reframe_style" not in st.session_state:
    st.session_state.video_reframe_style = "Smart Blur Background (မူရင်းအပြည့် + ဘေးဘက်ဝါး)"
if "last_uploaded_file_id" not in st.session_state:
    st.session_state.last_uploaded_file_id = None

VOICE_CATALOG = {
    "🇲🇲 Burmese (မြန်မာစကားပြောသံ)": {
        "မင်းသန့် (Action & Dynamic Narrator - သွက်လက်တက်ကြွ)": {"voice": "my-MM-ThihaNeural", "rate": "+10%", "pitch": "-1Hz", "lang": "my"},
        "မေသူ (Drama & Expressive Female - စိတ်ခံစားမှုအပြည့်)": {"voice": "my-MM-NilarNeural", "rate": "+8%", "pitch": "+1Hz", "lang": "my"}
    },
    "🇬🇧 English (English Dubbing)": {
        "Christopher (Deep Cinematic Narrator - Male)": {"voice": "en-US-ChristopherNeural", "rate": "+6%", "pitch": "-1Hz", "lang": "en"},
        "Jenny (Energetic & Expressive - Female)": {"voice": "en-US-JennyNeural", "rate": "+8%", "pitch": "+1Hz", "lang": "en"}
    }
}

RECAP_MODES = {
    "🔍 Auto-Detect (အလိုအလျောက် သုံးသပ်မည်)": "auto",
    "🔬 Science, Test & Experiment (စမ်းသပ်မှုနှင့် သိပ္ပံ)": "experiment",
    "🛠️ Silent Craft & DIY (အသံမဲ့ လက်မှုပညာ)": "craft",
    "🎬 Movie & Fiction Recap (ရုပ်ရှင်နှင့် ဇာတ်လမ်းတွဲများ)": "movie"
}

def extract_timeline_dialogues(raw_api_keys, video_path, target_language="my", mode_key="auto"):
    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_keys) if k.strip()]
    if not keys:
        raise ValueError("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။")

    lang_instruction = "Burmese language (မြန်မာစကားပြော အသုံးအနှုန်းသီးသန့်)" if target_language == "my" else "English language"

    mode_prompts = {
        "auto": "Observe this video with vision and audio very carefully.",
        "experiment": "This is a Science/Experiment video. Focus on explaining the scientific steps, tests, and results clearly while matching the dialogue timelines.",
        "craft": "This is a DIY/Craft video. Explain the crafting process step by step fitting the timeline.",
        "movie": "This is a Movie/Animation clip. Act as an expert movie recap dubbing director."
    }
    context = mode_prompts.get(mode_key, mode_prompts["auto"])

    prompt = f"""
{context}

CRITICAL TIMELINE RULES:
1. ONLY identify timestamps where characters or narrators are ACTUALLY SPEAKING.
2. If there is NO speech (e.g. background music, silent actions, walking, fighting with sound effects only), DO NOT create any dialogue entry for that gap.
3. For each active dialogue segment, output:
   - "start": exact start timestamp in seconds (float, e.g. 3.2)
   - "end": exact end timestamp in seconds (float, e.g. 6.8)
   - "speaker": character name or gender
   - "text": concise, natural, lip-fit dubbed speech translated into {lang_instruction}. The line MUST be brief enough to fit comfortably within the timeframe without rushing.

Return STRICTLY JSON format:
{{
  "hook_line1": "Catchy Hook Line 1 (3-4 words)",
  "hook_line2": "Catchy Hook Line 2 (3-4 words)",
  "seo_description": "2-sentence viral summary of this clip for social media",
  "hashtags": "#recap #animation #movie #viral",
  "dialogues": [
    {{
      "start": 2.5,
      "end": 5.4,
      "speaker": "Main Hero",
      "text": "Dubbed dialogue line..."
    }}
  ]
}}
"""
    last_err = None
    for k_idx, current_key in enumerate(keys):
        try:
            raw_resp = ""
            if use_new_sdk:
                client = genai.Client(api_key=current_key)
                contents = []
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယို Timeline အား AI မျက်စိဖြင့် လေ့လာရန် Gemini API သို့ ပေးပို့နေပါသည်..."):
                        video_file = client.files.upload(file=video_path)
                        waits = 0
                        while getattr(video_file, "state", None) == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file = client.files.get(name=video_file.name)
                        contents.append(video_file)

                contents.append(prompt)
                res = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
                raw_resp = res.text.strip()
            else:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=current_key)
                video_file_obj = None
                if video_path and os.path.exists(video_path):
                    with st.spinner("📤 ဗီဒီယို Timeline အား AI မျက်စိဖြင့် လေ့လာရန် Gemini API သို့ ပေးပို့နေပါသည်..."):
                        video_file_obj = legacy_genai.upload_file(path=video_path)
                        waits = 0
                        while video_file_obj.state.name == "PROCESSING" and waits < 35:
                            time.sleep(2)
                            waits += 1
                            video_file_obj = legacy_genai.get_file(video_file_obj.name)
                        if video_file_obj.state.name != "ACTIVE":
                            video_file_obj = None

                model = legacy_genai.GenerativeModel("gemini-2.5-flash")
                contents = [video_file_obj, prompt] if video_file_obj else prompt
                res = model.generate_content(contents)
                raw_resp = res.text.strip()

            match = re.search(r"\{.*\}", raw_resp, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data
            raise ValueError("AI JSON ပြန်ကြားချက် မမှန်ကန်ပါ။")
        except Exception as e:
            last_err = e
            if "429" in str(e).lower() or "quota" in str(e).lower():
                st.warning(f"⚠️ API Key (#{k_idx+1}) Quota ပြည့်သွားသဖြင့် နောက် Key သို့ ကူးပြောင်းနေပါသည်...")
                continue
            continue
    raise Exception(f"AI Extraction Error: {last_err}")

def render_timeline_locked_narration(dialogues, voice_cfg, total_video_duration, final_audio_path):
    import edge_tts
    sorted_dialogues = sorted(dialogues, key=lambda d: float(d.get("start", 0)))
    concat_list_file = "concat_segments.txt"
    segment_files = []
    current_time = 0.0

    with st.spinner("🎙️ စကားပြောချိန်ပြတင်းပေါက်အလိုက် အသံဖိုင်များကို Timeline ၁:၁ ကွက်တိ စီစဉ်နေပါသည်..."):
        for idx, item in enumerate(sorted_dialogues):
            d_start = max(0.0, float(item.get("start", 0.0)))
            d_end = min(total_video_duration, float(item.get("end", d_start + 2.5)))
            d_text = clean_script_line(item.get("text", ""), voice_cfg.get("lang", "my"))

            if not d_text:
                continue

            # 1. Fill silence gap before dialogue
            gap = d_start - current_time
            if gap > 0.08:
                silence_gap = f"silence_gap_{idx}.mp3"
                cmd_sil = [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", f"{gap:.3f}",
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    silence_gap
                ]
                subprocess.run(cmd_sil, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                segment_files.append(silence_gap)
                current_time = d_start

            # 2. Render dialogue TTS
            allowed_duration = max(0.8, d_end - d_start)
            raw_seg = f"raw_seg_{idx}.mp3"
            conformed_seg = f"conf_seg_{idx}.mp3"

            comm = edge_tts.Communicate(
                text=d_text,
                voice=voice_cfg["voice"],
                rate=voice_cfg["rate"],
                pitch=voice_cfg["pitch"]
            )
            asyncio.run(comm.save(raw_seg))

            raw_dur = get_media_duration(raw_seg)
            if raw_dur > 0:
                tempo = raw_dur / allowed_duration
                # Micro-tempo adjustment for natural voice scaling
                if 0.85 <= tempo <= 1.40:
                    cmd_conf = [
                        "ffmpeg", "-y", "-i", raw_seg,
                        "-filter:a", f"atempo={tempo:.3f}",
                        "-t", f"{allowed_duration:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "192k",
                        conformed_seg
                    ]
                elif tempo < 0.85:
                    pad = allowed_duration - raw_dur
                    cmd_conf = [
                        "ffmpeg", "-y", "-i", raw_seg,
                        "-af", f"apad=pad_dur={pad:.3f}",
                        "-t", f"{allowed_duration:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "192k",
                        conformed_seg
                    ]
                else:
                    cmd_conf = [
                        "ffmpeg", "-y", "-i", raw_seg,
                        "-filter:a", "atempo=1.40",
                        "-t", f"{allowed_duration:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "192k",
                        conformed_seg
                    ]
                subprocess.run(cmd_conf, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                segment_files.append(conformed_seg)
            else:
                segment_files.append(raw_seg)

            current_time = d_start + allowed_duration

        # 3. Final silence tail
        if total_video_duration > current_time + 0.08:
            tail_gap = total_video_duration - current_time
            tail_file = "silence_tail.mp3"
            cmd_tail = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{tail_gap:.3f}",
                "-c:a", "libmp3lame", "-b:a", "192k",
                tail_file
            ]
            subprocess.run(cmd_tail, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            segment_files.append(tail_file)

    # 4. Concatenate all audio segments into single timeline master
    with open(concat_list_file, "w", encoding="utf-8") as cf:
        for sf in segment_files:
            cf.write(f"file '{sf}'\n")

    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_file,
        "-t", f"{total_video_duration:.3f}",
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
        en_sec = min(duration, float(d.get("end", st_sec + 2.5)))
        line = d.get("text", "").strip()
        if line:
            # CapCut Style pop-in subtitle effect
            pop_fx = "{\\t(0,120,\\fscx112\\fscy112)\\t(120,240,\\fscx100\\fscy100)}"
            ass_text += f"Dialogue: 0,{fmt_ass_time(st_sec)},{fmt_ass_time(en_sec)},SubtitleStyle,,0,0,0,,{pop_fx}{line}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

def render_dialogue_synced_video(input_video, narration_audio, ass_path, output_video, logo_path=None, logo_pos="top_right", reframe_mode="Smart Blur Background"):
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

    # Advanced Audio Ducking
    audio_filter = (
        "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[orig_sfx];"
        "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[ai_dub];"
        "[ai_dub]asplit[ai_final][ai_sc];"
        "[orig_sfx][ai_sc]sidechaincompress=threshold=0.06:ratio=4.0:attack=10:release=500[ducked_sfx];"
        "[ducked_sfx][ai_final]amix=inputs=2:duration=first:dropout_transition=0[afinal]"
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
            "ffmpeg", "-y",
            "-i", input_video,
            "-i", narration_audio,
            "-i", logo_path,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
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
            "ffmpeg", "-y",
            "-i", input_video,
            "-i", narration_audio,
            "-t", f"{exact_duration:.3f}",
            "-filter_complex", full_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def generate_viral_thumbnail(video_path, timestamp_sec, hook1, hook2, logo_path, output_thumb_path):
    temp_frame = "raw_frame.png"
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1",
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        temp_frame
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(temp_frame):
        return False

    try:
        base = Image.open(temp_frame).convert("RGBA")
        shade = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shade)
        s_draw.rectangle([0, 0, 720, 300], fill=(0, 0, 0, 180))
        s_draw.rectangle([0, 980, 720, 1280], fill=(0, 0, 0, 180))
        base = Image.alpha_composite(base, shade)
        draw = ImageDraw.Draw(base)

        font_path = "Pyidaungsu.ttf" if os.path.exists("Pyidaungsu.ttf") else None
        font = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default()

        if hook1:
            draw.text((360, 100), hook1, fill=(255, 235, 59, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))
        if hook2:
            draw.text((360, 180), hook2, fill=(0, 242, 254, 255), font=font, anchor="mm", stroke_width=5, stroke_fill=(0, 0, 0, 255))

        draw.polygon([(320, 580), (320, 700), (430, 640)], fill=(255, 255, 255, 220), outline=(0, 242, 254, 255), width=8)

        if logo_path and os.path.exists(logo_path):
            l_img = Image.open(logo_path).convert("RGBA").resize((110, 110))
            base.paste(l_img, (720 - 130, 30), l_img)

        base.convert("RGB").save(output_thumb_path, "JPEG", quality=95)
        return True
    except Exception:
        return False

with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 10px 0 16px 0;">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #00f2fe; margin-bottom: 4px; font-weight: 800;">⚡ RECAP STUDIO PRO</h2>
        <span class="badge-sync">DIALOGUE-LOCKED AI</span>
    </div>
    """, unsafe_allow_html=True)

    if not use_new_sdk:
         st.warning("Running in Fallback SDK Mode (google.generativeai). Native google-genai module not found.")

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
    st.markdown("#### 🌐 **Language & Narrator**")
    st.session_state.target_language = st.selectbox(
        "ဘာသာစကား ရွေးချယ်ပါ",
        ["🇲🇲 Burmese (မြန်မာစကားပြောသံ)", "🇬🇧 English (English Dubbing)"],
        index=0 if "Burmese" in st.session_state.target_language else 1
    )

    available_voices = VOICE_CATALOG[st.session_state.target_language]
    voice_sel = st.selectbox("🎙️ Narrator Voice (အသံရွေးချယ်ပါ)", list(available_voices.keys()), index=0)

    st.markdown("---")
    if st.button("🧹 Storage ရှင်းလင်းမည် (Safe Cleanup)", use_container_width=True):
        cleaned_cnt = cleanup_workspace()
        st.success(f"🧹 Temporary ဖိုင်ပေါင်း {cleaned_cnt} ခုအား ရှင်းလင်းပြီးပါပြီ!")

tab_dub, tab_thumb, tab_splitter, tab_settings = st.tabs([
    "🎬 Master Studio (1:1 Dubbing)",
    "🖼️ Viral Thumbnail & SEO",
    "🍿 1 GB Shorts Splitter",
    "⚙️ System Features"
])

with tab_dub:
    st.markdown("""
    <div class="neo-card" style="animation: neonPulse 4s infinite alternate;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <h2 class="hero-title" style="font-size: 24px;">🎬 Dialogue-Locked 1:1 Timeline Dubbing</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-top: 6px; margin-bottom: 0;">
                    ဗီဒီယိုထဲတွင် စကားပြောခန်းရှိမှသာ AI က လိုက်ပြောမည်ဖြစ်ပြီး၊ စကားမပြောချိန်တွင် Audio Ducking ဖြင့် မူရင်း SFX ကို ပြန်လည် မြှင့်တင်ပေးမည့် အဆင့်မြင့်စနစ်
                </p>
            </div>
            <div>
                <span class="badge-sync">LIP-SYNC TIMELINE LOCK</span>
                <span class="badge-purple">AUDIO DUCKING SFX</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_up1, col_up2 = st.columns([1.2, 1.0])

    with col_up1:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">1. 📤 ဗီဒီယို တင်ပါ</h4>""", unsafe_allow_html=True)
        up_file = st.file_uploader("ဗီဒီယိုဖိုင် တင်ပါ (MP4, MOV, WebM - Max 1GB)", type=["mp4", "mov", "webm"])
        
        # Only overwrite temp_input.mp4 if a NEW file is uploaded
        if up_file and up_file.file_id != st.session_state.last_uploaded_file_id:
            with open("temp_input.mp4", "wb") as f:
                f.write(up_file.getbuffer())
            st.session_state.last_uploaded_file_id = up_file.file_id

        yt_url = st.text_input("သို့မဟုတ် Video Link ထည့်ပါ", placeholder="https://www.youtube.com/watch?v=...")

        vid_len = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
        if vid_len > 0:
            st.success(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(vid_len)} ({vid_len:.2f} စက္ကန့်)** | AI မှ စကားပြောချိန်များကို တိတိကျကျ ဖမ်းယူပါမည်။")

        selected_mode_label = st.selectbox("🎯 Recap အမျိုးအစား (Context)", list(RECAP_MODES.keys()), index=0)
        mode_key = RECAP_MODES[selected_mode_label]

        st.session_state.video_reframe_style = st.selectbox(
            "📐 မျက်နှာပြင် အချိုးအစား (Smart Reframe)",
            ["Smart Blur Background (မူရင်းအပြည့် + ဘေးဘက်ဝါး)", "Center Crop (အလယ်ကိုသာ ဖြတ်ယူမည်)"],
            index=0
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_up2:
        st.markdown("""<div class="neo-card-accent"><h4 style="color: #c084fc; margin-top: 0;">2. 🏷️ Channel Logo</h4>""", unsafe_allow_html=True)
        logo_file = st.file_uploader("Logo ပုံတင်ပါ (Auto Remove BG ပြုလုပ်ပေးမည်)", type=["png", "jpg", "jpeg", "webp"])
        if logo_file:
            raw_logo = "raw_user_logo.png"
            clean_logo = "processed_user_logo.png"
            with open(raw_logo, "wb") as f:
                f.write(logo_file.getbuffer())
            if process_user_logo(raw_logo, clean_logo):
                st.session_state.user_watermark_file = clean_logo
                st.success("✅ Logo Background ဖျက်ပြီး နီယွန်ကွင်း ထည့်သွင်းပြီးပါပြီ!")
                st.image(clean_logo, width=70)

        logo_pos_choice = st.selectbox("📍 Logo နေရာ", ["top_right (ညာဘက် အပေါ်)", "top_left (ဘယ်ဘက် အပေါ်)", "bottom_right (ညာဘက် အောက်)"], index=0)
        logo_pos_key = logo_pos_choice.split(" ")[0]
        st.markdown("</div>", unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1.5, 1.0])
    with col_btn1:
        start_magic_btn = st.button("⚡ ONE-CLICK DIALOGUE-LOCKED DUB (စကားပြောချိန်အတိုင်း ကွက်တိထည့်မည်)", type="primary", use_container_width=True)
    with col_btn2:
        extract_only_btn = st.button("🔍 Timeline သာ အရင်စစ်ဆေးမည်", use_container_width=True)

    if start_magic_btn or extract_only_btn:
        cleanup_workspace() # Safe clean before run
        if not os.path.exists("temp_input.mp4") and not yt_url:
            st.error("ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ (သို့) Splitter မှ ပို့ပေးပါ ခင်ဗျာ။")
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
                with st.spinner(f"👁️ AI က ဗီဒီယိုကို နားထောင်ပြီး စကားပြောသည့် အချိန်များကို Timeline တွက်ချက်နေပါသည်..."):
                    res_data = extract_timeline_dialogues(
                        raw_api_keys=st.session_state.gemini_api_key,
                        video_path="temp_input.mp4",
                        target_language=lang_code,
                        mode_key=mode_key
                    )
                    st.session_state.dialogues_timeline = res_data.get("dialogues", [])
                    st.session_state.top_hook_text = res_data.get("hook_line1", "စိတ်လှုပ်ရှားဖွယ်ရာ")
                    st.session_state.bottom_hook_text = res_data.get("hook_line2", "ဇာတ်ကွက်")
                    st.session_state.seo_description = res_data.get("seo_description", "")
                    st.session_state.seo_hashtags = res_data.get("hashtags", "")

                st.success(f"🎯 စကားပြောခန်းပေါင်း {len(st.session_state.dialogues_timeline)} ခုကို အချိန်အတိအကျဖြင့် ရှာဖွေတွေ့ရှိပါပြီ!")

                if start_magic_btn:
                    voice_cfg = available_voices[voice_sel]
                    synced_audio = "final_dialogue_synced_voice.mp3"
                    
                    render_timeline_locked_narration(
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

                    with st.spinner("🎬 Audio Ducking ပြုလုပ်ကာ SFX နှင့် AI Dialogue အား အသံညှိပြီး Final Video ထုတ်လုပ်နေပါသည်..."):
                        final_out = "recap_output.mp4"
                        render_dialogue_synced_video(
                            input_video="temp_input.mp4",
                            narration_audio=synced_audio,
                            ass_path=ass_file,
                            output_video=final_out,
                            logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                            logo_pos=logo_pos_key,
                            reframe_mode=st.session_state.video_reframe_style
                        )
                        st.session_state.last_rendered_video = final_out
                        st.success("🎉 အောင်မြင်ပါပြီ! စကားပြောချိန်တွင်သာ လိုက်ပြောပြီး CapCut Effect ပါဝင်သော ဗီဒီယို ထွက်ရှိပါပြီ ခင်ဗျာ!")
            except Exception as ex:
                st.error(f"❌ {ex}")

    st.markdown("---")
    
    col_p_vid, col_p_ctrl = st.columns([1.2, 1.2])

    with col_p_ctrl:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">⏱️ Dialogue Timeline Editor</h4>""", unsafe_allow_html=True)
        if st.session_state.dialogues_timeline:
            st.caption("AI ရှာဖွေထားသော အချိန်နှင့် စာသားများကို လိုသလို ပြင်ဆင်နိုင်ပါသည်:")
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

        st.markdown("#### ⚙️ Typography & CapCut Subtitles")
        st.session_state.enable_subtitles = st.checkbox("📝 Pop-up စာတန်းထိုး ထည့်သွင်းမည်", value=st.session_state.enable_subtitles)
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.session_state.sub_color_hex = st.color_picker("🎨 စာတန်းထိုး အရောင်", st.session_state.sub_color_hex)
        with col_s2:
            st.session_state.sub_bg_style = st.selectbox("📦 နောက်ခံစတိုင်", ["Solid Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline Only (အနားကွပ် သီးသန့်)"], index=0)

        st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ %", 5, 80, int(st.session_state.sub_v_pos_percent))
        st.session_state.hook_top_percent = st.slider("↕️ Hook ခေါင်းစဉ် အမြင့်နေရာ %", 2, 25, int(st.session_state.hook_top_percent))
        st.session_state.sub_font_size = st.slider("🔤 စာလုံး အရွယ်အစား", 28, 56, int(st.session_state.sub_font_size))

        if st.button("🚀 ပြင်ဆင်ချက်များဖြင့် Final Video ပြန်ထုတ်မည်", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                with st.spinner("Timeline အသစ်ဖြင့် ဗီဒီယို ပြန်လည်ထုတ်ယူနေပါသည်..."):
                    v_dur = get_media_duration("temp_input.mp4")
                    voice_cfg = available_voices[voice_sel]
                    synced_audio = "final_dialogue_synced_voice.mp3"
                    render_timeline_locked_narration(
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
                        logo_pos=logo_pos_key,
                        reframe_mode=st.session_state.video_reframe_style
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
                    file_name="dialogue_synced_master.mp4",
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
        <h2 style="font-family: 'Orbitron', sans-serif; color: #ffffff; margin: 0; font-size: 20px;">🖼️ 1-Click Viral Thumbnail & SEO Engine</h2>
        <p style="color: #cbd5e1; font-size: 13px; margin-top: 4px; margin-bottom: 0;">
            ဗီဒီယိုကို Social Media ပေါ် တိုက်ရိုက်တင်ရန် လိုအပ်သော Cover ပုံနှင့် Caption/Hashtag များကို AI က အလိုအလျောက် ထုတ်ပေးသည့် စနစ်
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_th1, col_th2 = st.columns([1.2, 1.2])

    with col_th1:
        st.markdown("""<div class="neo-card"><h4 style="color: #c084fc; margin-top: 0;">📸 Cover Thumbnail Settings</h4>""", unsafe_allow_html=True)
        v_d_max = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 10.0
        thumb_sec = st.slider("📍 ဖမ်းယူမည့် ဗီဒီယို စက္ကန့်နေရာ (Snapshot Time)", 0.0, float(v_d_max), float(min(2.5, v_d_max)), 0.1)

        t_h1 = st.text_input("Cover Title Line 1 (အပေါ်စာသား)", value=st.session_state.top_hook_text)
        t_h2 = st.text_input("Cover Title Line 2 (အောက်စာသား)", value=st.session_state.bottom_hook_text)

        if st.button("✨ Thumbnail Cover ဖန်တီးမည်", type="primary", use_container_width=True):
            if not os.path.exists("temp_input.mp4"):
                st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
            else:
                out_thumb = "viral_thumbnail.jpg"
                if generate_viral_thumbnail(
                    video_path="temp_input.mp4",
                    timestamp_sec=thumb_sec,
                    hook1=t_h1,
                    hook2=t_h2,
                    logo_path=st.session_state.user_watermark_file,
                    output_thumb_path=out_thumb
                ):
                    st.session_state.latest_thumbnail = out_thumb
                    st.success("🎉 Cover ပုံ ဖန်တီးပြီးပါပြီ ခင်ဗျာ!")

        if "latest_thumbnail" in st.session_state and os.path.exists(st.session_state.latest_thumbnail):
            st.image(st.session_state.latest_thumbnail, caption="9:16 Viral Cover Art", use_container_width=True)
            with open(st.session_state.latest_thumbnail, "rb") as tf:
                st.download_button("📥 Download Thumbnail JPG", data=tf.read(), file_name="viral_thumbnail.jpg", mime="image/jpeg", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_th2:
        st.markdown("""<div class="neo-card"><h4 style="color: #00f2fe; margin-top: 0;">🚀 Viral Auto-SEO (Copy & Paste)</h4>""", unsafe_allow_html=True)
        st.caption("AI မှ ဗီဒီယိုကို ကြည့်ရှုပြီး TikTok / Facebook Reels တွင် တင်ရန် အဆင်သင့် ရေးသားပေးထားသော စာသားများ:")
        
        st.markdown("<span class='badge-green'>Caption / Description</span>", unsafe_allow_html=True)
        st.text_area("Description", value=st.session_state.seo_description, height=140, label_visibility="collapsed")
        
        st.markdown("<span class='badge-purple' style='margin-top: 15px;'>Trending Hashtags</span>", unsafe_allow_html=True)
        st.text_area("Hashtags", value=st.session_state.seo_hashtags, height=80, label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)

with tab_splitter:
    st.markdown("""
    <div class="neo-card-accent">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #ffffff; margin: 0; font-size: 20px;">🍿 Multi-Part Auto Splitter (1 GB Support)</h2>
        <p style="color: #cbd5e1; font-size: 13px; margin-top: 6px; margin-bottom: 0;">
            ဗီဒီယိုရှည်ကြီးများကို ၆၀ စက္ကန့် Shorts အပိုင်း ၁၊ ၂၊ ၃ အဖြစ် အလိုအလျောက် ခွဲထုတ်ပေးသည့် စနစ်
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
                    # explicitly check if part file exists to prevent FileNotFoundError
                    if os.path.exists(file_name):
                        st.video(file_name)
                        c_b1, c_b2 = st.columns(2)
                        with c_b1:
                            with open(file_name, "rb") as pf:
                                st.download_button(f"📥 Download Part {p_num}", data=pf.read(), file_name=file_name, mime="video/mp4", key=f"dl_p_{p_num}")
                        with c_b2:
                            if st.button(f"🚀 Master Studio သို့ ပို့မည် (Part {p_num})", key=f"send_recap_{p_num}"):
                                shutil.copyfile(file_name, "temp_input.mp4")
                                # clear upload state so the file uploader doesn't overwrite temp_input.mp4
                                st.session_state.last_uploaded_file_id = None
                                st.success(f"✅ Part {p_num} အား Master Studio သို့ ပို့ဆောင်ပြီးပါပြီ! ပထမ Tab (Master Studio) ကို နှိပ်ပြီး ဆက်လက်လုပ်ဆောင်နိုင်ပါပြီ။")
                    else:
                        st.error(f"⚠️ ဖိုင်ရှာမတွေ့ပါ! (Auto-Cleanup ကြောင့် ပျက်သွားပါသည်) ကျေးဇူးပြု၍ ပြန်လည်ခွဲထုတ်ပေးပါ။")
                    st.markdown("</div>", unsafe_allow_html=True)

with tab_settings:
    st.markdown("""
    <div class="neo-card">
        <h2 style="font-family: 'Orbitron', sans-serif; color: #00f2fe; margin-top: 0;">⚙️ System Architecture & Added Features</h2>
        <ul style="color: #cbd5e1; line-height: 1.8;">
            <li><span class="badge-sync">DIALOGUE LOCK</span> Detects exact speech windows. AI speaks strictly within these windows.</li>
            <li><span class="badge-purple">AUDIO DUCKING</span> Original SFX is kept at 100% and gracefully ducked to 20% ONLY when AI speaks using <i>FFmpeg sidechaincompress</i>.</li>
            <li><span class="badge-green">HYBRID SDK</span> Automatically detects and uses the correct Gemini SDK (`google-genai` or `google.generativeai`) to prevent crash errors.</li>
            <li><span class="badge-sync">CAPCUT POP SUBS</span> Modern fast-paced pop-up subtitle animations via ASS tags.</li>
            <li><span class="badge-purple">SAFE CLEANUP</span> Temporary workspace files are safely purged without deleting your main video files.</li>
            <li><span class="badge-green">SMART BLUR REFRAME</span> Retains full horizontal view by padding with a cinematic blur.</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    key_input = st.text_area("Gemini API Key List (ကော်မာခံ၍ အပိုထည့်သွင်းနိုင်သည်)", value=st.session_state.gemini_api_key, height=100)
    if st.button("💾 သိမ်းဆည်းမည်", type="primary"):
        save_config("gemini_api_key", key_input)
        st.session_state.gemini_api_key = key_input
        st.success("Config သိမ်းဆည်းပြီးပါပြီ ခင်ဗျာ!")
