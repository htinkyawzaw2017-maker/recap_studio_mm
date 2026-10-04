# NEXT SESSION — အခြေအနေ အပြည့်အစုံ (v4.3.4 ပြီးနောက်)

> ရေးသည့်ရက် — 2026-10-04 · branch — `arena/01a10790-recap-studio-mm` · version — **4.3.4**
> ဤစာရွက်သည် session တစ်ခု ပြီးတိုင်း (နောက် session အတွက်) ဖတ်ရန် ဖြစ်သည်။

---

## 1. ⚠️ အရေးကြီး — v4.3.3 (OAuth) ဤ repo တွင် **မရှိပါ** (စစ်ပြီး)

| စစ်ဆေးချက် | ရလဒ် |
|---|---|
| `git log --oneline -3` | `3429e07 feat(thumbs): v4.3.2 — nano-banana AI viral thumbnail studio (#10)` **တစ်ကြောင်းသာ** |
| commit `7c3b8fb` | **မရှိပါ** (`git cat-file -t 7c3b8fb` → Not a valid object name) |
| remote branch အားလုံး + `refs/pull/*` | v4.3.3/OAuth commit **မရှိပါ** (အသစ်ဆုံး = `3429e07` v4.3.2) |
| `git rev-list --count origin/arena/01a105ed-recap-studio-mm..HEAD` | `0` → ဤ branch တွင် push စရာ **မရှိ** |
| `docs/NEXT_SESSION.md` | **မရှိခဲ့ပါ** (ဤ session မှာ အသစ် ဖန်တီးလိုက်သည်) |

**အနက်အဓိပ္ပာယ်** — v4.3.3 OAuth အလုပ်သည် သင့်ကွန်ပျူတာ (local) တွင်သာ ရှိပြီး
GitHub သို့ **တင်လိုက်ခြင်း မရှိသေးပါ**။ သင့် local မှ push လုပ်လိုလျှင် —

```cmd
cd C:\path\to\recap_studio_mm
git log --oneline -3                      :: 7c3b8fb ကို မြင်ရမည်
git show --stat 7c3b8fb | more            :: ဘယ်ဖိုင် ပြင်ထားလဲ စစ်
git branch --contains 7c3b8fb             :: ဘယ် branch ပေါ် ရှိလဲ စစ်
git push origin <ထို-branch>               :: push (ဥပမာ → arena/01a105ed-recap-studio-mm)
gh pr create --base arena/01a105ed-recap-studio-mm --head <ထို-branch> --fill
```

> ဤ session သည် `arena/01a10790-recap-studio-mm` တွင် သာ အလုပ်လုပ်နိုင်သည် (အခြား branch သို့
> ပြောင်း၍ မရပါ)။ v4.3.3 ကို အလိုရှိလျှင် ထို commit ကို ဒီ branch ပေါ် **merge/cherry-pick**
> လုပ်နိုင်သည် (ဤ branch က 4.3.4 ဖြစ်သဖြင့် version မထပ်တိုက်တော့ပါ)။

---

## 1b. ⚠️ v4.3.5 (`6a6d49d`) — ဤ repo/sandbox တွင် **မရှိပါ** (2026-10-04 စစ်ပြီး)

> v4.3.3 နှင့် အတူတူပင် — v4.3.5 သည် သင့် local machine တွင်သာ ရှိပြီး GitHub သို့ မရောက်သေးဟု ယူဆရသည်။

