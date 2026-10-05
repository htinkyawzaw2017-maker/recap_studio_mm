# Phase 2 — အကောင့်စနစ် + Database လုံခြုံရေး + User အများသုံး (v4.2)

> အကျဉ်းချုပ်: ယခင်က site ကို သိသူတိုင်း ဝင်နိုင်ခဲ့သည် (သို့) access key တစ်ခုတည်း မျှသုံးခဲ့သည်။
> v4.2 မှစ၍ **username + password အကောင့်စနစ်**၊ **user တစ်ယောက်ချင်းစီ ဖိုင်ခွဲထား**၊
> **API key များ encrypt သိမ်းဆည်း**၊ **brute-force ကာကွယ်မှု** တို့ ပါဝင်လာပါပြီ။

---

## 1. ဘာတွေ ပြောင်းသွားလဲ

| အရာ | v4.1 (ယခင်) | v4.2 (ယခု) |
|---|---|---|
| ဝင်ရောက်ခြင်း | access key တစ်ခု (သို့) လုံးဝဖွင့် | username + password အကောင့် (session cookie) |
| user များ | မရှိ — အားလုံး တစ်နေရာတည်း | အကောင့်တစ်ခုချင်း သီးသန့် workspace/output |
| job မြင်ရမှု | မည်သူမဆို job အားလုံး မြင်/ဖျက်နိုင် | ကိုယ့် job သာ မြင်ရ (သူများ job → 404) |
| Gemini API key | `.env` / JSON plaintext | DB ထဲ **encrypt** (Fernet) + user တစ်ယောက်ချင်း key |
| Password | မရှိ | PBKDF2-SHA256 240,000 rounds + salt |
| Brute force | ကာကွယ်မှု မရှိ | 8 ကြိမ် မှားလျှင် 15 မိနစ် ပိတ် + rate limit |
| Admin tools | မရှိ | UI admin panel + `useradmin` CLI + audit log |
| Database | JSON ဖိုင်များ | SQLite `data/recap.db` (0600, schema v3, WAL) |
| HTTP headers | အနည်းငယ် | CSP / nosniff / referrer-policy / permissions-policy |

### 1.1 အသစ်ထပ်တိုးသော ဖိုင်များ

```
recapstudio/db.py          SQLite schema + migration (users, sessions, jobs, audit, quotas)
recapstudio/crypto.py      secret key management + Fernet/HMAC encryption
recapstudio/auth.py        Principal, password policy, session, quota, audit logic
recapstudio/webauth.py     FastAPI dependency guards (cookie / Bearer / access key)
recapstudio/useradmin.py   command line account manager
tests/test_auth.py         75 checks (offline)
```

---

## 2. Auth mode ၄ မျိုး — `RECAP_AUTH_MODE`

| mode | ဘယ်အချိန် သုံးမလဲ | အပြုအမူ |
|---|---|---|
| `auto` *(default)* | ဘာမှ မသတ်မှတ်ချင်လျှင် | အကောင့်ရှိလျှင် `users`၊ မရှိလျှင် access key (သို့) ဖွင့်ထား |
| `users` | **public server အတွက် အကြံပြုချက်** | အကောင့် မဖြစ်မနေ — login မဝင်ဘဲ ဘာမှ မလုပ်နိုင် |
| `legacy` | အကောင့် မလိုချင်သေးလျှင် | `RECAP_ACCESS_PASSWORD` တစ်ခုတည်း |
| `open` | laptop/localhost သာ | ကာကွယ်မှု မရှိ |

> `auto` ဖြင့် ထားပြီး အကောင့်တစ်ခု ဖန်တီးလိုက်သည်နှင့် စနစ်က `users` သို့ အလိုအလျောက်
> ပြောင်းသွားပါမည် — ဒါကြောင့် **အကောင့် ဖန်တီးခြင်းသည် အရေးအကြီးဆုံး အဆင့်** ဖြစ်သည်။

