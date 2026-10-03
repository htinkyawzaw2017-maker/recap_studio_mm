# AWS ပေါ်မှာ Fix ကို တင်နည်း (Update Runbook)

## 0. ဘာကြောင့် AWS ပေါ်မှာ မပြောင်းသေးတာလဲ

ပြင်ထားတာက commit `7b1c264` — **branch `arena/01a10175-recap-studio-mm`** ပေါ်မှာ ရှိပါတယ်။
`main` က ဟောင်းနေဆဲ (`fd914bd`) ဖြစ်ပါတယ်။

```
origin/main                            fd914bd   ← AWS က ဒါကို build လုပ်နေတယ် (ဟောင်း)
origin/arena/01a10175-recap-studio-mm  7b1c264   ← fix အားလုံး (PR #1, still open)
```

ဒါကြောင့် **code ကို AWS ဆီ ရောက်အောင် ပို့ဖို့ လိုပါတယ်** — အောက်က လုပ်ရမည့်အဆင့် ၃ ခုပဲ ရှိပါတယ်။

---

## လုပ်ရမည့် အဆင့် ၃ ခု (TL;DR)

| # | လုပ်ရမည့်အရာ | ဘယ်မှာ |
|---|---|---|
| 1 | **PR #1 ကို merge** (သို့) branch/tarball ကို deploy target အဖြစ် သတ်မှတ် | GitHub |
| 2 | **Image ပြန် build + push** → service ကို force new deployment | AWS (ECR/ECS) |
| 3 | **Volume + env var စစ်** → `verify_deployment.py` ဖြင့် အတည်ပြု | AWS / laptop |

---

## 1. Code ကို deploy branch ဆီ ပို့ပါ

### နည်းလမ်း A — PR ကို merge (အကြံပြု၊ အလွယ်ဆုံး)

1. https://github.com/htinkyawzaw2017-maker/recap_studio_mm/pull/1 ကို ဖွင့်ပါ
2. **Merge pull request** → **Confirm merge**
3. `main` က `7b1c264` ဖြစ်သွားပါပြီ (Auto-deploy pipeline ရှိပါက အလိုအလျောက် deploy စပါပြီ)

### နည်းလမ်း B — merge မလုပ်ဘဲ branch ကို တိုက်ရိုက် deploy

```bash
# EC2 ကဲ့သို့ server ပေါ်မှာ
git fetch origin
git checkout arena/01a10175-recap-studio-mm     # ← fix ရှိသည့် branch
git pull origin arena/01a10175-recap-studio-mm
```

ECS/CodePipeline သုံးပါက source stage ၏ **branch name** ကို
`arena/01a10175-recap-studio-mm` သို့ ပြောင်းလိုက်ပါ။

### နည်းလမ်း C — git မသုံးဘဲ tarball ဖြင့်

```bash
# laptop ပေါ်တွင်
curl -L -o recap.tar.gz \
  https://github.com/htinkyawzaw2017-maker/recap_studio_mm/archive/refs/heads/arena/01a10175-recap-studio-mm.tar.gz

# server ပေါ်တွင်
scp recap.tar.gz ec2-user@YOUR_EC2:/tmp/
ssh ec2-user@YOUR_EC2
sudo mkdir -p /opt/recap && sudo tar xzf /tmp/recap.tar.gz -C /opt/recap --strip-components=1
```

---

## 2. Image ပြန် build လုပ်ပြီး deploy လုပ်ပါ

### 2a. ECS Fargate (+ ECR + ALB) — အသုံးအများဆုံး

```bash
export AWS_REGION=ap-southeast-1
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export REPO=recap-studio-mm

# ECR login
aws ecr get-login-password --region $AWS_REGION \
 | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

# build + push  (Apple Silicon ဖြစ်ပါက --platform linux/amd64 ထည့်ပါ / Graviton အတွက် linux/arm64)
docker build --platform linux/amd64 -t $REPO:4.0.0 .
docker tag $REPO:4.0.0 $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:4.0.0
docker tag $REPO:4.0.0 $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:4.0.0
docker push $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest

# service ကို image အသစ်ဖြင့် ပြန် deploy (task definition ကို register လုပ်ရန် မလိုအပ်ပါ)
aws ecs update-service \
  --cluster YOUR_CLUSTER --service YOUR_SERVICE \
  --force-new-deployment --region $AWS_REGION

# deploy ဖြစ်နေသည်ကို ကြည့်ရန်
aws ecs wait services-stable --cluster YOUR_CLUSTER --services YOUR_SERVICE --region $AWS_REGION
```

