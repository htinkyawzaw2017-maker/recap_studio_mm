# Recap Studio MM Pro 🎬

မြန်မာဘာသာ ဦးစားပေး **AI Movie/Video Recap + Zero-Drift Dubbing + Subtitle** စတူဒီယို။
FastAPI backend၊ ffmpeg render engine နှင့် hand-written SPA (CDN မလိုအပ်) ဖြင့် တည်ဆောက်ထားပါသည်။

---

## ⚡ အမြန်စတင်ရန်

### Docker (အကောင်းဆုံး)

```bash
cp .env.example .env         # GEMINI_API_KEY ထည့်ပါ
docker compose up --build    # http://localhost:8000
```

### Local (Python 3.10+)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install -y ffmpeg fonts-noto-core     # macOS: brew install ffmpeg
export GEMINI_API_KEY=AIza...
uvicorn app:app --host 0.0.0.0 --port 8000
```

စမ်းသပ်ရန် API key မလိုပါ — `RECAP_DEMO_MODE=1 RECAP_FAKE_TTS=1` ဖြင့် run ပါ (beep အသံဖြင့်
flow တစ်ခုလုံးကို စမ်းနိုင်သည်)။

---

## 🎯 အလုပ်လုပ်ပုံ (One-Click Flow)

```
ဗီဒီယို တင် (resumable chunked upload)
      ↓
1 fps proxy များအဖြစ် အပိုင်းခွဲ → Gemini ဖြင့် timeline ခွဲခြမ်းစိတ်ဖြာ (absolute timestamps)
      ↓
Coverage sweep — AI ကျန်ခဲ့သော အပိုင်းများကို ပြန်စစ်/ဖြည့်  → အစအဆုံး စကားပြောစာ ရရှိ
      ↓
edge-tts parallel အသံသွင်းခြင်း + time-fitting (rate boost → atempo → trim)
      ↓
Timeline အလိုက် အသံ ပေါင်းစပ် (drift-free) + loudnorm (I=-16 LUFS)
      ↓
