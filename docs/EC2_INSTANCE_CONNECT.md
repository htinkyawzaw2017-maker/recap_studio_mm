# AWS EC2 ပေါ်တွင် Recap Studio MM တင်နည်း — အဆင့်ဆင့် (ပြန်လုပ်ရန် Runbook)

> **ဒီစာရွက်စာတမ်းက ဘာအတွက်လဲ**
> EC2 server ပေါ်မှာ **Recap Studio MM v4.1** ကို တင်ခြင်း / ပြန် update လုပ်ခြင်း ကို
> ပထမဆုံးအကြိမ် လုပ်သူလည်း လုပ်နိုင်အောင် အဆင့် ၀ ကနေ စပြီး ရေးထားသည်။
> **SSH မရှိသေးလည်း ရသည်** — browser ထဲက EC2 Instance Connect terminal နဲ့ လုပ်နိုင်သည် (အဆင့် ၃-က)။

---

## 🧭 အကျဉ်းချုပ် (ဘာတွေ လုပ်မလဲ)

| အဆင့် | လုပ်ရမည့်အလုပ် | အချိန် |
|---|---|---|
| 1 | EC2 instance ရှိ/မရှိ စစ် (မရှိလျှင် အသစ် ဖန်တီး) | ၅ မိနစ် |
| 2 | Security Group တွင် **port 22 (SSH)** + **port 80 (HTTP)** ဖွင့် | ၃ မိနစ် |
| 3 | Server ထဲ ဝင်ရောက်ခြင်း (Instance Connect / SSH key / PuTTY) | ၅ မိနစ် |
| 4 | Recap Studio install / update script run | ၅–၁၀ မိနစ် |
| 5 | Gemini API Key ထည့် (Key #1–#3) + restart | ၃ မိနစ် |
| 6 | Browser မှ ဖွင့်စမ်း + verify script run | ၅ မိနစ် |

မဖြစ်မနေ လိုသည့် အရာ — **AWS account**, **EC2 instance (Ubuntu 22.04/24.04, t3.medium အကြံပြု)**, **Gemini API key** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))။

---

## 1️⃣ EC2 instance ရှိ/မရှိ စစ်ဆေးခြင်း

1. AWS Console → ညာဘက်အပေါ်မှ **Region** ကို ရွေးပါ (မြန်မာနှင့် အနီးဆုံး: **Asia Pacific (Singapore) ap-southeast-1**)။
2. Search box တွင် `EC2` ရိုက် → **EC2** ကို ဖွင့်ပါ။
3. ဘယ်ဘက် menu → **Instances**။
4. Instance တစ်ခု ရှိပြီးသားလျှင် → **အဆင့် 2** သို့ ကျော်ပါ။
5. မရှိလျှင် **Launch instance** နှိပ်ပြီး အောက်ပါအတိုင်း ဖြည့်ပါ:

| Field | ထည့်ရမည့် တန်ဖိုး |
|---|---|
| Name | `recap-studio` |
| AMI | **Ubuntu Server 22.04 LTS** (သို့) 24.04 LTS (x86_64) |
| Instance type | **t3.medium (2 vCPU / 4 GB)** — အနည်းဆုံး; t3.small ဖြစ်လျှင် `RECAP_MAX_CONCURRENT_JOBS=1` ထားပါ |
| Key pair | **Create new key pair** → နာမည် `recap-key` → `.pem` ဖိုင် download (SSH သုံးမည်ဆိုလျှင် လိုသည်) |
| Network settings | ✅ Allow SSH (22) · ✅ Allow HTTP (80) |
| Storage | **30 GB gp3** (ဗီဒီယိုကြီးများ render လုပ်ရန်) |

6. **Launch instance** → **View all instances** နှိပ်ပြီး instance ကို **Running** + **Status check: 2/2 passed** အထိ စောင့်ပါ (၁–၂ မိနစ်)။
7. Instance ကို နှိပ်၍ **Public IPv4 address** ကို မှတ်ထားပါ (ဥပမာ `13.212.45.67`)။