---

## 3. သင် ကိုယ်တိုင် လုပ်ရမည့် အဆင့်များ (AWS EC2) — အစအဆုံး

> လိုအပ်ချက်: EC2 terminal (EC2 Instance Connect browser terminal (သို့) SSH)။
> မသိလျှင် → [EC2_INSTANCE_CONNECT.md](EC2_INSTANCE_CONNECT.md)

### အဆင့် 1 — Code အသစ်ကို server ပေါ် တင်ပါ

```bash
cd /tmp
curl -fsSL -o recap.tgz \
  https://codeload.github.com/htinkyawzaw2017-maker/recap_studio_mm/tar.gz/refs/heads/arena/01a10a80-recap-studio-mm
rm -rf recap_studio_mm-arena-* && tar xzf recap.tgz
sudo bash /tmp/recap_studio_mm-arena-01a10a80-recap-studio-mm/deploy/ec2_install.sh
```

Installer က အောက်ပါတို့ကို **အလိုအလျောက်** လုပ်ပေးသည် —
`.env` ထဲ `RECAP_SECRET_KEY` ထည့်ပေး → database migrate → service restart → health check။
`.env` ထဲရှိ သင့် API key / setting အဟောင်းများ **မပျက်ပါ**။ `data/` ဖိုင်များလည်း မပျက်ပါ။

### အဆင့် 2 — Secret key ရှိ/မရှိ စစ်ပါ (အရေးကြီး)

```bash
sudo grep RECAP_SECRET_KEY /opt/recap-studio/.env
```

- တန်ဖိုး (hex ၆၄ လုံး) ပါလျှင် — ပြီးပါပြီ။
- အလွတ်ဖြစ်နေလျှင် —

```bash
sudo sed -i "s|^RECAP_SECRET_KEY=.*|RECAP_SECRET_KEY=$(openssl rand -hex 32)|" /opt/recap-studio/.env
```

> ⚠️ ဤ key ကို **နောင်တွင် မပြောင်းပါနှင့်**။ ပြောင်းလျှင် login session အားလုံး ပြုတ်ပြီး
> DB ထဲ သိမ်းထားသော Gemini API key များ ပြန်ဖတ်၍ မရတော့ပါ (ပြန်ထည့်ရမည်)။
> `.env` ကို backup ကူးထားပါ: `sudo cp /opt/recap-studio/.env ~/recap-env-backup.txt`

### အဆင့် 3 — Database ကို migrate လုပ်ပါ

```bash
# ① တစ်ကြိမ်သာ — command အတို "ua" ကို သတ်မှတ်ပါ (.env ကို လုံခြုံစွာ ဖတ်သည်)
ua() { sudo -u ubuntu bash -c "set -a; . /opt/recap-studio/.env; set +a; cd /opt/recap-studio && .venv/bin/python -m recapstudio.useradmin $*"; }
```

```bash
# ② migrate
ua migrate
```

> ⚠️ `env $(grep -v '^#' .env | xargs)` ပုံစံကို မသုံးပါနှင့် — `.env` ထဲ space ပါသော တန်ဖိုး
> (ဥပမာ စကားဝှက်) ရှိလျှင် env မပါဘဲ run သွားပြီး **DB မှားသော နေရာတွင်** ဆောက်မိတတ်သည်။
> အပေါ်က `ua` function သည် `.env` ကို source လုပ်သဖြင့် အမြဲ မှန်ကန်သည်။

ဤ command က schema အသစ် ဆောက်ပြီး `.env` ထဲက Gemini key များကို encrypt လုပ်ကာ DB ထဲ ထည့်သည်။
(Installer က run ပြီးသားဖြစ်နိုင်သည် — ထပ်run လျှင် ဘာမှ မပျက်ပါ။)

### အဆင့် 4 — ပထမဆုံး admin အကောင့် ဖန်တီးပါ ⭐

```bash
ua create myname --admin --random
```

