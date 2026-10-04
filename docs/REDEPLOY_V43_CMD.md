# v4.3.0 ကို အစအဆုံး ပြန်တင်နည်း — Windows CMD → AWS EC2 (Step by Step)

> **တင်မည့် commit** — `5de0263` · `feat(ui): v4.3 — WYSIWYG preview, all-device layout, Splitter → Studio`
> **branch** — `arena/01a105ed-recap-studio-mm` · **version** — `4.3.0`
> ဤစာရွက်ထဲက command အားလုံးကို **copy → paste** လုပ်ရုံပါပဲ။
> `<EC2-IP>` နေရာတွင် မိမိ server ၏ **Public IPv4** (ဥပမာ `13.212.45.67`) ထည့်ပါ။

---

## 📋 အကျဉ်းချုပ် — အဆင့် ၅ ဆင့်

| # | ဘယ်မှာ လုပ်မလဲ | ဘာလုပ်မလဲ | ကြာချိန် |
|---|---|---|---|
| 0 | **AWS Console** | *(EC2 မရှိသေးလျှင်သာ)* instance အသစ် ဆောက် | ၅ မိနစ် |
| 1 | **Windows CMD** | server ထဲ SSH ဝင် | ၂ မိနစ် |
| 2 | **Server (Ubuntu)** | code အသစ် ဆွဲ + installer run | ၄ မိနစ် |
| 3 | **Server** | admin အကောင့် + API key | ၂ မိနစ် |
| 4 | **Server / CMD** | version + markup စစ် | ၁ မိနစ် |
| 5 | **Browser** | hard refresh (Ctrl+Shift+R) | ၁၀ စက္ကန့် |
| 6 | **AWS Console / CMD** | *(လိုလျှင်)* အဟောင်း instance ဖျက် + ကျန် resource ရှင်း | ၃ မိနစ် |

---

## 0️⃣ (EC2 မရှိသေးလျှင်) AWS Console မှာ server အသစ် ဆောက်ခြင်း

> EC2 ရှိပြီးသားဆိုလျှင် ဤအပိုင်းကို ကျော်၍ **§1** သို့ သွားပါ။

1. **Console ဖွင့်** → https://console.aws.amazon.com/ec2/ → ညာဘက်အပေါ်တွင်
   region ကို **Asia Pacific (Singapore) `ap-southeast-1`** ရွေးပါ (မြန်မာနှင့် အနီးဆုံး)
2. **Launch instance** နှိပ်ပါ
3. **Name** — `recap-studio`
4. **Application and OS Images** — **Ubuntu Server 24.04 LTS (64-bit x86)**
5. **Instance type** — **`t3.medium`** (2 vCPU / 4 GB) *အနည်းဆုံး*၊
   ဗီဒီယိုကြီး/မြန်ဆန်လိုလျှင် **`t3.large`** (2 vCPU / 8 GB) သို့ **`c5.xlarge`** (4 vCPU)
   > `t2.micro` (free tier) သည် ffmpeg render အတွက် **မလုံလောက်ပါ** — job က ကြာလွန်း/ရပ်သွားတတ်သည်
6. **Key pair** — `Create new key pair` → Name: `recap-key` → Type: **RSA** → Format: **.pem**
   → Create → ဖိုင်က `Downloads` ထဲ ကျလာမည် (**ဤဖိုင် ပျောက်လျှင် server ထဲ ပြန်ဝင်၍ မရတော့ပါ**)
7. **Network settings** → Edit → ✅ Allow SSH traffic from **My IP**
   · ✅ Allow HTTP traffic from the internet (port 80)
8. **Configure storage** — **30 GiB** gp3 (ဗီဒီယိုများ သိမ်းရန် — 8 GiB default က နည်းလွန်းသည်)
9. **Launch instance** → ၁ မိနစ်ခန့် စောင့် → **Public IPv4 address** ကို copy ယူပါ (= `<EC2-IP>`)

> 💡 IP မပြောင်းစေလိုလျှင် — EC2 → **Elastic IPs** → Allocate → Associate with instance။

---

## 1️⃣ Windows CMD ဖွင့်ပြီး EC2 ထဲ ဝင်ခြင်း

