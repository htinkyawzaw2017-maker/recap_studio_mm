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
    page_title="Recap Studio MM Pro",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- MYANMAR UNICODE FONT CONFIG -----------------
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
        data = json.loads(res.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0

def format_time_str(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

# ----------------- PHONETIC & SSML HUMANIZER ENGINE -----------------
PHONETIC_REPLACEMENTS = {
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
    r"\bKiller\b": "လူသတ်သမား",
    r"\bZombie\b": "ဖုတ်ကောင်",
    r"\bGhost\b": "သရဲ",
    r"\bBoss\b": "သူဌေးကြီး",
    r"\bCar\b": "ကား",
    r"\bPhone\b": "ဖုန်း"
}

def clean_and_humanize_burmese_text(text):
    """Clean text and inject natural human prosody markings without breaking syntax."""
    if not text:
        return ""
    # Strip time markers and prefixes
    t = re.sub(r"[၀-၉0-9]+:[၀-၉0-9]+(\s*-\s*[၀-၉0-9]+:[၀-၉0-9]+)?", "", text)
    t = re.sub(r"(?m)^\s*[၀-၉0-9]+[\.\)။\-]\s*", "", t)
    t = re.sub(r"[\(\[（【].*?[\)\]）】]", "", t)
    t = re.sub(r"[*#_~>`]", "", t)
    t = re.sub(r"(?i)\b(scene|visual|audio|narrator|intro|outro|video)\s*\d*[:\-]*", "", t)

    # Phonetic replacements for English words
    for pattern, rep in PHONETIC_REPLACEMENTS.items():
        t = re.sub(pattern, rep, t, flags=re.IGNORECASE)

    # Normalize punctuation for SSML parsing
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t

def build_ssml_script(cleaned_text, voice_name, rate="+10%", pitch="-2Hz"):
    """
    Constructs professional SSML with natural breath pauses (အဖြတ်အတောက်)
    to eliminate robotic run-on speech.
    """
    # Replace commas with short pauses (160ms) and periods with cadence pauses (350ms)
    escaped_text = cleaned_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Inject SSML pauses at natural sentence boundaries
    ssml_body = escaped_text.replace("၊", '<break time="160ms"/>')
    ssml_body = ssml_body.replace("။", '<break time="340ms"/>')
    ssml_body = ssml_body.replace("...", '<break time="450ms"/>')

    ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="my-MM">
    <voice name="{voice_name}">
        <prosody rate="{rate}" pitch="{pitch}">
            {ssml_body}
        </prosody>
    </voice>
</speak>"""
    return ssml

# ----------------- USER LOGO BACKGROUND REMOVER -----------------
def process_user_logo(input_path, output_path, bg_mode="auto_white", make_circle=True):
    try:
        img = Image.open(input_path).convert("RGBA")
        data = list(img.getdata())
        new_data = []

        for item in data:
            r, g, b, a = item
            if bg_mode == "auto_white" and r > 210 and g > 210 and b > 210:
                new_data.append((255, 255, 255, 0))
            elif bg_mode == "auto_black" and r < 35 and g < 35 and b < 35:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)

        if make_circle:
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
                outline=(255, 215, 0, 230),
                width=b_width
            )
            img = badge

        img.save(output_path, "PNG")
        return True
    except Exception:
        return False

# ----------------- SESSION STATE -----------------
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = load_config("gemini_api_key", os.getenv("GEMINI_API_KEY", ""))

if "top_hook_text" not in st.session_state:
    st.session_state.top_hook_text = "တိရစ္ဆာန်တွေကို တရားစွဲ"

if "bottom_hook_text" not in st.session_state:
    st.session_state.bottom_hook_text = "ကြိုးပေးကွပ်မျက်ခဲ့"

if "recap_script_text" not in st.session_state:
    st.session_state.recap_script_text = "လူတွေတင် မကဘဲ တိရစ္ဆာန်တွေကိုပါ တရားရုံးတင်ပြီး ကြိုးပေးသတ်ခဲ့တဲ့ ထူးဆန်းတဲ့ သမိုင်းကြောင်း..."

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
    st.session_state.saved_bgm_vol = 0.10

VOICE_CONFIGS = {
    "မင်းသန့် (Agency - Confident Narrator - ထိပ်တန်းရွေးချယ်မှု)": {
        "voice": "my-MM-ThihaNeural", "pitch": "-2Hz", "rate": "+10%"
    },
    "ကိုမင်း (Deep Cinematic Movie Specialist - အသံနက်ကြီး)": {
        "voice": "my-MM-ThihaNeural", "pitch": "-6Hz", "rate": "+8%"
    },
    "သီဟ (Action & Dynamic Voice - အလွန်သွက်လက်)": {
        "voice": "my-MM-ThihaNeural", "pitch": "+1Hz", "rate": "+14%"
    },
    "မေသူ (Drama & Mystery Female - စိတ်ခံစားမှုအပြည့်)": {
        "voice": "my-MM-NilarNeural", "pitch": "+2Hz", "rate": "+6%"
    }
}

# ----------------- GEMINI SCRIPT GENERATOR (PRECISE PACING) -----------------
def generate_pacing_matched_script(api_key, model_name, video_path, target_duration):
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # 1 second of energetic recap = ~1.85 to 2.0 Burmese words (with punctuation pauses)
    target_words = max(35, int(target_duration * 1.9))

    prompt = f"""
သင်သည် အတွေ့အကြုံရင့်ကျက်သော Professional Movie Recapper တစ်ဦး ဖြစ်သည်။
မူရင်းဗီဒီယို၏ စကားပြော လေယူလေသိမ်း၊ အဖြတ်အတောက်နှင့် စိတ်လှုပ်ရှားဖွယ် ဇာတ်ကွက်များအတိုင်း မြန်မာလို အသက်ဝင်အောင် ပြန်လည်ပြောပြပေးရပါမည်။

အလွန်အရေးကြီးသော လိုက်နာရမည့် စည်းမျဉ်းများ:
1. ဗီဒီယို ကြာချိန်: အတိအကျ {round(target_duration)} စက္ကန့် ({round(target_duration/60, 1)} မိနစ်) ဖြစ်သည်။
2. အသံနှင့် အရုပ် ၁၀၀% ကိုက်ညီမှု: ဗီဒီယို စတင်သည့် စက္ကန့် ၀ မှ ပြီးဆုံးသည့်စက္ကန့်အထိ အတိအကျ ပြည့်မီစေရန်အတွက် စကားလုံးပေါင်း အနီးစပ်ဆုံး {target_words} လုံးခန့် ပါဝင်အောင် ရေးပေးပါ။ ဗီဒီယိုထက် အသံစောပြီးသွားခြင်း သို့မဟုတ် ဗီဒီယိုထက် ပိုရှည်နေခြင်း လုံးဝ မဖြစ်ရပါ။
3. လူအစစ် စကားပြောဟန် (Human Storyteller Cadence): စာအုပ်ဖတ်ပြသလို အသံပြားပြားကြီး မဖြစ်စေဘဲ ဇာတ်လမ်းပြောသူများ သုံးသော "ဒီအချိန်မှာပဲ..."၊ "ရုတ်တရက်ဆိုသလို..."၊ "တကယ်တော့..." စသည့် အချိတ်အဆက်များ ထည့်သွင်းပါ။
4. အဖြတ်အတောက် အသက်ရှူသံ: လိုအပ်သည့်နေရာများတွင် ပုဒ်ဖြတ် (၊) နှင့် ပုဒ်မ (။) များကို သေချာ ထည့်ပေးပါ။
5. အင်္ဂလိပ်စာလုံး လုံးဝ မပါရ။ (FBI အစား အက်ဖ်ဘီအိုင်၊ Doctor အစား ဒေါက်တာ စသည်ဖြင့် မြန်မာလိုသာ ရေးပါ)။
6. အောက်ပါ JSON Format သီးသန့်ဖြင့်သာ ပြန်ဖြေပါ:
{{
  "hook_line1": "ဆွဲဆောင်မှုရှိသော ခေါင်းစဉ် ၁ (စကားလုံး ၃-၄ လုံး)",
  "hook_line2": "ဆွဲဆောင်မှုရှိသော ခေါင်းစဉ် ၂ (စကားလုံး ၃-၄ လုံး)",
  "script": "မြန်မာစကားပြော Recap ဇာတ်ညွှန်း အပြည့်အစုံ..."
}}
"""
    video_upload = None
    if video_path and os.path.exists(video_path):
        try:
            video_upload = genai.upload_file(path=video_path)
            waits = 0
            while video_upload.state.name == "PROCESSING" and waits < 25:
                time.sleep(2)
                waits += 1
                video_upload = genai.get_file(video_upload.name)
            if video_upload.state.name != "ACTIVE":
                video_upload = None
        except Exception:
            video_upload = None

    model = genai.GenerativeModel(model_name)
    res = model.generate_content([video_upload, prompt] if video_upload else prompt)
    raw_resp = res.text.strip()

    try:
        clean_json_match = re.search(r"\{.*\}", raw_resp, re.DOTALL)
        if clean_json_match:
            data = json.loads(clean_json_match.group(0))
            return data["script"], data["hook_line1"], data["hook_line2"]
    except Exception:
        pass

    clean_lines = [l.strip() for l in raw_resp.split("\n") if l.strip() and not l.startswith("```") and not l.startswith("#")]
    h1 = clean_lines[0][:30] if len(clean_lines) > 0 else "ထူးဆန်းသော သမိုင်း"
    h2 = clean_lines[1][:30] if len(clean_lines) > 1 else "တရားရုံး၏ ဆုံးဖြတ်ချက်"
    script = " ".join(clean_lines[2:]) if len(clean_lines) > 2 else raw_resp
    return script, h1, h2

# ----------------- NATURAL VOICE GENERATION (EDGE-TTS + SSML) -----------------
async def run_edge_tts_ssml(ssml_content, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text=ssml_content, voice="my-MM-ThihaNeural")
    # Using Communicate with direct raw text/SSML
    await communicate.save(output_path)

def generate_human_voice(text, voice_cfg, output_path, target_duration):
    cleaned = clean_and_humanize_burmese_text(text)
    
    # Save SSML to temporary file
    temp_raw_audio = "temp_raw_ssml_audio.mp3"
    
    # Direct edge-tts command line call handles complex prosody perfectly
    import edge_tts
    communicate = edge_tts.Communicate(text=cleaned, voice=voice_cfg["voice"], rate=voice_cfg["rate"], pitch=voice_cfg["pitch"])
    asyncio.run(communicate.save(temp_raw_audio))

    raw_dur = get_media_duration(temp_raw_audio)
    
    # Precise duration matching (Within natural tolerance without robotic distortion)
    if target_duration > 5.0 and raw_dur > 1.0:
        ratio = raw_dur / target_duration
        if 0.90 <= ratio <= 1.18:
            # Subtle micro-tempo adjustment: Preserves natural pitch
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_raw_audio,
                "-filter:a", f"atempo={ratio:.3f}",
                output_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
        elif ratio < 0.90:
            # If audio is slightly shorter, add natural silence pad at the end
            pad_s = target_duration - raw_dur
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_raw_audio,
                "-af", f"apad=pad_dur={pad_s:.2f}",
                output_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return

    if os.path.exists(temp_raw_audio):
        import shutil
        shutil.copyfile(temp_raw_audio, output_path)

# ----------------- SUBTITLE BUILDER -----------------
def hex_to_ass(hex_code):
    h = hex_code.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H0000FFFF&"

def create_ass_subtitles(h1, h2, script, duration, ass_path, font_size, v_margin, hex_color, bg_style, cta_text):
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

    chunks = [s.strip() for s in re.split(r"[၊။\.\?\!\n]+", script) if s.strip()]
    if not chunks:
        chunks = [script]
    chunk_time = duration / len(chunks)

    for i, c in enumerate(chunks):
        st_t = i * chunk_time
        en_t = min((i + 1) * chunk_time, duration)
        ass_text += f"Dialogue: 0,{fmt_ass_time(st_t)},{fmt_ass_time(en_t)},SubtitleStyle,,0,0,0,,{c}\n"

    if cta_text and duration > 6.0:
        ass_text += f"Dialogue: 2,{fmt_ass_time(duration - 6.0)},{fmt_ass_time(duration)},CTAStyle,,0,0,0,,{cta_text}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

# ----------------- PRO VIDEO RENDER PIPELINE -----------------
def render_recap_video(input_video, narration_audio, ass_path, output_video, logo_path=None, logo_pos="top_right", bgm_vol=0.10):
    v_dur = get_media_duration(input_video)
    a_dur = get_media_duration(narration_audio)
    target_dur = max(v_dur, a_dur) if v_dur > 0 else 60.0

    # Generate dramatic background drone/score
    bgm_path = "temp_bgm.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"aevalsrc=sin(88*2*PI*t)*0.025+sin(128*2*PI*t)*0.015:d={target_dur+2}",
        "-c:a", "libmp3lame", bgm_path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 9:16 vertical crop + slight saturation boost
    vf_filters = [
        "scale=720:1280:force_original_aspect_ratio=increase",
        "crop=720:1280",
        "eq=contrast=1.03:brightness=0.01:saturation=1.05"
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
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[afinal]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", input_video,
            "-i", narration_audio,
            "-i", bgm_path,
            "-i", logo_path,
            "-t", str(target_dur),
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]
    else:
        filter_complex = (
            f"[0:v]{','.join(vf_filters)}[vfinal];"
            f"[1:a]volume=1.0[voice];[2:a]volume={bgm_vol:.2f}[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[afinal]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", input_video,
            "-i", narration_audio,
            "-i", bgm_path,
            "-t", str(target_dur),
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            output_video
        ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.markdown("### 🎬 **RECAP STUDIO MM**")
    st.caption("Human-Cadence Movie Recap Engine")
    st.markdown("---")

    if st.session_state.gemini_api_key:
        st.success("🔑 Gemini API: Active")
    else:
        st.warning("⚠️ API Key လိုအပ်ပါသည်")

    model_sel = st.selectbox("🤖 AI Model", ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"], index=0)
    voice_sel = st.selectbox("🎙️ Narrator Voice (ဇာတ်လမ်းပြောသံ)", list(VOICE_CONFIGS.keys()), index=0)
    bgm_val = st.slider("🎵 Background Music Volume", 0.0, 0.35, float(st.session_state.saved_bgm_vol), 0.02)
    st.session_state.saved_bgm_vol = bgm_val

# ----------------- MAIN UI -----------------
st.title("🎬 Professional Recap Video Creator")
st.markdown("အသံ၊ ဇာတ်ညွှန်းနှင့် အရုပ် ၁၀၀% ကိုက်ညီသော လူအစစ်ပြောပြသကဲ့သို့ သဘာဝကျသည့် Recap Studio ခင်ဗျာ။")

if not st.session_state.gemini_api_key:
    key_in = st.text_input("🔑 Google Gemini API Key ထည့်သွင်းပါ", type="password")
    if key_in:
        st.session_state.gemini_api_key = key_in
        save_config("gemini_api_key", key_in)
        st.rerun()

col_top_left, col_top_right = st.columns([1.2, 1.0])

with col_top_left:
    st.markdown("#### 1. 📤 ဗီဒီယို ဖိုင်တင်ပါ (သို့မဟုတ် YouTube Link)")
    up_file = st.file_uploader("ဗီဒီယို ရွေးချယ်ပါ (MP4, MOV)", type=["mp4", "mov", "webm"])
    yt_url = st.text_input("သို့မဟုတ် YouTube/TikTok Link", placeholder="[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=)...")

    if up_file:
        with open("temp_input.mp4", "wb") as f:
            f.write(up_file.getbuffer())

    vid_len = get_media_duration("temp_input.mp4") if os.path.exists("temp_input.mp4") else 0.0
    if vid_len > 0:
        st.info(f"⏱️ ဗီဒီယိုကြာချိန်: **{format_time_str(vid_len)} ({round(vid_len)} စက္ကန့်)** | အရုပ်မမြန် မနှေးဘဲ လူအစစ်ပြောပြသကဲ့သို့ အသံနှင့် ကွက်တိကိုက်ညီစေပါမည်။")

with col_top_right:
    st.markdown("#### 2. 🏷️ Channel Logo (Auto Background Remover)")
    logo_file = st.file_uploader("Logo ပုံတင်ပါ (PNG, JPG)", type=["png", "jpg", "jpeg", "webp"])
    if logo_file:
        raw_logo = "raw_user_logo.png"
        clean_logo = "processed_user_logo.png"
        with open(raw_logo, "wb") as f:
            f.write(logo_file.getbuffer())
        if process_user_logo(raw_logo, clean_logo, bg_mode="auto_white", make_circle=True):
            st.session_state.user_watermark_file = clean_logo
            st.success("✅ Logo Background ဖျက်ပြီး ရွှေရောင်အနားကွပ် ထည့်သွင်းပြီးပါပြီ!")
            st.image(clean_logo, width=80)

    logo_pos_choice = st.selectbox(
        "📍 Logo ထားမည့်နေရာ",
        ["top_right (အပေါ် ညာဘက်)", "top_left (အပေါ် ဘယ်ဘက်)", "bottom_right (အောက် ညာဘက်)", "bottom_left (အောက် ဘယ်ဘက်)"],
        index=0
    )
    logo_pos_key = logo_pos_choice.split(" ")[0]

st.markdown("---")

# ----------------- ONE-CLICK EXECUTION BUTTON -----------------
col_act1, col_act2 = st.columns([1.5, 1.0])
with col_act1:
    one_click_btn = st.button("⚡ ONE-CLICK MAGIC RECAP (ဇာတ်ညွှန်း၊ အသံနှင့် ဗီဒီယို တစ်ခါတည်း အပြီးထုတ်မည်)", type="primary", use_container_width=True)
with col_act2:
    script_only_btn = st.button("📝 Script သာ အရင်ထုတ်ယူမည်", use_container_width=True)

if one_click_btn or script_only_btn:
    if not os.path.exists("temp_input.mp4") and not yt_url:
        st.error("ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ သို့မဟုတ် Link ထည့်ပေးပါ ခင်ဗျာ။")
    elif not st.session_state.gemini_api_key:
        st.error("Gemini API Key ထည့်သွင်းပေးပါ ခင်ဗျာ။")
    else:
        if yt_url and not up_file:
            with st.spinner("ဗီဒီယို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."):
                subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "temp_input.mp4", yt_url.split("?")[0]], capture_output=True)

        v_duration = get_media_duration("temp_input.mp4")
        if v_duration <= 0.0:
            v_duration = 60.0

        with st.spinner(f"⏱️ {round(v_duration)} စက္ကန့်နှင့် အတိအကျ ကိုက်ညီသော လူအစစ်ပြောဟန် ဇာတ်ညွှန်းနှင့် Hook ခေါင်းစဉ် ရေးသားနေပါသည်..."):
            s_text, h1, h2 = generate_pacing_matched_script(
                api_key=st.session_state.gemini_api_key,
                model_name=model_sel,
                video_path="temp_input.mp4" if os.path.exists("temp_input.mp4") else None,
                target_duration=v_duration
            )
            st.session_state.recap_script_text = s_text
            st.session_state.top_hook_text = h1
            st.session_state.bottom_hook_text = h2

        if one_click_btn:
            with st.spinner("🎙️ အဖြတ်အတောက် လေယူလေသိမ်းမှန်ကန်သော အသံဖတ်ကြားခြင်းနှင့် စက္ကန့်မလွဲ Sync ပြုလုပ်နေပါသည်..."):
                voice_cfg = VOICE_CONFIGS[voice_sel]
                synced_audio = "final_synced_voice.mp3"
                generate_human_voice(s_text, voice_cfg, synced_audio, target_duration=v_duration)

            ass_file = "final_subtitles.ass"
            if st.session_state.enable_subtitles:
                with st.spinner("📝 Myanmar Unicode စာတန်းထိုးများကို အချိန်ကိုက် တည်ဆောက်နေပါသည်..."):
                    calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                    create_ass_subtitles(
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

            with st.spinner("🎬 Final MP4 ဗီဒီယိုအား အရုပ်နှင့်အသံ ၁၀၀% ကွက်တိကျအောင် Render ပြုလုပ်နေပါသည်..."):
                final_out = "recap_output.mp4"
                render_recap_video(
                    input_video="temp_input.mp4",
                    narration_audio=synced_audio,
                    ass_path=ass_file,
                    output_video=final_out,
                    logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                    logo_pos=logo_pos_key,
                    bgm_vol=st.session_state.saved_bgm_vol
                )
                st.session_state.last_rendered_video = final_out
                st.success("🎉 Final Video အောင်မြင်စွာ ထွက်ရှိပါပြီ ခင်ဗျာ!")

st.markdown("---")

# ----------------- DIRECT VIDEO & SUBTITLE ADJUSTER -----------------
st.markdown("### 🎬 **Video Preview & Subtitle Live Adjuster**")
st.caption("အသံသွင်းထားသော ဗီဒီယိုပေါ်တွင် Subtitle အရောင်၊ အမြင့်နှင့် စတိုင်များကို တိုက်ရိုက် ပြင်ဆင်နိုင်ပါသည် ခင်ဗျာ။")

col_prev_v, col_prev_c = st.columns([1.2, 1.2])

with col_prev_c:
    st.markdown("#### ⚙️ **Subtitle & Typography Controls**")
    st.session_state.enable_subtitles = st.checkbox("📝 စာတန်းထိုး (Subtitles) ထည့်သွင်းမည်", value=st.session_state.enable_subtitles)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.session_state.sub_color_hex = st.color_picker("🎨 စာတန်းထိုး အရောင်", st.session_state.sub_color_hex)
    with col_c2:
        st.session_state.sub_bg_style = st.selectbox("📦 နောက်ခံစတိုင်", ["Solid Box (အမည်းနောက်ခံ)", "Semi-Transparent (မှန်ကြည်)", "Outline Only (အနားကွပ် သီးသန့်)"], index=0)

    st.session_state.sub_v_pos_percent = st.slider("↕️ စာတန်းထိုး အမြင့်နေရာ (Subtitle Height %)", 5, 80, int(st.session_state.sub_v_pos_percent))
    st.session_state.hook_top_percent = st.slider("↕️ Hook ခေါင်းစဉ် အမြင့်နေရာ (Top %)", 2, 25, int(st.session_state.hook_top_percent))
    st.session_state.sub_font_size = st.slider("🔤 စာလုံး အရွယ်အစား (Font Size)", 28, 56, int(st.session_state.sub_font_size))

    st.session_state.cta_type = st.selectbox(
        "🔘 Call-to-Action ခလုတ် စာသား",
        [
            "👍 Like & 🔔 Subscribe လုပ်ထားပါ ခင်ဗျာ",
            "🔔 Subscribe လုပ်ထားပေးပါ ခင်ဗျာ",
            "👍 Like ပေးခဲ့ပါဦး ခင်ဗျာ",
            "စာရင်းသွင်းပါ (Formal Burmese)"
        ],
        index=0
    )

    st.markdown("##### 📝 Hook ခေါင်းစဉ် တိုက်ရိုက်ပြင်ရန်:")
    ch1, ch2 = st.columns(2)
    with ch1:
        st.session_state.top_hook_text = st.text_input("Line 1 Hook", value=st.session_state.top_hook_text)
    with ch2:
        st.session_state.bottom_hook_text = st.text_input("Line 2 Hook", value=st.session_state.bottom_hook_text)

    st.markdown("##### 📄 ဇာတ်ညွှန်း စာသား (Script Editor):")
    st.session_state.recap_script_text = st.text_area("Script", value=st.session_state.recap_script_text, height=90, label_visibility="collapsed")

    if st.button("🚀 သတ်မှတ်ချက်အသစ်ဖြင့် Final Video ပြန်ထုတ်မည် (Re-Export MP4)", type="primary", use_container_width=True):
        if not os.path.exists("temp_input.mp4"):
            st.error("ဗီဒီယိုဖိုင် မရှိသေးပါ ခင်ဗျာ။")
        else:
            with st.spinner("သတ်မှတ်ထားသော စတိုင်အတိုင်း Final Video ထုတ်ယူနေပါသည်..."):
                t_dur = get_media_duration("temp_input.mp4")
                ass_f = "final_subtitles.ass"
                if st.session_state.enable_subtitles:
                    calc_vm = int(1280 * (st.session_state.sub_v_pos_percent / 100.0))
                    create_ass_subtitles(
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

                audio_to_use = "final_synced_voice.mp3" if os.path.exists("final_synced_voice.mp3") else "temp_raw_ssml_audio.mp3"
                final_out = "recap_output.mp4"
                render_recap_video(
                    input_video="temp_input.mp4",
                    narration_audio=audio_to_use,
                    ass_path=ass_f,
                    output_video=final_out,
                    logo_path=st.session_state.user_watermark_file if os.path.exists(st.session_state.user_watermark_file) else None,
                    logo_pos=logo_pos_key,
                    bgm_vol=st.session_state.saved_bgm_vol
                )
                st.session_state.last_rendered_video = final_out
                st.success("✨ အောင်မြင်စွာ ပြန်လည် Render ပြီးပါပြီ ခင်ဗျာ!")
                st.rerun()

with col_prev_v:
    st.markdown("#### 📱 **Live Video Player & Frame Placement**")

    if st.session_state.last_rendered_video and os.path.exists(st.session_state.last_rendered_video):
        st.video(st.session_state.last_rendered_video)
    elif os.path.exists("temp_input.mp4"):
        st.video("temp_input.mp4")
    else:
        st.info("ဗီဒီယို ဖိုင်တင်ပြီးသည်နှင့် ဤနေရာတွင် တိုက်ရိုက် ကြည့်ရှုနိုင်မည် ဖြစ်ပါသည် ခင်ဗျာ။")

    # Clean HTML Mockup Frame with ZERO Indentation (NO MORE CODE GLITCH!)
    box_css = "background: rgba(0,0,0,0.85); border-radius: 6px; padding: 4px 10px;" if "Solid" in st.session_state.sub_bg_style else ("background: rgba(0,0,0,0.45); backdrop-filter: blur(4px); border-radius: 6px; padding: 4px 10px;" if "Semi" in st.session_state.sub_bg_style else "background: transparent; text-shadow: -2px -2px 0 #000, 2px -2px 0 #000, 0 3px 6px #000;")
    sub_preview_sample = clean_and_humanize_burmese_text(st.session_state.recap_script_text)[:60] + "..." if st.session_state.recap_script_text else "မြန်မာယူနီကုဒ် စာတန်းထိုး နမူနာ..."

    phone_mockup_html = textwrap.dedent(f"""
<div style="width: 100%; max-width: 310px; height: 490px; margin: 10px auto; background: radial-gradient(circle, #0e1e2d, #04090e); border: 2.5px solid #0284c7; border-radius: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.7);">
<div style="position: absolute; top: {st.session_state.hook_top_percent}%; left: 0; width: 100%; text-align: center; padding: 0 10px;">
<span style="display: inline-block; background: rgba(0,0,0,0.9); border: 1.5px solid #FFD700; color: #FFDF00; font-size: 12px; font-weight: 800; padding: 3px 8px; border-radius: 5px;">
{st.session_state.top_hook_text}<br>{st.session_state.bottom_hook_text}
</span>
</div>
<div style="position: absolute; top: 48%; left: 8%; width: 84%; text-align: center;">
<div style="background: #e11d48; color: white; padding: 5px 10px; border-radius: 16px; font-size: 11px; font-weight: bold; box-shadow: 0 3px 10px rgba(225,29,72,0.4);">
{st.session_state.cta_type}
</div>
</div>
<div style="position: absolute; bottom: {st.session_state.sub_v_pos_percent}%; left: 8%; width: 84%; text-align: center;">
<div style="border: 1.5px dashed #38bdf8; {box_css}">
<span style="color: {st.session_state.sub_color_hex}; font-size: {int(st.session_state.sub_font_size * 0.32)}px; font-weight: bold; line-height: 1.2;">
{sub_preview_sample}
</span>
</div>
</div>
</div>
""")
    st.markdown(phone_mockup_html, unsafe_allow_html=True)

# ----------------- FINAL DOWNLOAD BUTTON -----------------
if st.session_state.last_rendered_video and os.path.exists(st.session_state.last_rendered_video):
    st.markdown("---")
    with open(st.session_state.last_rendered_video, "rb") as vf:
        st.download_button(
            label="📥 Final Recap MP4 ဗီဒီယို ဒေါင်းလုဒ်ရယူရန်",
            data=vf.read(),
            file_name="recap_studio_master.mp4",
            mime="video/mp4",
            type="primary",
            use_container_width=True
        )
