#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Recap Studio MM — one-shot installer / updater for a plain Ubuntu EC2
#  (works with the browser based "EC2 Instance Connect" terminal, no key pair)
#
#  Run it as many times as you like: it is idempotent, keeps your data and
#  your API key, and simply updates the code + restarts the service.
#
#  Quick use:
#     sudo bash ec2_install.sh
#
#  Optional overrides (env vars):
#     RECAP_BRANCH=main                 # which git branch to install
#                                       (default: the Arena working branch; use
#                                        main once the update is merged)
#     RECAP_DIR=/opt/recap-studio       # where the app lives
#     RECAP_PORT=80                     # port to listen on
#     RECAP_USER=ubuntu                 # service user (created automatically if missing)
#     RECAP_SKIP_APT=1                  # do not touch apt (for non-Ubuntu hosts)
#     RECAP_SKIP_SERVICE=1              # do not create a systemd unit (prints tmux command)
#     RECAP_ALLOW_NONROOT=1             # allow running without root (testing only)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="${RECAP_REPO:-htinkyawzaw2017-maker/recap_studio_mm}"
BRANCH="${RECAP_BRANCH:-arena/01a105ed-recap-studio-mm}"
APP_DIR="${RECAP_DIR:-/opt/recap-studio}"
PORT="${RECAP_PORT:-80}"
SERVICE="${RECAP_SERVICE:-recap-studio}"
SKIP_APT="${RECAP_SKIP_APT:-0}"
SKIP_SERVICE="${RECAP_SKIP_SERVICE:-0}"
ALLOW_NONROOT="${RECAP_ALLOW_NONROOT:-0}"