ASS subtitle + hook + logo overlay + reframe → ffmpeg single-pass render → MP4 + SRT + MP3
```

### 🩺 v4.3.4 — "AI analysis failed" အမှား အမှန်ဖော်ပြခြင်း + input pre-flight

EC2 ပေါ်တွင် ဒေါင်းလုဒ်လုပ်ထားသော ဖိုင်တစ်ခုနှင့် recap လုပ်ကြည့်ရာ
`AI analysis failed for every chunk` ထွက်ပြီး website layout လည်း ကျယ်ထွက်သွားသည်။
အမှန်တကယ် ဖြစ်နေသည်က **AI မရောက်ဘဲ ffmpeg (proxy ဖြတ်ထုတ်သည့်အဆင့်) မှာ သေနေသည်**။
ပြင်ဆင်ချက် ၄ ချက် —

* **1. ffmpeg ကျရှုံးမှုကို သီးသန့် ခွဲပြ** — `FFmpegFailure` / `ProxyBuildError` ဟူသော
  type အသစ်များဖြင့် "🎬 ffmpeg က ဗီဒီယိုကို ဖြတ်ထုတ်၍ မရပါ — AI ဆီ မပို့ရသေးပါ" ဟု
  မြန်မာလို ရှင်းရှင်းလင်းလင်း ပြသည် ("AI analysis failed" ဟု မပြတော့ပါ)။
* **2. Upload ပြီးချင်း pre-flight** — `ffprobe` + **တကယ့် ၅-frame decode စမ်းသပ်မှု**
  (`recapstudio/media.py: preflight_video`). video track မပါခြင်း၊ ဖိုင်ပျက်ခြင်း၊
  AV1/VP9 decoder မရှိခြင်း၊ ကြာချိန်ဖတ်၍မရခြင်းကို **upload ချက်ချင်း** မြန်မာ error ဖြင့်
  ပြောပြီး job မစတင်စေတော့ပါ။ yt-dlp link import တွင်လည်း H.264 (avc1) ကို ဦးစားပေး
  ဒေါင်းစေပြီး import ပြီးချင်း စစ်သည်။
* **3. Layout မကျယ်ထွက်တော့ပါ** — `.log-box`/`.toast` တွင် `overflow-wrap:anywhere` +
  `html,body { overflow-x:hidden }` guard ထည့်ပြီး၊ error ကို **အတိုချုပ်** (toast
  အများဆုံး ၂၆၀ လုံး) သာ ပို့တော့သည် (၇,၅၀၀ လုံး မဟုတ်တော့ပါ)။
* **4. ffmpeg log အကြမ်း** — တိုတိုမြန်မာလို ပြီး အပြည့်အစုံကို **collapsible `<details>`**
  ထဲ (လိုအပ်မှ ဖွင့်ကြည့်) ထည့်ထားသည်။ Job panel တွင် "👉 ဘာလုပ်ရမလဲ" hint ပါ ပြသည်။

* Tests — `tests/test_input_diagnostics.py` (33 checks, offline) ·
  `tests/test_ffmpeg_diagnostics.py` (ffmpeg ရှိလျှင် run) · `tests/test_ui_preview.mjs` (40 checks)

### 🍌 v4.3.2 — AI Viral Thumbnail Studio (nano-banana) (Phase 3 · Batch C-1 · #10)

Thumbnail tab သည် ယခင်က **ဗီဒီယို ထပ်တင်ခိုင်း**ပြီး ဖရိမ်တစ်ခုပေါ် စာနှစ်ကြောင်း
တင်ရုံသာ ဖြစ်သည်။ ယခု —

* **ထပ်တင်စရာ မလိုတော့ပါ** — Studio မှာ **ပြီးသွားသော ဗီဒီယိုများ**၏ စာရင်းကို
  `/api/thumb-sources` မှ ဆွဲယူပြီး drop-down ထဲ အလိုအလျောက် ပြသည်။ recap တစ်ခု
  ပြီးတိုင်း ထိုစာရင်းထဲ ချက်ချင်း ရောက်သည် (hook စာသားများပါ ကူးယူပေးသည်)။
* **ဖရိမ် အကောင်းဆုံးကို AI ရွေးသည်** — ဗီဒီယိုတစ်ခုလုံးမှ နမူနာ ၁၀ ခု ဖမ်း၍
  အလင်းအမှောင် + အသေးစိတ် (edge energy) ဖြင့် အမှတ်ပေးကာ မှောင်သော/ဝါးသော
  ဖရိမ်များကို ကျော်သည်။
* **🍌 nano-banana (Gemini 2.5 Flash Image)** — အခမဲ့ image model ဖြင့် ဖရိမ်ကို
  cinematic poster အဖြစ် ပြန်ပုံဖော်သည် (key ring ကို သုံးသဖြင့် key လှည့်ခြင်း
  အလုပ်လုပ်သည်)။ **key မရှိ / quota ကုန် / server busy ဖြစ်လျှင် ဖရိမ်အတိုင်း
  ဆက်ထုတ်ပေးသည် — thumbnail ဘယ်တော့မှ မပျက်ပါ။**
* **မြန်မာစာ hook ကို Pillow ဖြင့် ကိုယ်တိုင် ရေးသည်** — image model များသည်
  မြန်မာ အက္ခရာများကို မှန်မှန် မရေးနိုင်သေးသဖြင့် စာကို Noto Sans Myanmar ဖြင့်
  ထပ်ရေးသည် (gradient shade + stroke ဖြင့် ဖတ်ရလွယ်အောင်)။
* **တစ်ချက်နှိပ် → ရွေးစရာ ၂–၄ မျိုး** — style ၄ မျိုး (Bold Yellow / Red Alert /
  Clean White / Neon Violet) × အချိုးအစား ၃ မျိုး
  (**16:9** YouTube · **9:16** Shorts/Reels · **1:1** Facebook/IG)။
* **Tests** — `tests/test_thumbs.py` (52 checks, offline — API key မလို)

### 🗣️ v4.3.1 — Link import, narration အရှည်အတို, Recap ⇄ Dubbing ခွဲခြားမှု (Phase 3 · Batch B-1)

* **#1 Link import** — `youtu.be` / `shorts` / `live` / `&list=` ပါသော link များကို သန့်စင်ပြီး
  yt-dlp ကို **နည်းလမ်း ၄ မျိုး** (default → android → ios+IPv4 → tv) ဖြင့် အဆင့်ဆင့် စမ်းသည်။
  မအောင်မြင်လျှင် မြန်မာလို အကြောင်းပြချက် + ပြင်နည်း (cookies / yt-dlp update / proxy) ပြသည်။
* **#2 narration မြန်လွန်းခြင်း** — မြန်မာ **10.5 စာလုံး/စက္ကန့်** budget ဖြင့် window ထက်
  ရှည်သော စာကြောင်းကို TTS မလုပ်မီ သဘာဝကျစွာ ချုံ့သည် (စာတန်းနှင့် အသံ တစ်ထပ်တည်း)။
* **#4 တို/ပြတ်သား/သဘာဝကျ** — prompt တွင် budget ကိန်းဂဏန်း အတိအကျ + filler စကား ပိတ်ပင်ချက်။
* **#6 Recap ⇄ Dubbing** — 🎭 dubbing mode တွင် တိတ်ဆိတ်ချိန်ကို **စကား လုံးဝ မဖြည့်တော့**၊
  speech boundary ±0.3s တိကျရန် တောင်းဆိုသည်။ 🎬 recap mode သာ အစအဆုံး narration ထည့်သည်။
* **Tests** — `tests/test_narration_fit.py` (39 checks, offline)

### 🎛️ v4.3 — WYSIWYG Live Preview + ဖုန်း/တက်ဘလက်/ကွန်ပျူတာ အားလုံး အဆင်ပြေ (Phase 3 · Batch A)

Live Preview သည် ယခင်က **9:16 box တစ်မျိုးတည်း** ဖြစ်နေသဖြင့် 16:9 / 1:1 /
မူရင်း အချိုးရွေးလျှင် ဗီဒီယိုက အပေါ်ပိုင်းသို့ တက်သွားပြီး စာတန်းနေရာလည်း
ထွက်လာသော ဖိုင်နှင့် မကိုက်ပါ။ ယခု preview သည် **ffmpeg ထုတ်မည့် ဖရိမ်အတိအကျ**
ဖြစ်သည် —

* **Frame-accurate box** — `aspect` ရွေးလိုက်သည်နှင့် box က `720×1280` /
  `1080×1080` / `1280×720` / မူရင်းအရွယ် သို့ ချက်ချင်း ပြောင်းသည်
  (chip တွင် ထွက်မည့် pixel အရွယ် ပြသည်)
* **စာတန်း/hook အတိအကျ** — စာလုံးအရွယ်ကို `box height ÷ output height` ဖြင့်
  တွက်သည် (ASS PlayRes နှင့် တူညီ)၊ အနားသတ် 5% / 4%၊ hook top 6% — ဆွဲချထားသည့်
  နေရာအတိုင်း render ထဲတွင် ထွက်သည်
* **Logo** — ffmpeg `overlay=(W-w)·p` နှင့် တစ်ထပ်တည်း ကျအောင် ပြင်ထားသည်
  (100% ဆိုလျှင် ဘေးနားကပ်၊ ယခင်က ဖရိမ်ပြင်ပ ထွက်သွားသည်)
* **Center Crop** preview သည် crop အတိုင်း ဖြည့်ပြသည် (ကျန် mode = letterbox)
* **အားလုံးသော device** — ဖုန်း (≤430 / ≤620)၊ တက်ဘလက် (≤1024)၊ laptop (≤1400)၊
  4K အထိ breakpoint ladder၊ touch target 44px၊ iOS zoom-on-focus ပိတ်၊
  landscape ဖုန်း၊ safe-area (notch)၊ reduced-motion
* **⚡ One-Click bar** — ဖုန်း/တက်ဘလက်တွင် ခလုတ်ကြီး အပေါ်ရောက်သွားလျှင်
  အောက်ခြေတွင် sticky bar အဖြစ် လိုက်ပါလာသည်
* **🍿 Splitter → 🎬 Studio** — ခွဲထုတ်ပြီးသော အပိုင်းတိုင်းတွင်
  **"🎬 Studio သို့ ပို့မည်"** ခလုတ် — နှိပ်လိုက်သည်နှင့် Studio သို့ ရောက်ပြီး
  One-Click နှိပ်ရုံဖြင့် recap ထုတ်နိုင်သည် (ပြန်တင်စရာ မလို)
* **Tests** — `tests/test_ui_preview.mjs` (31 checks, server မလိုပါ)

### 🔐 v4.2 — အကောင့်စနစ် + Database လုံခြုံရေး + User အများသုံး (Phase 2)

Site ကို link သိသူတိုင်း ဝင်နိုင်ခြင်း ပြီးဆုံးပါပြီ။ ယခု **username + password**
အကောင့်စနစ်၊ user တစ်ယောက်ချင်း သီးသန့် workspace၊ encrypt လုပ်ထားသော API key
သိမ်းဆည်းမှု တို့ ပါဝင်သည်။

* **အကောင့်** — PBKDF2-SHA256 (240k rounds) + salt၊ session cookie (HttpOnly/SameSite/Secure)၊
  CSRF token၊ ၈ ကြိမ် မှားလျှင် ၁၅ မိနစ် lock၊ IP rate limit
* **User ခွဲခြားမှု** — job တိုင်းတွင် ပိုင်ရှင်ရှိ (သူများ job → **404**)၊
  `workspace/users/<user>/` + `outputs/u_<user>/` သီးသန့်၊ per-user quota (job/disk)
* **Database** — JSON အစား SQLite `data/recap.db` (0600 permission, schema migration, WAL)၊
  audit log (login/create/delete/role အပြောင်းအလဲ)
* **API key** — server ring အပြင် **user တစ်ယောက်ချင်း key** ကို Fernet ဖြင့် encrypt သိမ်း
* **UI** — login/sign-up screen၊ 👤 account chip + logout၊
  Settings → **အကောင့်** (password ပြောင်း / device အားလုံး ထွက်) နှင့်
  **အကောင့် စီမံခန့်ခွဲမှု** (admin: user ဖန်တီး/ပိတ်/reset/ဖျက် + audit log)
* **CLI** — `python -m recapstudio.useradmin status|migrate|create|list|passwd|disable|promote|delete|sessions|audit`
* **Tests** — `tests/test_auth.py` (69 checks, offline)

👉 သင် ကိုယ်တိုင် လုပ်ရမည့် အဆင့်များ (secret key, admin အကောင့်, restart, စစ်ဆေးချက်) —
**[docs/PHASE2_AUTH.md](docs/PHASE2_AUTH.md)**

👉 v4.3 ကို **Windows CMD မှ AWS EC2 ပေါ် အစအဆုံး ပြန်တင်နည်း** —
**[docs/REDEPLOY_V43_CMD.md](docs/REDEPLOY_V43_CMD.md)**

### ⚡ v4.1.2 — hotfix: `'TimelineExtractor' object has no attribute 'sdk'`

v4.1.1 တွင် ထည့်လိုက်သော log line တစ်ကြောင်းက `self.sdk` (မှန်သည် `self.client.sdk`)
ဟု ဖတ်မိသဖြင့် **အလုပ် စတင်သည်နှင့် ချက်ချင်း ကျ**ခဲ့သည် (Gemini သို့ request မရောက်မီ၊
quota မကုန်)။ Demo mode က ထို line မရောက်သဖြင့် tests မမိခဲ့ပါ။ ယခု ပြင်ပြီး၊
ထပ်မဖြစ်စေရန် —

* `tests/test_real_run.py` — demo mode **ပိတ်ပြီး** `extract_timeline()` ကို
  offline stub client ဖြင့် အပြည့်အဝ run (7 checks)
* `tests/test_self_attrs.py` — code တစ်ခုလုံးရှි `self.<name>` အားလုံး ရှိ/မရှိ
  static စစ်ဆေးခြင်း (12 module)

### 🔧 v4.1.1 — "file uri and mime_type are required" ပြင်ဆင်ချက် (အရေးကြီး)

တကယ့် job များတွင် `AI request failed: file uri and mime_type are required.` ဖြင့်
အပိုင်းတိုင်း ကျရှုံးခဲ့သည် — AI ထံ ဗီဒီယို ပေးပို့သည့် အပိုင်းတွင်
`pathlib.Path` ကို တိုက်ရိုက် ပေးပို့နေခြင်းကြောင့် (google-genai 1.20+ တွင်
လုံးဝ လက်မခံ၊ 1.0.x တွင် ဗီဒီယို ပျောက်သွား)။ ယခု
`GeminiClient.build_media_part()` က 12 MB အောက် proxy များကို
`inline_data` (video/mp4) အဖြစ် တိုက်ရိုက်၊ ကြီးသော ဖိုင်များကို Files API
+ အတိအကျ mime type ဖြင့် ပေးပို့သည်။ Demo mode ဖြင့် စမ်းသပ်စဉ် AI ခေါ်ဆိုမှု
မရှိသဖြင့် ဤ အမှားကို ရှာမတွေ့နိုင်ခဲ့ပါ — `tests/test_ai_parts.py`
(21 checks) က လက်တွေ့ HTTP body ကို စစ်ဆေးပေးသည်။

ထို့အပြင် `run_ffmpeg()` သည် job cancel ကြောင့် ရပ်ခံရသော ffmpeg ကို `CancelledError` အဖြစ် တင်ပြသည် (ယခင် "FFmpeg error" အဖြစ် ပြပြီး စာတန်းမပါဘဲ ပြန်ရိုက်ရန် ကြိုးစားခဲ့သည်) — `tests/test_cancel.py`။

### 🆕 v4.1 — အသုံးပြုသူ တိုင်ကြားချက် ၇ ခုအတွက် ပြင်ဆင်ချက်များ

| # | တိုင်ကြားချက် | အကြောင်းရင်း | ဖြေရှင်းချက် |
|---|---|---|---|
| 1 | Refresh လုပ်လျှင် **"Engine စစ်ဆေးနေသည်…"** တွင် ရပ်နေ / စာမျက်နှာ ပျက် | `/api/system` က data directory ကို တစ်ခါတည်း walk လုပ်သဖြင့် ကြာနေသည် + JS တစ်နေရာ error တက်လျှင် တစ်ခုလုံး ရပ် | cached disk size + non-blocking `/api/system`၊ UI က built-in catalog ကို ချက်ချင်း ဆွဲပြ၊ timeout+retry၊ error banner (crash မဖြစ်တော့) |
| 2 | Refresh လုပ်တိုင်း **API key ပျောက်** | key ကို server memory/config တွင်သာ သိမ်းသည် | **Key #1–#3** ring + `localStorage` mirror + “ဒီ browser တွင် မှတ်ထားမည်” (refresh လုပ်လျှင် အလိုအလျောက် ပြန်ဖြည့်) |
| 3 | **API key switch** လိုသည် | key တစ်ခုတည်း | Key ၃ ခုအထိ၊ quota/429 ဖြစ်လျှင် **အလိုအလျောက် failover** + UI မှ active slot ရွေးနိုင် + Key test |
| 4 | အသံကို **အစအဆုံး မသွင်း** | AI coverage gaps + TTS လိုင်းကျော်လွန် + အလွန်ရှည်သော အပိုင်းများ | gap splitting + coverage sweep (အနှစ်ချုပ် ၂–၃ လှည့်)၊ လိုင်းကျော်လွန်လျှင် ပြန်စမ်း၊ အသံသွင်းပြီးနောက် **silence repair** (စမ်းသပ်မှုတွင် 46.2s → 3.2s အများဆုံး လစ်လပ်) |
| 5 | Job Progress က **video preview က အုပ်** | preview card သည် sticky ဖြစ်ပြီး viewport ထက် မြင့်သည် | sticky ကို neutralise၊ `#preview-card` ကို sticky မဖြစ်စေ၊ **Job Progress** ကိုသာ (အလုပ် run နေစဉ်) sticky ထားသည် |
| 6 | **Shorts Splitter** — ဖိုင်တင်မရ / အပိုင်းခွဲပြီးမှ ရပ် | တင်ခြင်းနှင့် ခွဲခြင်းကို request အတွင်းမှာပဲ လုပ်သည် (timeout → "ရပ်နေ") | upload UI အပြည့် + **background split job** (progress %၊ ရပ်နိုင်၊ ပြီးလျှင် part များ စာရင်း + Download all) |
| 7 | Progress **"ရပ်မရ"** | cancel flag ကို stage ပြီးမှသာ စစ်သည် | ffmpeg watchdog + `kill` (ownership အတိအကျ)၊ cancel ကို ၀.၂–၀.၅ စက္ကန့်အတွင်း ပြီး၊ process ကျန်မနေ |