- `myname` နေရာတွင် သင် သုံးလိုသော username (ဥပမာ `htin`) ထည့်ပါ။
- `--random` က password ကို အလိုအလျောက် ထုတ်ပေးပြီး **တစ်ကြိမ်သာ ပြပါမည်** — ချက်ချင်း မှတ်ထားပါ။
- ကိုယ်တိုင် password ပေးချင်လျှင် `--random` အစား `--password 'YourStrongPass123'`
  (စည်းကမ်း: အနည်းဆုံး ၁၀ လုံး၊ အက္ခရာ+ဂဏန်း ၂ မျိုးပါရမည်၊ username ကို ထည့်မရပါ)

### အဆင့် 5 — Service ကို restart လုပ်ပါ

```bash
sudo systemctl restart recap-studio
sudo systemctl status recap-studio --no-pager | head -12
```

### အဆင့် 6 — စစ်ဆေးပါ

```bash
ua status
```

အောက်ပါအတိုင်း မြင်ရမည် —

```
auth mode       : users          ← 'open' ဖြစ်နေလျှင် အကောင့် မဖန်တီးရသေးပါ
accounts        : 1
secret storage  : fernet(cryptography) (persistent)
```

Browser တွင် `http://<EC2-IP>` ဖွင့်ပါ → **Ctrl + Shift + R** (hard refresh) →
login စာမျက်နှာ ပေါ်လာရမည် → အဆင့် ၄ မှ username/password ဖြင့် ဝင်ပါ။

Laptop မှ အပြီးသတ် စစ်ဆေးရန် —

```bash
python tests/verify_deployment.py http://<EC2-IP> --username myname --password 'xxxx'
```

### အဆင့် 7 (ရွေးချယ်ခွင့်) — အခြား user များ ထည့်ပါ

**နည်း A — သင်ကိုယ်တိုင် ဖန်တီးပေးခြင်း (အကြံပြု)**
UI ထဲ admin အဖြစ် ဝင် → ⚙️ **Settings → အကောင့် စီမံခန့်ခွဲမှု** → username/password ထည့် → **ဖန်တီးမည်**။
(CLI ဖြင့်လည်း ရသည်: `useradmin create friend --random`)

**နည်း B — သူတို့ ကိုယ်တိုင် အကောင့်ဖွင့်ခွင့် ပေးခြင်း**

```bash
sudo nano /opt/recap-studio/.env
# RECAP_ALLOW_SIGNUP=1
# RECAP_SIGNUP_CODE=team2026        ← invite code (မဖြစ်မနေ ထည့်သင့်သည်)
sudo systemctl restart recap-studio
```

---

## 4. Browser UI ထဲ ဘာတွေ အသစ်ပါလာလဲ

| နေရာ | အသစ် |
|---|---|
| ပထမဆုံး စာမျက်နှာ | login / sign-up ကတ် (အကောင့်မရှိသေးလျှင် "ပထမဆုံး အကောင့် = admin" ဟု ပြမည်) |
| ညာဘက် အပေါ်ထောင့် | 👤 username chip + **ထွက်မည်** ခလုတ် |
| ⚙️ Settings → အကောင့် | စကားဝှက် ပြောင်းရန် / အခြား device အားလုံးမှ ထွက်ရန် |
| ⚙️ Settings → အကောင့် စီမံခန့်ခွဲမှု *(admin သာ)* | user စာရင်း၊ password reset၊ ပိတ်/ဖွင့်၊ admin ပေး/ရုပ်သိမ်း၊ ဖျက်၊ audit log |
| ⚙️ Settings → API key | သိမ်းလျှင် ယခု **သင့်အကောင့်အတွက်သာ** သိမ်းသည် (encrypt ထားသည်) |

---

## 5. `useradmin` CLI — အမိန့် အားလုံး

အောက်ပါ `ua` function ကို တစ်ကြိမ် သတ်မှတ်ပြီး သုံးပါ —