C_OK=$'\033[92m'; C_WARN=$'\033[93m'; C_ERR=$'\033[91m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✔%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '%s⚠%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()  { printf '%s✖%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }
step() { printf '\n%s── %s ─────────────────────────────────────%s\n' "$C_DIM" "$*" "$C_OFF"; }

# ── 0. preflight ───────────────────────────────────────────────────────────
step "0/8 စစ်ဆေးခြင်း (preflight)"

if [ "$(id -u)" -ne 0 ]; then
  if [ "$ALLOW_NONROOT" = "1" ]; then
    warn "root မဟုတ်ဘဲ run နေသည် (RECAP_ALLOW_NONROOT=1) — sudo လိုအပ်သော အဆင့်များ ကျော်သွားမည်"
  else
    die "sudo ဖြင့် run ပါ:  sudo bash $0"
  fi
fi

if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  say "OS: ${PRETTY_NAME:-unknown}  (${ARCH:-$(uname -m)})"
else
  warn "/etc/os-release မတွေ့ပါ — Ubuntu မဟုတ်နိုင်ပါ (RECAP_SKIP_APT=1 ဖြင့် ဆက်နိုင်သည်)"
fi

SERVICE_USER="${RECAP_USER:-}"
if [ -z "$SERVICE_USER" ]; then
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    SERVICE_USER="$SUDO_USER"
  elif id ubuntu >/dev/null 2>&1; then
    SERVICE_USER="ubuntu"
  else
    SERVICE_USER="root"
  fi
fi
say "install dir : $APP_DIR"
say "port        : $PORT"
say "branch      : $BRANCH"
say "service user: $SERVICE_USER"

# ── 1. stop the old (tmux / nohup) instance ────────────────────────────────
step "1/8 အဟောင်း process ရပ်ခြင်း"

OLD_PIDS="$(pgrep -f "uvicorn app:app" || true)"
if [ -n "$OLD_PIDS" ]; then
  warn "အဟောင်း uvicorn process တွေ့သည် (PIDs: $(echo "$OLD_PIDS" | tr '\n' ' ')) — ရပ်လိုက်ပါမည်"
  # shellcheck disable=SC2086
  kill $OLD_PIDS 2>/dev/null || true
  sleep 2
  # shellcheck disable=SC2086
  kill -9 $OLD_PIDS 2>/dev/null || true
  ok "အဟောင်း process ရပ်ပြီ (tmux ထဲက ဖြစ်ခဲ့လျှင် tmux session ကို ဖျက်ရန် မလိုပါ)"
else
  say "run နေသော uvicorn process မရှိပါ"
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop "$SERVICE" 2>/dev/null || true
fi

# ── 2. system packages ─────────────────────────────────────────────────────
step "2/8 လိုအပ်သော software များ (ffmpeg, python, curl)"

if [ "$SKIP_APT" = "1" ]; then
  warn "RECAP_SKIP_APT=1 — apt အဆင့် ကျော်လိုက်သည်"
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ffmpeg curl ca-certificates python3 python3-venv python3-pip rsync \
    fonts-noto-core fonts-sil-padauk
  ok "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}') + python $(python3 -V | awk '{print $2}')"
fi

command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg မတွေ့ပါ — 'sudo apt install ffmpeg' လုပ်ပါ (rendering အတွက် မဖြစ်မနေ လိုသည်)"
command -v python3 >/dev/null 2>&1 || die "python3 မတွေ့ပါ"

# ── 3. download the application ────────────────────────────────────────────
step "3/8 Code ရယူခြင်း (${REPO} @ ${BRANCH})"

TMP_SRC="$(mktemp -d /tmp/recap-src.XXXXXX)"
trap 'rm -rf "$TMP_SRC"' EXIT

fetch_tarball() {
  local ref="$1"
  local url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${ref}"
  say "${C_DIM}⬇ ${url}${C_OFF}"
  curl -fsSL --retry 3 --retry-delay 2 --max-time 300 "$url" -o "$TMP_SRC/src.tar.gz"
}

if ! fetch_tarball "$BRANCH"; then
  warn "branch '${BRANCH}' ရယူ၍ မရပါ — 'main' ဖြင့် ပြန်စမ်းပါမည်"
  BRANCH="main"
  fetch_tarball "$BRANCH" || die "code download မအောင်မြင်ပါ (internet / repo permission စစ်ပါ)"
fi

tar xzf "$TMP_SRC/src.tar.gz" -C "$TMP_SRC"
SRC_DIR="$(find "$TMP_SRC" -maxdepth 1 -type d -name 'recap_studio_mm-*' | head -1)"
[ -n "$SRC_DIR" ] || die "extract လုပ်ထားသော folder ကို ရှာမတွေ့ပါ"
[ -f "$SRC_DIR/app.py" ] || die "app.py မတွေ့ပါ — download ပျက်နိုင်သည်"
ok "code ရယူပြီ: $(grep -m1 '__version__' "$SRC_DIR/recapstudio/__init__.py" 2>/dev/null || echo 'version ?')"

# ── 4. install into $APP_DIR (keep data / .env) ────────────────────────────
step "4/8 install လုပ်ခြင်း → $APP_DIR"

mkdir -p "$APP_DIR" "$APP_DIR/data"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude 'data/' --exclude '.env' --exclude '.venv/' --exclude '.git/' \
    --exclude '__pycache__/' --exclude '*.pyc' \
    "$SRC_DIR"/ "$APP_DIR"/
else
  find "$APP_DIR" -mindepth 1 -maxdepth 1 \
    ! -name data ! -name .env ! -name .venv ! -name .git -exec rm -rf {} +
  cp -a "$SRC_DIR"/. "$APP_DIR"/
fi
ok "code sync ပြီးပါပြီ (data folder နှင့် .env ကို မထိခိုက်ပါ)"

# ── 5. python environment ──────────────────────────────────────────────────
step "5/8 Python packages (venv)"

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv"
  ok "venv အသစ် ဖန်တီးပြီ"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "packages install ပြီ ($("$APP_DIR/.venv/bin/python" -c 'import fastapi,edge_tts,PIL;print("fastapi",fastapi.__version__)'))"

# ── 6. configuration (.env) + API key migration ────────────────────────────
step "6/8 ဖိုင် ပြင်ဆင်ခြင်း (.env)"

ENV_FILE="$APP_DIR/.env"

# session/secret key — အကောင့် login cookie နှင့် သိမ်းထားသော API key များ encrypt ရန်
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    "$APP_DIR/.venv/bin/python" -c "import secrets;print(secrets.token_hex(32))"
  fi
}

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# Recap Studio MM — server configuration (systemd EnvironmentFile format)
# ပြင်ပြီးတိုင်း:  sudo systemctl restart $SERVICE
RECAP_DATA_DIR=$APP_DIR/data
PORT=$PORT
RECAP_MAX_CONCURRENT_JOBS=1
RECAP_TTS_WORKERS=8
RECAP_WORKSPACE_TTL_HOURS=12
RECAP_OUTPUT_TTL_HOURS=72
RECAP_LOG_LEVEL=INFO
# production: demo ပိတ်ထားရမည် (1 ဖြစ်နေပါက AI/အသံ အစစ် မထွက်ပါ)
RECAP_DEMO_MODE=0
RECAP_FAKE_TTS=0
# public URL အတွက် လျှို့ဝှက်စာ (ထည့်လိုက်ပါ — SPA Settings တွင် ထည့်ရမည်)
RECAP_ACCESS_PASSWORD=
# https://aistudio.google.com/apikey မှ ရယူပါ
# Key ၃ ခုအထိ ထည့်နိုင်သည် — Key #1 quota ပြည့်လျှင် #2 / #3 သို့ အလိုအလျောက် ပြောင်းသည်
GEMINI_API_KEY=
GEMINI_API_KEY_2=
GEMINI_API_KEY_3=
# quota/error တက်လျှင် key အလိုအလျောက် ပြောင်းခြင်း (1=ဖွင့်)
RECAP_API_KEY_FAILOVER=1
# ffmpeg ပြတ်တောက်နေလျှင် အလိုအလျောက် ရပ်ပြီး error ပြရန် (စက္ကန့်)
RECAP_FFMPEG_STALL_SECONDS=900