တိုးတက်လာသည့် အပိုအချက်များ — ကြီးမားပြီး စာသားအပြည့်အစုံသော UI (upload dropzone ကြီး၊ အဆင့်လိုက်
လမ်းညွှန်၊ tab တိုင်းတွင် ရှင်းလင်းချက်)၊ resumable upload ကို refresh ပြီးလျှင် ဆက်တင်နိုင်၊
running job ကို refresh လုပ်လျှင် ပြန်ချိတ်နိုင်၊ server နှင့် ချိတ်မရလျှင် banner ပြ၍ ဆက်လက် အသုံးပြုနိုင်။

### v4.0 တွင် ပြင်ဆင်ခဲ့သော bug များ (မှတ်တမ်း)

| # | ပြဿနာ | အကြောင်းရင်း | ဖြေရှင်းချက် |
|---|---|---|---|
| 1 | **`pip install` / Docker build fail** | requirements.txt ထဲတွင် apt package နာမည်များ (`ffmpeg`, `fonts-*`) ပါနေသည် | pip-only requirements + packages.txt/Dockerfile ခွဲထားသည် |
| 2 | **ဗီဒီယို/Logo "နှစ်ခါတင်ရ" ဖြစ်နေသည်** | input.value ကို reset မလုပ်သဖြင့် ဖိုင်တူပြန်ရွေးလျှင် change event မဖြစ်ပေါ် | reset + resumable chunked upload (8 MB) + retry + progress |
| 3 | **အသံ အစအဆုံး မသွင်းပေးခြင်း** | လိုင်းတစ်ခု ကျော်လွန်လျှင် နောက်လိုင်းများကို 0.3s သာ ဖြတ်ထားခဲ့သည် | time-fitting mixer (မည့်လိုင်းမျှ မပျောက်) + coverage sweep |
| 4 | **AI က အလယ်တွင် ရပ်သွားခြင်း** | `max_output_tokens=8192` + chunk မခွဲဘဲ တစ်ခါတည်း ခွဲခြမ်းစိတ်ဖြာ | parallel chunk analysis (absolute offset) + 32k tokens + JSON salvage |
| 5 | **Render "ကြာနေ/ရပ်နေ" ဟု ထင်ရသည်** | progress မရှိ၊ TTS ကို တစ်လိုင်းချင်း sequential သွင်း | ffmpeg `-progress` live % + ETA + 8 parallel TTS + stream-copy fast path |
| 6 | **မြန်မာစာလုံး လေးထပ်ကွက် (tofu)** | repo ထဲက `Pyidaungsu.ttf` သည် 1 byte ပျက်နေသည် | Noto Sans Myanmar (OFL) ကို `assets/fonts` တွင် bundle လုပ်ထားသည် |
| 7 | **YouTube link import fail** | `url.split("?")[0]` က video id ကို ဖျက်ပစ်သည် | URL အပြည့်အစုံ + yt-dlp error အမှန်အတိုင်း ပြသည် |
| 8 | **Logo overlay render error** | filtergraph က `[2:v]` ကို ညွှန်းသော်လည်း logo input မထည့် | input index ကို မှန်ကန်စွာ ထည့်သွင်းသည် |
| 9 | **SRT/ASS/MP3 ဒေါင်းလုဒ် ပျောက်** | job store တွင် အဆိုပါ field များ မရှိ | `srt_url`, `ass_url`, `audio_url` ထည့်ထားသည် |
| 10 | Security / Ops | `allow_origins=["*"]` + credentials, path traversal, cancel/health/disk check မရှိ | CORS ပြင်၊ traversal guard၊ `/healthz`၊ cancel၊ disk check၊ janitor |

