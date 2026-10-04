# v4.3.4 — "AI analysis failed" အမှား အမှန်ဖော်ပြ + Input pre-flight
### AWS EC2 ပေါ် ပြန်တင်နည်း (Windows CMD / EC2 Instance Connect → Step by Step)

> **branch** — `arena/01a10790-recap-studio-mm` · **version** — `4.3.4`
> **ဘာဖြစ်ခဲ့လဲ** — downloader site မှ ရလာသော ဖိုင်နှင့် recap လုပ်ရာ
> `AI analysis failed for every chunk` ထွက်ပြီး website layout လည်း ဘေးတိုက် ကျယ်ထွက်သွားသည်။
> **တကယ်ဖြစ်နေသည်က** AI မရောက်ဘဲ **ffmpeg (proxy ဖြတ်ထုတ်သည့်အဆင့်) မှာ သေနေသည်**။
> ဤ build သည် အမှားကို အမှန်ဖော်ပြပြီး၊ upload ပြီးချင်းမှာပင် ဖိုင်ကို ကြိုစစ်ပေးသည်။
>
> command အားလုံးကို **copy → paste** လုပ်ရုံပါ။ `<EC2-IP>` နေရာတွင် သင့် server ၏
> Public IPv4 (ဥပမာ `13.212.45.67`) ထည့်ပါ။

---

## 📋 အကျဉ်းချုပ် — အဆင့် ၆ ဆင့်

| # | ဘယ်မှာ | ဘာလုပ်မလဲ | ကြာချိန် |
|---|---|---|---|
| 1 | **Windows CMD / EC2 Connect** | server ထဲ ဝင် | ၁ မိနစ် |
| 2 | **Server** | code အသစ် (v4.3.4) ဆွဲတင် | ၂–၄ မိနစ် |
| 3 | **Server** | version + code စစ် | ၁ မိနစ် |
| 4 | **Server** | ⚠️ သင့်ဖိုင်၏ codec နှင့် server decoder စစ် | ၂ မိနစ် |
| 5 | **Browser** | hard refresh + ဖိုင် တင် → error ချက်ချင်း ပြ/မပြ စမ်း | ၂ မိနစ် |
| 6 | **Server** | (လိုလျှင်) log ကြည့် / အနောက်သို့ ပြန်လှည့် | ၂ မိနစ် |

---

## 🩺 0. ဤ build တွင် ပြင်ထားသည့် bug ၄ ချက်

| # | ပြဿနာ (ယခင်) | ယခု v4.3.4 |
|---|---|---|
| 1 | ffmpeg ကျရှုံးမှုကို "AI analysis failed" ဟု မှားပြ | `FFmpegFailure` / `ProxyBuildError` သီးသန့် type — **"🎬 ffmpeg က ဗီဒီယိုကို ဖြတ်ထုတ်၍ မရပါ — AI ဆီ မပို့ရသေးပါ"** ဟု မြန်မာလို ပြ |
| 2 | ဖိုင်မကောင်းလျှင် job စပြီးမှ (မိနစ်များစွာ အကြာ) error | **upload ပြီးချင်း** ffprobe + တကယ့် ၅-frame decode စမ်း → မြန်မာ error ချက်ချင်း |
| 3 | error ရှည် (၇,၅၀၀ လုံး) → layout ကျယ်၊ zoom ထွက် | `.log-box`/`.toast` တွင် `overflow-wrap:anywhere` + `overflow-x:hidden` guard၊ toast အများဆုံး ၂၆၀ လုံး |
| 4 | ffmpeg log အကြမ်း တိုက်ရိုက်ပြ | အတိုချုပ် မြန်မာ + အပြည့်အစုံကို **collapsible `<details>`** ထဲ (လိုမှ ဖွင့်ကြည့်) + "👉 ဘာလုပ်ရမလဲ" hint |

---

## 1️⃣ Server ထဲ ဝင်ခြင်း

**နည်း ၁ — Windows CMD**
```cmd
ssh -i "%USERPROFILE%\.ssh\recap-key.pem" ubuntu@<EC2-IP>
```

**နည်း ၂ (key မလိုဘဲ၊ အလွယ်ဆုံး)** — AWS Console → EC2 → သင့် instance ရွေး →
**Connect** → **EC2 Instance Connect** → **Connect** (browser terminal ပေါ်လာမည်)။

---

## 2️⃣ Code အသစ် (v4.3.4) တင်ခြင်း