# ── v4.2 — အကောင့်စနစ် (Phase 2 / security) ─────────────────────────────
# ⚠️ RECAP_SECRET_KEY ကို ဘယ်တော့မှ မပြောင်းပါနှင့် / မဖျက်ပါနှင့်
#    ပြောင်းလိုက်လျှင် login session အားလုံး ပြုတ်ပြီး သိမ်းထားသော API key များ ဖတ်မရတော့ပါ
RECAP_SECRET_KEY=$(gen_secret)
# auto = အကောင့်ရှိလျှင် အကောင့်စနစ်၊ မရှိလျှင် access key / ဖွင့်ထား
RECAP_AUTH_MODE=auto
# user များ ကိုယ်တိုင် အကောင့်ဖွင့်ခွင့် (1=ဖွင့်) — ဖွင့်ပါက invite code ထည့်ထားသင့်သည်
RECAP_ALLOW_SIGNUP=0
RECAP_SIGNUP_CODE=
# တစ်ယောက်ချင်းစီ ကန့်သတ်ချက် (0 = အကန့်အသတ်မရှိ)
RECAP_USER_MAX_CONCURRENT_JOBS=1
RECAP_USER_DAILY_JOBS=0
RECAP_USER_QUOTA_BYTES=0
# domain ကန့်သတ် (ဥပမာ: studio.example.com,13.212.45.67) — အလွတ် = အားလုံး
RECAP_TRUSTED_HOSTS=
RECAP_ALLOWED_ORIGINS=
EOF
  ok ".env အသစ် ဖန်တီးပြီ: $ENV_FILE"
else
  say ".env ရှိပြီးသား — မထိခိုက်ပါ"
fi

# upgrade path: v4.1 .env များတွင် RECAP_SECRET_KEY မပါသေး — တစ်ကြိမ်တည်း ဖြည့်ပေးသည်
if ! grep -q '^RECAP_SECRET_KEY=..*' "$ENV_FILE" 2>/dev/null; then
  sed -i '/^RECAP_SECRET_KEY=$/d' "$ENV_FILE" 2>/dev/null || true
  {
    echo ""
    echo "# ── v4.2 အကောင့်စနစ် (auto-added by installer) ─────────────────────"
    echo "# ⚠️ ဤ key ကို မပြောင်းပါနှင့် — ပြောင်းလျှင် session + သိမ်းထားသော API key များ ပျက်မည်"
    echo "RECAP_SECRET_KEY=$(gen_secret)"
    echo "RECAP_AUTH_MODE=auto"
    echo "RECAP_ALLOW_SIGNUP=0"
    echo "RECAP_SIGNUP_CODE="
    echo "RECAP_USER_MAX_CONCURRENT_JOBS=1"
    echo "RECAP_USER_DAILY_JOBS=0"
    echo "RECAP_USER_QUOTA_BYTES=0"
  } >> "$ENV_FILE"
  ok "RECAP_SECRET_KEY အသစ် ထုတ်ပြီး .env ထဲ ထည့်လိုက်ပါပြီ (အကောင့်စနစ် အတွက်)"
else
  say "RECAP_SECRET_KEY ရှိပြီးသား — မထိခိုက်ပါ"
fi