---

## 🖥️ UI/UX

* ၆ ခုသော tab — **Studio · Timeline Editor · Thumbnail · Shorts Splitter · Jobs · Settings**
* Drag & drop upload + **progress meter + cancel + auto-retry**
* **Live Preview** — subtitle နှင့် logo ကို ပုံပေါ်တွင် တိုက်ရိုက် ဆွဲ၍ နေရာချန်
* **Job Progress** — အဆင့် ၈ ဆင့်၏ အခြေအနေ၊ % ၊ ကျန်ချိန် ခန့်မှန်းချက်၊ live log
* **Coverage panel** — ဘယ်အပိုင်း အသံထွက်ပြီး/မပြီး ကြည့်နိုင်သည်
* **Timeline Editor** — လိုင်း ပြင်/ထည့်/ဖျက်၊ auto-fix overlaps၊ ပြန် render
* Myanmar font ကို server မှ တိုက်ရိုက် load (offline တွင်လည်း စာလုံး မှန်ကန်)
* Ctrl/⌘ + Enter = render စတင်
* **ကြီးမားသော၊ စာသားအပြည့်အစုံ UI** — အဆင့် ၄ ဆင့် လမ်းညွှန် strip၊ ကြီးမားသော upload dropzone၊
  field တိုင်းတွင် အမည်+ရှင်းလင်းချက် (v4.1)