```bash
ua() { sudo -u ubuntu bash -c "set -a; . /opt/recap-studio/.env; set +a; cd /opt/recap-studio && .venv/bin/python -m recapstudio.useradmin $*"; }
```

| အမိန့် | အလုပ် |
|---|---|
| `ua status` | auth mode, အကောင့်အရေအတွက်, DB path, secret storage |
| `ua migrate` | schema migrate + `.env` key များ encrypt သိမ်း |
| `ua create NAME --admin --random` | အကောင့်ဖန်တီး (`--password X`, `--must-change` ရှိ) |
| `ua list` / `list --json` | အကောင့် စာရင်း |
| `ua passwd NAME --random` | password reset (session အားလုံး ပြုတ်မည်) |
| `ua disable NAME` / `enable NAME` | ခေတ္တ ပိတ် / ပြန်ဖွင့် |
| `ua promote NAME` / `demote NAME` | admin ပေး / ရုပ်သိမ်း |
| `ua delete NAME --yes` | အကောင့် + ဖိုင်များ ဖျက် |
| `ua sessions NAME [--revoke]` | ဝင်ထားသော device များ ကြည့် / ထွက်ခိုင်း |
| `ua audit --limit 50` | security log (login, create, delete, …) |

---

## 6. Environment variable အားလုံး (v4.2 အသစ်)

| Variable | Default | အဓိပ္ပာယ် |
|---|---|---|
| `RECAP_SECRET_KEY` | *(auto → `data/.recap_secret`)* | session + encryption သော့ ⚠️ မပြောင်းပါနှင့် |
| `RECAP_AUTH_MODE` | `auto` | `auto` / `users` / `legacy` / `open` |
| `RECAP_ALLOW_SIGNUP` | `0` | user ကိုယ်တိုင် အကောင့်ဖွင့်ခွင့် |
| `RECAP_SIGNUP_CODE` | *(အလွတ်)* | signup invite code |
| `RECAP_SESSION_TTL_HOURS` | `168` | login တစ်ခု သက်တမ်း (၇ ရက်) |
| `RECAP_SESSION_IDLE_HOURS` | `72` | မလှုပ်ရှားဘဲ ကြာလျှင် ထွက် |
| `RECAP_PASSWORD_MIN_LENGTH` | `10` | password အနည်းဆုံး အရှည် |
| `RECAP_PBKDF2_ITERATIONS` | `240000` | hashing rounds |
| `RECAP_LOGIN_MAX_ATTEMPTS` | `8` | မှားခွင့် အကြိမ် |
| `RECAP_LOGIN_WINDOW_MINUTES` | `15` | အထက်ပါအကြိမ်ကို တွက်သည့် ကာလ |
| `RECAP_LOGIN_LOCKOUT_MINUTES` | `15` | ပိတ်ထားမည့် ကြာချိန် |
| `RECAP_RATE_LIMIT_PER_MINUTE` | `300` | IP တစ်ခု API ကန့်သတ် |
| `RECAP_LOGIN_RATE_LIMIT_PER_MINUTE` | `12` | login endpoint ကန့်သတ် |
| `RECAP_USER_MAX_CONCURRENT_JOBS` | `1` | user တစ်ယောက် တစ်ပြိုင်နက် job |
| `RECAP_USER_DAILY_JOBS` | `0` | တစ်ရက် job ကန့်သတ် (0 = အကန့်အသတ်မရှိ) |
| `RECAP_USER_QUOTA_BYTES` | `0` | user တစ်ယောက် disk ကန့်သတ် (0 = မကန့်သတ်) |
| `RECAP_TRUSTED_HOSTS` | *(အလွတ်)* | ခွင့်ပြုမည့် domain စာရင်း |
| `RECAP_FRAME_ANCESTORS` | `self` | iframe embed policy |
| `RECAP_COOKIE_SECURE` | `auto` | HTTPS ဖြစ်မှ cookie ပို့ (`auto`/`1`/`0`) |
| `RECAP_COOKIE_SAMESITE` | `lax` | cookie SameSite |