# migrate a Gemini key saved by the old single-file app
if ! grep -q '^GEMINI_API_KEY=..*' "$ENV_FILE" 2>/dev/null; then
  CANDIDATE="$(find /home /root /opt -maxdepth 3 -name '.recap_config.json' 2>/dev/null \
               | xargs -r ls -t 2>/dev/null | head -1 || true)"
  if [ -n "$CANDIDATE" ] && [ -f "$CANDIDATE" ]; then
    KEY="$("$APP_DIR/.venv/bin/python" - "$CANDIDATE" <<'PY' 2>/dev/null || true
import json, sys
try:
    print((json.load(open(sys.argv[1], encoding="utf-8")) or {}).get("gemini_api_key", ""))
except Exception:
    pass
PY
)"
    cp -f "$CANDIDATE" "$APP_DIR/data/.recap_config.json" 2>/dev/null || true
    if [ -n "$KEY" ]; then
      sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=$KEY|" "$ENV_FILE"
      ok "အဟောင်း config ထဲက Gemini API key ကို ရှာတွေ့၍ .env ထဲ ထည့်လိုက်ပါပြီ"
    else
      say "အဟောင်း config ကို $APP_DIR/data/ သို့ ကူးထားသည် (key အလွတ်ဖြစ်နေသည်)"
    fi
  fi
fi

if [ "$(id -u)" -eq 0 ]; then
  chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR" 2>/dev/null || true
  chmod 600 "$ENV_FILE" 2>/dev/null || true
fi

# ── 6b. account database (v4.2 auth) ───────────────────────────────────────
step "6b/8 အကောင့် database ပြင်ဆင်ခြင်း (v4.2)"

useradmin_cmd() {
  if [ "$(id -u)" -eq 0 ] && id "$SERVICE_USER" >/dev/null 2>&1; then
    su -s /bin/sh "$SERVICE_USER" -c \
      "cd '$APP_DIR' && set -a && . '$ENV_FILE' && set +a && '$APP_DIR/.venv/bin/python' -m recapstudio.useradmin $*"
  else
    ( cd "$APP_DIR" && set -a && . "$ENV_FILE" && set +a \
      && "$APP_DIR/.venv/bin/python" -m recapstudio.useradmin "$@" )
  fi
}

ACCOUNTS="?"
if useradmin_cmd migrate >/tmp/recap-useradmin.log 2>&1; then
  ok "database schema + API key များ migrate ပြီး (data/recap.db)"
  ACCOUNTS="$(useradmin_cmd status 2>/dev/null | sed -n 's/.*accounts *: *\([0-9]*\).*/\1/p' | head -1)"
  [ -z "$ACCOUNTS" ] && ACCOUNTS="?"
else
  warn "useradmin migrate မအောင်မြင်ပါ — log: /tmp/recap-useradmin.log"
  tail -5 /tmp/recap-useradmin.log 2>/dev/null || true
fi

# အကောင့် တစ်ခုမှ မရှိလျှင် admin အကောင့်ကို အလိုအလျောက် ဖန်တီးပေးသည်
# (ကျော်လိုလျှင် RECAP_SKIP_ADMIN=1 ၊ အမည်ပြောင်းလိုလျှင် RECAP_ADMIN_USER=myname)
ADMIN_CREATED=""
ADMIN_PASSWORD_SHOWN=""
ADMIN_USER="${RECAP_ADMIN_USER:-admin}"
AUTH_MODE_ENV="$(sed -n 's/^RECAP_AUTH_MODE=//p' "$ENV_FILE" 2>/dev/null | tail -1 | tr -d '"'"'"'"' )"
if [ "$ACCOUNTS" = "0" ] && [ "${RECAP_SKIP_ADMIN:-0}" != "1" ] \
   && [ "$AUTH_MODE_ENV" != "legacy" ] && [ "$AUTH_MODE_ENV" != "open" ]; then
  if [ -n "${RECAP_ADMIN_PASSWORD:-}" ]; then
    if useradmin_cmd create "$ADMIN_USER" --admin --password "$RECAP_ADMIN_PASSWORD" \
         >/tmp/recap-admin.log 2>&1; then
      ADMIN_CREATED="$ADMIN_USER"
      ok "admin အကောင့် '$ADMIN_USER' ဖန်တီးပြီး (သင်ပေးထားသော password)"
    else
      warn "admin အကောင့် ဖန်တီး၍ မရပါ:"; tail -5 /tmp/recap-admin.log 2>/dev/null || true
    fi
  elif useradmin_cmd create "$ADMIN_USER" --admin --random >/tmp/recap-admin.log 2>&1; then
    ADMIN_CREATED="$ADMIN_USER"
    ADMIN_PASSWORD_SHOWN="$(sed 's/\x1b\[[0-9;]*m//g' /tmp/recap-admin.log \
      | sed -n 's/.*စကားဝှက်[^:]*: *//p' | head -1)"
    ok "admin အကောင့် '$ADMIN_USER' ကို အလိုအလျောက် ဖန်တီးပြီးပါပြီ"
  else
    warn "admin အကောင့် ဖန်တီး၍ မရပါ:"; tail -5 /tmp/recap-admin.log 2>/dev/null || true
  fi
  ACCOUNTS="$(useradmin_cmd status 2>/dev/null | sed -n 's/.*accounts *: *\([0-9]*\).*/\1/p' | head -1)"
  [ -z "$ACCOUNTS" ] && ACCOUNTS="?"