> 💡 **Elastic IP** (အကြံပြု) — instance ကို stop/start လုပ်တိုင်း IP မပြောင်းစေရန်
> EC2 → **Elastic IPs** → *Allocate Elastic IP address* → *Associate* → instance ရွေးပါ။
> (running instance တစ်ခုနှင့် ချိတ်ထားစဉ် အခမဲ့ဖြစ်သည်။)

---

## 2️⃣ Security Group — port 22 နှင့် 80 ဖွင့်ခြင်း

1. EC2 → **Instances** → သင့် instance ကို ရွေး → အောက် tab မှ **Security** → Security group ကို နှိပ်။
2. **Inbound rules** → **Edit inbound rules** → **Add rule** နှစ်ခါ နှိပ်ပြီး ဖြည့်ပါ:

| Type | Port | Source | ဘာအတွက် |
|---|---|---|---|
| SSH | 22 | **My IP** (အကြံပြု) သို့မဟုတ် `0.0.0.0/0` | server ထဲ ဝင်ရန် (Instance Connect သုံးလည်း လိုသည်) |
| HTTP | 80 | `0.0.0.0/0` | ဝဘ်စာမျက်နှာ ဖွင့်ရန် |

3. **Save rules**။
4. HTTPS တပ်မည်ဆိုလျှင် **HTTPS (443)** ကိုပါ ဖွင့်ထားပါ (`0.0.0.0/0`).

> ⚠️ မဖွင့်ထားလျှင် browser တွင် **"ဒီ site ကို ချိတ်ဆက်၍ မရပါ / timeout"** ဖြစ်နေမည်။
> Update လုပ်တိုင်း ဤအချက် ပထမဆုံး စစ်ပါ။

---

## 3️⃣ Server ထဲ ဝင်ရောက်ခြင်း — ၃ နည်း (တစ်နည်း ရွေးပါ)

### 🅰️ EC2 Instance Connect (browser terminal) — **အလွယ်ဆုံး၊ SSH key မလိုပါ**

1. EC2 → **Instances** → သင့် instance ကို ရွေး။
2. ညာဘက်အပေါ် **Connect** ခလုတ် → tab **EC2 Instance Connect** ကို ရွေး။
3. **User name**: `ubuntu` (Ubuntu AMI အတွက်)။
4. **Connect** နှိပ် → အောက်ဘက် browser window တွင် **အနက်ရောင် terminal** ပေါ်လာမည်။

ဤ terminal ထဲတွင် အောက်ပါ အဆင့် 4 ကို တိုက်ရိုက် paste လုပ်နိုင်သည် (paste လုပ်ရန် `Ctrl+Shift+V`၊ Windows ဆိုလျှင် right-click → Paste)။

> ❗ Instance Connect မရလျှင်:
> * `Connection failed: EC2 Instance Connect is not available for this instance` → instance ကို **Amazon Linux / Ubuntu** AMI ဖြင့် ပြန်ဖန်တီးပါ၊
>   သို့မဟုတ် **EC2 Instance Connect Endpoint** (VPC → Endpoints) ဖန်တီးပါ၊
> * Port 22 ကို ဖွင့်ထားခြင်း မရှိလျှင် အရင် ဖွင့်ပါ (အဆင့် 2)။

### 🅱️ SSH key ဖြင့် ဝင်ခြင်း (Mac / Linux)

```bash
# 1) key ဖိုင် permission ပြင်ပါ (download လုပ်ထားသည့် folder ထဲမှာ)
chmod 400 ~/Downloads/recap-key.pem

# 2) ဝင်ပါ (IP ကို သင့် Public IPv4 ဖြင့် အစားထိုးပါ)
ssh -i ~/Downloads/recap-key.pem ubuntu@13.212.45.67

# "Are you sure you want to continue connecting (yes/no)?" → yes
```

### 🅲 Windows မှ ဝင်ခြင်း

* **PowerShell / CMD (Windows 10+)** — အထက်ပါ SSH command အတိုင်း run ပါ (OpenSSH ပါပြီးသား)။
* **PuTTY** — *Host Name*: `ubuntu@13.212.45.67`, *Port*: `22`,
  *Connection → SSH → Auth → Credentials → Private key file* တွင် `.ppk` ဖိုင်ထည့် (PuTTYgen ဖြင့် `.pem` → `.ppk` ပြောင်း)။