---

## 7. လုံခြုံရေး အသေးစိတ် (နည်းပညာ)

- **Password**: PBKDF2-HMAC-SHA256, 240k rounds, 16-byte salt, constant-time compare,
  iteration မြှင့်လိုက်လျှင် login ဝင်ချိန်တွင် auto-rehash။
- **Session**: `secrets.token_urlsafe(40)` → DB ထဲ **SHA-256 hash သာ** သိမ်းသည်
  (DB ပေါက်သွားလျှင်လည်း token ပြန်မရ)။ Cookie = HttpOnly + SameSite=lax + HTTPS တွင် Secure။
- **CSRF**: `recap_csrf` cookie + `X-CSRF-Token` header (cookie ဖြင့် ဝင်သော POST/PATCH/DELETE အားလုံး)။
  Bearer token API client များ ကင်းလွတ်သည်။
- **Isolation**: job တိုင်းတွင် `user_id` ရှိသည်။ သူများ job ကို ခေါ်လျှင် **403 မဟုတ်ဘဲ 404** ပြန်သည်
  (job ရှိ/မရှိ ပင် မသိစေရန်)။ ဖိုင်များ `workspace/users/<user>/…`, `outputs/u_<user>/…` ခွဲထားသည်။
- **Secrets**: `cryptography` ရှိလျှင် Fernet (`v2:`), မရှိလျှင် HMAC-CTR fallback (`v1:`)။
  `useradmin status` တွင် ဘယ်ဟာသုံးနေသည် ပြသည်။
- **Audit log**: login/logout/create/delete/password/role အပြောင်းအလဲတိုင်း DB ထဲ မှတ်သည်
  (UI ၏ admin panel (သို့) `useradmin audit`)။
- **Headers**: `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Cache-Control: no-store` (API), CSP `frame-ancestors`။

---

## 8. ပြဿနာ ဖြေရှင်းချက်

### 8.0 အမြန်ဆုံးနည်း — browser (သို့) curl တစ်ကြောင်းဖြင့် admin ဖန်တီးခြင်း ⭐⭐

**နည်း A — browser မှ (terminal မလို)**
v4.2.1 မှစ၍ အကောင့် တစ်ခုမှ မရှိသေးသော server ကို ဖွင့်လိုက်လျှင်
**“ပထမဆုံး အကောင့် (admin) ကို ဖန်တီးပါ”** ကတ် အလိုအလျောက် ပေါ်လာပါမည် —
username + password ထည့်၍ ဖန်တီးလိုက်ရုံဖြင့် login စနစ် ချက်ချင်း ဖွင့်သွားပါမည် (restart မလို)။

**နည်း B — server terminal မှ တစ်ကြောင်းတည်း (DB path မှားစရာ မရှိ)**

```bash
curl -s -X POST http://localhost/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"myname","password":"Choose-Strong-Pass-2026"}'
curl -s http://localhost/api/auth/me      # "mode":"users" ဖြစ်သွားရမည်
```

> ဤနည်းသည် **run နေသော service ကိုယ်တိုင်** ကို ခေါ်သဖြင့် `.env` / `RECAP_DATA_DIR` မှားစရာ
> လုံးဝ မရှိပါ — `useradmin` CLI ဖြင့် အကောင့်ဖန်တီးပြီးမှ server က မမြင်တာမျိုး မဖြစ်တော့ပါ။

---

### 8.1 `/healthz` က 4.2.0 ပြနေပြီး web မှာ login မပေါ်ဘူး ⭐

အောက်ပါ command ၄ ကြောင်းကို server terminal တွင် run ပြီး ဘယ်ဟာလဲ ခွဲခြားပါ —