---

## 🔌 API (အဓိကအချက်များ)

| Method | Path | ရည်ရွယ်ချက် |
|---|---|---|
| GET | `/healthz` | health check (ALB/ECS) |
| GET | `/api/system` | ffmpeg/font/disk/voices/models |
| POST | `/api/upload/init` → `/chunk` → `/complete` | resumable chunked upload |
| POST | `/api/upload` · `/api/upload-logo` | simple upload / logo badge |
| GET | `/api/asset?path=` | workspace ဖိုင် (Range support) |
| POST | `/api/download-url` | YouTube/TikTok import |
| POST | `/api/tasks` | recap job စတင် |
| GET | `/api/tasks/{id}` | status (progress/stage/logs/ETA/coverage) |
| POST | `/api/tasks/{id}/cancel` · `/rerender` · DELETE | ရပ် / ပြန် render / ဖျက် |
| GET | `/api/download/{file}` | MP4 · SRT · ASS · MP3 |
| POST | `/api/thumbnail` · `/api/split-video` · `/api/estimate-parts` | tools |
| GET | `/api/auth/me` | login အခြေအနေ + mode (v4.2) |
| POST | `/api/auth/login` · `/logout` · `/register` | အကောင့် ဝင်/ထွက်/ဖွင့် |
| POST | `/api/auth/password` · `/api/auth/sessions/revoke` | password ပြောင်း / device အားလုံး ထွက် |
| GET/POST/PATCH/DELETE | `/api/admin/users` | admin — user စီမံခန့်ခွဲမှု |
| GET | `/api/admin/audit` | admin — security log |

