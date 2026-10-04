# v4.3 — Live Preview အတိအကျ + Device အားလုံး အဆင်ပြေ (Phase 3 · Batch A)

> Phase 3 စာရင်းထဲမှ **#8 (preview နေရာ + စာတန်း မကိုက်မှု + responsive)** နှင့်
> **#9 (Splitter → Studio တိုက်ရိုက် recap)** ကို ဤ build တွင် ပြီးစီးပါပြီ။
> ကျန်အရာများ (#1–#7, #10–#14) ကို နောက် batch များတွင် ဆက်လုပ်ပါမည်။

---

## 1. ဘာတွေ ပြောင်းသွားလဲ

### 1.1 Live Preview = ထွက်မည့် ဖိုင်အတိအကျ (WYSIWYG)

| ယခင် v4.2 | ယခု v4.3 |
|---|---|
| Preview box ကို CSS ထဲ `9 / 16` အသေ ထည့်ထား — 16:9 / 1:1 ရွေးလည်း box မပြောင်း | `aspect` ရွေးသည်နှင့် box က **720×1280 / 1080×1080 / 1280×720 / မူရင်းအရွယ်** သို့ ချက်ချင်း ပြောင်း |
| `max-height` ကြောင့် box အချိုး ပျက် → ဗီဒီယိုက အပေါ်ပိုင်း ကပ်နေ၊ အောက်တွင် အနက်ရောင် ကျန် | box အကျယ်ကို **အမြင့် budget မှ တွက်** သဖြင့် အချိုး ဘယ်တော့မှ မပျက် |
| စာတန်း စာလုံးအရွယ် = `size × 0.5` (box နှင့် မဆိုင်) | စာလုံးအရွယ် = `size × (box အမြင့် ÷ ထွက်မည့် အမြင့်)` — **ASS PlayRes** တွက်ချက်မှု အတိအကျ |
| hook top 3.2%၊ စာတန်း အကျယ် 92% | hook **top 6%**၊ hook အကျယ် 92% (ASS MarginL/R 4%)၊ စာတန်း အကျယ် **90%** (MarginL/R 5%) |
| Logo `left:p%` — 100% ဆိုလျှင် ဖရိမ်ပြင်ပ ထွက်သွား | ffmpeg `overlay=(W-w)·p` နှင့် တစ်ထပ်တည်း (`left:p%` + `translate(-p%)`) |
| Center Crop ရွေးလည်း preview က letterbox ပြ | Center Crop → preview ဖြည့်ပြ (`object-fit: cover`) |

👉 **ရလဒ်** — preview ထဲ ဆွဲချထားသည့် စာတန်း/logo နေရာသည် ထွက်လာသော MP4 ထဲတွင်
တူညီစွာ ထွက်ပါသည်။ Preview card ခေါင်းစီးတွင် `720×1280 · 9:16` ကဲ့သို့
**ထွက်မည့် pixel အရွယ်** ကို chip ဖြင့် ပြထားသည်။ အောက်တွင် `Preview စကေး: 41%`
ဟု ပြသည် — preview သည် အထွက်ဖိုင်၏ ဘယ်နှစ်ရာခိုင်နှုန်း အရွယ်ဖြစ်ကြောင်း သိရသည်။

### 1.2 Device အားလုံး (phone → tablet → laptop → 4K)

* Breakpoint ladder — **≤430** (ဖုန်းသေး) · **≤620** (ဖုန်း) · **≤1024** (တက်ဘလက်) ·
  **≤1200** (studio ၂ တန်း → ၁ တန်း) · **≤1400** (laptop) · **1601+** (desktop ကြီး)
* Touch target **44px** (`pointer: coarse`) — လက်ချောင်းဖြင့် နှိပ်ရ လွယ်
* iOS တွင် input နှိပ်လျှင် စာမျက်နှာ **zoom မဝင်တော့** (control font 16px)
* **Landscape ဖုန်း** — preview သည် အမြင့် 76vh အထိသာ၊ topbar မကပ်တော့
* **Notch/safe-area** — အောက်ခြေ ခလုတ်များ iPhone home bar အောက် မပျောက်
* `prefers-reduced-motion` — animation မလိုသူများအတွက် ပိတ်ပေးသည်
* Tab bar သည် ဖုန်းတွင် scroll-snap ဖြင့် ချောမွေ့စွာ ရွှေ့နိုင်
* Settings ထဲ table များ ဖုန်းတွင် ဘေးတိုက် scroll

### 1.3 ⚡ One-Click bar (ဖုန်း/တက်ဘလက်)

ဗီဒီယို တင်ပြီးနောက် စာမျက်နှာ အောက်ဆွဲလိုက်၍ ခလုတ်ကြီး မမြင်ရတော့လျှင်
**အောက်ခြေတွင် sticky bar** အဖြစ် `⚡ One-Click Recap စမည်` လိုက်ပါလာသည်
(job run နေစဉ် `⏳ လုပ်ဆောင်နေသည်…` ဖြစ်ပြီး နှိပ်၍ မရ)။

### 1.4 🍿 Splitter → 🎬 Studio (တိုက်ရိုက် recap)

အပိုင်းခွဲပြီးသည်နှင့် အပိုင်းတိုင်း၏ card ပေါ်တွင် **`🎬 Studio သို့ ပို့မည်`**
ခလုတ် ပါလာသည် —

1. နှိပ်လိုက်သည်နှင့် ထို clip သည် Studio ၏ source ဖြစ်သွားသည် (ပြန်တင်စရာ မလို —
   server ပေါ်ရှိ ဖိုင်ကိုပဲ သုံးသည်၊ bandwidth မကုန်)
2. Studio tab သို့ အလိုအလျောက် ပြောင်းပြီး preview တွင် ထို clip ပေါ်လာသည်
3. `⚡ One-Click` ခလုတ် အရောင်လင်း၍ ပြသည် — နှိပ်ရုံဖြင့် recap/dubbing စတင်သည်

---

## 2. သင် လုပ်ရမည့် အဆင့်များ (AWS EC2 — ၅ မိနစ်)

```bash
# 1) server terminal (EC2 Instance Connect / SSH) ထဲ ဝင်ပါ — code အသစ် ဆွဲချ
cd /tmp
curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm
rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz
sudo bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh

# 2) restart
sudo systemctl restart recap-studio

# 3) တကယ် ရောက်/မရောက် စစ်
curl -s http://localhost/healthz          # "version":"4.3.0" ဖြစ်ရမည်
curl -s http://localhost/ | grep -c preview-frame    # 1 ဖြစ်ရမည် (v4.3 markup)
```

> Docker / ECS သုံးပါက → [AWS_UPDATE.md](AWS_UPDATE.md) §2a / §2b အတိုင်း
> image ပြန် build → `--force-new-deployment`။

### 2.1 Browser cache — ⚠️ အရေးကြီးဆုံး အဆင့်

Server မှာ v4.3 တင်ပြီးဖြစ်သော်လည်း browser က **ဟောင်းသော app.js/styles.css**
ကို cache ထဲမှ ပြန်သုံးနေတတ်သည် (ဒါကြောင့် "ပြင်ပြီးတယ်ဆိုပေမယ့် မပြောင်းဘူး"
ဖြစ်တတ်သည်)။ အောက်ပါအတိုင်း လုပ်ပါ —

| Device | လုပ်ရန် |
|---|---|
| Windows Chrome/Edge | **Ctrl + Shift + R** (သို့) Ctrl+Shift+Delete → Cached images and files → Clear |
| Mac Chrome/Safari | **Cmd + Shift + R** |
| Android Chrome | ⋮ → History → Clear browsing data → Cached images and files |
| iPhone Safari | Settings → Safari → Clear History and Website Data |

ပြီးလျှင် စာမျက်နှာ ခေါင်းစီးတွင် **`v4.3.0`** ဟု ပြနေရပါမည်။
`v4.2` / `v4.1` ပြနေသေးလျှင် cache မရှင်းရသေးပါ။

---

## 3. အလုပ်လုပ်/မလုပ် စစ်ဆေးရန် checklist

### 3.1 Desktop (၁ မိနစ်)

1. 🎬 Studio → ဗီဒီယိုတစ်ခု တင်ပါ
2. **ထွက်မည့် ဖော်မတ်** ကို `16:9` ပြောင်းကြည့်ပါ → preview box သည် အလျားလိုက်
   ဖြစ်သွားပြီး chip တွင် `1280×720 · 16:9` ပြရမည်
3. `1:1` ပြောင်းကြည့် → စတုရန်း ဖြစ်ရမည် (`1080×1080`)
4. စာတန်း စာလုံးအရွယ် slider ဆွဲကြည့် → preview ထဲ စာလုံး အချိုးကျ ကြီး/ငယ် ဖြစ်ရမည်
5. စာတန်းကို ဆွဲချကြည့် → `Subtitle အနိမ့်: NN%` ပြောင်းရမည်
6. Render ထုတ်ပြီး preview နှင့် နှိုင်းယှဉ်ကြည့် → နေရာ တူညီရမည်

### 3.2 ဖုန်း (၁ မိနစ်)

1. ဖုန်းဖြင့် site ဖွင့် → tab bar ကို ဘေးတိုက် ပွတ်ဆွဲ၍ ရရမည်
2. ဗီဒီယိုတင်ပြီး အောက်ဆွဲကြည့် → အောက်ခြေတွင် **⚡ One-Click Recap စမည်** bar ပေါ်ရမည်
3. ဖုန်းကို အလျားလိုက် လှည့်ကြည့် → preview က မပြည့်ကျပ်ဘဲ သပ်သပ်ရပ်ရပ် ရှိရမည်
4. input တစ်ခု နှိပ်ကြည့် → စာမျက်နှာ zoom မဝင်ရပါ (iOS)

### 3.3 Splitter → Studio

1. 🍿 Shorts Splitter → ဗီဒီယို တင် → `✂ အပိုင်းများ ခွဲထုတ်မည်`
2. အပိုင်းတစ်ခု၏ **`🎬 Studio သို့ ပို့မည်`** နှိပ် → Studio သို့ ရောက်ပြီး
   ဖိုင်အမည်မှာ `..._part_1.mp4` ဖြစ်ရမည်
3. `⚡ One-Click` နှိပ် → recap ထွက်ရမည်

---

## 4. Developer — offline test များ

```bash
node tests/test_ui_preview.mjs        # 31 checks — preview geometry + splitter→studio (server မလို)
node tests/test_ui_auth.mjs http://127.0.0.1:8000 myname 'password'   # 17 checks
python tests/smoke_test.py            # 69 checks
python tests/test_auth.py             # 69 checks
python tests/verify_deployment.py http://<EC2-IP>     # deploy ပြီးနောက် စစ်ရန်
```

`verify_deployment.py` တွင် v4.3 အတွက် စစ်ဆေးချက် ၃ ခု အသစ် ထပ်ထည့်ထားသည် —
`v4.3 responsive preview UI served`, `app.js previews the real output frame (v4.3)`,
`styles.css is the responsive v4.3 sheet`။ ဤ ၃ ခု PASS မဖြစ်လျှင် server သည်
build ဟောင်း ဖြစ်နေသည် (သို့) cache မရှင်းရသေးပါ။

---

## 5. နည်းပညာ မှတ်စု (ဘာကြောင့် တိကျသွားသလဲ)

ffmpeg က render လုပ်ပုံ —

```
pipeline._target_size()   9:16 → 720×1280 · 1:1 → 1080×1080 · 16:9 → 1280×720
                          မူရင်း → source size (long edge ≤ 1920, even)
subtitles.build_ass()     PlayResX/Y = target_w/target_h
                          SubtitleStyle Fontsize = sub_font_size   Alignment 2
                          MarginL/R = 0.05·W   MarginV = H · sub_v_pos%/100
                          HookStyle    Fontsize = 0.058·W          Alignment 8
                          MarginL/R = 0.04·W   MarginV = 0.06·H
render.py                 logo: scale=0.16·W, overlay=(W-w)·px : (H-h)·py
```

Preview သည် ဤတွက်ချက်မှုများကို browser ထဲတွင် တိုက်ရိုက် ပြန်တွက်သည် —

```
scale        = preview box အမြင့် (px) ÷ ထွက်မည့် အမြင့် (px)
စာတန်း px    = sub_font_size × scale
hook px      = 0.058 × ထွက်မည့် အကျယ် × scale
စာတန်း bottom = sub_v_pos %        hook top = 6 %
logo         = left:p% + translate(-p%)   ⇔  overlay=(W-w)·p
```

box အကျယ်ကို `max-width: calc(var(--preview-max-h) × ဖရိမ်အချိုး)` ဖြင့် သတ်မှတ်သဖြင့်
`max-height` က အချိုးကို ဖျက်သော ပြဿနာ (ယခင် bug) ပြန်မဖြစ်နိုင်တော့ပါ။