| စစ်ဆေးချက် | ရလဒ် |
|---|---|
| `/home/user/downloads/` | **မရှိပါ** (`No such file or directory`) |
| `/home/user/recap_studio_mm/release/` | **မရှိပါ** (`No such file or directory`) |
| `recap-studio-mm-v4.3.5.bundle` (filesystem တစ်ခုလုံး `find`) | **မတွေ့ပါ** — `.bundle` ဖိုင် တစ်ဖိုင်မှ မရှိ |
| `git cat-file -t 6a6d49d` | `fatal: Not a valid object name 6a6d49d` |
| git object အားလုံး (၉၇ ခု) တွင် `6a6d49d` / `4.3.5` ရှာခြင်း | **0 hit** (repo အတွင်း အမြင့်ဆုံး version = **v4.3.4**) |
| `git fsck --full --lost-found --dangling` | dangling/lost object **မရှိပါ** |
| `gh api .../commits/6a6d49d` | `422 — No commit found for SHA: 6a6d49d` |
| GitHub branches | `main`, `arena/01a10175`, `arena/01a105ed`, `arena/01a10790` — **`v4.3.5` မရှိပါ** |
| GitHub tags / releases | **ဗလာ** (tag တစ်ခုမှ မရှိပါ) |

**အနက်အဓိပ္ပာယ်** — push လုပ်စရာ commit/bundle မရှိသဖြင့် `v4.3.5` branch ကို ဖန်တီး၍ မရပါ။
ထို့အပြင် ဤ sandbox session သည် `arena/01a1081f-recap-studio-mm` branch တစ်ခုတည်းတွင်သာ
push လုပ်နိုင်သည် (အခြား branch အသစ် `v4.3.5` ကို ဤနေရာမှ push၍ မရပါ)။

**သင့် local မှ push လုပ်နည်း (Windows)** —

```cmd
cd C:\path\to\recap_studio_mm
git log --oneline -5                      :: 6a6d49d ကို မြင်ရမည်
git show --stat 6a6d49d | more            :: ဘယ်ဖိုင် ပြင်ထားလဲ စစ်
git branch --contains 6a6d49d             :: ဘယ် branch ပေါ် ရှိလဲ စစ်
git branch v4.3.5 6a6d49d                 :: v4.3.5 branch အသစ် ဖန်တီး
git push -u origin v4.3.5                 :: GitHub သို့ push
gh pr create --base main --head v4.3.5 --fill
```

သို့မဟုတ် bundle ဖြင့် ဤ sandbox ဆီ ပို့လိုလျှင် —

```cmd
git bundle create recap-studio-mm-v4.3.5.bundle main..6a6d49d
```
ထိုဖိုင်ကို ဤ chat သို့ upload လုပ်ပါ → ဤနေရာမှ `arena/01a1081f-recap-studio-mm` ပေါ်သို့
fetch/merge လုပ်ပြီး PR တင်ပေးနိုင်သည်။

---

## 2. ဤ session တွင် ပြီးစီးသွားသည် — v4.3.4 (bug ၄ ချက်)

### Bug 1 — "AI analysis failed" သည် အမှား ဖော်ပြချက် ဖြစ်နေသည်
* **အရင်း** — `ai.py:906` က `AI analysis failed for every chunk` ဟု ပြသော်လည်း
  အမှန်မှာ `build_proxy()` (ffmpeg) အဆင့်တွင် သေသည် → **AI ဆီ လုံးဝ မရောက်ခဲ့ပါ**။
* **ပြင်** — `recapstudio/media.py`: `FFmpegFailure(RuntimeError)` ·
  `recapstudio/ai.py`: `ProxyBuildError` + `aggregate_chunk_failure()`
  → ယခု ပြသည်မှာ **"🎬 ffmpeg က ဗီဒီယိုကို ဖြတ်ထုတ်၍ မရပါ — AI ဆီ မပို့ရသေးပါ (chunk 3/3 လုံး မှာ ကျရှုံး)"**
  ဖြစ်ပြီး အောက်တွင် **အကြောင်းရင်း (မြန်မာ)** + **👉 ဘာလုပ်ရမလဲ** ပါလာသည်။
  AI/API key ကြောင့် တကယ်ကျလျှင် ယခင်အတိုင်း AI error ဟု ပြသည် (မှန်ကန်စွာ ခွဲထားသည်)။

### Bug 2 — Upload ပြီးချင်း ကြိုစစ်ခြင်း မရှိ
* **ပြင်** — `media.py: preflight_video()` = ffprobe + **တကယ့် ၅-frame decode စမ်းသပ်မှု**
  (`ffmpeg -i FILE -map 0:v:0 -frames:v 5 -f null -`)
