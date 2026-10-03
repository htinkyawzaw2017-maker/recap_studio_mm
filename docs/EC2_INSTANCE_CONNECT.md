# AWS EC2 (Instance Connect · Ubuntu · port 80) — အသစ် Version တင်နည်း

> **သင့်လက်ရှိ setup အတွက် တိုက်ရိုက် အဖြေ** — `app.py` ဖိုင်တစ်ခုတည်းကို `nano` နဲ့ paste ထားတဲ့
> နည်းလမ်းနဲ့ **အသစ်ကို update လုပ်၍ မရပါ**။ ဘာကြောင့်လဲ ဆိုတော့ fix အသစ်မှာ `app.py` အပြင်
> `recapstudio/` (engine အပိုင်း ၁၂ ဖိုင်)၊ `static/` (UI) နှင့် `assets/fonts/` (မြန်မာဖောင့်) ပါဝင်လို့ပါ။
> အောက်က script က အဲဒါအားလုံးကို အလိုအလျောက် ရယူတပ်ဆင်ပေးပါတယ် — **command တစ်ကြောင်းပါ။**

---

## ⚡ အမြန်ဆုံးနည်းလမ်း — command တစ်ကြောင်းတည်း

EC2 Instance Connect terminal (အမည်းရောင် မျက်နှာပြင်) ထဲမှာ ဒါကို copy ကူးပြီး Enter ခေါက်ပါ:

```bash
curl -fsSL -o /tmp/recap_install.sh https://raw.githubusercontent.com/htinkyawzaw2017-maker/recap_studio_mm/arena/01a10175-recap-studio-mm/deploy/ec2_install.sh && sudo bash /tmp/recap_install.sh
```

ဒါပါပဲ။ Script က အောက်ပါအလုပ်အားလုံးကို လုပ်ပေးပါမည်:

1. အဟောင်း `uvicorn` (tmux ထဲက) process ကို ရပ်ပေးသည်
2. `ffmpeg`, `python3-venv`, မြန်မာဖောင့်များ သွင်းပေးသည်
3. GitHub မှ **fix အားလုံးပါသော code** ကို ရယူသည်
4. `/opt/recap-studio` ထဲ တပ်ဆင်သည် (data နှင့် setting များ မပျောက်ပါ)
5. Python packages များ venv ထဲ သွင်းသည်
6. `.env` config ဖိုင် ဖန်တီးသည် + **အဟောင်း `.recap_config.json` ထဲက Gemini API key ကို အလိုအလျောက် ကူးယူသည်**
7. **systemd service** တည်ဆောက်သည် (reboot ဖြစ်လည်း အလိုအလျောက် ပြန်တက် — tmux မလိုတော့ပါ)
8. Health check လုပ်ပြီး အောင်မြင်မှုကို ပြပေးသည်

**ဖြစ်နိုင်သည့် အခက်အခဲ:** အချို့ network များတွင် `raw.githubusercontent.com` ပိတ်ထားတတ်သည်။
အဲဒီအခါ အောက်က နည်းလမ်း (၃) ကြောင်းကို သုံးပါ 👇

---

## 🅱️ backup နည်းလမ်း (raw URL မရပါက)

```bash
cd /tmp
curl -fsSL -o recap.tar.gz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a10175-recap-studio-mm
tar xzf recap.tar.gz
sudo bash recap_studio_mm-*/deploy/ec2_install.sh
```

---

## 📋 ပြီးသွားပါက လုပ်ရမည့် အဆင့် (၂) ခု

### ၁။ Gemini API Key ထည့်ပါ

```bash
sudo nano /opt/recap-studio/.env
```