### 1.1 CMD ဖွင့်ရန်

```
Win + R  →  cmd  →  Enter
```

ssh ပါ/မပါ စစ်ပါ (Windows 10 build 1809 နောက်ပိုင်း အားလုံး ပါပြီးသား) —

```cmd
ssh -V
curl --version
```

> `ssh` မရှိလျှင် — **Settings → Apps → Optional features → Add a feature → OpenSSH Client** ထည့်ပါ။
> (သို့မဟုတ် key မလိုတဲ့ **EC2 Instance Connect** browser terminal ကို သုံးပါ → [EC2_INSTANCE_CONNECT.md](EC2_INSTANCE_CONNECT.md))

### 1.2 `.pem` key ကို နေရာချ + permission ပြင် (တစ်ကြိမ်သာ)

AWS မှ download လုပ်ထားသော key ဖိုင် (ဥပမာ `recap-key.pem`) သည် များသောအားဖြင့် `Downloads` ထဲ ရှိသည် —

```cmd
if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
move "%USERPROFILE%\Downloads\recap-key.pem" "%USERPROFILE%\.ssh\"
icacls "%USERPROFILE%\.ssh\recap-key.pem" /inheritance:r
icacls "%USERPROFILE%\.ssh\recap-key.pem" /grant:r "%USERNAME%":R
```

> ⚠️ `icacls` မလုပ်လျှင် `UNPROTECTED PRIVATE KEY FILE` error တက်ပြီး ssh ဝင်၍ မရပါ။

### 1.3 Server ထဲ ဝင်

```cmd
ssh -i "%USERPROFILE%\.ssh\recap-key.pem" ubuntu@<EC2-IP>
```

* Ubuntu AMI → user က `ubuntu`
* Amazon Linux AMI → user က `ec2-user`
* ပထမဆုံး အကြိမ် `Are you sure you want to continue connecting (yes/no)?` မေးလျှင် **`yes`** ရိုက်ပါ

ဝင်ပြီးလျှင် prompt က `ubuntu@ip-172-31-x-x:~$` ပုံစံ ဖြစ်သွားပါမည် — ဒီကစပြီး command တွေက **server ပေါ်မှာ** run သည်။

---

## 2️⃣ Code အသစ် (commit `5de0263`) ကို တင်ခြင်း

### 2A. ပုံမှန် နည်း — data/.env မပျက်ဘဲ အစအဆုံး ပြန်တင် *(အကြံပြုသည်)*

**တစ်ကြောင်းချင်း —**

```bash
cd /tmp
curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm
rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz
sudo bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh
```

**တစ်ကြောင်းတည်း (copy-paste တစ်ချက်) —**

```bash
cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm && rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz && sudo bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh
```

Installer က အလိုအလျောက် လုပ်ပေးသည် —

```
0/8 preflight            OS/user/port စစ်
1/8 အဟောင်း process ရပ်
2/8 ffmpeg · python3 · fonts (apt)
3/8 code download (branch @ v4.3.0)
4/8 /opt/recap-studio သို့ sync   ← data/ နှင့် .env ကို မထိ
5/8 .venv + pip install -r requirements.txt
6/8 .env (RECAP_SECRET_KEY အလိုအလျောက်)
6b/8 account DB migrate + admin အကောင့် (မရှိသေးလျှင် ဖန်တီး၍ password ပြ)
7/8 systemd service (recap-studio) enable + restart
8/8 health check + အကျဉ်းချုပ် ပြ
```

> ⏳ ပထမဆုံး အကြိမ်သာ ~၄ မိနစ် (apt + pip)၊ နောက်ပိုင်း update များက ~၁ မိနစ်။
> အဆုံးမှာ ပေါ်လာတဲ့ **username / password box** ကို ချက်ချင်း မှတ်ထားပါ။

### 2B. အကုန် ဖျက်ပြီး အသစ်စက်စက် ပြန်တင် *(server ရှုပ်နေလျှင်သာ)*

> ⚠️ data ဖျက်လျှင် **အကောင့်များ၊ API key၊ ထွက်ပြီးသား ဗီဒီယိုများ ပျောက်သွားမည်**။
> အောက်က backup ၂ ခု အရင် ယူပါ။