> ⚠️ Container တွင် `latest` tag ကို cache လုပ်ထားတတ်သည်။ `--force-new-deployment`
> မလုပ်ပါက task အဟောင်း ဆက်ပြေးနေနိုင်သည်။ တိကျစေရန် tag ကို version နှင့် ပေးပါ (ဥပမာ `4.0.0`)။

### 2b. EC2 + Docker / docker-compose

```bash
ssh ec2-user@YOUR_EC2
cd /opt/recap                                  # repo ရှိသည့်နေရာ
git fetch origin && git checkout arena/01a10175-recap-studio-mm && git pull

docker compose down
docker compose up -d --build
docker compose logs -f --tail=50               # 'Recap Studio 4.0.0 starting' ကို တွေ့ရမည်
```

### 2c. EC2 bare-metal (Docker မသုံး၊ systemd + uvicorn)

```bash
ssh ec2-user@YOUR_EC2
cd /opt/recap && git fetch origin && git checkout arena/01a10175-recap-studio-mm && git pull

source .venv/bin/activate
pip install -r requirements.txt                # ← ယခုမှ အလုပ်လုပ်ပါသည် (အရင် apt package များ ကြောင့် fail ဖြစ်ခဲ့သည်)
deactivate

sudo systemctl restart recap-studio            # unit ဖိုင်က ExecStart=.../uvicorn app:app ... ဖြစ်ရမည်
sudo systemctl status recap-studio --no-pager
```

> systemd unit မရှိသေးပါက `docs/AWS_DEPLOY.md` ထဲက command အတိုင်း
> `uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'`
> ဖြင့် run ပါ။ **App ၀ ကို `0.0.0.0` ပေါ်မှာ bind လုပ်ရပါမည်** (ALB က 127.0.0.1 ကို မမြင်ပါ)။

### 2d. App Runner / Lightsail container

* App Runner: **Edit service → Deployment trigger → Deploy** (image tag အသစ် push ပြီးပါက Auto)
* Lightsail Containers: `aws lightsail create-container-service-deployment ...` ဖြင့်
  image အသစ်ကို deploy

---

## 3. Storage နှင့် Environment စစ်ဆေးပါ (အရေးကြီး)

### 3a. Persistent volume — မရှိပါက render တိုင်း ပျောက်မည်

App က `RECAP_DATA_DIR` အောက်တွင် uploads/renders များကို သိမ်းပါသည်။ Container သည်
ephemeral ဖြစ်သဖြင့် **EFS (သို့) EBS ကို mount လုပ်ရပါမည်**။

```bash
# EFS ဖြစ်ပါက access point ကို UID 10001 ဖြင့် ဖန်တီးပါ (container က appuser=10001)
aws efs create-access-point --file-system-id fs-XXXX \
  --posix-user Uid=10001,Gid=10001 \
  --root-directory '{"Path":"/data","CreationInfo":{"OwnerUid":10001,"OwnerGid":10001,"Permissions":"0755"}}'
```

Task definition ၏ volume ကို:

```json
"volumes": [{
  "name": "recap-data",
  "efsVolumeConfiguration": {
    "fileSystemId": "fs-XXXX",
    "transitEncryption": "ENABLED",
    "authorizationConfig": { "accessPointId": "fsap-XXXX", "iam": "ENABLED" }
  }
}],
"containerDefinitions": [{
  "mountPoints": [{ "sourceVolume": "recap-data", "containerPath": "/data" }],
  ...
}]
```

EC2 + EBS ဖြစ်ပါက **ownership** ကို သတိထားပါ (container က UID 10001):

