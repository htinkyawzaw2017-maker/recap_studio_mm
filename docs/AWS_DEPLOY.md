# AWS Deployment Guide — Recap Studio MM

This app is a **stateful, CPU-heavy FastAPI service** (ffmpeg renders). The
recommended AWS setup is **ECS Fargate + ALB + EFS**, with S3 optional for
long-term asset storage. Everything below is copy-paste ready.

---

## 0. What the container needs

| Requirement | Value | Why |
|---|---|---|
| Port | `8000` (env `PORT`) | must bind `0.0.0.0` |
| Health check | `GET /healthz` | ALB target group |
| CPU / RAM | **2 vCPU / 4 GB** minimum (4 vCPU / 8 GB recommended) | x264 encode + parallel TTS |
| Scratch disk | **≥ 20 GB** (`RECAP_DATA_DIR`) | uploads, WAV segments, renders |
| Outbound HTTPS | `generativelanguage.googleapis.com`, `speech.platform.bing.com`, `www.youtube.com` | Gemini, Edge TTS, yt-dlp |

> Fargate tasks are ephemeral: mount **EFS at `/data`** (or S3, see §6) or the
> uploads/renders disappear when the task restarts.

---

## 1. Build & push the image (ECR)

```bash
export AWS_REGION=ap-southeast-1            # Singapore = lowest latency for MM
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REPO=recap-studio-mm

aws ecr create-repository --repository-name $REPO --region $AWS_REGION || true
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $REPO:latest .
docker tag $REPO:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest
```

For Apple Silicon / Graviton build with `--platform linux/arm64` (Fargate
supports ARM and it is ~20 % cheaper).

---

## 2. Persistent storage (EFS)

```bash
aws efs create-file-system --creation-token recap-studio --region $AWS_REGION
# create mount targets in each subnet of your VPC, then:
aws efs create-access-point \
  --file-system-id fs-XXXXXXXX \
  --posix-user Uid=10001,Gid=10001 \
  --root-directory '{"Path":"/data","CreationInfo":{"OwnerUid":10001,"OwnerGid":10001,"Permissions":"0755"}}'
```

Task definition volume:

```json
"volumes": [{
  "name": "recap-data",
  "efsVolumeConfiguration": {
    "fileSystemId": "fs-XXXXXXXX",
    "transitEncryption": "ENABLED",
    "authorizationConfig": { "accessPointId": "fsap-XXXXXXXX", "iam": "ENABLED" }
  }
}]
```

---

## 3. Environment variables (task definition)

```json
"environment": [
  { "name": "RECAP_DATA_DIR",          "value": "/data" },
  { "name": "PORT",                    "value": "8000" },
  { "name": "RECAP_MAX_CONCURRENT_JOBS","value": "1" },
  { "name": "RECAP_TTS_WORKERS",       "value": "8" },
  { "name": "RECAP_ANALYZE_WORKERS",   "value": "2" },
  { "name": "RECAP_WORKSPACE_TTL_HOURS","value": "12" },
  { "name": "RECAP_OUTPUT_TTL_HOURS",  "value": "72" },
  { "name": "RECAP_ACCESS_PASSWORD",   "value": "change-me-please" },
  { "name": "RECAP_DEFAULT_MODEL",     "value": "gemini-2.5-flash" }
],
"secrets": [
  { "name": "GEMINI_API_KEY",
    "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:recap/gemini-AbCdEf" }
]
```

* `RECAP_ACCESS_PASSWORD` — the SPA asks for this once (Settings tab) and
  sends it as `X-Access-Key`. **Set it for any public endpoint**, otherwise
  anyone who finds the ALB can burn your Gemini quota.
* `RECAP_MAX_CONCURRENT_JOBS=1` on a 2 vCPU task keeps memory and CPU sane;
  raise it on bigger instances.
* YouTube import from a datacenter IP usually hits bot checks — provide
  cookies: put a Netscape cookie file on the EFS volume and set
  `RECAP_YTDLP_COOKIES=/data/cookies.txt` (or a proxy via `RECAP_YTDLP_PROXY`).

---

## 4. Load balancer

| Setting | Value |
|---|---|
| Target group | HTTP, port 8000, health check path `/healthz`, interval 30 s |
| Idle timeout | **300 s** (uploads + long polls) |
| Stickiness | off (stateless API, jobs live in `/data`) |
| Listener | HTTPS `443` with an ACM certificate, redirect 80 → 443 |

**Upload size:** the SPA uploads videos in **8 MB chunks**
(`RECAP_UPLOAD_CHUNK_BYTES`), so ALB/nginx body limits no longer matter.
You can still raise the limits for the compatible single-shot endpoint:

```bash
# nginx in front of the app (optional)
client_max_body_size 2g;
proxy_read_timeout 600s;
proxy_request_buffering off;
```

---

## 5. Scaling notes

* The container is **CPU bound**; scale on `ECSServiceAverageCPUUtilization`
  (target 65 %) or on ALB request count.
* Long jobs run in a background thread inside the task. If the task is
  killed mid-render the job is marked `failed` on restart (the store
  persists to `/data/workspace/tasks`), so users see a clear message
  instead of a stuck bar.
* For very heavy traffic, run **two services**: an API/UI service and a
  worker service (same image, `RECAP_MAX_CONCURRENT_JOBS=1`, no ALB), and
  point the API at a queue later — the pipeline code is already isolated in
  `recapstudio/pipeline.py`.

---

## 6. Optional: keep masters in S3 / CloudFront

Renders live in `${RECAP_DATA_DIR}/output` and are served by
`GET /api/download/{file}`. To serve them from CloudFront:

```bash
# 1. sync finished masters (write a tiny cron or a lifecycle Lambda)
aws s3 sync /data/output s3://recap-studio-output/ --exclude "*" --include "*.mp4"

# 2. serve the bucket through CloudFront, allow the app origin
RECAP_ALLOWED_ORIGINS=https://studio.example.com,https://d111111abcdef8.cloudfront.net
```

Signed URLs / private buckets: keep `/api/download/...` (it already
supports HTTP Range, so players can seek) and let CloudFront cache it with
the `Cache-Control` header the app sends.

---

## 7. Cost sketch (ap-southeast-1, on-demand)

| Component | Sizing | ≈ / month |
|---|---|---|
| Fargate | 2 vCPU / 4 GB, 8 h/day | $35 |
| EFS | 20 GB standard | $6 |
| ALB | 1 LCU avg | $20 |
| ECR | 2 GB images | $0.2 |
| Gemini | 200 recaps × 10 min video | usage based |
| **Total** | | **≈ $60 + AI usage** |

Stop the service (`aws ecs update-service --desired-count 0`) when unused.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `/healthz` returns `degraded` | ffmpeg missing → rebuild image (Dockerfile installs it) |
| "လုံလောက်သော disk space မရှိပါ" | EFS/EBS too small or `RECAP_MIN_FREE_DISK_BYTES` too high |
| Render stuck at 0 % | check task CPU (2 vCPU min) and `docker stats` locally |
| Myanmar subtitles show boxes | bundled font missing → keep `assets/fonts/*.ttf` in the image |
| Upload fails at ~8 MB | proxy/ALB body limit → chunks are 8 MB, raise limits or lower `RECAP_UPLOAD_CHUNK_BYTES` |
| YouTube import fails (bot check) | add cookies file + `RECAP_YTDLP_COOKIES` |
| 401 everywhere | `RECAP_ACCESS_PASSWORD` is set — enter it in Settings tab |