```bash
curl -s http://localhost/healthz;        echo      # version
curl -s http://localhost/api/auth/me;    echo      # mode + has_users  ← အဓိက
curl -s http://localhost/ | grep -c 'id="auth-overlay"'   # 1 = HTML အသစ် မှန်
ua status                                          # accounts ဘယ်နှစ်ယောက်
```

| ရလဒ် | အဓိပ္ပာယ် | ဖြေရှင်းနည်း |
|---|---|---|
| `"mode":"open"` / `accounts : 0` | **code အသစ် မှန်သည် — ဒါပေမဲ့ အကောင့် မရှိသေး** (login စနစ် မဖွင့်ရသေး) | `ua create myname --admin --random` → `sudo systemctl restart recap-studio` |
| `grep -c` က `0` ပြ | static ဖိုင်များ အဟောင်း ကျန်နေသည် | installer ကို ပြန် run ပါ |
| `"mode":"users"` ဖြစ်ပြီး browser မှာသာ အဟောင်း | **browser cache** | **Ctrl + Shift + R** (Mac: ⌘ + Shift + R) / incognito window / ဖုန်းဖြစ်လျှင် browser cache ရှင်းပါ |

> v4.2.0 မှစ၍ စာမျက်နှာ ခေါင်းစဉ်တွင် **server မှ ပြန်ပေးသော version အစစ်** (ဥပမာ `v4.2.0`) ပေါ်ပါမည်။
> `v4.1` ဟု ပြနေလျှင် သင်မြင်နေသည်မှာ **cache ထဲက စာမျက်နှာအဟောင်း** ဖြစ်သည်။
> အကောင့် မရှိသေးလျှင်လည်း စာမျက်နှာ အပေါ်ဆုံးတွင် 🟡 သတိပေးစာတန်း တိုက်ရိုက် ပေါ်ပါမည်။

| လက္ခဏာ | အကြောင်းရင်း | ဖြေရှင်းနည်း |
|---|---|---|
| Login စာမျက်နှာ မပေါ်ဘဲ အရင်အတိုင်း ဝင်သွားသည် | အကောင့် မရှိသေး (`mode=open`) | အဆင့် ၄ (admin အကောင့် ဖန်တီး) ကို လုပ်ပါ |
| Browser က ဟောင်းနေသည် | cache | **Ctrl + Shift + R** / private window |
| `password ... မှား` ဟု အမြဲပြ | ၈ ကြိမ် မှားပြီး lock ဖြစ်နေ | ၁၅ မိနစ် စောင့် (သို့) `useradmin passwd NAME --random` |
| login ဝင်ပြီး ချက်ချင်း ပြန်ထွက် | `RECAP_SECRET_KEY` ပြောင်းသွား / restart တိုင်း ပြောင်း | `.env` ထဲ key အမြဲတမ်း တစ်ခု သတ်မှတ်ပါ |
| API key ပျောက် / `decrypt failed` log | secret key ပြောင်းသွားသည် | Settings → API key ပြန်ထည့်ပါ |
| 429 `too many requests` | rate limit | `RECAP_RATE_LIMIT_PER_MINUTE` မြှင့်ပါ |
| 507 `quota` | user disk ပြည့် | `RECAP_USER_QUOTA_BYTES` မြှင့် (သို့) output ဖျက် |
| admin password မေ့သွား | — | server မှ `useradmin passwd myname --random` |
| အကောင့်စနစ် ခေတ္တ ပိတ်ချင်သည် | — | `.env` → `RECAP_AUTH_MODE=legacy` + `RECAP_ACCESS_PASSWORD=...` → restart |

---

## 9. စမ်းသပ်ချက် (developer)

```bash
python tests/test_auth.py          # 75 checks — auth, session, CSRF, quota, isolation
python tests/smoke_test.py         # 69 checks — core pipeline
python tests/verify_deployment.py https://your-domain.com --username admin --password '...'
```

`test_auth.py` သည် offline — network/ffmpeg မလို၊ temp data dir ဖြင့် run သည်။
