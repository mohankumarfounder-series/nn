# நிதி நீதி தமிழ் — Automation Bot v1.0

Fully automated YouTube channel for Tamil Finance & Legal Rights.

## Channel: [@NidhiNeethiTamil](https://www.youtube.com/@NidhiNeethiTamil)

---

## What this bot does

Every day at 5:30 AM IST:
1. LLM scans RBI/SEBI news + Google trends → picks best topic
2. Generates 2-minute Tamil script (320-360 words)
3. Translates to English subtitles automatically
4. Fetches relevant Pexels images (rupee, court, bank etc)
5. Generates voice — male or female based on content type
6. Creates professional video with Ken Burns, transitions, text overlays
7. Burns English subtitles into video
8. Uploads to YouTube with title, description, tags, pinned comment

---

## Setup

### 1. Install dependencies
```bash
pip install google-genai groq edge-tts google-api-python-client \
            google-auth-oauthlib requests beautifulsoup4 Pillow schedule
sudo apt install ffmpeg
```

### 2. Set environment variables
```bash
export GEMINI_KEY="your_key"          # aistudio.google.com/apikey
export GROQ_API_KEY="your_key"        # console.groq.com
export PEXELS_API_KEY="your_key"      # pexels.com/api
```

### 3. YouTube OAuth (one time)
```bash
# Place client_secrets.json from Google Cloud Console
python3 nidhi_neethi_bot.py --auth-youtube

# Encode token for GitHub Actions
base64 -w 0 youtube_token.pickle
# → Copy output → GitHub Secrets → YOUTUBE_TOKEN_BASE64
```

### 4. GitHub Secrets to set
| Secret | Value |
|--------|-------|
| `GEMINI_KEY` | Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `PEXELS_API_KEY` | Pexels API key |
| `YOUTUBE_TOKEN_BASE64` | base64 of youtube_token.pickle |
| `CLIENT_SECRETS_BASE64` | base64 of client_secrets.json |

---

## Usage

```bash
# Auto topic (LLM decides)
python3 nidhi_neethi_bot.py --day today

# Auto topic + upload
python3 nidhi_neethi_bot.py --day today --upload

# Custom topic
python3 nidhi_neethi_bot.py --topic "CIBIL score சரிசெய்வது எப்படி"

# Custom topic + format
python3 nidhi_neethi_bot.py --topic "UPI fraud" --format warning

# 24/7 daemon
python3 nidhi_neethi_bot.py --daemon
```

---

## Content formats

| Format | Voice | BGM mood | Use case |
|--------|-------|----------|----------|
| `warning` | Female | Tense corporate | Loan traps, fraud alerts |
| `explainer` | Male | Calm informative | How SIP works, CIBIL guide |
| `rights` | Male | Empowering | Consumer court, legal rights |
| `comparison` | Female | Analytical neutral | FD vs MF, loan types |
| `story` | Female | Narrative cinematic | Real scam survivor stories |
| `news` | Male | Corporate breaking | RBI rate cut, new scheme |

---

## Output per video

```
videos/          → full 2-min video (1920×1080)
shorts/          → 58s vertical clip (1080×1920)
subtitles/       → English SRT file
scripts/         → Tamil script text
metadata/        → title, description, tags, thumbnail concept JSON
```

---

## Revenue potential

- RPM: $10–20 (finance/legal advertisers)
- Target advertisers: Zerodha, Groww, HDFC, LIC, Angel One
- Affiliate income: Groww, ET Money referrals
- Community: paid financial templates (future)