---

## ⚙️ Environment variables (အရေးကြီးသည်များ)

| Variable | Default | အဓိပ္ပာယ် |
|---|---|---|
| `GEMINI_API_KEY` | — | AI timeline extraction အတွက် |
| `RECAP_DATA_DIR` | app folder | workspace/output/tasks ထားမည့်နေရာ (AWS တွင် `/data`) |
| `RECAP_SECRET_KEY` | auto | **v4.2** session + API key encryption သော့ (`openssl rand -hex 32`) ⚠️ မပြောင်းပါနှင့် |
| `RECAP_AUTH_MODE` | `auto` | `auto` / `users` / `legacy` / `open` |
| `RECAP_ALLOW_SIGNUP` | `0` | user ကိုယ်တိုင် အကောင့်ဖွင့်ခွင့် (+ `RECAP_SIGNUP_CODE`) |
| `RECAP_USER_MAX_CONCURRENT_JOBS` | `1` | user တစ်ယောက် တစ်ပြိုင်နက် job |
| `RECAP_ACCESS_PASSWORD` | — | legacy shared secret (အကောင့်စနစ် သုံးလျှင် မလို) |
| `RECAP_MAX_CONCURRENT_JOBS` | 2 | တစ်ချိန်တည်း render အရေအတွက် |
| `RECAP_TTS_WORKERS` | 8 | parallel အသံသွင်း workers |
| `RECAP_MAX_CHUNK_SECONDS` | 480 | Gemini သို့ ပေးပို့မည့် အပိုင်းအရှည် |
| `RECAP_DEMO_MODE` / `RECAP_FAKE_TTS` | 0 | စမ်းသပ်ရန် (production တွင် မဖွင့်ပါနှင့်) |