```bash
sudo mkfs.ext4 /dev/nvme1n1 && sudo mount /dev/nvme1n1 /data
sudo chown -R 10001:10001 /data          # ← ဤအဆင့် မလုပ်ပါက "Permission denied" ဖြစ်မည်
echo '/dev/nvme1n1 /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

### 3b. Environment variables

| Variable | တန်ဖိုး | မှတ်ချက် |
|---|---|---|
| `RECAP_DATA_DIR` | `/data` | mount လုပ်ထားသည့် volume |
| `GEMINI_API_KEY` | `AIza...` | Secrets Manager မှ ယူပါ |
| `RECAP_DEMO_MODE` | `0` | **1 ဖြစ်နေပါက AI မဟုတ်ဘဲ demo စာသား ထွက်မည်** |
| `RECAP_FAKE_TTS` | `0` | 1 ဖြစ်နေပါက အသံအစား beep ထွက်မည် |
| `RECAP_ACCESS_PASSWORD` | လျှို့ဝှက်စာ | public URL အတွက် လိုအပ်သည် (SPA Settings တွင် ထည့်ရမည်) |
| `RECAP_MAX_CONCURRENT_JOBS` | `1` (2 vCPU) / `2` (4 vCPU) | memory/CPU ကို ကာကွယ်ရန် |
| `RECAP_TTS_WORKERS` | `8` | အသံသွင်း အမြန်နှုန်း |
| `PORT` | `8000` | ALB target group နှင့် တူရမည် |

အရင် deployment မှာ `RECAP_DEMO_MODE=1` (သို့) `RECAP_FAKE_TTS=1` ကျန်နေခဲ့ပါက
အသံအစစ် မထွက်ပါ — စစ်ပါ။

### 3c. Task size

| | အနည်းဆုံး | အကြံပြု |
|---|---|---|
| CPU / RAM | 2 vCPU / 4 GB | **4 vCPU / 8 GB** |
| Scratch disk | 20 GB | 50 GB |

OOM ဖြစ်ပါက x264 encode က task ကို သတ်ပစ်နိုင်သည် (log တွင် `Killed` / exit code 137)။

### 3d. ALB health check

Target group → Health check path ကို **`/healthz`** သို့ ပြောင်း (**`/`** မဟုတ်)၊
interval 30s, timeout 5s, success 200။ ALB idle timeout ကို **300s** ထားပါ။

---

## 4. Verify — deploy တကယ် ရောက်/မရောက် စစ်ပါ

```bash
# repo ထဲက script ကို သင့် domain နှင့် run ပါ (dependencies မလိုပါ)
python tests/verify_deployment.py https://your-alb-domain.com
# access password သတ်မှတ်ထားပါက:
python tests/verify_deployment.py https://your-alb-domain.com --access-key 'YOUR-SECRET'
# တကယ့် job တစ်ခုအထိ စမ်းရန်:
python tests/verify_deployment.py https://your-alb-domain.com --video ./sample.mp4
```

မျှော်မှန်းရလဒ်:

```
[PASS] server reports v4+ (new build) — version=4.0.0
[PASS] Myanmar font available on server — /app/assets/fonts/NotoSansMyanmar-Regular.ttf
[PASS] resumable upload API exists — HTTP 200
[PASS] job completed — 42 lines, coverage 98.4%, 12.3MB
...
25/25 checks passed
✔ Deployment is running the fixed build and is healthy.
```

script က FAIL ဖြစ်ပါက ဘယ်အဆင့်မှာ ရပ်နေသည်ကို တိုက်ရိုက် ပြပါမည်။
ဥပမာ `server reports v4+` FAIL ဖြစ်ပါက → **image အသစ် အမှန် deploy မဖြစ်သေးပါ**၊
`/api/upload/init` က 404 ပြနေပါက → **အရင် build အဟောင်း ဆက်ပြေးနေသည်**။

---

## 5. Deploy ပြီးနောက် လက်တွေ့စစ်ရန် (browser)

1. `https://your-domain/` → UI အသစ် (dark glass, tab ၆ ခု: Studio / Timeline / Thumbnail / Splitter / Jobs / Settings)
   * UI အဟောင်း (neon Tailwind၊ badge `ZERO-DRIFT SYNC`) ပေါ်နေပါက **cache အဟောင်း** ဖြစ်သည် —
     `Ctrl+Shift+R` နှိပ်ပါ (ALB/CloudFront cache ရှိပါက invalidate လုပ်ပါ)