### 🅳 SSH key လုံးဝ မရှိတော့လျှင် (key ပျောက်/မမှတ်မိ)

1. EC2 → instance ရွေး → **Actions → Instance settings → Replace root volume** (snapshot လိုသည်), **သို့မဟုတ်**
2. **Instance Connect** ဖြင့် ဝင်နိုင်လျှင် ထိုလမ်းဖြင့်သာ ဆက်လုပ်ပါ၊
3. လုံးဝ မရတော့လျှင်: instance ကို stop → **Detach volume** → နောက် instance တစ်ခုမှာ attach → `~/.ssh/authorized_keys` ပြင်ပြီး → ပြန်ပြောင်း → start။
   (နည်းလမ်းရှိသော်လည်း ရှုပ်သည် — key အသစ်တစ်ခု ဖန်တီးပြီး instance အသစ်တင်ခြင်းက လက်တွေ့ ပိုမြန်)

---

## 4️⃣ Install / Update (server terminal ထဲတွင်)

### 🚀 အမြန်ဆုံးနည်းလမ်း — command တစ်ကြောင်းတည်း

```bash
curl -fsSL https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a1027a-recap-studio-mm \
  | tar xz -C /tmp \
  && sudo bash /tmp/recap_studio_mm-arena-01a1027a-recap-studio-mm/deploy/ec2_install.sh
```

> `main` branch ပေါ် merge လုပ်ပြီးသားလျှင် အထက်ပါ link ရှိ branch နာမည်ကို `main` ဖြင့် အစားထိုးပါ (သို့)
> `sudo RECAP_BRANCH=main bash /tmp/.../deploy/ec2_install.sh` ဟု run ပါ။

### အဆင့်ချင်း (script က လုပ်သည့်အလုပ်ကို နားလည်ထားရန်)

```bash
# 1) code ရယူပါ
cd /tmp
curl -fsSL -o recap.tar.gz \
  https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a1027a-recap-studio-mm
tar xzf recap.tar.gz

# 2) installer run (idempotent — ဘယ်နှစ်ခါ run လည်း ရသည်၊ data/key မပျောက်)
sudo bash /tmp/recap_studio_mm-arena-01a1027a-recap-studio-mm/deploy/ec2_install.sh
```

Installer က အလိုအလျောက် လုပ်ပေးသည်များ —
ffmpeg + python သွင်း၊ `/opt/recap-studio` သို့ code sync (`data/` နှင့် `.env` ကို မထိခိုက်)၊
venv ဖန်တီး + `pip install -r requirements.txt`၊ `.env` ဖန်တီး၊
`recap-studio.service` (systemd) တည်ဆောက်၍ 24/7 run， reboot ဖြစ်လည်း အလိုအလျောက် ပြန်တက်၊
နောက်ဆုံး health check (`http://127.0.0.1:80/healthz`) ဖြင့် စမ်း။

### 🅱️ backup နည်းလမ်း (script ဖိုင်တစ်ခုတည်း လိုလျှင်)

```bash
curl -fsSL -o /tmp/ec2_install.sh \
  https://raw.githubusercontent.com/htinkyawzaw2017-maker/recap_studio_mm/arena/01a1027a-recap-studio-mm/deploy/ec2_install.sh
sudo bash /tmp/ec2_install.sh
```

---

## 5️⃣ Gemini API Key ထည့်ခြင်း (Key ၃ ခုအထိ)

```bash
sudo nano /opt/recap-studio/.env
```

အောက်ပါ လိုင်းများကို ဖြည့်ပါ (quote `"` မထည့်ပါနှင့်၊ space မထည့်ပါ) —

```ini
GEMINI_API_KEY=AIzaSy................................
GEMINI_API_KEY_2=AIzaSy................................   # မဖြစ်မနေ မဟုတ် (quota ဖြည့်)
GEMINI_API_KEY_3=AIzaSy................................   # မဖြစ်မနေ မဟုတ် (အပို)
RECAP_API_KEY_FAILOVER=1                                  # quota/error တက်လျှင် အလိုအလျောက် ပြောင်း
RECAP_ACCESS_PASSWORD=သင့်လျှို့ဝှက်စာ                   # public URL အတွက် (အကြံပြု)
```

