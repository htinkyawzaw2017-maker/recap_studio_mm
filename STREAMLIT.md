# 🎬 Recap Studio MM — Free Edition (Streamlit) · `streamlit-free-edition` branch

ဒီ branch သည် မူရင်း Recap Studio MM Pro (FastAPI) engine ကို **Streamlit UI** နဲ့
သုံးနိုင်အောင် upgrade လုပ်ထားတဲ့ version ပါ။ မူရင်း `main` branch ကို မထိပါ။

## ✨ ဒီ branch မှာ အသစ်ပါတာတွေ

- **`streamlit_app.py`** — အဆင့် ၆ ဆင့် stepper UI:
  1️⃣ ဗီဒီယို တင် / YouTube-TikTok လင့်ခ် →
  2️⃣ **Long Video Splitter** (၃/၅/၈/၁၀/၁၅ မိနစ်) အပိုင်းတိုင်းမှာ **🎬 Recap ပို့မည်** transfer ခလုတ် →
  3️⃣ Recap setup (🇲🇲/🇬🇧, Recap/Dubbing, အသံ, ပုံစံ) + Gemini script ထုတ် →
  4️⃣ **✍️ Script Editor** — စချိန်/ဆုံးချိန်/စာသား ပြင်၊ ထည့်/ဖျက်၊ ရှည်လွန်းတဲ့ လိုင်း ⚠️ + အလိုအလျောက် ချုံ့။
  **အတည်ပြုပြီးမှ Render ပွင့်ပါတယ်** →
  5️⃣ Render → MP4 + SRT + MP3 ဒေါင်းလုဒ်
- **Unlimited Gemini Key Pool** (`recapstudio/keys.py` → `UnlimitedKeyPool`) —
  Sidebar မှာ တစ်ကြောင်း တစ်ခု ကြိုက်သလောက် ထည့်၊ quota ပြည့်ရင် နောက် key သို့ အလိုအလျောက် ပြောင်း
  (မူရင်း KeyRing ရဲ့ slot အများဆုံး ၃ ခု ကန့်သတ်ချက်ကိုလည်း ၁၀၀ အထိ ဖြေလိုက်ပါတယ်)
- အသံများ (အခမဲ့ Edge TTS): 🇲🇲 Thiha/Nilar • 🇬🇧 Christopher/Jenny/Guy/Aria

## 🚀 Streamlit Cloud မှာ Deploy လုပ်နည်း

1. [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repository: `htinkyawzaw2017-maker/recap_studio_mm`
   Branch: **`streamlit-free-edition`** · Main file: **`streamlit_app.py`** → **Deploy**
3. App **Settings → Secrets** မှာ (ထည့်ချင်ရင်):

```toml
GEMINI_API_KEYS = ["AIza...key1...", "AIza...key2...", "AIza...key3..."]
```

Secrets မထည့်ဘဲ app ရဲ့ Sidebar မှာလည်း key ထည့်နိုင်ပါတယ် (session အတွင်းသာ သိမ်းထားပါတယ်)။

⚠️ **Quota တကယ် တိုးချင်ရင်** key တွေကို **Google project မတူတူချင်း** ထုတ်ပါ —
project တစ်ခုတည်းက key အများကြီးသည် quota တစ်ခုတည်းကို မျှသုံးနေတာ ဖြစ်ပါတယ်။

## ⚠️ Streamlit Cloud ကန့်သတ်ချက်များ

- RAM/CPU နည်းလို့ **၈ မိနစ်အောက် အပိုင်းခွဲ**ပြီး လုပ်ဖို့ အကြံပြုပါတယ် (Splitter ပါပြီးသား)
- ဖိုင်တွေ မမြဲပါ — app restart ဖြစ်ရင် ပျောက်ပါတယ်၊ ပြီးတာနဲ့ ချက်ချင်း ဒေါင်းပါ
- Upload ကို 1 GB ဖွင့်ထားပေမယ့် Cloud ကန့်သတ်ချက် ရှိနိုင်ပါတယ် — ဖိုင်ကြီးရင် လင့်ခ် import သုံးပါ

## 💻 Local

```bash
pip install -r requirements.txt   # + ffmpeg (packages.txt / system)
streamlit run streamlit_app.py    # http://localhost:8501
```

## 🧪 Test

```bash
RECAP_DATA_DIR=/tmp/recap_test RECAP_FAKE_TTS=1 RECAP_DEMO_MODE=1 \
  python tests/test_streamlit_core.py   # 9 checks: key pool, splitter, TTS, subtitle, render
```