```bash
# (1) backup — အကောင့် DB + .env + outputs
sudo systemctl stop recap-studio
sudo tar czf /root/recap-backup-$(date +%F-%H%M).tgz -C /opt/recap-studio data .env
ls -lh /root/recap-backup-*.tgz          # backup ရှိ/မရှိ စစ်

# (2) အကုန် ဖျက်
sudo rm -rf /opt/recap-studio

# (3) အသစ် တင် (2A အဆင့်အတိုင်း)
cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm && rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz && sudo bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh
```

**Backup ပြန်ထည့်လိုလျှင် (optional) —**

```bash
sudo systemctl stop recap-studio
sudo tar xzf /root/recap-backup-XXXX.tgz -C /opt/recap-studio
sudo chown -R ubuntu:ubuntu /opt/recap-studio/data /opt/recap-studio/.env
sudo systemctl start recap-studio
```

---

## 3️⃣ admin အကောင့် + API key

### 3.1 admin အကောင့်

Installer က အကောင့် မရှိသေးလျှင် **အလိုအလျောက် ဖန်တီး၍ password ကို ပြပါသည်**။
ကိုယ်တိုင် ထပ်ဖန်တီး/ပြောင်းလိုလျှင် — အောက်က helper ကို တစ်ခါ paste လုပ်ပါ —

```bash
ua() { sudo -u ubuntu bash -c "set -a; . /opt/recap-studio/.env; set +a; cd /opt/recap-studio && .venv/bin/python -m recapstudio.useradmin $*"; }

ua status                      # အကောင့် ဘယ်နှစ်ခု ရှိလဲ
ua create myname --admin --random     # အသစ် (password ကျပန်း ထုတ်ပေး)
ua passwd myname               # password ပြောင်း
ua list                        # စာရင်း
```

> အကောင့် တစ်ခုမှ မရှိလျှင် site သည် **login မတောင်းဘဲ** ဖွင့်နေပါမည် (open mode)။
> ဖန်တီးပြီးလျှင် `sudo systemctl restart recap-studio` လုပ်ပါ။

### 3.2 Gemini API key

**နည်း ၁ (လွယ်) —** browser ထဲ login ဝင် → **⚙️ Settings → API Key** → paste → Save
**နည်း ၂ (server မှ) —**

```bash
sudo nano /opt/recap-studio/.env
#   GEMINI_API_KEY=AIzaSy....        ← ဤတစ်ကြောင်း ပြင်
#   Ctrl+O → Enter → Ctrl+X ဖြင့် save
sudo systemctl restart recap-studio
```

---

## 4️⃣ တကယ် ရောက်/မရောက် စစ်ခြင်း

### 4.1 Server ပေါ်မှာ (SSH ထဲမှ)

```bash
curl -s http://localhost/healthz                      # "version":"4.3.0" ဖြစ်ရမည်
curl -s http://localhost/api/auth/me                  # "mode":"users" ဖြစ်ရမည် (login စနစ် ဖွင့်ပြီ)
curl -s http://localhost/ | grep -c preview-frame     # 1 ဖြစ်ရမည် ← v4.3 markup
grep __version__ /opt/recap-studio/recapstudio/__init__.py        # 4.3.0
grep -c applyPreviewGeometry /opt/recap-studio/static/app.js      # 1 အထက် ဖြစ်ရမည်
sudo systemctl status recap-studio --no-pager | head -5           # active (running)
```

အားလုံး မှန်လျှင် — **commit `5de0263` ရောက်ပြီ**။

### 4.2 Windows CMD မှ (SSH မဝင်ဘဲ)

```cmd
curl -s http://<EC2-IP>/healthz
curl -s http://<EC2-IP>/healthz | findstr "4.3.0"
curl -s http://<EC2-IP>/ | findstr "preview-frame"
```

**အပြည့်အစုံ စစ်ချင်လျှင်** (PC တွင် Python ရှိလျှင်) —