* **Key #1 quota ပြည့်လျှင် Key #2 → Key #3 သို့ အလိုအလျောက် ပြောင်းပေးမည်** — ဗီဒီယို အလယ်မှာ ရပ်မသွားတော့ပါ။
* `Ctrl+O` → `Enter` (သိမ်း) → `Ctrl+X` (ထွက်)။
* Key များကို browser Settings (⚙️) ထဲကလည်း ထည့်နိုင်သည် — server ပေါ် `.env` က ပိုစိတ်ချရသည်။

ပြီးလျှင် service ကို ပြန်စပါ:

```bash
sudo systemctl restart recap-studio
sudo systemctl status recap-studio --no-pager   # active (running) ဖြစ်ရမည်
curl -s http://localhost/healthz                # {"status":"ok", ...} ပြန်ရမည်
```

---

## 6️⃣ Browser မှ ဖွင့်စမ်းခြင်း

1. Browser တွင် ဖွင့်ပါ: `http://<EC2-Public-IPv4>` (ဥပမာ `http://13.212.45.67`)
2. အပေါ်ညာဘက် chip တွင် **⚙️ FFmpeg Ready / 🔤 Myanmar Font OK / 💾 x GB free / 🔑 Key n/3** ပေါ်ရမည်။
3. **Ctrl + Shift + R** (hard refresh) နှိပ်ပါ — version အဟောင်း cache မနေစေရန်။
4. Settings (⚙️) → Key များ ထည့် → **🧪 Key အားလုံး စစ်မည်** → ✅ ဖြစ်ရမည်။
5. ဗီဒီယိုတစ်ခု တင် → **⚡ ONE-CLICK RECAP + DUBBING** → Job Progress ကို ကြည့်ပါ။

### Deploy တကယ် ရောက်/မရောက် အပြင်မှ စစ်ရန် (laptop မှ)

```bash
curl -s http://13.212.45.67/healthz            # version ကို စစ်ပါ (4.1.0 ဖြစ်ရမည်)
python tests/verify_deployment.py http://13.212.45.67
# access password ထည့်ထားလျှင်:
python tests/verify_deployment.py http://13.212.45.67 --password သင့်လျှို့ဝှက်စာ
```

---

## 🔁 နောက်တစ်ခါ Update လုပ်ရန် (အတိုဆုံး)

```bash
# server terminal ထဲ
cd /tmp
curl -fsSL -o recap.tar.gz \
  https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a1027a-recap-studio-mm
rm -rf recap_studio_mm-arena-* && tar xzf recap.tar.gz
sudo bash /tmp/recap_studio_mm-arena-01a1027a-recap-studio-mm/deploy/ec2_install.sh
```

Installer ကိုပဲ ပြန် run လုပ်ခြင်းဖြင့် — code အသစ်၊ package အသစ်၊ service restart အားလုံး ဖြစ်သွားမည်။
**`.env` နှင့် `data/` (job မှတ်တမ်း၊ ဖိုင်များ) မပျောက်ပါ။**

---

## 🧯 ပြဿနာ တက်လာလျှင် (Troubleshooting)