**တစ်ကြောင်းတည်း (copy-paste တစ်ချက်) —**
```bash
cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a10790-recap-studio-mm && rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz && sudo RECAP_BRANCH=arena/01a10790-recap-studio-mm bash /tmp/recap_studio_mm-arena-01a10790-recap-studio-mm/deploy/ec2_install.sh
```

> 💡 `data/` (အကောင့်များ၊ API key၊ ထွက်ပြီးသားဗီဒီယိုများ) နှင့် `.env` ကို installer က
> **မထိပါ** — code သာ အစားထိုးပြီး service ကို restart လုပ်သည်။

Installer က အလိုအလျောက် လုပ်ပေးသည် —
```
0/8 preflight · 1/8 process ရပ် · 2/8 ffmpeg+python+fonts (apt) · 3/8 code ဆွဲ
4/8 /opt/recap-studio သို့ sync · 5/8 .venv + pip · 6/8 .env + admin · 7/8 systemd restart · 8/8 health check
```

---

## 3️⃣ တကယ် ရောက်/မရောက် စစ်ခြင်း

```bash
curl -s http://localhost/healthz | head -c 200; echo
```
→ `"version":"4.3.4"` ပါရမည်။

```bash
grep -c preflight_video /opt/recap-studio/recapstudio/pipeline.py    # 2 (recap + split) ရမည်
grep -c "err-detail" /opt/recap-studio/static/index.html             # 1 အထက် ရမည်
grep -c "overflow-wrap: anywhere" /opt/recap-studio/static/styles.css # 1 အထက် ရမည်
```

---

## 4️⃣ ⚠️ အရေးကြီးဆုံးအဆင့် — သင့်ဖိုင် (downloader site ဖိုင်) ကို စစ်ခြင်း

### 4.1 ဖိုင်၏ video codec က ဘာလဲ

```bash
ls -lh /opt/recap-studio/data/uploads/ | head          # သင့်ဖိုင် ရှာပါ
FILE=/opt/recap-studio/data/uploads/<သင့်ဖိုင်အမည်>.mp4

ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate \
        -of default=nw=1 "$FILE"
```
ဥပမာ ရလဒ် — `codec_name=av1` သို့မဟုတ် `codec_name=vp9` ဖြစ်နေလျှင် **ဒါက သင့်ပြဿနာ၏ အရင်း** ဖြစ်သည်။

### 4.2 Server ရဲ့ ffmpeg မှာ decoder ရှိ/မရှိ

```bash
ffmpeg -hide_banner -decoders 2>/dev/null | grep -Ei "libdav1d|libaom-av1|(^|\s)(av1|vp9|h264)\s"
```
* `libdav1d` / `av1` / `vp9` / `h264` ပေါ်နေလျှင် — decoder ရှိသည် → **ဖိုင်ကိုယ်တိုင် ပျက်နိုင်သည်** →
  4.3 (ဂ) ကို ကြည့်ပါ။
* **av1/vp9 decoder မပေါ်လျှင်** — 4.3 (ခ) ကို လုပ်ပါ။

### 4.3 ဖြေရှင်းနည်း (၃ မျိုး — အစဉ်လိုက် စမ်းပါ)

**(က) အကောင်းဆုံး နည်း — H.264 ဖိုင်အဖြစ် ပြန်ဒေါင်းပါ** *(အကြံပြုသည်)*
```bash
# server ပေါ်တွင်ဖြစ်စေ၊ မိမိကွန်ပျူတာတွင်ဖြစ်စေ
yt-dlp -f "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[height<=1080][vcodec^=avc1]/b" "<URL>" -o recap.mp4
```
> v4.3.4 မှစ၍ app ထဲက **🔗 Link မှ Import** ကလည်း H.264 (avc1) ကို **ဦးစားပေး** ဒေါင်းပြီး
> import ပြီးချင်း စစ်ပေးသည်။ ထို့ကြောင့် downloader site အစား **app ထဲက Link Import** ကို
> သုံးခြင်းသည် အကောင်းဆုံး။

**(ခ) Server ffmpeg တွင် codec ဖြည့်တင်ခြင်း (Ubuntu)**
```bash
sudo apt update
sudo apt install -y libavcodec-extra ffmpeg
sudo systemctl restart recap-studio
ffmpeg -hide_banner -decoders 2>/dev/null | grep -Ei "libdav1d|(^|\s)(av1|vp9)\s"   # ပြန်စစ်
```

**(ဂ) ဖိုင် ပျက်နေလျှင် (moov atom / frame=0 / ဖိုင် လမ်းတစ်ဝက် ပြတ်)**
```bash
# ffprobe duration က 0 ဖြစ်နေလျှင် (သို့) "moov atom not found" တက်လျှင် → ဖိုင်ပျက်
ffprobe -v error -show_entries format=duration -of default=nw=1 "$FILE"
```
→ ဖိုင်ကို ဖျက်ပြီး **ပြန်ဒေါင်းလုဒ်** (သို့) app ထဲ **ပြန်တင်** ပါ။