fi

if [ "$ACCOUNTS" = "0" ]; then
  warn "အကောင့် တစ်ခုမှ မရှိသေးပါ — site က လက်ရှိတွင် ကာကွယ်မှု မရှိပါ (သို့) access key သာ သုံးနေသည်"
else
  say "အကောင့် အရေအတွက် : ${ACCOUNTS}"
fi

if [ "$(id -u)" -eq 0 ]; then
  chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/data" 2>/dev/null || true
fi

# ── 7. service ─────────────────────────────────────────────────────────────
step "7/8 24/7 run ဖြစ်စေရန် service တည်ဆောက်ခြင်း"

SUDO_PREFIX=""; [ "$(id -u)" -ne 0 ] && SUDO_PREFIX="sudo "
TMUX_HINT="cd $APP_DIR && ${SUDO_PREFIX}.venv/bin/uvicorn app:app --host 0.0.0.0 --port $PORT"

MANUAL_MODE=0
if [ "$SKIP_SERVICE" = "1" ] || ! command -v systemctl >/dev/null 2>&1; then
  MANUAL_MODE=1
  warn "systemd မရနိုင်ပါ (သို့) ကျော်လိုက်သည်။ ကိုယ်တိုင် run ရန်:"
  say ""
  say "    $TMUX_HINT"
  say ""
  say "  (tmux ဖြင့် ၂၄ နာရီ ထားလိုပါက:  tmux new -s recap  → အပေါ်က command → Ctrl+B ပြီး D)"
else
  UNIT="/etc/systemd/system/${SERVICE}.service"
  cat > "$UNIT" <<EOF
[Unit]
Description=Recap Studio MM (AI recap · dubbing · subtitles)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/uvicorn app:app --host 0.0.0.0 --port \${PORT} --proxy-headers --forwarded-allow-ips=* --timeout-keep-alive 30
Restart=always
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
TimeoutStopSec=20
KillMode=mixed
# ffmpeg အတွက် process/file limit များ
LimitNOFILE=65535
# security hardening
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1 || true
  systemctl restart "$SERVICE"
  sleep 6
  if systemctl is-active --quiet "$SERVICE"; then
    ok "service '$SERVICE' run နေပါပြီ (reboot ဖြစ်လည်း အလိုအလျောက် ပြန်တက်)"
  else
    warn "service စတင်၍ မရပါ — log ကို ကြည့်ပါ:  sudo journalctl -u $SERVICE -n 60 --no-pager"
  fi
fi

# ── 8. health check ────────────────────────────────────────────────────────
step "8/8 စမ်းသပ်ခြင်း (health check)"

HEALTH_URL="http://127.0.0.1:${PORT}/healthz"
RESPONSE=""
if [ "$MANUAL_MODE" = "0" ]; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    RESPONSE="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    [ -n "$RESPONSE" ] && break
    sleep 2
  done
  if [ -n "$RESPONSE" ]; then
    ok "server အောင်မြင်စွာ တက်နေပါပြီ"
    say "   ${RESPONSE}"
  else
    warn "health check မဖြေပါ — အောက်ပါ log ကို ကြည့်ပါ:"
    say "     sudo journalctl -u $SERVICE -n 60 --no-pager"
  fi