```cmd
cd %USERPROFILE%\Downloads
curl -L -o recap.zip https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/zip/refs/heads/arena/01a105ed-recap-studio-mm
tar -xf recap.zip
cd recap_studio_mm-arena-01a105ed-recap-studio-mm
python tests\verify_deployment.py http://<EC2-IP>
```

→ **25/25 checks passed** + `v4.3 responsive preview UI served` PASS ဖြစ်ရမည်။

---

## 5️⃣ Browser — cache ရှင်း (မဖြစ်မနေ)

| Device | လုပ်ရန် |
|---|---|
| Windows Chrome / Edge | **Ctrl + Shift + R** (မရလျှင် Ctrl+Shift+Delete → *Cached images and files* → Clear) |
| Mac Chrome / Safari | **⌘ + Shift + R** |
| Android Chrome | ⋮ → History → Clear browsing data → Cached images and files |
| iPhone Safari | Settings → Safari → Clear History and Website Data |

ဖွင့်ပြီးလျှင် ခေါင်းစီးတွင် **`v4.3.0`** ပြရမည်။ `v4.2` / `v4.1` ပြနေလျှင် cache မရှင်းရသေးပါ
(အရင်က “ပြင်ပြီးသား ပြဿနာတွေ ပြန်တွေ့နေတယ်” ဆိုတာ ဒီအကြောင်းကြောင့် ဖြစ်သည်)။

**မြင်ရမည့် အသစ်များ** — preview box က ရွေးထားသော ဖော်မတ်အတိုင်း ပုံစံပြောင်း၊
ခေါင်းစီးတွင် `720×1280 · 9:16` chip၊ စာတန်းနေရာ render နှင့် တူ၊ ဖုန်းတွင် အောက်ခြေ
`⚡ One-Click Recap စမည်` bar၊ Splitter အပိုင်းတိုင်းတွင် `🎬 Studio သို့ ပို့မည်`။

---

## 6️⃣ အဟောင်း EC2 instance ကို ဖျက်နည်း (ပိုက်ဆံ မကုန်စေရန်)

> ⚠️ **Terminate = အပြီးဖျက်** — root EBS volume ပါ ပါသွားသဖြင့် အဲဒီ server ထဲက
> အကောင့် DB၊ API key၊ ထွက်ပြီးသား ဗီဒီယိုများ **ပြန်ရလို့ မရတော့ပါ**။
> လိုအပ်သော ဖိုင်များကို **§6.1 အရင် backup ယူပါ**။

### 6.1 အဟောင်း server မှ data ကို အသစ်သို့ ရွှေ့ခြင်း *(မလိုလျှင် ကျော်)*

```bash
# ── အဟောင်း server ထဲ ဝင်ပြီး (ssh) — backup တစ်ဖိုင် ထုတ်
sudo tar czf /home/ubuntu/recap-backup.tgz -C /opt/recap-studio data .env
sudo chown ubuntu:ubuntu /home/ubuntu/recap-backup.tgz
ls -lh /home/ubuntu/recap-backup.tgz
exit
```

```cmd
:: ── Windows CMD — အဟောင်းမှ PC သို့ ဆွဲချ → အသစ်သို့ တင်
scp -i "%USERPROFILE%\.ssh\recap-key.pem" ubuntu@<OLD-IP>:/home/ubuntu/recap-backup.tgz "%USERPROFILE%\Downloads\"
scp -i "%USERPROFILE%\.ssh\recap-key.pem" "%USERPROFILE%\Downloads\recap-backup.tgz" ubuntu@<NEW-IP>:/home/ubuntu/
```

```bash
# ── အသစ် server ထဲ ဝင်ပြီး — ပြန်ထည့်
sudo systemctl stop recap-studio
sudo tar xzf /home/ubuntu/recap-backup.tgz -C /opt/recap-studio
sudo chown -R ubuntu:ubuntu /opt/recap-studio/data /opt/recap-studio/.env
sudo systemctl start recap-studio
curl -s http://localhost/api/auth/me          # အကောင့်များ ပြန်ပါလာသလား
```

> 💡 `data` နှင့် `.env` ကို **အတူတူ** ပြန်ထည့်ရပါမည် — `.env` ထဲက `RECAP_SECRET_KEY`
> မတူလျှင် encrypt လုပ်ထားသော API key များ ပြန်ဖတ်၍ မရပါ။