2. **⚙️ Settings** → Gemini API Key ထည့် → `💾` (server ပေါ်တွင် `GEMINI_API_KEY` ရှိပြီးသားဆိုပါက ဤအဆင့် မလိုပါ)
3. **Settings → 🩺 System Diagnostics** တွင် FFmpeg ✅ / Myanmar Font ✅ / Free disk ကို စစ်ပါ
4. ဗီဒီယိုတစ်ခု တင် → **⚡ ONE-CLICK** → job panel တွင် အဆင့် ၈ ဆင့် နှင့် % ကို တိုက်ရိုက် ကြည့်နိုင်သည်

---

## 6. ပြဿနာ တက်လာပါက

| လက္ခဏာ | အကြောင်းရင်း / ဖြေရှင်းချက် |
|---|---|
| UI အဟောင်း ပေါ်နေသည် | Browser/CloudFront cache → `Ctrl+Shift+R`, CloudFront invalidation, သို့မဟုတ် image အသစ် deploy မဖြစ်သေး |
| `verify` တွင် v4 FAIL | `aws ecs update-service --force-new-deployment` ပြန်လုပ်ပါ၊ image tag အသစ် push ဖြစ်သည်ကို စစ်ပါ |
| Container `unhealthy` | `/healthz` ကို ALB health check path မှာ ထည့်ထားပါ; `PORT=8000` ဖြစ်စေ |
| Permission denied `/data` | `chown -R 10001:10001 /data` (container user = UID 10001) |
| `လုံလောက်သော disk space မရှိပါ` | EBS/EFS size တိုးပါ (သို့) `RECAP_MIN_FREE_DISK_BYTES` ကို လျှော့ပါ |
| Render ရပ်သွားပြီး exit 137 | memory မလုံလောက် → task ကို 4 vCPU / 8 GB သို့ တင်ပါ |
| အသံ မထွက် / beep ထွက် | `RECAP_FAKE_TTS=0` ဖြစ်စေ (demo mode မှာ beep ထွက်သည်) |
| AI မဟုတ်ဘဲ demo စာသား | `RECAP_DEMO_MODE=0` ဖြစ်စေ + `GEMINI_API_KEY` ထည့်ပါ |
| 401 Unauthorized | `RECAP_ACCESS_PASSWORD` သတ်မှတ်ထားသည် → SPA ၏ Settings တွင် Access Key ထည့်ပါ |
| အသံသွင်း အားလုံး fail | Task ၏ outbound HTTPS ကို `speech.platform.bing.com` သို့ ခွင့်ပြုပါ (private subnet ဖြစ်ပါက NAT/VPC endpoint) |
| YouTube import fail (bot check) | cookies ဖိုင် ထည့်ပြီး `RECAP_YTDLP_COOKIES=/data/cookies.txt` သတ်မှတ်ပါ |

---

## 7. Rollback (ပြဿနာတက်ပါက အမြန် ပြန်လှည့်ရန်)

```bash
# ECS: image tag အဟောင်းကို ပြန်ညွှန်းပါ
aws ecs update-service --cluster YOUR_CLUSTER --service YOUR_SERVICE \
  --task-definition YOUR_TASK_DEF_FAMILY:OLD_REVISION --region $AWS_REGION

# EC2 + docker compose
cd /opt/recap && git checkout main && docker compose up -d --build
```

App ၏ runtime data (uploads/renders) က `/data` volume ပေါ်တွင် ရှိသဖြင့်
image ပြန်လှည့်ခြင်းက data ကို မထိခိုက်ပါ။

---

## 8. နောက်ဆက်တွဲ (optional အကောင်းများ)

* **CI/CD**: GitHub Actions ဖြင့် `main` push တိုင်း ECR push + `update-service` လုပ်ပါ
  (PR #1 တွင် လိုအပ်သော IAM permission များ — `ecr:*` push, `ecs:UpdateService` — လိုအပ်သည်)
* **CloudWatch**: log group `/ecs/recap-studio` မှ `ERROR` filter ဖြင့် alarm ဖွင့်ပါ;
  metric `ECSServiceAverageCPUUtilization` ကို 65% မှာ target tracking scaling လုပ်ပါ
* **CloudFront + S3**: master ဖိုင်များကို S3 သို့ sync လုပ်ပြီး CloudFront မှ serve လုပ်ပါ
  (`docs/AWS_DEPLOY.md` §6)