| လက္ခဏာ | စစ်ရမည့်အချက် | ဖြေရှင်းနည်း |
|---|---|---|
| Browser တွင် ချိတ်မရ / timeout | Security Group 80 ဖွင့်ထားလား | အဆင့် 2 အတိုင်း HTTP rule ထည့်ပါ |
| Terminal မရ / SSH timeout | Security Group 22 ဖွင့်ထားလား | SSH rule ထည့်ပါ (Source: My IP) |
| `502` / empty page | service run နေလား | `sudo systemctl status recap-studio` → `sudo journalctl -u recap-studio -n 60 --no-pager` |
| "Engine စစ်ဆေးနေသည်…" မှာ ရပ်နေ | version အဟောင်း cache | `Ctrl+Shift+R`; `curl -s http://IP/api/system \| head -c 200` |
| API Key မထည့်ရသေးပါ error | key ထည့်ပြီးလား | `.env` ပြင် → `sudo systemctl restart recap-studio` |
| Quota error အလယ်မှာ ရပ် | Key #2/#3 မထည့်ရသေး | `.env` တွင် `GEMINI_API_KEY_2/3` ထည့် → restart |
| Render နှေး / ရပ်နေ | RAM/CPU မလုံလောက် | t3.medium (သို့) ↑; `.env` တွင် `RECAP_MAX_CONCURRENT_JOBS=1` |
| Disk ပြည့် | `df -h` | `sudo journalctl --vacuum-time=3d`; data TTL လျှော့ (`RECAP_WORKSPACE_TTL_HOURS=6`) |
| ffmpeg မတွေ့ | `ffmpeg -version` | `sudo apt install -y ffmpeg` |
| Font မလှ | `ls /usr/share/fonts/truetype/noto \| grep Myanmar` | `sudo apt install -y fonts-noto-core fonts-sil-padauk` |
| Update ရောက်/မရောက် မသိ | `curl -s http://localhost/healthz` | version နှိုင်းယှဉ်ပါ (4.1.0) |

Log ကြည့်ရန် အတိုဆုံး command များ —

```bash
sudo journalctl -u recap-studio -f              # live log
sudo journalctl -u recap-studio -n 100 --no-pager
sudo tail -50 /opt/recap-studio/data/*.log 2>/dev/null
```

---

## 🎁 အကြံပြုချက်များ (ပိုကောင်းလာစေရန်)

1. **HTTPS တပ်ပါ** (ဗီဒီယိုတင်/clipboard အလုပ်လုပ်ရန် လိုအပ်လာတတ်သည်) —
   ```bash
   sudo apt install -y nginx certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com      # domain ရှိရန် လိုသည် (Route 53 / Namecheap)
   ```
2. **Elastic IP** ချိတ်ပါ — IP မပြောင်းတော့ပါ။
3. **Backup** — တစ်ပတ်တစ်ခါ `sudo tar czf ~/recap-backup-$(date +%F).tgz -C /opt/recap-studio data .env` လုပ်ပြီး `scp` ဖြင့် ဆွဲထုတ်ပါ။
4. **CloudWatch alarm** — CPU 80% အပေါ်၊ free disk 2 GB အောက် ဖြစ်လျှင် email ရစေရန်။
5. **ငွေ ချွေတာရန်** — အသုံးမလုပ်သည့်အခါ instance ကို **Stop** လုပ်ပါ (data မပျောက်; Public IP ပြောင်းနိုင် → Elastic IP ချိတ်ထားပါ)။
6. **နောက် upgrade** တွင် t3.large (2 vCPU / 8 GB) သို့ ပြောင်းလျှင် ဗီဒီယိုရှည်ကြီးများ ပိုလျင်မြန်မည်။

---

## 📌 မှတ်သားရန် — ဤ version (4.1) ၏ အဓိက ပြောင်းလဲမှုများ

* Refresh လုပ်လျှင် **"Engine စစ်ဆေးနေသည်…"** တွင် ရပ်မနေတော့ပါ (UI က catalog ကို ချက်ချင်း ဆွဲပြသည်)၊ server မရလျှင် banner ဖြင့် ပြန် ကြိုးစားပေးသည်။
* **API Key ၃ ခု** + **ဒီ browser တွင် မှတ်ထားမည်** → refresh လုပ်တိုင်း key ပြန်ထည့်ရန် မလိုတော့ပါ။
* အသံကို **ဗီဒီယို အစအဆုံး** ဖုံးအောင်သွင်းသည် (လစ်လပ်နေသည့် အပိုင်းများကို AI မှ ပြန်ဖြည့် + နောက်ဆုံး silence ကို ပြန်ပြင်သည်)။
* **Shorts Splitter** — ဖိုင်တင်ခြင်း၊ progress၊ background job နှင့် **⏹ ရပ်မည်** အပြည့်အစုံ။
* Job Progress ကို **ရပ်နိုင်သည်** (ffmpeg ကို ချက်ချင်း ရပ် — အလုပ်ပြီးသည်အထိ မစောင့်ရ)။
* Scrolling တွင် **Job Progress** ကို video preview က အုပ်တော့မည် မဟုတ်ပါ။