* ခေါ်သည့်နေရာများ — `uploads.py::_describe` (upload complete ချက်ချင်း) ·
  `pipeline.py::run_recap` (job စချိန်) · `pipeline.py::run_split` · `app.py::import_from_url`
* စစ်သည်များ — video track မပါ · ကြာချိန် 0 · ဖိုင်ပျက် (moov atom) · **AV1/VP9 decoder မရှိ** ·
  ဖိုင် လုံးဝဖတ်၍မရ · audio track မပါ (သတိပေးချက်သာ)
* **+** `app.py` yt-dlp format ladder တွင် **H.264 (avc1) ကို ဦးစားပေး** ဒေါင်းစေသည်
  (`bv*[vcodec^=avc1]+ba/b` → ယခင် selectors များက fallback အဖြစ် ကျန်)

### Bug 3 — Error ရှည်လို့ layout ကျယ် / zoom ထွက်
* **အရင်း** — `media.py:266` က ၂,၅၀၀ လုံး × chunk ၃ ခု = ၇,၅၀၀ လုံး၊ အတွင်းမှာ space မပါသော
  path ၁၃၀+ လုံး။ `.log-box`/`.toast` တွင် `overflow-wrap` မရှိ၊ `html,body` တွင် `overflow-x` guard မရှိ။
* **ပြင်** — `static/styles.css`:
  `html, body { max-width:100%; overflow-x:hidden }` ·
  `.log-box` / `.toast` / `.err-text` → `overflow-wrap:anywhere; word-break:break-word; min-width:0` ·
  `.toast` → `max-height:45vh; overflow-y:auto` ·
  `static/app.js` → `clampToast()` (toast အများဆုံး ၂၆၀ လုံး)
* **အပိုပြင်** — `str(exc)` ကို အတိုချုပ် (toast-safe)၊ အပြည့်အစုံကို `.detail` ထဲ ရွှေ့ခြင်း

### Bug 4 — ffmpeg log အကြမ်း တိုက်ရိုက်ပြခြင်း
* **ပြင်** — `media.summarize_ffmpeg_error()` က log ကို **တစ်ကြောင်း မြန်မာ** အဖြစ် ပြောင်းသည်
  (moov atom · decoder မရှိ · received no packets · ဖိုင်မရှိ · disk ပြည့် · permission ·
  filter/option မရှိ · memory · font · network · timeout · output ဖွင့်မရ)
* **+** Job panel တွင် **collapsible `<details>`** အသစ် — `#job-error-panel`
  (အတို အကြောင်းရင်း → 👉 hint → 🔎 အပြည့်အစုံ raw log)
* `jobs.py` တွင် field အသစ် ၂ ခု — `error_detail`, `error_hint` (task JSON ဟောင်းများ ဆက်ဖတ်နိုင်သည်)

### ဖိုင်စာရင်း (ပြင်လိုက်သည်များ)
```
recapstudio/media.py     error type ၃ ခု + summarizer + preflight_video() + decode probe
recapstudio/ai.py        ProxyBuildError, aggregate_chunk_failure(), _short_reason(), build_proxy wrap
recapstudio/pipeline.py  preflight (recap+split), failure handler (error_detail/hint), _error_hint()
recapstudio/jobs.py      Job.error_detail / Job.error_hint
recapstudio/uploads.py   upload complete တွင် preflight + payload.validation
app.py                   yt-dlp avc1-first, import ပြီးချင်း preflight, _json_error summarizer
static/styles.css        overflow guards + .err-panel/.err-detail
static/index.html        #job-error-panel (collapsible)
static/app.js            renderJobError(), clampToast(), upload verdict toast
recapstudio/__init__.py 4.3.4        recapstudio/config.py  app_version 4.3.4
```

---

## 3. Test အခြေအနေ (ဤ session တွင် run ပြီး)

