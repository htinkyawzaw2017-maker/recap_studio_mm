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

---

## ⚙️ Environment variables (အရေးကြီးသည်များ)

| Variable | Default | အဓိပ္ပာယ် |
|---|---|---|
| `GEMINI_API_KEY` | — | AI timeline extraction အတွက် |
| `RECAP_DATA_DIR` | app folder | workspace/output/tasks ထားမည့်နေရာ (AWS တွင် `/data`) |
| `RECAP_ACCESS_PASSWORD` | — | public deployment အတွက် shared secret |
| `RECAP_MAX_CONCURRENT_JOBS` | 2 | တစ်ချိန်တည်း render အရေအတွက် |
| `RECAP_TTS_WORKERS` | 8 | parallel အသံသွင်း workers |
| `RECAP_MAX_CHUNK_SECONDS` | 480 | Gemini သို့ ပေးပို့မည့် အပိုင်းအရှည် |
| `RECAP_DEMO_MODE` / `RECAP_FAKE_TTS` | 0 | စမ်းသပ်ရန် (production တွင် မဖွင့်ပါနှင့်) |

အားလုံးစာရင်း → `.env.example`

---

## 🚀 Deployment

* **AWS EC2 (Instance Connect, port 80) — command တစ်ကြောင်းတည်း** — [docs/EC2_INSTANCE_CONNECT.md](docs/EC2_INSTANCE_CONNECT.md)
  ```bash
  cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a1027a-recap-studio-mm && tar xzf recap.tgz && sudo bash recap_studio_mm-*/deploy/ec2_install.sh
  ```
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

# Deploy လုပ်ပြီးသော server (AWS/Render) ကို စစ်ရန် — dependencies မလိုပါ
python tests/verify_deployment.py https://your-domain.com
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