### 4.4 (စမ်းလိုလျှင်) app ၏ pre-flight ကို ကိုယ်တိုင် run ခြင်း
```bash
sudo -u ubuntu bash -lc 'cd /opt/recap-studio && set -a && . ./.env && set +a && .venv/bin/python - <<"PY"
from recapstudio.media import preflight_video
import json
rep = preflight_video("/opt/recap-studio/data/uploads/<သင့်ဖိုင်>.mp4")
print(json.dumps({k: v for k, v in rep.items() if k != "detail"}, ensure_ascii=False, indent=2))
print("--- raw ---"); print((rep.get("detail") or "")[-800:])
PY'
```
`"ok": false` ဖြစ်လျှင် `message` (မြန်မာ) တွင် အကြောင်းရင်း ပါလာမည်။

---

## 5️⃣ Browser မှာ စမ်းသပ်ခြင်း

1. `http://<EC2-IP>/` ကို ဖွင့်ပြီး **Ctrl + Shift + R** (hard refresh — CSS/JS အသစ် ရမည်)
2. Settings → **About / version** တွင် `4.3.4` ဖြစ်ကြောင်း စစ်
3. ပြဿနာဖြစ်သော **ဖိုင်ကို ပြန်တင်** ကြည့်ပါ —
   * ဖိုင် မကောင်းလျှင် → **upload ပြီးချင်း** မြန်မာ error ပေါ်ပြီး job မစတင်တော့ပါ
     (ယခင် လို မိနစ်များစွာ စောင့်ရမည် မဟုတ်တော့ပါ)
   * ဖိုင် ကောင်းလျှင် → `⚡ One-Click` နှိပ်ပြီး recap စမ်းပါ
4. recap တစ်ခု ပျက်လျှင် **Job Progress** card တွင် —
   * အပေါ်ဆုံးတွင် **အတို မြန်မာ အကြောင်းရင်း**
   * အောက်တွင် **👉 ဘာလုပ်ရမလဲ (hint)**
   * အောက်ဆုံးတွင် **🔎 အပြည့်အစုံ (ffmpeg / log)** — နှိပ်မှ ပွင့်မည်
   ဆိုသည့် အစီအစဉ်ဖြင့် ပေါ်လာမည် (ယခင်လို အပေါ်စာမျက်နှာတစ်ခုလုံး ကျယ်ထွက်မည် မဟုတ်တော့ပါ)။

---

## 6️⃣ ပြဿနာ ရှိလျှင် (log / rollback)

```bash
# service အခြေအနေ + log အသစ် ၂၀၀
sudo systemctl status recap-studio --no-pager
sudo journalctl -u recap-studio -n 200 --no-pager

# ffmpeg လုံးဝ မတွေ့လျှင်
sudo apt install -y ffmpeg && sudo systemctl restart recap-studio

# disk ပြည့်နေလျှင်
df -h / ; sudo du -sh /opt/recap-studio/data/*
sudo rm -rf /opt/recap-studio/data/tmp/*          # ယာယီဖိုင်များ
# မကောင်းသော (စစ်ဆေး၍ ကျရှုံးခဲ့သော) upload ဖိုင်များ ဖျက်ရန် — disk ပြန်ရယူ
ls -lh /opt/recap-studio/data/workspace/ | head
sudo rm -f /opt/recap-studio/data/workspace/video_*
```

**အနောက်သို့ ပြန်လှည့်လိုလျှင် (v4.3.2)** —
```bash
cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm && rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz && sudo RECAP_BRANCH=arena/01a105ed-recap-studio-mm bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh
```

---

## 7️⃣ မရသေးလျှင် ကျွန်ုပ်ကို ပို့ပေးရန်

```bash
curl -s http://localhost/healthz; echo
ffmpeg -hide_banner -decoders 2>/dev/null | grep -Ei "dav1d|libaom|(^|\s)(av1|vp9|h264)\s"
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -of default=nw=1 "$FILE"
sudo journalctl -u recap-studio -n 80 --no-pager | grep -Ei "ffmpeg|preflight|failed" | tail -20
```
ဤ output ၄ ခုကို ပို့ပေးပါ — ဘယ်အဆင့်မှာ ဘာကြောင့် သေသည်ကို တိကျစွာ ပြောနိုင်ပါမည်။