```bash
.venv/bin/python tests/test_input_diagnostics.py        # 33/33 ✅  (offline, ffmpeg mock)
.venv/bin/python tests/test_ai_parts.py                 # 21/21 ✅
.venv/bin/python tests/test_auth.py                     # 69/69 ✅
.venv/bin/python tests/test_key_ring.py                 # 27/27 ✅
.venv/bin/python tests/test_narration_fit.py            # 39/39 ✅
.venv/bin/python tests/test_self_attrs.py               # ✅
.venv/bin/python tests/test_ui_preview.mjs              # 40/40 ✅ (jsdom — section 6 အသစ်)
FFMPEG_BINARY=<ffmpeg> .venv/bin/python tests/test_ffmpeg_diagnostics.py   # 14/14 ✅ (ffmpeg ရှိလျှင်)
# ffmpeg လိုသည့် အခြား test များ (smoke_test, test_real_run, test_cancel, test_audio_coverage)
# သည် sandbox တွင် ffmpeg မရှိသဖြင့် EC2 ပေါ်မှာ ပြန် run ပါ
```

---

## 4. ကျန် backlog — အတည်ပြုရန် (yes/no)

| # | အလုပ် | လက်ရှိ အခြေအနေ (ကုဒ်ထဲ စစ်ပြီး) | ခန့်မှန်း အတိုင်းအတာ |
|---|---|---|---|
| **#3** | **Adaptive video speed** | မရှိသေးပါ။ လက်ရှိတွင် အသံကို window ထဲ သွင်းရန် TTS `rate` boost → `atempo` → trim (ဗီဒီယိုကို မပြောင်းပါ) | အလယ်အလတ် — UI toggle + `setpts`/`atempo` + Drift စစ် |
| **#8** | **Senior UI/UX rework (all-device)** | v4.3 Batch A တွင် breakpoint ladder, 44px touch, landscape, safe-area ပြီးသည်။ ကျန် — information architecture/အမြင်ပိုင်း ပြန်စီခြင်း | **ကြီး** — design pass တစ်ခုလုံး (အကြီးစား) |
| **#9** | **Splitter → Studio** | v4.3 တွင် အခြေခံ ပြီးသည် (clip → Studio → One-Click; `tests/test_ui_preview.mjs` section 5 က အတည်ပြု) | ကျန် လိုအပ်ချက် ရှိ/မရှိ အတည်ပြုရန် |
| **#14** | **Competitor benchmark** | မရှိသေးပါ | သုတေသန + စာရွက် (build မဟုတ်) |

> **အတည်ပြုရန် မေးခွန်းများ** (yes/no)
> 1. **#3 adaptive video speed** — ဗီဒီယိုကို 1.05–1.15× မြန်စေ၍ အသံနှင့် ကိုက်စေလိုခြင်း ဟုတ်ပါသလား?
> 2. **#8** ကို ယခု အကြီးအကျယ် လုပ်မလား၊ သို့ #3 ကို အရင် လုပ်မလား?
> 3. **#9** လက်ရှိ Splitter→Studio က လုံလောက်ပြီလား၊ ဘာ ထပ်ထည့်လိုပါသလဲ?
> 4. v4.3.3 OAuth commit (`7c3b8fb`) — မိမိကိုယ်တိုင် push မလား၊ ဒီ branch ပေါ် cherry-pick လုပ်ပေးရမလား?

---

## 5. AWS အခြေအနေ

* **တင်ရန် remote branch** — `arena/01a10790-recap-studio-mm` (ဤ session branch)
* **runbook** — `docs/V434_FIX_CMD.md` (copy-paste အဆင့်ဆင့်)
* **installer** — `deploy/ec2_install.sh` (idempotent — data/.env ကို မထိ)
* **v4.3.4 ၏ AWS သက်ဆိုင်မှု** — EC2 ပေါ်ရှိ downloader-site ဖိုင် (AV1/VP9) ပြဿနာကို
  upload ချိန်တွင်ပင် မြန်မာလို ဖော်ပြပြီး၊ yt-dlp import က H.264 ကို ဦးစားပေးတော့သည်။