### 6.2 AWS Console မှ ဖျက်နည်း (အလွယ်ဆုံး)

1. https://console.aws.amazon.com/ec2/ → **Instances**
2. ဘယ်ဟာက အဟောင်းလဲ သေချာစစ်ပါ — **Public IPv4** နှင့် **Launch time** ကြည့်ပါ
   (အသစ်ကို မဖျက်မိစေရန် — အသစ်၏ IP ကို အရင် မှတ်ထားပါ)
3. အဟောင်း instance ကို ☑ အမှန်ခြစ် → **Instance state ▾** → **Terminate (delete) instance**
4. `Terminate` ကို ပြန်နှိပ်၍ အတည်ပြု → state က `shutting-down` → `terminated` ဖြစ်သွားမည်
   (စာရင်းထဲ ၁ နာရီခန့် ကျန်နေမည် — ပိုက်ဆံ မကုန်တော့ပါ)

> **Stop vs Terminate** — `Stop` = ပိတ်ထားရုံ (data ကျန်၊ **EBS ခ ဆက်ကုန်**)၊
> `Terminate` = အပြီးဖျက် (data ပါ ပျောက်၊ ခ မကုန်တော့)။

### 6.3 ကျန်နေတတ်သော ပိုက်ဆံကုန်စရာများ ရှင်းခြင်း ⭐

Instance ဖျက်ပြီးရင်တောင် အောက်ပါတို့က **ဆက်ပြီး ပိုက်ဆံ ကုန်နေတတ်သည်** —

| ဘယ်မှာ | ဘာလုပ်ရမလဲ |
|---|---|
| EC2 → **Elastic IPs** | instance မရှိတော့သော IP = **နာရီခြင်း ကုန်သည်** → ရွေး → *Actions → Release Elastic IP address* |
| EC2 → **Volumes** | `Available` (မချိတ်ထားသော) volume → ရွေး → *Actions → Delete volume* |
| EC2 → **Snapshots** | မလိုတော့သော snapshot → Delete |
| ECS/ALB သုံးဖူးလျှင် | ECS service → tasks 0 → delete · **Load Balancer** → Delete (ALB က အကုန်ဆုံး) |
| ECR | မသုံးတော့သော image များ → Delete |

### 6.4 Windows CMD မှ ဖျက်ချင်လျှင် (AWS CLI)

```cmd
:: တစ်ကြိမ်သာ — CLI install ပြီး credentials ထည့်
winget install --id Amazon.AWSCLI -e
aws configure
::   AWS Access Key ID / Secret / region = ap-southeast-1 / output = json

:: instance စာရင်း (ID · Name · State · IP · Launch time)
aws ec2 describe-instances --query "Reservations[].Instances[].{ID:InstanceId,Name:Tags[?Key=='Name']|[0].Value,State:State.Name,IP:PublicIpAddress,Launched:LaunchTime}" --output table

:: ⚠️ ID သေချာစစ်ပြီးမှ — အဟောင်းကို terminate
aws ec2 terminate-instances --instance-ids i-0123456789abcdef0

:: ကျန် resource များ
aws ec2 describe-addresses --query "Addresses[].{IP:PublicIp,Alloc:AllocationId,Assoc:AssociationId}" --output table
aws ec2 release-address --allocation-id eipalloc-0123456789abcdef0
aws ec2 describe-volumes --filters Name=status,Values=available --query "Volumes[].{ID:VolumeId,GiB:Size,AZ:AvailabilityZone}" --output table
aws ec2 delete-volume --volume-id vol-0123456789abcdef0
```

### 6.5 ဖျက်ပြီးကြောင်း စစ်ဆေးခြင်း

```cmd
aws ec2 describe-instances --filters Name=instance-state-name,Values=running --query "Reservations[].Instances[].{ID:InstanceId,IP:PublicIpAddress}" --output table
curl -s -m 5 http://<OLD-IP>/healthz
```

→ ဒုတိယ command က **မတုံ့ပြန်တော့ရင်** (timeout) အဟောင်း ပိတ်သွားပြီ။
Billing → **Cost Explorer / Billing Dashboard** တွင် ၂၄ နာရီအတွင်း ကျသွားတာ မြင်ရမည်။