else
  # no service installed: boot the app briefly just to prove the install works
  say "install မှန်/မမှန် စမ်းရန် server ကို ခေတ္တ တင်ကြည့်ပါမည်…"
  ( cd "$APP_DIR" && PORT="$PORT" RECAP_DEMO_MODE=1 RECAP_FAKE_TTS=1 \
      setsid "$APP_DIR/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port "$PORT" \
      >/tmp/recap-pretest.log 2>&1 & echo $! > /tmp/recap-pretest.pid )
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    RESPONSE="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    [ -n "$RESPONSE" ] && break
    sleep 1
  done
  if [ -n "$RESPONSE" ]; then
    ok "app အောင်မြင်စွာ run နိုင်သည်"
    say "   ${RESPONSE}"
  else
    warn "app စတင်၍ မရပါ — log: /tmp/recap-pretest.log"
    tail -20 /tmp/recap-pretest.log 2>/dev/null || true
  fi
  if [ -f /tmp/recap-pretest.pid ]; then
    kill "$(cat /tmp/recap-pretest.pid)" 2>/dev/null || true
    rm -f /tmp/recap-pretest.pid
  fi
fi

PUBLIC_IP="$(curl -fsS --max-time 5 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"

say ""
say "════════════════════════════════════════════════════════════════"
say " 🎬  Recap Studio MM တပ်ဆင်ခြင်း ပြီးစီးပါပြီ"
say "════════════════════════════════════════════════════════════════"
if [ -n "$PUBLIC_IP" ]; then
  say " 🌐 ဖွင့်ရန်      : http://${PUBLIC_IP}${PORT:+:$PORT}"
else
  say " 🌐 ဖွင့်ရန်      : http://<EC2-Public-IPv4>${PORT:+:$PORT}"
fi
say " 📁 install dir  : $APP_DIR"
say " ⚙️  config file  : $ENV_FILE"
if [ "$MANUAL_MODE" = "1" ]; then
  say " ▶️  run ရန်      : $TMUX_HINT"
else
  say " ▶️  restart      : sudo systemctl restart $SERVICE"
  say " 📜 log ကြည့်ရန်  : sudo journalctl -u $SERVICE -f"
fi
say ""
say " နောက်လုပ်ရမည့်အဆင့် (၂) ခု:"
say "  1) API key ထည့်ပါ:   sudo nano $ENV_FILE   →  GEMINI_API_KEY=AIza... (Key #2/#3 ပါ ထည့်နိုင်သည်)"
if [ "$MANUAL_MODE" = "1" ]; then
  say "                        (service မရှိပါ — app ကို ပြန် run ပါ)"
else
  say "                        sudo systemctl restart $SERVICE"
fi
if [ -n "$ADMIN_CREATED" ]; then
  say "  2) admin အကောင့် '$ADMIN_CREATED' ဖြင့် browser မှ login ဝင်ပါ"
  if [ -n "$ADMIN_PASSWORD_SHOWN" ]; then
    say ""
    say "     ┌────────────────────────────────────────────────┐"
    say "     │  username : $ADMIN_CREATED"
    say "     │  password : $ADMIN_PASSWORD_SHOWN"
    say "     └────────────────────────────────────────────────┘"
    say "     ⚠️ ဤ password ကို ယခုပဲ မှတ်ထားပါ — နောက်တစ်ခါ ပြမည် မဟုတ်ပါ"
    say ""
  fi
  say "                        password ပြောင်းရန်: ⚙️ Settings → အကောင့် → စကားဝှက် ပြောင်းရန်"
else
  say "  2) admin အကောင့် ဖန်တီးပါ (v4.2 — ဤအဆင့် မလုပ်လျှင် login စာမျက်နှာ ပေါ်မည် မဟုတ်ပါ):"
  say "        ua() { sudo -u $SERVICE_USER bash -c \"set -a; . $ENV_FILE; set +a; cd $APP_DIR && .venv/bin/python -m recapstudio.useradmin \$*\"; }"
  say "        ua create myname --admin --random"
  say "        ${SUDO_PREFIX}systemctl restart $SERVICE"
fi
say ""
say " စစ်ဆေးရန် (server မှ):  curl -s http://localhost/api/auth/me   → \"mode\":\"users\" ဖြစ်ရမည်"
say " စစ်ဆေးရန် (laptop မှ):  python tests/verify_deployment.py http://${PUBLIC_IP:-YOUR-IP}"
say " ⚠️  Browser တွင် အဟောင်း မြင်နေလျှင် Ctrl+Shift+R (Mac: ⌘+Shift+R) နှိပ်ပါ"
say " နောက်တစ်ခါ update လုပ်ရန်:  sudo bash $0   (ဤ script ကိုပဲ ပြန် run ပါ)"
say " ⚠️  Security Group တွင် HTTP (port ${PORT}) inbound ဖွင့်ထားရန် မမေ့ပါနှင့်"
say "════════════════════════════════════════════════════════════════"