အားလုံးစာရင်း → `.env.example`

---

## 🚀 Deployment

* **AWS EC2 (Instance Connect, port 80) — command တစ်ကြောင်းတည်း** — [docs/EC2_INSTANCE_CONNECT.md](docs/EC2_INSTANCE_CONNECT.md)
  ```bash
  cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm && tar xzf recap.tgz && sudo bash recap_studio_mm-*/deploy/ec2_install.sh
  ```
  install ပြီးလျှင် **admin အကောင့် ဖန်တီးရန် မမေ့ပါနှင့်** →
  [docs/PHASE2_AUTH.md](docs/PHASE2_AUTH.md) အဆင့် ၄
* **AWS (ECS Fargate + ALB + EFS)** — [docs/AWS_DEPLOY.md](docs/AWS_DEPLOY.md)
* **AWS ပေါ်ရှိ deployment ကို update လုပ်ရန်** — [docs/AWS_UPDATE.md](docs/AWS_UPDATE.md)
  (`python tests/verify_deployment.py https://your-domain.com` ဖြင့် စစ်နိုင်သည်)
* **Render** — [RENDER_DEPLOY.md](RENDER_DEPLOY.md) (`render.yaml` အဆင်သင့်)
* **Docker တစ်ခုတည်း** — `docker build -t recap . && docker run -p 8000:8000 -e GEMINI_API_KEY=... -v recap:/data recap`