---

## 🧯 ပြဿနာ ဖြေရှင်းချက် (Troubleshooting)

| လက္ခဏာ | CMD / SSH မှာ စစ်ရန် | ဖြေရှင်းနည်း |
|---|---|---|
| `ssh: connect to host ... port 22: Connection timed out` | `curl -s -m 5 http://<EC2-IP>/healthz` | Security Group → Inbound rules → **SSH 22** (My IP) + **HTTP 80** (0.0.0.0/0) ဖွင့်ပါ |
| `UNPROTECTED PRIVATE KEY FILE` | — | §1.2 `icacls` ၂ ကြောင်း ပြန်လုပ်ပါ |
| site မဖွင့်နိုင် | `sudo systemctl status recap-studio --no-pager` | `sudo systemctl restart recap-studio` → မရလျှင် `sudo journalctl -u recap-studio -n 80 --no-pager` |
| version က `4.2.x` ပဲ ပြနေ | `grep __version__ /opt/recap-studio/recapstudio/__init__.py` | installer ပြန် run (§2A) → ပြီးမှ browser hard refresh |
| login စာမျက်နှာ မပေါ် | `curl -s http://localhost/api/auth/me` | `"mode":"open"` ဖြစ်နေလျှင် `ua create myname --admin --random` → restart |
| `port 80 address already in use` | `sudo ss -lptn 'sport = :80'` | အခြား nginx/apache ရပ်ပါ — `sudo systemctl stop nginx` |
| disk ပြည့် | `df -h /` | `sudo du -sh /opt/recap-studio/data/*` → outputs အဟောင်း ဖျက် |
| pip/apt error | — | `sudo apt-get update && sudo apt-get -f install` ပြီးမှ installer ပြန် run |

---

## 💻 (Optional) Windows PC ပေါ်မှာ local စမ်းချင်လျှင် — CMD

```cmd
:: 1) ffmpeg (winget ရှိလျှင်)
winget install --id Gyan.FFmpeg -e

:: 2) code
cd %USERPROFILE%\Documents
curl -L -o recap.zip https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/zip/refs/heads/arena/01a105ed-recap-studio-mm
tar -xf recap.zip
cd recap_studio_mm-arena-01a105ed-recap-studio-mm

:: 3) python venv + packages
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt

:: 4) run
.venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

ပြီးလျှင် browser တွင် `http://localhost:8000` ဖွင့်ပါ။
အကောင့်စနစ် စမ်းလိုလျှင် (CMD အသစ်တစ်ခုမှာ) —

```cmd
cd %USERPROFILE%\Documents\recap_studio_mm-arena-01a105ed-recap-studio-mm
.venv\Scripts\python -m recapstudio.useradmin create myname --admin --random
```

ရပ်ရန် — CMD ထဲတွင် **Ctrl + C**။

---

## 🔁 နောက်တစ်ခါ update လုပ်ရန်

အထက် §2A တစ်ကြောင်းတည်း command ကိုပဲ ပြန် run ပါ — idempotent ဖြစ်၍
data/.env မပျက်ဘဲ code သစ်ကိုသာ တင်ပေးပါသည်။

```bash
cd /tmp && curl -fsSL -o recap.tgz https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a105ed-recap-studio-mm && rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz && sudo bash /tmp/recap_studio_mm-arena-01a105ed-recap-studio-mm/deploy/ec2_install.sh && sudo systemctl restart recap-studio && curl -s http://localhost/healthz
```

ဆက်စပ်စာရွက်များ — [UI_V43.md](UI_V43.md) (v4.3 ဘာတွေ ပြောင်းသွားလဲ) ·
[AWS_UPDATE.md](AWS_UPDATE.md) (ECS/Docker လမ်းကြောင်း) ·
[EC2_INSTANCE_CONNECT.md](EC2_INSTANCE_CONNECT.md) (key မလိုဘဲ ဝင်နည်း) ·
[PHASE2_AUTH.md](PHASE2_AUTH.md) (အကောင့်စနစ်)