`GEMINI_API_KEY=` နောက်တွင် သင့် key ကို ထည့်ပါ (https://aistudio.google.com/apikey မှ ရယူနိုင်သည်):

```
GEMINI_API_KEY=AIzaSy....................
```

`Ctrl + X` → `Y` → `Enter` (save) ပြီးရင်:

```bash
sudo systemctl restart recap-studio
```

> အဟောင်း app က key ကို server ပေါ် save ထားခဲ့ပါက script က အလိုအလျောက် ကူးပေးပြီးသား ဖြစ်နိုင်သည်။
> စစ်ရန်: `sudo grep GEMINI_API_KEY=..* /opt/recap-studio/.env`

### ၂။ Public URL အတွက် လျှို့ဝှက်စာ (အကြံပြု — မဖြစ်မနေ မဟုတ်)

သင့် IP ကို သိတဲ့သူများ Gemini credit ကို သုံးနိုင်မည် ဖြစ်လို့ လျှို့ဝှက်စာ ထည့်ပါ:

```bash
sudo nano /opt/recap-studio/.env
# RECAP_ACCESS_PASSWORD=သင့်လျှို့ဝှက်စာ
sudo systemctl restart recap-studio
```

ပြီးရင် Browser ထဲ open ပြီး **⚙️ Settings → Access Key** တွင် ထည့်ပါ။

---

## 🌐 ဖွင့်ကြည့်ပါ

```
http://<သင့် EC2 Public IPv4>
```

(port 80 ဖြစ်လို့ `:80` မလိုပါ။ Public IP ကို EC2 Console → Instances → သင့်စက် → **Public IPv4 address** မှာ ကြည့်ပါ။
IP ပြောင်းတတ်သည် — မပြောင်းစေလိုပါက **Elastic IP** တစ်ခု attach လုပ်ပါ။)

**UI အဟောင်း (neon အရောင်၊ `ZERO-DRIFT SYNC` badge) ပေါ်နေဆဲဆိုပါက** browser cache ဖြစ်သည် — `Ctrl + Shift + R` နှိပ်ပါ။

---

## ✅ Update တကယ် ရောက်/မရောက် စစ်ဆေးခြင်း

**EC2 ပေါ်မှာ:**

```bash
sudo systemctl status recap-studio --no-pager | head -12
curl -s http://localhost/healthz
```

မျှော်မှန်းရလဒ်:

```json
{"status":"ok","ffmpeg":true,"ffprobe":true,"version":"4.0.0"}
```

* **`version":"4.0.0"`** → fix အသစ် ရောက်ပါပြီ ✔
* `version` မပါဘူး (သို့) connection refused → အဟောင်း process ဆက်ပြေးနေဆဲ ဖြစ်နိုင်သည်
  → `sudo pkill -f "uvicorn app:app"` ပြီး `sudo systemctl restart recap-studio`

**သင့် laptop ပေါ်မှ (ပိုစုံစုံ):**

```bash
python tests/verify_deployment.py http://<သင့်-IP>
```

ဒီ script က version၊ မြန်မာဖောင့်၊ disk၊ upload API နှင့် တကယ့် recap job တစ်ခုအထိ စစ်ပေးပြီး
ဘယ်အဆင့်မှာ ရပ်နေသည်ကို တိုက်ရိုက် ပြပေးပါမည်။ (`--video clip.mp4` ထည့်ပါက အသံ/စာတန်းထိုးအထိ စမ်းပေးသည်။)

---

## 🔁 နောက်တစ်ခါ Update လုပ်ရန်

Script ကို **ထပ်ပဲ run ပါ** (idempotent — setting/data များ မပျောက်ပါ):

```bash
sudo bash /opt/recap-studio/deploy/ec2_install.sh
```

သို့မဟုတ် (code ကို GitHub မှ အသစ် ပြန်လိုချင်လျှင်):

```bash
curl -fsSL -o /tmp/recap_install.sh https://raw.githubusercontent.com/htinkyawzaw2017-maker/recap_studio_mm/arena/01a10175-recap-studio-mm/deploy/ec2_install.sh && sudo bash /tmp/recap_install.sh
```

> 💡 အရေးကြီး — **`main` branch ကို merge လုပ်လိုက်ပါက** `RECAP_BRANCH=main` ဖြင့် run နိုင်သည်:
> `sudo RECAP_BRANCH=main bash /opt/recap-studio/deploy/ec2_install.sh`
> (merge လုပ်ရန်: https://github.com/htinkyawzaw2017-maker/recap_studio_mm/pull/1 → **Merge pull request**)

---

## 🧹 အဟောင်း code ရှင်းလင်းခြင်း (optional)

အရင် `nano app.py` နဲ့ paste ခဲ့သည့် ဖိုင်များ (ဥပမာ `/home/ubuntu/app.py`) ကို ဖျက်နိုင်သည် —
အသစ်က `/opt/recap-studio` မှာ ရှိပါသည်:

```bash
mv /home/ubuntu/app.py /home/ubuntu/app.py.OLD.bak   # သေချာမှ ဖျက်ပါ
tmux ls            # အဟောင်း session ရှိပါက
tmux kill-server   # (သို့) tmux kill-session -t <name>
```

---

## 🩺 ပြဿနာ တက်လာပါက

| လက္ခဏာ | ဖြေရှင်းချက် |
|---|---|
| Browser မဖွင့်နိုင် (timeout) | EC2 **Security Group → Inbound rules** တွင် `HTTP (port 80)` ကို `0.0.0.0/0` မှ ခွင့်ပြုထားပါ |
| `Connection refused` | `sudo systemctl status recap-studio` → `sudo journalctl -u recap-studio -n 60 --no-pager` |
| UI အဟောင်း ပေါ်နေဆဲ | `Ctrl+Shift+R`; ပြီးရင် `sudo pkill -f "uvicorn app:app"; sudo systemctl restart recap-studio` |
| Port 80 already in use | အဟောင်း tmux process: `sudo pkill -f "uvicorn app:app"` ပြီး service ကို ပြန် restart |
| API key error (job fail) | `sudo grep GEMINI_API_KEY=..* /opt/recap-studio/.env` — မရှိပါက အပေါ်က အဆင့် ၁ ကို လုပ်ပါ |
| အသံ အစားထိုး beep ထွက်နေသည် | `.env` ထဲ `RECAP_FAKE_TTS=1` ရှိ/မရှိ စစ်ပါ (0 ဖြစ်ရမည်) |
| AI မဟုတ်ဘဲ demo စာသား ထွက်သည် | `.env` ထဲ `RECAP_DEMO_MODE=1` ရှိ/မရှိ စစ်ပါ (0 ဖြစ်ရမည်) |
| `Permission denied` (data folder) | `sudo chown -R ubuntu:ubuntu /opt/recap-studio` |
| Render အလယ်မှာ ရပ်သွား / OOM | `t3.medium` (4 GB) တွင် `RECAP_MAX_CONCURRENT_JOBS=1` ထားပါ; ပိုကြီးသော ဗီဒီယိုများအတွက် `t3.large` သို့ တင်ပါ |
| မြန်မာစာလုံး လေးထွက်ကွက် (tofu) | `sudo apt install fonts-noto-core -y` (font ကို app ထဲမှာလည်း bundle ထားသည်) |
| Disk ပြည့် | `df -h`; ပြီးသော ဖိုင်များကို `sudo rm -rf /opt/recap-studio/data/output/*` (သို့) `.env` တွင် `RECAP_OUTPUT_TTL_HOURS=24` လျှော့ပါ |

---

## 💰 ကုန်ကျစရိတ် / ကောင်းမွန်စေရန် အကြံပြုချက်များ

* **မသုံးချိန်** EC2 Console မှ **Stop instance** လုပ်ပါ (EBS storage ဖိုးသာ ကျန်) — $100 credit ကို ကြာကြာ ခံစေသည်။
  * Stop လုပ်ပါက Public IP ပြောင်းနိုင်သည် → **Elastic IP** attach ထားပါ။
* **Backup**: ဗီဒီယိုများသည် `/opt/recap-studio/data/` အောက်တွင် ရှိသည်။ လိုအပ်ပါက `sudo tar czf /tmp/backup.tgz /opt/recap-studio/data` ဖြင့် ယူထားနိုင်သည်။
* **နောက်ဆက်တွဲ အဆင့်တင်ရန်** (မြန်နှုန်း + HTTPS):
  * Instance type ကို `t3.large` (2 vCPU / 8 GB) သို့ တင်ခြင်း → render ~2 ဆ မြန်လာသည်
  * `c6i.xlarge` သို့မဟုတ် `c7g.xlarge` (Graviton) သုံးပါက render အများကြီး ပိုမြန်သည်
  * HTTPS လိုပါက **ALB + ACM certificate** (သို့) `nginx` + `certbot` ကို အသုံးပြုနိုင်သည် — `docs/AWS_DEPLOY.md` §4
  * နောက်ပိုင်း အလိုအလျောက် deploy လိုချင်ပါက ECS Fargate + ECR သို့ ပြောင်းနိုင်သည် — `docs/AWS_DEPLOY.md`