---

## 🧪 Test

```bash
pip install -r requirements.txt
python tests/smoke_test.py            # offline: pipeline + HTTP layer (69 checks)
python tests/test_ai_parts.py        # AI ထံ ပေးပို့သော video part များ (21 checks, network မလိုပါ)
python tests/test_real_run.py         # demo မပါဘဲ AI analysis အပြည့် (7 checks, offline)
python tests/test_self_attrs.py       # self.<name> static စစ်ဆေးခြင်း (12 modules)
python tests/test_cancel.py          # ⏹ ရပ်တန့်ခြင်း = CancelledError (5 checks, ~3s)
python tests/test_key_ring.py         # API key ၃ ခု + quota failover (27 checks, network မလိုပါ)
python tests/test_auth.py             # အကောင့်/session/CSRF/quota/isolation (69 checks, offline)
python tests/test_audio_coverage.py   # narration အစအဆုံး ရောက်/မရောက် (16 checks, ffmpeg လိုသည်)
python tests/test_narration_fit.py    # narration budget · mode ခွဲခြားမှု · link import (39 checks)
python tests/test_thumbs.py           # nano-banana thumbnail studio · frame ရွေးချယ်မှု (52 checks)

# Front-end (jsdom)
npm install jsdom
node tests/test_ui_preview.mjs                                           # 31 checks (server မလိုပါ)
node tests/test_ui_auth.mjs http://127.0.0.1:8000 myname 'မိမိစကားဝှက်'   # 17 checks (server လိုသည်)

# Deploy လုပ်ပြီးသော server (AWS/Render) ကို စစ်ရန် — dependencies မလိုပါ
python tests/verify_deployment.py https://your-domain.com
python tests/verify_deployment.py https://your-domain.com --username admin --password 'XXXX'
python tests/verify_deployment.py https://your-domain.com --video ./clip.mp4
```

`RECAP_DEMO_MODE=1 RECAP_FAKE_TTS=1` ဖြင့် run သည် — ခွန်အား/API key မလိုဘဲ
timeline → အသံ → စာတန်းထိုး → render တစ်ခုလုံးကို အမှန် တည်ဆောက်စမ်းသပ်သည်။

---

## 📁 Project layout

```
app.py                  FastAPI routes + SPA serving
recapstudio/
  config.py             env-driven settings & paths
  media.py              ffmpeg/ffprobe + progress parsing
  ai.py                 chunked Gemini analysis + coverage sweep
  tts.py                edge-tts parallel synthesis + time fitting
  subtitles.py          ASS/SRT builder (libass-safe escaping)
  db.py                 SQLite schema + migrations (users/sessions/jobs/audit)
  crypto.py             secret key + Fernet/HMAC encryption
  auth.py               password policy, session, quota, audit
  webauth.py            FastAPI auth guards (cookie / Bearer / access key)
  useradmin.py          account CLI (status/create/list/passwd/…)
  render.py             single-pass master render (+ fast copy path)
  pipeline.py           orchestration / splitter / thumbnail
  jobs.py uploads.py fonts.py util.py
static/                 index.html · app.js · styles.css · fonts/
assets/fonts/           Noto Sans Myanmar (OFL) bundled
deploy/ec2_install.sh   Ubuntu/EC2 one-shot installer + updater (systemd)
docs/EC2_INSTANCE_CONNECT.md  EC2 (Instance Connect) အဆင့်ဆင့် လမ်းညွှန်
docs/AWS_DEPLOY.md      AWS guide
tests/test_cancel.py    cancel semantics (kill → CancelledError, not a crash)
tests/test_real_run.py  non-demo analysis run (offline stub client)
tests/test_self_attrs.py static: undefined self.<name> attributes
tests/test_ai_parts.py  AI content parts (file uri / mime type regression)
tests/smoke_test.py     offline end-to-end test
```

---

## 📄 License

MIT — see [LICENSE](LICENSE). Bundled Noto Sans Myanmar font is SIL OFL 1.1
(`assets/fonts/OFL.txt`).
