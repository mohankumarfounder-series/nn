#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          நிதி நீதி தமிழ் — FULLY AUTOMATED BOT v1.5            ║
║  Tamil Finance & Legal Rights YouTube Channel                   ║
║  MCQ · Series · Source cite · Bilingual · Update checks        ║
║  Auto topic · Pexels visuals · YouTube upload · Daily 6AM IST  ║
╚══════════════════════════════════════════════════════════════════╝

Setup:
  pip install google-genai groq edge-tts google-api-python-client \
              google-auth-oauthlib requests beautifulsoup4 schedule \
              Pillow

Usage:
  python nidhi_neethi_bot.py --day today          # today's video
  python nidhi_neethi_bot.py --day today --upload # generate + upload
  python nidhi_neethi_bot.py --topic "custom"     # custom topic
  python nidhi_neethi_bot.py --daemon             # 24/7 scheduler
  python nidhi_neethi_bot.py --auth-youtube       # first-time OAuth
"""

import argparse
import base64
import concurrent.futures
import datetime
import hashlib
import json
import os
import pickle
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import google.genai as genai
except ImportError:
    print("pip install google-genai"); sys.exit(1)

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("pip install google-api-python-client google-auth-oauthlib"); sys.exit(1)

try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
GEMINI_KEY     = os.environ.get("GEMINI_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

GROQ_MODEL   = "llama-3.3-70b-versatile"
BGM_FILE     = "bgm.mp3"
OUTPUT_DIR   = "videos"
SHORTS_DIR   = "shorts"
METADATA_DIR = "metadata"
SCRIPTS_DIR  = "scripts"
PEXELS_DIR   = "pexels_images"
SUBS_DIR     = "subtitles"
QUEUE_FILE   = "upload_queue.json"

YOUTUBE_SCOPES         = ["https://www.googleapis.com/auth/youtube",
                          "https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_TOKEN_FILE     = "youtube_token.pickle"
YOUTUBE_CLIENT_SECRETS = "client_secrets.json"

CHANNEL_NAME    = "நிதி நீதி தமிழ்"
CHANNEL_HANDLE  = "@NidhiNeethiTamil"
CHANNEL_EMAIL   = "nidhineethitamil@gmail.com"

# 2 min video = ~320-360 Tamil words at -13% TTS rate
# chars: ~2200-2600 (Tamil avg 6.5 chars/word)
TARGET_MIN_CHARS = 2200
TARGET_MAX_CHARS = 3200

# ═══════════════════════════════════════════════════════════════
# VOICE CONFIGURATION — Male + Female mix
# ═══════════════════════════════════════════════════════════════

# edge-tts Tamil voices
VOICE_FEMALE = "ta-IN-PallaviNeural"   # warm, clear female
VOICE_MALE   = "ta-IN-ValluvarNeural"  # authoritative male

# Voice EQ profiles
# Light, natural EQ — minimal processing = less robotic
EQ_FEMALE_FINANCE = (
    "highpass=f=80,"
    "equalizer=f=300:t=q:w=0.7:g=1.5,"
    "equalizer=f=3000:t=q:w=0.8:g=1,"
    "acompressor=threshold=-18dB:ratio=2:attack=8:release=80:makeup=1,"
    "loudnorm=I=-14:TP=-1.5:LRA=11"
)

# Light natural EQ for male — warm, authoritative, not processed
EQ_MALE_FINANCE = (
    "highpass=f=60,"
    "equalizer=f=200:t=q:w=0.7:g=2,"
    "equalizer=f=2500:t=q:w=0.8:g=1.5,"
    "acompressor=threshold=-20dB:ratio=1.8:attack=8:release=80:makeup=2,"
    "loudnorm=I=-14:TP=-1.5:LRA=10"
)

# Content type → voice assignment
VOICE_ASSIGNMENT = {
    "warning":    ("female", VOICE_FEMALE, EQ_FEMALE_FINANCE),
    "explainer":  ("male",   VOICE_MALE,   EQ_MALE_FINANCE),
    "rights":     ("male",   VOICE_MALE,   EQ_MALE_FINANCE),
    "comparison": ("female", VOICE_FEMALE, EQ_FEMALE_FINANCE),
    "story":      ("female", VOICE_FEMALE, EQ_FEMALE_FINANCE),
    "news":       ("male",   VOICE_MALE,   EQ_MALE_FINANCE),
    "default":    ("female", VOICE_FEMALE, EQ_FEMALE_FINANCE),
}

# ═══════════════════════════════════════════════════════════════
# BGM PROFILES — professional finance/legal tones
# ═══════════════════════════════════════════════════════════════

BGM_PROFILES = {
    "warning":    {"freq": "220", "freq2": "440",  "mood": "tense corporate"},
    "explainer":  {"freq": "396", "freq2": "528",  "mood": "calm informative"},
    "rights":     {"freq": "285", "freq2": "570",  "mood": "empowering"},
    "comparison": {"freq": "417", "freq2": "528",  "mood": "analytical neutral"},
    "story":      {"freq": "174", "freq2": "348",  "mood": "narrative cinematic"},
    "news":       {"freq": "528", "freq2": "396",  "mood": "corporate breaking"},
    "default":    {"freq": "396", "freq2": "528",  "mood": "calm professional"},
}

# ═══════════════════════════════════════════════════════════════
# PEXELS QUERIES — finance & legal imagery
# ═══════════════════════════════════════════════════════════════

TOPIC_PEXELS_QUERIES = {
    "loan":        ["bank loan documents india", "rupee currency india", "loan agreement signing"],
    "cibil":       ["credit score report", "bank statement india", "financial documents"],
    "investment":  ["stock market india", "mutual fund investment", "money growth chart"],
    "fraud":       ["cyber fraud warning", "bank fraud alert", "online scam prevention"],
    "legal":       ["indian court justice", "legal documents india", "consumer court"],
    "tax":         ["income tax india", "tax filing documents", "rupee notes"],
    "insurance":   ["insurance policy india", "health insurance documents", "life insurance"],
    "rights":      ["consumer rights protest", "legal rights india", "justice symbol"],
    "bank":        ["indian bank branch", "banking documents", "atm india"],
    "salary":      ["salary slip india", "office work india", "professional indian"],
    "rbi":         ["reserve bank india building", "monetary policy india", "rupee symbol"],
    "default":     ["indian finance professional", "rupee currency", "business india"],
}

# ═══════════════════════════════════════════════════════════════
# CONTENT INTELLIGENCE — what topics to cover
# ═══════════════════════════════════════════════════════════════

EVERGREEN_TOPICS = [
    "CIBIL score 750+ எப்படி பெறுவது — 5 நடைமுறை வழிகள்",
    "Personal loan vs Gold loan — எது நல்லது உங்களுக்கு",
    "Credit card minimum payment trap — இந்த தவறை செய்யாதீர்கள்",
    "EPF பணம் எப்படி withdraw செய்வது — step by step",
    "Consumer court complaint எப்படி file செய்வது — உங்கள் உரிமை",
    "SIP vs Lump sum — முதல் முறை முதலீடு செய்பவருக்கு",
    "Bank loan reject ஆனால் என்ன செய்வது",
    "GST bill இல்லாமல் purchase — உங்களுக்கு என்ன ஆபத்து",
    "FD vs RD vs Savings account — எது அதிக வட்டி தரும்",
    "Insurance claim reject ஆனால் என்ன செய்வது",
    "UPI fraud ஆனால் பணம் திரும்ப பெறுவது எப்படி",
    "Home loan prepayment — எப்போது செய்வது, எப்போது வேண்டாம்",
    "PF account login செய்வது எப்படி — EPFO portal guide",
    "Online shopping return denied — consumer rights என்ன",
    "Salary account vs savings account — வித்தியாசம் என்ன",
    "Income tax notice வந்தால் என்ன செய்வது",
    "Loan guarantor ஆவதன் risks — தெரிந்துகொள்ளுங்கள்",
    "Health insurance claim process — step by step guide",
    "Mutual fund SIP stop செய்யலாமா — என்ன நடக்கும்",
    "Bank mis-selling complaint எப்படி file செய்வது",
]

CONTENT_FORMAT_TYPES = [
    "warning",
    "explainer",
    "rights",
    "comparison",
    "story",
    "news",
]

# ═══════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════

DAILY_TOPIC_PROMPT = """You are a content strategist for "நிதி நீதி தமிழ்" — a Tamil YouTube channel covering personal finance and legal rights for middle-class Tamil people.

YOUR AUDIENCE: Salaried Tamil people aged 25-45, earning ₹20,000-₹80,000/month. They worry about loans, CIBIL scores, savings, job rights, bank frauds, and government schemes. They are NOT financial experts.

TODAY: {date} | {day}
FINANCE NEWS (raw — needs viewer-friendly translation): {finance_news}
TRENDING SEARCHES: {trends}
RECENTLY USED TOPICS (DO NOT repeat any of these): {recent_topics}

STEP 1 — NEWS TRANSLATION RULE:
If using news, NEVER use raw RBI/SEBI jargon as the topic.
Translate it to viewer impact. Examples:
  ❌ BAD: "RBI விற்கு VRR ஏலம் அறிவிப்பு" (meaningless to viewer)
  ✅ GOOD: "RBI வட்டி விகிதம் மாறினால் உங்கள் EMI என்னாகும்?" (viewer impact)
  ❌ BAD: "SEBI circular on mutual fund NAV"
  ✅ GOOD: "Mutual Fund-ல் பணம் போட்டால் இப்போது safe-ஆ? SEBI புதிய விதி"

STEP 2 — TOPIC QUALITY CHECK:
Before finalising, ask: "Will a 30-year-old Chennai office employee immediately want to watch this?"
If no → pick a different topic.

STEP 3 — FORMAT SELECTION:
- warning: fraud alerts, EMI traps, loan dangers (high CTR)
- explainer: how SIP works, what CIBIL means (educational)
- rights: consumer court, bank complaint, RTI (empowering)
- comparison: FD vs RD, loan types (analytical)
- story: real situation → problem → solution (emotional)
- news: RBI/govt decision translated to viewer impact (timely)

STEP 4 — UNIQUENESS CHECK:
The recently used topics above must NOT be repeated even in different phrasing.

Return ONLY valid JSON, nothing else:
{{
  "topic": "<Viewer-friendly Tamil topic — clickable, specific, emotionally relevant>",
  "format": "<warning/explainer/rights/comparison/story/news>",
  "pexels_keyword": "<loan/cibil/investment/fraud/legal/tax/insurance/rights/bank/salary/rbi>",
  "hook_angle": "<First 5 seconds — the exact fear or curiosity you trigger>",
  "reason": "<Why this topic today, why this format>"
}}"""

SCRIPT_PROMPT = """You are a professional Tamil YouTube scriptwriter for "நிதி நீதி தமிழ்" — a finance and legal rights channel trusted by Tamil middle-class families.

Topic: {topic}
Format: {format_type}
Hook: {hook_angle}
Voice: {voice_gender}

━━━━━━━━━━━━━━━━━━━━━━━━━
SCRIPT STRUCTURE (follow exactly — 4 beats):

BEAT 1 — HOOK (15 seconds)
Use the hook angle above. Make it feel urgent or curious.
DO NOT introduce yourself. Jump straight into the problem or surprise fact.
Example good hook: "உங்கள் CIBIL score இன்று 100 points கீழே போயிருக்கு... காரணம் தெரியுமா?"
Example bad hook: "வணக்கம் நண்பர்களே, இன்று நாம் பேசப்போவது..."

BEAT 2 — CORE INFORMATION (60 seconds)
This is the most important part. Deliver COMPLETE, ACCURATE information.
- Give the actual facts, numbers, percentages, steps — NOT vague generalities
- If explaining a process: give each step clearly (step 1... step 2...)
- If warning: explain exactly what the trap is and how it works
- If comparing: give real numbers for both sides
- NEVER say "இன்னும் நிறைய இருக்கு" or leave things incomplete
- Use real data: actual RBI rules, actual percentages, actual timeframes

BEAT 3 — PRACTICAL TAKEAWAY (25 seconds)
ONE specific action the viewer can take TODAY.
Make it so simple a first-time viewer can act on it immediately.
Example: "இப்பவே உங்கள் phone-ல் CIBIL app திறந்து free report download பண்ணுங்க"

BEAT 4 — CTA (10 seconds)
Natural close. Thank viewer. One line subscribe ask.
DO NOT sound desperate. Sound like a knowledgeable friend.
━━━━━━━━━━━━━━━━━━━━━━━━━

FORMAT TONE:
- warning:    urgent, protective friend — "இந்த தவறை நான் உங்களிடம் சொல்லியே ஆகணும்"
- explainer:  clear teacher — "step by step பார்க்கலாம்"
- rights:     empowering lawyer friend — "சட்டம் உங்கள் பக்கம் இருக்கு"
- comparison: data-driven friend — "numbers பேசட்டும்"
- story:      storyteller — situation → problem → solution (NO fictional names — say "ஒரு Chennai-ல் இருக்கிற software engineer" not "Rajan என்பவர்")
- news:       confident news anchor tone

CRITICAL RULES:
1. 380-420 Tamil words exactly (2 min at natural pace)
2. NO fictional Tamil names (Rajan, Priya, Murugan etc) — say roles instead:
   ✅ "ஒரு Chennai software engineer"
   ✅ "ஒரு 35 வயது bank employee"
   ❌ "ராஜன் என்பவர்" (sounds fake, breaks trust)
3. Use REAL numbers — actual RBI rates, actual law sections, actual timeframes
4. Conversational Tamil — NOT formal written Tamil. How you talk to a friend.
5. "..." for natural pauses at key moments
6. NO headers, bullets, numbering, markdown — pure flowing speech
7. Information must be COMPLETE — viewer should not need to search elsewhere
8. Every sentence must earn its place — no filler, no repetition
"""

SUBTITLE_PROMPT = """You are a professional subtitle translator.

Below is a Tamil voiceover script. Translate it into English subtitles.

Rules:
1. Keep translations natural English — not word-for-word literal
2. Break into short subtitle lines (max 8 words per line)
3. Maintain the same energy and urgency as the Tamil original
4. Financial terms: keep Tamil terms with English in brackets (e.g. "CIBIL score (credit score)")
5. Return ONLY the English subtitle text, line by line
6. No timestamps — just the translated lines in order

Tamil script:
{tamil_script}
"""

METADATA_PROMPT = """Generate YouTube metadata for "நிதி நீதி தமிழ்" — Tamil finance & legal rights channel.

Topic: {topic}
Format: {format_type}
Hook: {hook_angle}

Return ONLY valid JSON, no markdown:
{{
  "title": "<SEO-optimized title — see rules below>",
  "description": "<Full description — see rules below>",
  "tags": "<30 comma-separated tags — see rules below>",
  "pinned_comment": "<Tamil pinned comment — see rules below>",
  "thumbnail_concept": "<Thumbnail description — see rules below>"
}}

TITLE RULES (critical for SEO):
- Under 60 characters
- Format: [Tamil hook question or statement] | [English keyword] | நிதி நீதி தமிழ்
- Use question format when possible (gets YouTube rich snippets): "CIBIL Score கீழே போனால் என்ன நடக்கும்? | CIBIL Drop Explained | நிதி நீதி தமிழ்"
- Include the most-searched keyword naturally
- Never start with channel name

DESCRIPTION RULES (first 2 lines = SEO snippet — most important):
Line 1: Tamil hook that matches the video's first 5 seconds (same urgency)
Line 2: English keyword sentence: "Learn how to [topic in English] | Tamil Finance Guide"
Then:
- Chapter timestamps (MANDATORY — YouTube shows these in search):
  0:00 Introduction
  0:15 [Beat 1 — hook topic in Tamil]
  0:45 [Beat 2 — core info topic in Tamil]
  1:30 [Beat 3 — action step in Tamil]
  1:50 Subscribe & Share
- 5 key points viewers will learn (Tamil)
- Disclaimer: "⚠️ இந்த video educational purpose மட்டுமே. Financial advice இல்லை. உங்கள் நிதி முடிவுகளுக்கு certified advisor-ஐ consult செய்யுங்கள்."
- Subscribe CTA: "🔔 Subscribe பண்ணுங்கள்: @NidhiNeethiTamil"
- Hashtags: #நிதிநீதிதமிழ் #NidhiNeethiTamil #TamilFinance #TamilLegalRights #PersonalFinanceTamil #[topic-specific hashtag]

TAGS RULES (30 tags, ordered by volume):
- 5 high-volume: "tamil finance", "personal finance tamil", "cibil score tamil", "tamil money tips", "tamil investment"
- 10 medium: topic-specific Tamil terms
- 10 long-tail: specific question phrases people search
- 5 English: broader reach terms

PINNED COMMENT:
- Ask viewers a specific question related to the topic
- Example: "உங்கள் CIBIL score எவ்வளவு? Comment பண்ணுங்கள் 👇"
- End with: நிதி நீதி தமிழ்-ஐ subscribe பண்ணி bell icon click பண்ணுங்கள் 🔔

THUMBNAIL CONCEPT:
- Background: deep blue (#0A1E3C) or urgent red (#B01020)
- Large bold Tamil text (main hook) — left 60% of image
- Right 40%: visual element (rupee symbol, court scale, phone with alert etc)
- Small channel logo bottom-right
- High contrast — readable at 120px thumbnail size
"""

THUMBNAIL_PROMPT = """Create a detailed AI image generation prompt for a YouTube thumbnail.

Channel: நிதி நீதி தமிழ் (Tamil Finance & Legal Rights)
Topic: {topic}
Format: {format_type}
Thumbnail concept: {thumbnail_concept}

Return a detailed prompt for image generation (Midjourney/DALL-E style):
- Professional finance/legal visual
- Bold Tamil text overlay space on left or right
- High contrast — works at small size
- Color scheme: deep blue + gold OR red + white (trust + urgency)
- Indian professional context
- No faces unless essential
- Clean, minimal, premium look
"""


# ═══════════════════════════════════════════════════════════════
# KEN BURNS PRESETS — professional finance look
# ═══════════════════════════════════════════════════════════════

KB_PRESETS = [
    ("min(1.0+0.0006*on,1.15)", "iw/2-(iw/zoom/2)+on*0.2", "ih/2-(ih/zoom/2)",       "zoom-in pan-right"),
    ("min(1.0+0.0006*on,1.15)", "iw/2-(iw/zoom/2)-on*0.2", "ih/2-(ih/zoom/2)",       "zoom-in pan-left"),
    ("max(1.15-0.0006*on,1.0)", "iw/2-(iw/zoom/2)",         "ih/2-(ih/zoom/2)",       "zoom-out center"),
    ("min(1.0+0.0005*on,1.10)", "iw/2-(iw/zoom/2)",         "ih/2-(ih/zoom/2)+on*0.15","zoom-in pan-up"),
    ("max(1.12-0.0005*on,1.0)", "iw/2-(iw/zoom/2)+on*0.15", "ih/2-(ih/zoom/2)",       "zoom-out pan-right"),
    ("min(1.0+0.0003*on,1.08)", "iw/2-(iw/zoom/2)",         "ih/2-(ih/zoom/2)",       "slow-zoom"),
]

XFADE_TRANSITIONS = ["fade", "dissolve", "wipeleft", "wiperight", "fadeblack", "fade"]


# ═══════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_dur(f):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", f])
    try:
        return float(r.stdout.strip())
    except:
        return 0.0


def ensure_dirs():
    for d in [OUTPUT_DIR, SHORTS_DIR, METADATA_DIR, SCRIPTS_DIR,
              PEXELS_DIR, SUBS_DIR]:
        os.makedirs(d, exist_ok=True)


def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return []


def save_queue(q):
    with open(QUEUE_FILE, "w") as f:
        json.dump(q, f, indent=2)


USED_TOPICS_FILE = "used_topics.txt"

def load_recent_topics(n=20):
    """
    Load recently used topics from used_topics.txt (committed to git).
    This file persists across GitHub Actions runs — solves stateless CI problem.
    Falls back to metadata/ folder for local runs.
    """
    topics = []
    # Primary: committed file (works on CI)
    if os.path.exists(USED_TOPICS_FILE):
        with open(USED_TOPICS_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        topics = lines[-n:]  # most recent n topics
    # Fallback: local metadata folder
    if not topics and os.path.isdir(METADATA_DIR):
        files = sorted(Path(METADATA_DIR).glob("*.json"), reverse=True)[:n]
        for fp in files:
            try:
                d = json.loads(fp.read_text())
                t = d.get("topic", "")
                if t:
                    topics.append(t)
            except:
                pass
    return topics


def save_used_topic(topic):
    """
    Append topic to used_topics.txt and commit to git.
    This ensures topic history persists across CI runs.
    """
    try:
        existing = []
        if os.path.exists(USED_TOPICS_FILE):
            with open(USED_TOPICS_FILE, encoding="utf-8") as f:
                existing = [l.strip() for l in f.readlines() if l.strip()]
        # Avoid duplicates
        if topic not in existing:
            existing.append(topic)
        # Keep last 60 topics (2 months of 2x daily)
        existing = existing[-60:]
        with open(USED_TOPICS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(existing) + "\n")
        # Commit to git so it persists across CI runs
        run(["git", "config", "user.email", "bot@nidhineethitamil.com"])
        run(["git", "config", "user.name",  "Nidhi Neethi Bot"])
        run(["git", "add", USED_TOPICS_FILE])
        r = run(["git", "commit", "-m", f"chore: log topic [{topic[:40]}]"])
        if r.returncode == 0:
            run(["git", "push"])
            log("  ✅ Topic history committed to git")
        else:
            log("  ℹ️  Nothing to commit")
    except Exception as e:
        log(f"  ⚠️ Could not save topic history: {e}")


def call_llm(prompt, max_retries=3):
    errs = []
    if GROQ_API_KEY and Groq:
        for attempt in range(max_retries):
            try:
                client = Groq(api_key=GROQ_API_KEY)
                resp = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=GROQ_MODEL, temperature=0.85, max_tokens=4000,
                )
                return resp.choices[0].message.content
            except Exception as e:
                wait = 10 * (attempt + 1)
                log(f"⏳ Groq retry {attempt+1}/{max_retries} in {wait}s: {str(e)[:80]}")
                errs.append(str(e))
                time.sleep(wait)
        log("⚠️ Groq failed → Gemini fallback")

    client = genai.Client(api_key=GEMINI_KEY)
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt)
            return resp.text
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = min(30 * (2 ** attempt), 300)
                log(f"⏳ Gemini quota wait {wait}s")
                time.sleep(wait)
            else:
                raise
    raise Exception(f"All LLM providers failed: {'; '.join(errs[:2])}")


def parse_json_response(raw):
    clean = raw.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    return json.loads(clean.strip())


# ═══════════════════════════════════════════════════════════════
# NEWS & TRENDS FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_finance_news():
    """Fetch RBI, SEBI, finance news relevant to Tamil audience."""
    news = []
    sources = [
        ("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx", "RBI"),
        ("https://economictimes.indiatimes.com/markets/rbi", "ET"),
        ("https://www.thehindu.com/business/Economy/", "TheHindu"),
        ("https://www.dinamani.com/business/", "Dinamani"),
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, src in sources:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    t = a.get_text(strip=True)
                    keywords = ["rate", "loan", "bank", "fraud", "consumer",
                                "CIBIL", "credit", "EMI", "RBI", "SEBI",
                                "insurance", "tax", "rupee", "வட்டி", "கடன்"]
                    if any(k.lower() in t.lower() for k in keywords) and len(t) > 15:
                        news.append(f"[{src}] {t[:100]}")
        except:
            pass
    return "\n".join(news[:15]) if news else "No live news. Use evergreen topics."


def fetch_trends():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://trends.google.com/trends/trendingsearches/daily?geo=IN",
                         headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            items = [d.get_text(strip=True) for d in soup.find_all("div", class_="title")]
            return "\n".join(f"- {i}" for i in items[:10])
    except:
        pass
    return "- personal finance tamil\n- loan eligibility\n- cibil score"


# ═══════════════════════════════════════════════════════════════
# PEXELS IMAGE FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_pexels_images(keyword, output_dir, count=5):
    if not PEXELS_API_KEY:
        log("⚠️ PEXELS_API_KEY not set")
        return []

    os.makedirs(output_dir, exist_ok=True)
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded = []

    queries = TOPIC_PEXELS_QUERIES.get(keyword, TOPIC_PEXELS_QUERIES["default"])
    queries = list(queries)
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= count:
            break
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers=headers,
                params={"query": query, "per_page": 3, "orientation": "landscape"},
                timeout=15
            )
            if resp.status_code != 200:
                continue
            for photo in resp.json().get("photos", []):
                if len(downloaded) >= count:
                    break
                img_url = photo["src"]["large2x"]
                fname = os.path.join(output_dir, f"{photo['id']}.jpg")
                if os.path.exists(fname):
                    downloaded.append(fname)
                    continue
                ir = requests.get(img_url, timeout=30, stream=True)
                if ir.status_code == 200:
                    with open(fname, "wb") as f:
                        for chunk in ir.iter_content(8192):
                            f.write(chunk)
                    downloaded.append(fname)
                    log(f"  📸 {os.path.basename(fname)} ({query})")
        except Exception as e:
            log(f"  ⚠️ Pexels error: {e}")

    log(f"  ✅ {len(downloaded)} images fetched")
    return downloaded


def ensure_fallback_image():
    if not os.path.exists("image.png"):
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (1920, 1080), (10, 30, 60))
            d = ImageDraw.Draw(img)
            d.rectangle([80, 400, 600, 680], fill=(20, 50, 100))
            d.rectangle([640, 200, 1840, 880], fill=(15, 40, 80))
            img.save("image.png")
        except:
            pass


# ═══════════════════════════════════════════════════════════════
# BGM GENERATION — professional finance tone
# ═══════════════════════════════════════════════════════════════

def ensure_bgm(format_type="default"):
    profile = BGM_PROFILES.get(format_type, BGM_PROFILES["default"])
    bgm_path = f"bgm_{format_type}.mp3"
    if os.path.exists(bgm_path):
        return bgm_path

    log(f"🎵 Generating BGM: {profile['mood']} ({profile['freq']}Hz)...")
    f1, f2 = profile["freq"], profile["freq2"]
    r = run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={f1}:duration=200",
        "-f", "lavfi", "-i", f"sine=frequency={f2}:duration=200",
        "-f", "lavfi", "-i", "anoisesrc=d=200:c=pink:r=44100:a=0.005",
        "-filter_complex",
        "[0:a]volume=0.12,afade=t=in:st=0:d=3,afade=t=out:st=197:d=3[s1];"
        "[1:a]volume=0.07,afade=t=in:st=0:d=5[s2];"
        "[2:a]lowpass=f=600,volume=0.08[n];"
        "[s1][s2][n]amix=inputs=3:duration=first[out]",
        "-map", "[out]", "-ar", "44100", "-ac", "2", bgm_path
    ], timeout=60)

    if r.returncode == 0:
        log(f"  ✅ BGM: {bgm_path}")
        return bgm_path
    else:
        log("  ⚠️ BGM generation failed")
        return BGM_FILE if os.path.exists(BGM_FILE) else None


# ═══════════════════════════════════════════════════════════════
# SUBTITLE GENERATION (SRT format)
# ═══════════════════════════════════════════════════════════════

def generate_srt(english_lines, total_duration, output_path):
    """
    Generate SRT subtitle file.
    Timing proportional to word count per line — longer lines get more time.
    Leaves 5% buffer at end for natural ending.
    """
    lines = [l.strip() for l in english_lines if l.strip()]
    if not lines:
        return None

    usable_duration = total_duration * 0.95  # 5% buffer at end
    # Weight time by word count — longer subtitle = more screen time
    word_counts = [max(len(l.split()), 1) for l in lines]
    total_words = sum(word_counts)
    # Min display time: 1.2s per line, max: 5s
    time_weights = [max(1.2, min(5.0, (wc / total_words) * usable_duration))
                    for wc in word_counts]
    # Normalize to fit total duration
    scale = usable_duration / sum(time_weights)
    durations = [t * scale for t in time_weights]

    srt_content = ""
    cursor = 0.3  # small delay before first subtitle

    def fmt(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    for i, (line, dur) in enumerate(zip(lines, durations)):
        start = cursor
        end   = min(cursor + dur - 0.1, total_duration - 0.2)
        srt_content += f"{i+1}\n{fmt(start)} --> {fmt(end)}\n{line}\n\n"
        cursor += dur

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    log(f"  ✅ SRT: {output_path} ({len(lines)} lines, proportional timing)")
    return output_path


def burn_subtitles(video_in, srt_path, video_out):
    """Burn English subtitles into video."""
    # Style: white text, black outline, bottom center, professional
    subtitle_style = (
        "FontName=Arial,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=30"
    )
    r = run([
        "ffmpeg", "-y", "-i", video_in,
        "-vf", f"subtitles={srt_path}:force_style='{subtitle_style}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-c:a", "copy", video_out
    ], timeout=300)
    return r.returncode == 0


# ═══════════════════════════════════════════════════════════════
# TEXT OVERLAY — channel branding on video
# ═══════════════════════════════════════════════════════════════

def build_text_overlay(title_short, format_type):
    safe = lambda s: s.replace("'", "").replace(":", "-").replace('"', "")
    channel = safe(CHANNEL_NAME)
    title   = safe(title_short[:45]) if title_short else ""

    fmt_labels = {
        "warning":    "WARNING",
        "explainer":  "EXPLAINER",
        "rights":     "YOUR RIGHTS",
        "comparison": "COMPARISON",
        "story":      "TRUE STORY",
        "news":       "BREAKING",
    }
    fmt_label = fmt_labels.get(format_type, "FINANCE")

    overlays = [
        # Channel name — top left, always visible
        f"drawtext=text='{channel}':fontsize=26:fontcolor=white@0.85:"
        f"x=30:y=28:shadowcolor=black@0.9:shadowx=2:shadowy=2",
        # Format badge — top right
        f"drawtext=text='{fmt_label}':fontsize=20:fontcolor=yellow@0.9:"
        f"x=w-tw-30:y=28:shadowcolor=black@0.9:shadowx=2:shadowy=2",
    ]

    # Title fades in at 0.5s, holds 6s
    if title:
        overlays.append(
            f"drawtext=text='{title}':fontsize=38:fontcolor=white@1.0:"
            f"x=(w-tw)/2:y=h-100:"
            f"shadowcolor=black@0.95:shadowx=3:shadowy=3:"
            f"alpha='if(lt(t,0.5),0,if(lt(t,2),(t-0.5)/1.5,if(lt(t,7),1,if(lt(t,8),(8-t),0))))'"
        )

    return ",".join(overlays)



# ═══════════════════════════════════════════════════════════════
# CHARACTER OVERLAY — consistent branded explainer character
# ═══════════════════════════════════════════════════════════════

CHARACTER_DIR = "assets/character"
BRAND_DIR      = "assets/brand"

# Brand asset paths
LOGO_WATERMARK = f"{BRAND_DIR}/logo_watermark.png"  # 120x120 transparent
INTRO_FRAME    = f"{BRAND_DIR}/intro_frame.png"      # 1920x1080 logo on teal
OUTRO_FRAME    = f"{BRAND_DIR}/outro_frame.png"      # 1920x1080 banner

INTRO_DURATION = 2.0   # seconds — logo sting at start
OUTRO_DURATION = 3.0   # seconds — banner + subscribe at end

# Which pose to use at each beat timestamp
# Beat 1 (0-15s): hook   → warning or explaining depending on format
# Beat 2 (15-75s): core  → explaining
# Beat 3 (75-100s): action → celebrating
# Beat 4 (100-120s): CTA  → neutral with wave

POSE_BY_FORMAT_AND_BEAT = {
    "warning":    ["warning",    "warning",    "explaining",  "neutral"],
    "explainer":  ["explaining", "explaining", "celebrating", "neutral"],
    "rights":     ["warning",    "explaining", "celebrating", "neutral"],
    "comparison": ["explaining", "explaining", "celebrating", "neutral"],
    "story":      ["neutral",    "explaining", "celebrating", "neutral"],
    "news":       ["explaining", "explaining", "neutral",     "neutral"],
    "default":    ["explaining", "explaining", "celebrating", "neutral"],
}


def make_intro_clip(output_path):
    """2s logo sting: intro_frame.png + bell sound."""
    if not os.path.exists(INTRO_FRAME):
        return None
    # Bell tone
    bell = f"/tmp/brand_bell.mp3"
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=880:duration=2.5",
         "-f", "lavfi", "-i", "sine=frequency=1320:duration=2.5",
         "-filter_complex",
         "[0:a]volume=0.5,afade=t=out:st=1.5:d=1[b1];"
         "[1:a]volume=0.3,afade=t=out:st=1.2:d=1[b2];"
         "[b1][b2]amix=inputs=2[bell]",
         "-map", "[bell]", bell], timeout=15)

    cmd = ["ffmpeg", "-y",
           "-loop", "1", "-t", str(INTRO_DURATION), "-i", INTRO_FRAME]
    if os.path.exists(bell):
        cmd.extend(["-i", bell,
                    "-filter_complex",
                    f"[0:v]scale=1920:1080,fade=t=in:st=0:d=0.5,"
                    f"fade=t=out:st={INTRO_DURATION-0.5}:d=0.5[v]",
                    "-map", "[v]", "-map", "1:a"])
    else:
        cmd.extend(["-filter_complex",
                    f"[0:v]scale=1920:1080,fade=t=in:st=0:d=0.5,"
                    f"fade=t=out:st={INTRO_DURATION-0.5}:d=0.5[v]",
                    "-map", "[v]",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-map", "1:a", "-t", str(INTRO_DURATION)])
    cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-t", str(INTRO_DURATION), output_path])
    r = run(cmd, timeout=30)
    return output_path if r.returncode == 0 else None


def make_outro_clip(output_path):
    """3s brand outro: banner frame with subscribe text."""
    if not os.path.exists(OUTRO_FRAME):
        return None
    text_filter = (
        "drawtext=text='Subscribe பண்ணுங்கள் 🔔':fontsize=52:"
        "fontcolor=white@0.95:x=(w-tw)/2:y=h-120:"
        "shadowcolor=black@0.9:shadowx=3:shadowy=3,"
        "drawtext=text='@NidhiNeethiTamil':fontsize=36:"
        "fontcolor=gold@0.9:x=(w-tw)/2:y=h-65:"
        "shadowcolor=black@0.8:shadowx=2:shadowy=2"
    )
    r = run(["ffmpeg", "-y",
             "-loop", "1", "-t", str(OUTRO_DURATION), "-i", OUTRO_FRAME,
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-filter_complex",
             f"[0:v]scale=1920:1080,"
             f"fade=t=in:st=0:d=0.5,"
             f"fade=t=out:st={OUTRO_DURATION-0.5}:d=0.5,"
             f"{text_filter}[v]",
             "-map", "[v]", "-map", "1:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-t", str(OUTRO_DURATION), output_path], timeout=30)
    return output_path if r.returncode == 0 else None


def concat_clips(clips, output_path):
    """Concatenate multiple video clips into one."""
    # Write filelist
    flist = f"/tmp/concat_{os.path.basename(output_path)}.txt"
    with open(flist, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    r = run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", flist, "-c", "copy", output_path], timeout=120)
    try: os.remove(flist)
    except: pass
    return r.returncode == 0


def ensure_character_assets():
    """Generate character PNGs if they don't exist."""
    poses = ["neutral", "explaining", "warning", "celebrating"]
    missing = [p for p in poses
               if not os.path.exists(f"{CHARACTER_DIR}/{p}.png")]
    if not missing:
        return True

    log(f"🎨 Generating character assets: {missing}...")
    try:
        from PIL import Image, ImageDraw
        os.makedirs(CHARACTER_DIR, exist_ok=True)

        def draw_character(pose):
            img = Image.new("RGBA", (200, 280), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            SKIN = (210,160,110,255); HAIR = (30,20,15,255)
            SHIRT = (25,80,160,255); SHIRT_LT = (40,100,190,255)
            PANT = (40,50,70,255); WHITE = (240,240,240,255)
            OUTLINE = (20,20,30,255); LIP = (180,80,70,255)
            CHEEK = (220,150,110,200)

            d.rectangle([72,175,128,260], fill=PANT, outline=OUTLINE, width=1)
            d.rectangle([55,120,145,185], fill=SHIRT, outline=OUTLINE, width=1)
            d.polygon([100,120,85,135,100,130,115,135], fill=WHITE, outline=OUTLINE)

            if pose == "neutral":
                d.ellipse([38,120,65,175], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([135,120,162,175], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([38,160,60,185], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([140,160,162,185], fill=SKIN, outline=OUTLINE, width=1)
            elif pose == "explaining":
                d.ellipse([38,120,65,175], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([38,160,60,185], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([135,70,162,130], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([140,55,162,80], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([145,42,158,62], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([148,30,156,50], fill=SKIN, outline=OUTLINE, width=1)
            elif pose == "warning":
                d.ellipse([20,85,55,140], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([145,85,180,140], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([15,70,55,100], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([145,70,185,100], fill=SKIN, outline=OUTLINE, width=1)
            elif pose == "celebrating":
                d.ellipse([20,60,65,120], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([135,60,180,120], fill=SHIRT_LT, outline=OUTLINE, width=1)
                d.ellipse([15,40,55,75], fill=SKIN, outline=OUTLINE, width=1)
                d.ellipse([145,40,185,75], fill=SKIN, outline=OUTLINE, width=1)

            d.rectangle([88,105,112,125], fill=SKIN, outline=OUTLINE, width=1)
            d.ellipse([68,45,132,115], fill=SKIN, outline=OUTLINE, width=2)
            d.ellipse([68,44,132,90], fill=HAIR)
            d.rectangle([68,44,100,75], fill=HAIR)
            d.ellipse([115,48,140,75], fill=HAIR)
            d.line([78,68,90,65], fill=HAIR, width=2)
            d.line([110,65,122,68], fill=HAIR, width=2)

            if pose == "warning":
                d.line([78,64,92,68], fill=HAIR, width=2)
                d.line([108,68,122,64], fill=HAIR, width=2)

            d.ellipse([78,72,92,82], fill=WHITE, outline=OUTLINE, width=1)
            d.ellipse([108,72,122,82], fill=WHITE, outline=OUTLINE, width=1)
            d.ellipse([83,74,89,80], fill=HAIR)
            d.ellipse([113,74,119,80], fill=HAIR)
            d.ellipse([85,75,87,77], fill=WHITE)
            d.ellipse([115,75,117,77], fill=WHITE)
            d.ellipse([72,83,84,93], fill=CHEEK)
            d.ellipse([116,83,128,93], fill=CHEEK)
            d.ellipse([96,82,104,90], fill=(195,140,95,200))

            if pose == "celebrating":
                d.arc([85,88,115,105], start=0, end=180, fill=LIP, width=2)
                d.arc([78,72,92,85], start=0, end=180, fill=OUTLINE, width=2)
                d.arc([108,72,122,85], start=0, end=180, fill=OUTLINE, width=2)
            elif pose == "warning":
                d.line([88,95,112,95], fill=LIP, width=2)
            elif pose == "explaining":
                d.arc([88,90,112,103], start=0, end=180, fill=LIP, width=2)
            else:
                d.arc([90,90,110,102], start=0, end=180, fill=LIP, width=2)

            return img

        for pose in missing:
            img = draw_character(pose)
            img.save(f"{CHARACTER_DIR}/{pose}.png")
            log(f"  ✅ {pose}.png")
        return True
    except Exception as e:
        log(f"  ⚠️ Character generation failed: {e}")
        return False


def overlay_character_on_video(video_in, video_out, format_type, total_dur):
    """
    Overlay character at bottom-right of video.
    Character changes pose at each beat timestamp.
    Uses ffmpeg overlay filter with enable expressions.
    """
    if not ensure_character_assets():
        shutil.copy(video_in, video_out)
        return False

    poses_for_format = POSE_BY_FORMAT_AND_BEAT.get(
        format_type, POSE_BY_FORMAT_AND_BEAT["default"])

    # Beat timestamps (seconds)
    beats = [0, 15, 75, 100]
    beat_ends = [15, 75, 100, total_dur]

    # Character position: bottom-right, 20px margin, scaled to 120px wide
    char_x = "W-140"   # 140px from right
    char_y = "H-160"   # 160px from bottom

    try:
        # Build filter_complex with 4 overlay segments
        filter_parts = []
        prev = "[0:v]"

        for i, (pose, start, end) in enumerate(zip(poses_for_format, beats, beat_ends)):
            char_path = f"{CHARACTER_DIR}/{pose}.png"
            if not os.path.exists(char_path):
                char_path = f"{CHARACTER_DIR}/neutral.png"

            input_idx = i + 1  # inputs: 0=video, 1-4=character PNGs
            out_label = f"[v{i}]" if i < 3 else "[vout]"

            filter_parts.append(
                f"{prev}[{input_idx}:v]overlay="
                f"x={char_x}:y={char_y}:"
                f"enable='between(t,{start},{end:.1f})'"
                f"{out_label}"
            )
            prev = out_label

        filter_str = ";".join(filter_parts)

        cmd = ["ffmpeg", "-y", "-i", video_in]
        for pose in poses_for_format:
            char_path = f"{CHARACTER_DIR}/{pose}.png"
            if not os.path.exists(char_path):
                char_path = f"{CHARACTER_DIR}/neutral.png"
            cmd.extend(["-i", char_path])
        cmd.extend([
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-c:a", "copy", video_out
        ])

        r = run(cmd, timeout=300)
        if r.returncode == 0:
            log(f"  ✅ Character overlay applied ({format_type})")
            return True
        else:
            log(f"  ⚠️ Character overlay failed: {r.stderr[-200:]}")
            shutil.copy(video_in, video_out)
            return False
    except Exception as e:
        log(f"  ⚠️ Character overlay error: {e}")
        shutil.copy(video_in, video_out)
        return False

# ═══════════════════════════════════════════════════════════════
# VIDEO CREATION
# ═══════════════════════════════════════════════════════════════

def build_video_filter(images, total_frames, fps=25, seed=0):
    import random as _r
    rng = _r.Random(seed)
    num = len(images)
    seg_frames = total_frames // num
    filters = []

    for i in range(num):
        preset = KB_PRESETS[i % len(KB_PRESETS)]
        z_expr, x_expr, y_expr, label = preset
        adj = max(int(seg_frames * rng.uniform(0.9, 1.1)), fps * 3)
        log(f"    Image {i+1}: {label}")
        filters.append(
            f"[{i}:v]loop=loop=-1:size=1:start=0,"
            f"scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={adj}:fps={fps}:s=1920x1080,"
            f"trim=0:{adj/fps:.2f},setpts=PTS-STARTPTS[v{i}]"
        )

    prev = "v0"
    xfade_dur = 0.8
    for i in range(1, num):
        transition = XFADE_TRANSITIONS[i % len(XFADE_TRANSITIONS)]
        offset = max(0.5, i * seg_frames / fps - xfade_dur)
        label  = f"x{i}"
        filters.append(
            f"[{prev}][v{i}]xfade=transition={transition}"
            f":duration={xfade_dur}:offset={offset:.2f}[{label}]"
        )
        prev = label

    return num, ";".join(filters), prev


def create_video(script_text, english_subtitles, images_input, output_name,
                 format_type="default", title_short="", bgm_path=None,
                 source_citation="", topic_val=""):
    ensure_dirs()
    ensure_fallback_image()

    script_file = f"/tmp/{output_name}_script.txt"
    voice_file  = f"/tmp/{output_name}_voice.mp3"
    human_file  = f"/tmp/{output_name}_human.mp3"
    mixed_file  = f"/tmp/{output_name}_mixed.mp3"
    raw_file    = f"/tmp/{output_name}_raw.mp4"
    overlay_file= f"/tmp/{output_name}_overlay.mp4"
    srt_file    = f"{SUBS_DIR}/{output_name}.srt"
    video_file  = f"{OUTPUT_DIR}/{output_name}_video.mp4"
    short_file  = f"{SHORTS_DIR}/{output_name}_short.mp4"

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(script_text)

    # ── Voice selection
    gender, voice_id, eq_filter = VOICE_ASSIGNMENT.get(
        format_type, VOICE_ASSIGNMENT["default"])
    log(f"🔊 Step 1/7 Voice ({gender} — {voice_id})...")
    t0 = time.time()
    try:
        r = run(["edge-tts", "--file", script_file, "--voice", voice_id,
                 "--rate=-18%", "--pitch=+0Hz", "--write-media", voice_file],
                timeout=300)
    except subprocess.TimeoutExpired:
        log("❌ TTS timeout"); return None
    if r.returncode != 0:
        log(f"❌ TTS error: {r.stderr[-200:]}"); return None
    dur = get_dur(voice_file)
    log(f"  Voice: {dur:.1f}s ({time.time()-t0:.0f}s)")

    log("🎧 Step 2/7 Voice EQ...")
    r = run(["ffmpeg", "-y", "-i", voice_file, "-af", eq_filter, human_file])
    if r.returncode != 0:
        shutil.copy(voice_file, human_file)
    dur = get_dur(human_file)

    log("🎵 Step 3/7 BGM mix...")
    if bgm_path and os.path.exists(bgm_path):
        fo  = max(0, dur - 2)
        bfo = max(0, dur - 3)
        fc = (
            "[0:a]volume=1.0,afade=t=in:st=0:d=1,afade=t=out:st={fo}:d=2[v];"
            "[1:a]volume=0.10,afade=t=in:st=0:d=3,afade=t=out:st={bfo}:d=3[b];"
            "[v][b]amix=inputs=2:duration=first:dropout_transition=2[out]"
        ).format(fo=fo, bfo=bfo)
        run(["ffmpeg", "-y", "-i", human_file, "-i", bgm_path,
             "-filter_complex", fc, "-map", "[out]", "-ac", "2", mixed_file])
        audio = mixed_file if os.path.exists(mixed_file) else human_file
    else:
        audio = human_file
    total_dur = get_dur(audio)

    log("🎬 Step 4/7 Video (Ken Burns)...")
    if isinstance(images_input, list):
        images = [f for f in images_input if os.path.exists(f)]
    else:
        images = []

    if not images and os.path.exists(OUTRO_FRAME):
        images = [OUTRO_FRAME]   # use brand banner as fallback bg
    elif not images and os.path.exists("image.png"):
        images = ["image.png"]
    if not images:
        log("❌ No images"); return None

    log(f"  Using {len(images)} images")
    fps = 25
    seed = int(hashlib.md5(output_name.encode()).hexdigest()[:8], 16)
    total_frames = max(int(total_dur * fps), fps * 5)
    num_inputs, vfilter, vlabel = build_video_filter(images, total_frames, fps, seed)

    cmd = ["ffmpeg", "-y"]
    for img in images:
        cmd.extend(["-loop", "1", "-t", str(total_dur + 2), "-i", img])
    cmd.extend(["-i", audio, "-filter_complex", vfilter,
                "-map", f"[{vlabel}]", "-map", f"{num_inputs}:a",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                "-avoid_negative_ts", "make_zero", raw_file])
    r = run(cmd, timeout=400)
    if r.returncode != 0:
        # Fallback single image
        r = run(["ffmpeg", "-y", "-loop", "1", "-i", images[0], "-i", audio,
                 "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", raw_file],
                timeout=300)
        if r.returncode != 0:
            log("❌ Video encoding failed"); return None

    log("✍️  Step 5/7 Text overlays...")
    overlay_filter = build_text_overlay(title_short, format_type)
    r = run(["ffmpeg", "-y", "-i", raw_file,
             "-vf", overlay_filter,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-c:a", "copy", overlay_file], timeout=200)
    working = overlay_file if r.returncode == 0 else raw_file

    log("📝 Step 6/7 English subtitles...")
    srt_created = False
    if english_subtitles:
        srt_path = generate_srt(english_subtitles, total_dur, srt_file)
        if srt_path:
            r = run(["ffmpeg", "-y", "-i", working,
                     "-vf", f"subtitles={srt_path}:force_style='"
                            "FontName=Arial,FontSize=20,"
                            "PrimaryColour=&H00FFFFFF,"
                            "OutlineColour=&H00000000,"
                            "BackColour=&H60000000,"
                            "Bold=1,Outline=2,Shadow=1,"
                            "Alignment=2,MarginV=50'",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                     "-c:a", "copy", video_file], timeout=200)
            if r.returncode == 0:
                srt_created = True
                log("  ✅ English subtitles burned in")
    if not srt_created:
        shutil.copy(working, video_file)

    log("🔤 Step 7/8 Source citation + bilingual hook + brand overlays...")

    # Step 7a: Source citation overlay (Beat 2 — 15s to 75s)
    citation_file = f"/tmp/{output_name}_citation.mp4"
    add_source_overlay(video_file, citation_file, source_citation, total_dur)
    if os.path.exists(citation_file) and os.path.getsize(citation_file) > 0:
        shutil.move(citation_file, video_file)

    # Step 7b: Bilingual English hook (first 5 seconds)
    bilingual_file = f"/tmp/{output_name}_bilingual.mp4"
    add_bilingual_hook_overlay(video_file, bilingual_file, topic_val, format_type)
    if os.path.exists(bilingual_file) and os.path.getsize(bilingual_file) > 0:
        shutil.move(bilingual_file, video_file)

    log("🎨 Brand overlays (logo watermark + intro + outro)...")

    # Step 7a: Logo watermark — bottom-right corner, always visible
    if os.path.exists(LOGO_WATERMARK):
        wm_file = f"/tmp/{output_name}_wm.mp4"
        r_wm = run(["ffmpeg", "-y",
                    "-i", video_file, "-i", LOGO_WATERMARK,
                    "-filter_complex",
                    "overlay=W-130:H-130:format=auto",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                    "-c:a", "copy", wm_file], timeout=300)
        if r_wm.returncode == 0:
            shutil.move(wm_file, video_file)
            log("  ✅ Logo watermark added")
        else:
            log("  ⚠️ Watermark failed — skipping")

    # Step 7b: Build intro + outro clips, then concat
    intro_clip = f"/tmp/{output_name}_intro.mp4"
    outro_clip = f"/tmp/{output_name}_outro.mp4"
    final_clip = f"/tmp/{output_name}_final.mp4"

    has_intro = make_intro_clip(intro_clip)
    has_outro = make_outro_clip(outro_clip)

    clips = []
    if has_intro and os.path.exists(intro_clip):
        clips.append(intro_clip)
    clips.append(video_file)
    if has_outro and os.path.exists(outro_clip):
        clips.append(outro_clip)

    if len(clips) > 1:
        ok = concat_clips(clips, final_clip)
        if ok and os.path.exists(final_clip):
            shutil.move(final_clip, video_file)
            log(f"  ✅ Intro({has_intro and INTRO_DURATION}s) + content + Outro({has_outro and OUTRO_DURATION}s) combined")
        else:
            log("  ⚠️ Concat failed — using content-only video")
    else:
        log("  ℹ️  No brand assets found — using content-only video")

    for f in [intro_clip, outro_clip, final_clip]:
        try:
            if os.path.exists(f): os.remove(f)
        except: pass

    log("📱 Step 8/8 Shorts (9:16 reframe)...")
    run(["ffmpeg", "-y", "-i", video_file, "-ss", "0", "-t", "58",
         "-vf", "scale=1920:1080,"
                "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
                "scale=1080:1920",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
         "-c:a", "aac", short_file], timeout=120)

    mb = os.path.getsize(video_file) / (1024*1024)
    log(f"  ✅ {video_file} ({mb:.1f}MB)")

    for f in [script_file, voice_file, human_file, mixed_file, raw_file, overlay_file]:
        try:
            if os.path.exists(f): os.remove(f)
        except: pass

    return video_file


# ═══════════════════════════════════════════════════════════════
# CONTENT GENERATION
# ═══════════════════════════════════════════════════════════════

def discover_daily_config():
    """LLM decides best topic + format for today."""
    log("🧠 LLM deciding today's topic...")
    now = datetime.datetime.now()

    finance_news  = fetch_finance_news()
    trends        = fetch_trends()
    recent_topics = load_recent_topics(10)

    slot     = os.environ.get("SLOT_HINT", "")
    pref_fmt = os.environ.get("PREFERRED_FORMATS", "")
    slot_note = ""
    if slot == "morning":
        slot_note = "TIME SLOT: Morning (7 AM IST). Prefer explainer or comparison format — calm educational tone for start of day."
    elif slot == "evening":
        slot_note = "TIME SLOT: Evening (8 PM IST). Prefer warning, story or rights format — emotional, engaging tone after work."

    prompt = DAILY_TOPIC_PROMPT.format(
        date=now.strftime("%Y-%m-%d"),
        day=now.strftime("%A"),
        finance_news=finance_news[:600],
        trends=trends[:300],
        recent_topics=", ".join(recent_topics[:5]) or "None yet",
    )
    if slot_note:
        prompt += f"\n\n{slot_note}"

    raw = call_llm(prompt)
    try:
        data = parse_json_response(raw)
        log(f"  📌 Topic: {data['topic']}")
        log(f"  🎭 Format: {data['format']}")
        log(f"  💡 Reason: {data.get('reason','')}")
        return data
    except Exception as e:
        log(f"  ⚠️ JSON parse failed ({e}) — using random evergreen")
        return {
            "topic":           random.choice(EVERGREEN_TOPICS),
            "format":          random.choice(CONTENT_FORMAT_TYPES),
            "pexels_keyword":  "default",
            "hook_angle":      "இந்த முக்கியமான தகவல் உங்களுக்கு தெரியுமா?",
            "reason":          "Fallback",
        }


def generate_script(topic, format_type, hook_angle, voice_gender):
    log(f"  📝 Script ({format_type}, {voice_gender} voice)...")
    t0 = time.time()

    def build_prompt(attempt=0):
        note = ""
        if attempt > 0:
            note = (
                f"\n\nCRITICAL — ATTEMPT {attempt+1}: Previous response was too short. "
                "You MUST write 380-420 Tamil words = ~2500-2800 characters. "
                "Beat 2 alone needs 200+ words. Write FULL complete sentences. No shortcuts."
            )
        return SCRIPT_PROMPT.format(
            topic=topic,
            format_type=format_type,
            hook_angle=hook_angle,
            voice_gender=voice_gender,
        ) + note

    text = ""
    for attempt in range(3):
        resp = call_llm(build_prompt(attempt))
        chars = len(resp.strip())
        log(f"  Attempt {attempt+1}: {chars} chars")
        if chars >= TARGET_MIN_CHARS:
            text = resp.strip()
            break
        text = resp.strip()
        if attempt < 2:
            log(f"  Too short ({chars} < {TARGET_MIN_CHARS}) — retrying...")
            time.sleep(3)

    if len(text) > TARGET_MAX_CHARS:
        log(f"  Trimming {len(text)} → {TARGET_MAX_CHARS} chars")
        trimmed = text[:TARGET_MAX_CHARS]
        for punct in [".\n", ". ", "\n\n"]:
            idx = trimmed.rfind(punct)
            if idx > TARGET_MIN_CHARS:
                trimmed = trimmed[:idx+1]
                break
        text = trimmed

    log(f"  ✅ Script: {len(text)} chars in {time.time()-t0:.0f}s")
    return text


def generate_mcq(topic, script):
    """Generate an MCQ quiz question from the video script."""
    try:
        # Extract a key fact from script (first 500 chars has the hook + key claim)
        key_fact = script[:500].strip()
        prompt = MCQ_PROMPT.format(topic=topic, key_fact=key_fact)
        raw = call_llm(prompt).strip()
        # Validate it has MCQ structure
        if "A)" in raw and "B)" in raw and "comment" in raw.lower():
            log(f"  ✅ MCQ generated")
            return raw
        return ""
    except Exception as e:
        log(f"  ⚠️ MCQ generation failed: {e}")
        return ""


def generate_subtitles(tamil_script):
    """Translate Tamil script to English subtitle lines."""
    log("  🌐 Generating English subtitles...")
    prompt = SUBTITLE_PROMPT.format(tamil_script=tamil_script[:2000])
    raw = call_llm(prompt)
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    log(f"  ✅ {len(lines)} subtitle lines")
    return lines


def generate_metadata(topic, format_type, hook_angle):
    log("  📋 Generating metadata...")
    prompt = METADATA_PROMPT.format(
        topic=topic,
        format_type=format_type,
        hook_angle=hook_angle,
    )
    raw = call_llm(prompt)
    try:
        return parse_json_response(raw)
    except Exception as e:
        log(f"  ⚠️ Metadata JSON parse failed ({e}) — using structured fallback")
        return {
            "title": f"{topic[:55]} | {CHANNEL_NAME}",
            "description": (
                f"{hook_angle}\n"
                f"Learn about {topic} in Tamil | {CHANNEL_NAME}\n\n"
                f"0:00 Introduction\n"
                f"0:15 {topic[:40]}\n"
                f"0:45 விரிவான விளக்கம்\n"
                f"1:30 நீங்கள் என்ன செய்யவேண்டும்\n"
                f"1:50 Subscribe & Share\n\n"
                f"இந்த video-ல் நீங்கள் கற்றுக்கொள்வது:\n"
                f"✅ {topic} பற்றிய முழு தகவல்\n"
                f"✅ உங்களுக்கு என்ன பலன்\n"
                f"✅ இப்போதே எடுக்க வேண்டிய action\n\n"
                f"⚠️ இந்த video educational purpose மட்டுமே. Financial advice இல்லை.\n\n"
                f"🔔 Subscribe: @NidhiNeethiTamil\n\n"
                f"#நிதிநீதிதமிழ் #NidhiNeethiTamil #TamilFinance #TamilLegalRights #PersonalFinanceTamil"
            ),
            "tags": (
                "tamil finance, personal finance tamil, cibil score tamil, "
                "tamil money tips, tamil investment, நிதி நீதி தமிழ், "
                "NidhiNeethiTamil, tamil banking guide, loan tips tamil, "
                f"{topic[:30]}, finance tamil 2026"
            ),
            "pinned_comment": (
                f"இந்த topic பற்றி உங்கள் அனுபவம் என்ன? Comment பண்ணுங்கள் 👇\n"
                f"நிதி நீதி தமிழ்-ஐ subscribe பண்ணி bell icon click பண்ணுங்கள் 🔔"
            ),
            "thumbnail_concept": (
                f"Deep blue background. Bold Tamil text: '{topic[:30]}'. "
                "Right side: rupee symbol or relevant icon. High contrast."
            ),
        }



# ═══════════════════════════════════════════════════════════════
# PLAYLIST CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Maps format/topic keywords → playlist name
# Playlists are auto-created on first run, then cached
PLAYLIST_DEFINITIONS = {
    "loan_emi": {
        "name":        "கடன் & EMI வழிகாட்டி | Loan & EMI Guide",
        "description": "Personal loan, home loan, car loan, EMI calculation, prepayment strategies — complete Tamil guide.",
        "keywords":    ["loan", "emi", "கடன்", "home loan", "personal loan", "car loan", "mortgage", "prepayment"],
    },
    "legal_rights": {
        "name":        "உங்கள் உரிமைகள் | Your Legal Rights",
        "description": "Consumer rights, RTI, tenant rights, police rights, bank rights — know your rights in Tamil.",
        "keywords":    ["rights", "உரிமை", "consumer", "court", "legal", "complaint", "RTI", "police", "tenant"],
    },
    "investment": {
        "name":        "முதலீடு & சேமிப்பு | Investment & Savings",
        "description": "Mutual funds, SIP, FD, RD, gold, stocks — Tamil investment guide for beginners.",
        "keywords":    ["investment", "mutual fund", "SIP", "FD", "RD", "gold", "stocks", "சேமிப்பு", "முதலீடு"],
    },
    "banking_cibil": {
        "name":        "வங்கி & CIBIL அறிவு | Banking & Credit",
        "description": "CIBIL score, credit cards, bank accounts, UPI, net banking — complete banking guide in Tamil.",
        "keywords":    ["cibil", "credit", "bank", "atm", "upi", "credit card", "வங்கி", "account"],
    },
    "govt_schemes": {
        "name":        "அரசு திட்டங்கள் | Govt Schemes",
        "description": "PM Kisan, Aadhaar, PF, EPF, insurance schemes, subsidy — Tamil Nadu and Central government schemes.",
        "keywords":    ["scheme", "govt", "government", "pm kisan", "aadhaar", "epf", "pf", "subsidy", "திட்டம்"],
    },
    "fraud_warning": {
        "name":        "மோசடி எச்சரிக்கை | Fraud Warnings",
        "description": "UPI fraud, online scam, investment fraud, loan fraud — protect yourself with awareness.",
        "keywords":    ["fraud", "scam", "மோசடி", "warning", "alert", "fake", "cheat", "phishing"],
    },
}

PLAYLIST_CACHE_FILE = "playlist_ids.json"


def load_playlist_cache():
    if os.path.exists(PLAYLIST_CACHE_FILE):
        with open(PLAYLIST_CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_playlist_cache(cache):
    with open(PLAYLIST_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_or_create_playlist(youtube, playlist_key):
    """Get existing playlist ID or create new one. Returns playlist_id."""
    cache = load_playlist_cache()
    if playlist_key in cache:
        return cache[playlist_key]

    defn = PLAYLIST_DEFINITIONS.get(playlist_key)
    if not defn:
        return None

    try:
        # Check if playlist already exists
        resp = youtube.playlists().list(
            part="snippet", mine=True, maxResults=50).execute()
        for item in resp.get("items", []):
            if item["snippet"]["title"] == defn["name"]:
                pid = item["id"]
                cache[playlist_key] = pid
                save_playlist_cache(cache)
                log(f"  ✅ Found existing playlist: {defn['name'][:40]}")
                return pid

        # Create new playlist
        resp = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title":       defn["name"],
                    "description": defn["description"],
                },
                "status": {"privacyStatus": "public"},
            }
        ).execute()
        pid = resp["id"]
        cache[playlist_key] = pid
        save_playlist_cache(cache)
        log(f"  ✅ Created playlist: {defn['name'][:40]} ({pid})")
        return pid

    except Exception as e:
        log(f"  ⚠️ Playlist error: {e}")
        return None


def detect_playlist(topic, format_type):
    """Detect which playlist this video belongs to based on topic keywords."""
    topic_lower = topic.lower()
    for key, defn in PLAYLIST_DEFINITIONS.items():
        for kw in defn["keywords"]:
            if kw.lower() in topic_lower:
                return key
    # Fallback by format
    format_map = {
        "warning":    "fraud_warning",
        "rights":     "legal_rights",
        "explainer":  "banking_cibil",
        "comparison": "investment",
        "news":       "banking_cibil",
        "story":      "legal_rights",
    }
    return format_map.get(format_type, "banking_cibil")


def add_video_to_playlist(youtube, video_id, topic, format_type):
    """Add uploaded video to the correct playlist."""
    playlist_key = detect_playlist(topic, format_type)
    log(f"  📂 Playlist: {playlist_key}")
    playlist_id = get_or_create_playlist(youtube, playlist_key)
    if not playlist_id:
        return

    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind":    "youtube#video",
                        "videoId": video_id,
                    },
                }
            }
        ).execute()
        log(f"  ✅ Added to playlist: {PLAYLIST_DEFINITIONS[playlist_key]['name'][:40]}")
    except Exception as e:
        log(f"  ⚠️ Playlist add failed: {e}")


MCQ_PROMPT = """Generate a fun multiple-choice quiz question for a Tamil YouTube finance video.

Topic: {topic}
Key fact from video: {key_fact}

Rules:
1. Question must test ONE specific fact from this exact topic
2. 4 options (A, B, C, D) — only one correct
3. Options must be plausible — not obviously wrong
4. Write entirely in Tamil (numbers in English are OK)
5. Keep it short — max 3 lines total
6. End with "சரியான answer comment பண்ணுங்கள் 👇"

Format exactly like this:
[Question in Tamil]?
A) [option]  B) [option]
C) [option]  D) [option]
சரியான answer comment பண்ணுங்கள் 👇

Return ONLY the quiz text, nothing else."""

# ═══════════════════════════════════════════════════════════════
# SERIES FORMAT — auto-detect and link related videos
# ═══════════════════════════════════════════════════════════════

SERIES_FILE = "video_series.json"

SERIES_TOPIC_GROUPS = {
    "cibil":       ["cibil", "credit score", "கிரெடிட்", "loan eligibility"],
    "loan":        ["loan", "கடன்", "emi", "interest", "வட்டி", "personal loan", "home loan"],
    "investment":  ["mutual fund", "sip", "fd", "rd", "investment", "முதலீடு", "stock"],
    "rights":      ["rights", "உரிமை", "consumer court", "complaint", "rti", "police"],
    "fraud":       ["fraud", "மோசடி", "scam", "upi fraud", "phishing", "fake"],
    "tax":         ["tax", "வரி", "income tax", "gst", "itr", "pan"],
    "insurance":   ["insurance", "காப்பீடு", "claim", "health insurance", "life insurance"],
    "bank":        ["bank", "வங்கி", "account", "savings", "atm", "net banking"],
}


def detect_series_group(topic):
    """Detect which series group this topic belongs to."""
    topic_lower = topic.lower()
    for group, keywords in SERIES_TOPIC_GROUPS.items():
        if any(kw in topic_lower for kw in keywords):
            return group
    return None


def load_series_data():
    if os.path.exists(SERIES_FILE):
        with open(SERIES_FILE) as f:
            return json.load(f)
    return {}


def save_series_data(data):
    with open(SERIES_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Commit to git so it persists across CI runs
    try:
        run(["git", "add", SERIES_FILE])
        run(["git", "commit", "-m", "chore: update series data"])
        run(["git", "push"])
    except:
        pass


def get_series_info(topic, video_id=None):
    """
    Returns (part_number, total_in_series, series_title, prev_video_id).
    Adds this video to series tracking.
    """
    group = detect_series_group(topic)
    if not group:
        return None, None, None, None

    data = load_series_data()
    if group not in data:
        data[group] = []

    series = data[group]
    part_num = len(series) + 1

    # Build series title
    series_titles = {
        "cibil":      "CIBIL Score முழு வழிகாட்டி",
        "loan":       "கடன் அறிவு தொடர்",
        "investment": "முதலீடு அடிப்படை தொடர்",
        "rights":     "உங்கள் உரிமைகள் தொடர்",
        "fraud":      "மோசடி எச்சரிக்கை தொடர்",
        "tax":        "வரி அறிவு தொடர்",
        "insurance":  "காப்பீடு வழிகாட்டி தொடர்",
        "bank":       "வங்கி அறிவு தொடர்",
    }
    series_title = series_titles.get(group, f"{group} தொடர்")

    prev_video_id = series[-1]["video_id"] if series else None

    if video_id:
        series.append({
            "part":     part_num,
            "topic":    topic,
            "video_id": video_id,
            "date":     datetime.datetime.now().isoformat(),
        })
        data[group] = series
        save_series_data(data)

    return part_num, len(series), series_title, prev_video_id


def build_series_end_card(part_num, series_title, prev_video_id):
    """Returns text to append to description for series navigation."""
    if part_num == 1:
        return f"\n\n📚 இது '{series_title}' தொடரின் முதல் பாகம்."
    else:
        prev_url = f"https://youtu.be/{prev_video_id}" if prev_video_id else ""
        return (
            f"\n\n📚 {series_title} — பாகம் {part_num}\n"
            f"முந்தைய பாகம்: {prev_url}"
        )


def build_series_script_ending(part_num, series_title, next_topic_hint=""):
    """Returns script lines to append for series continuity."""
    if part_num == 1:
        return f"இது {series_title} தொடரின் முதல் பாகம். அடுத்த பாகம் விரைவில் வருகிறது."
    return ""


# ═══════════════════════════════════════════════════════════════
# SOURCE CITATION — credibility overlay during core info beat
# ═══════════════════════════════════════════════════════════════

SOURCE_PROMPT = """Given this Tamil finance video topic, identify the authoritative source.

Topic: {topic}
Format: {format_type}

Return ONLY a short source attribution (max 40 chars English):
- For RBI-related: "Source: RBI.org.in"
- For consumer rights: "Source: ConsumerAffairs.nic.in"
- For tax: "Source: IncomeTax.gov.in"
- For EPFO/PF: "Source: EPFO.gov.in"
- For SEBI/investments: "Source: SEBI.gov.in"
- For insurance: "Source: IRDAI.gov.in"
- For general finance: "Source: RBI.org.in"
- For legal/consumer court: "Source: NCDRCIndia.nic.in"

Return ONLY the source string, nothing else."""


def get_source_citation(topic, format_type):
    """Get the authoritative source for this topic."""
    try:
        prompt = SOURCE_PROMPT.format(topic=topic, format_type=format_type)
        raw = call_llm(prompt).strip().strip('"').strip("'")
        # Validate it looks like a source
        if "Source:" in raw and len(raw) < 50:
            return raw
        return "Source: RBI.org.in"
    except:
        return "Source: RBI.org.in"


def add_source_overlay(video_in, video_out, source_text, total_dur):
    """
    Add source citation badge during Beat 2 (15s-75s).
    Small text bottom-left, semi-transparent — builds trust without distraction.
    """
    safe_source = source_text.replace("'", "").replace(":", " -")
    # Show during core info beat: 15s to min(75s, total_dur-5s)
    show_start = 15
    show_end   = min(75, total_dur - 5)

    if show_end <= show_start:
        shutil.copy(video_in, video_out)
        return False

    vf = (
        f"drawtext=text='{safe_source}':fontsize=18:"
        f"fontcolor=white@0.70:x=20:y=h-45:"
        f"shadowcolor=black@0.8:shadowx=1:shadowy=1:"
        f"enable='between(t,{show_start},{show_end:.0f})'"
    )
    r = run(["ffmpeg", "-y", "-i", video_in,
             "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-c:a", "copy", video_out], timeout=200)
    if r.returncode == 0:
        log(f"  ✅ Source citation: {source_text}")
        return True
    shutil.copy(video_in, video_out)
    return False


# ═══════════════════════════════════════════════════════════════
# BILINGUAL HOOK — English text overlay for first 5 seconds
# Catches non-Tamil search traffic + YouTube English indexing
# ═══════════════════════════════════════════════════════════════

def add_bilingual_hook_overlay(video_in, video_out, topic, format_type):
    """
    Show English hook text for first 5 seconds of video.
    This helps YouTube index the video for English search terms.
    """
    # Map format to English hook phrase
    hooks = {
        "warning":    "MUST WATCH before you apply for a loan",
        "explainer":  "Complete guide explained in Tamil",
        "rights":     "Know your legal rights — explained in Tamil",
        "comparison": "Which is better? Find out in Tamil",
        "story":      "Real story — what happened and what you can learn",
        "news":       "Breaking finance news explained in Tamil",
    }
    hook_phrase = hooks.get(format_type, "Tamil finance guide")

    # Shorten topic for English subtitle
    topic_en_words = topic.replace("?", "").strip()[:30]

    safe_hook = hook_phrase.replace("'", "").replace(":", " -")

    vf = (
        f"drawtext=text='{safe_hook}':fontsize=28:"
        f"fontcolor=yellow@0.95:x=(w-tw)/2:y=40:"
        f"shadowcolor=black@0.9:shadowx=2:shadowy=2:"
        f"enable='between(t,0,5)'"
    )
    r = run(["ffmpeg", "-y", "-i", video_in,
             "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-c:a", "copy", video_out], timeout=200)
    if r.returncode == 0:
        log(f"  ✅ Bilingual hook: {hook_phrase}")
        return True
    shutil.copy(video_in, video_out)
    return False


# ═══════════════════════════════════════════════════════════════
# UPDATE COMMENT BOT — checks old videos for outdated facts
# Run separately: python nidhi_neethi_bot.py --check-updates
# ═══════════════════════════════════════════════════════════════

UPDATE_CHECK_FILE = "update_checks.json"

UPDATE_CHECK_PROMPT = """You are a Tamil finance fact-checker.

Old video topic: {topic}
Video published: {date}
Current date: {today}

Based on the topic, check if any of these might have changed since publication:
- RBI repo rate or bank interest rates
- CIBIL score requirements
- Consumer protection laws
- Tax slabs or deductions
- EPF/PF rules
- Insurance regulations

Return JSON only:
{{
  "needs_update": true/false,
  "update_comment": "<Tamil comment under 200 chars if update needed, else empty string>",
  "reason": "<brief English reason>"
}}

If needs_update is false, return empty string for update_comment."""


def load_update_checks():
    if os.path.exists(UPDATE_CHECK_FILE):
        with open(UPDATE_CHECK_FILE) as f:
            return json.load(f)
    return {}


def save_update_checks(data):
    with open(UPDATE_CHECK_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        run(["git", "add", UPDATE_CHECK_FILE])
        run(["git", "commit", "-m", "chore: update checks log"])
        run(["git", "push"])
    except:
        pass


def post_update_comment(youtube, video_id, comment_text):
    """Post an update comment on a video."""
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "topLevelComment": {
                "snippet": {"textOriginal": comment_text}
            }}}).execute()
        log(f"  ✅ Update comment posted on {video_id}")
        return True
    except Exception as e:
        log(f"  ⚠️ Comment failed: {e}")
        return False


def run_update_checks():
    """
    Check all tracked videos for outdated information.
    Posts update comments on videos where facts may have changed.
    Only checks videos older than 30 days, max 5 per run.
    """
    log("🔄 Running update checks on published videos...")
    youtube = get_authenticated_service()
    if not youtube:
        log("⚠️ YouTube auth required for update checks")
        return

    checks = load_update_checks()
    today  = datetime.datetime.now().strftime("%Y-%m-%d")

    # Load published video history from metadata dir
    if not os.path.isdir(METADATA_DIR):
        log("No metadata found — skipping update checks")
        return

    checked = 0
    for meta_file in sorted(Path(METADATA_DIR).glob("*.json"), reverse=True):
        if checked >= 5:
            break
        try:
            meta = json.loads(meta_file.read_text())
            vid_id = meta.get("video_id", "")
            topic  = meta.get("topic", "")
            date   = meta.get("created", "")[:10]

            if not vid_id or not topic or not date:
                continue

            # Skip recently published (< 30 days)
            try:
                pub_date = datetime.datetime.fromisoformat(date)
                days_old = (datetime.datetime.now() - pub_date).days
                if days_old < 30:
                    continue
            except:
                continue

            # Skip already checked recently (within 7 days)
            last_check = checks.get(vid_id, {}).get("last_check", "")
            if last_check:
                try:
                    lc = datetime.datetime.fromisoformat(last_check)
                    if (datetime.datetime.now() - lc).days < 7:
                        continue
                except:
                    pass

            log(f"  Checking: {topic[:50]} ({days_old} days old)")
            prompt = UPDATE_CHECK_PROMPT.format(
                topic=topic, date=date, today=today)
            raw = call_llm(prompt)

            try:
                result = parse_json_response(raw)
                checks[vid_id] = {
                    "last_check":    today,
                    "needs_update":  result.get("needs_update", False),
                    "reason":        result.get("reason", ""),
                }

                if result.get("needs_update") and result.get("update_comment"):
                    comment = (
                        f"📢 UPDATE ({today}): {result['update_comment']}\n"
                        f"நிதி நீதி தமிழ் — புதுப்பிக்கப்பட்ட தகவல்"
                    )
                    post_update_comment(youtube, vid_id, comment)
                    log(f"  ✅ Update: {result.get('reason','')}")
                else:
                    log(f"  ✅ No update needed: {result.get('reason','up to date')}")

                checked += 1

            except Exception as e:
                log(f"  ⚠️ Parse failed: {e}")

        except Exception as e:
            log(f"  ⚠️ Check failed: {e}")

    save_update_checks(checks)
    log(f"✅ Update checks done ({checked} videos checked)")

# ═══════════════════════════════════════════════════════════════
# YOUTUBE AUTH & UPLOAD
# ═══════════════════════════════════════════════════════════════

def get_authenticated_service():
    creds = None
    b64 = os.environ.get("YOUTUBE_TOKEN_BASE64")
    if b64:
        try:
            creds = pickle.loads(base64.b64decode(b64))
        except: pass

    if not creds and os.path.exists(YOUTUBE_TOKEN_FILE):
        with open(YOUTUBE_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                log(f"⚠️ Token refresh failed: {e}")
                return None
        else:
            if not os.path.exists(YOUTUBE_CLIENT_SECRETS):
                log(f"⚠️ {YOUTUBE_CLIENT_SECRETS} not found — skipping upload")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
                creds = flow.run_local_server(port=8080)
            except Exception as e:
                log(f"⚠️ OAuth flow failed: {e}"); return None
        try:
            with open(YOUTUBE_TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
        except: pass

    try:
        return build("youtube", "v3", credentials=creds)
    except Exception as e:
        log(f"⚠️ YouTube service error: {e}"); return None


def upload_to_youtube(video_path, metadata, privacy="public"):
    if not os.path.exists(video_path):
        log(f"❌ Video not found: {video_path}"); return None

    youtube = get_authenticated_service()
    if not youtube:
        log("⚠️ YouTube auth failed — skipping upload"); return None

    body = {
        "snippet": {
            "title":       metadata.get("title", "")[:100],
            "description": metadata.get("description", "")[:5000],
            "tags":        [t.strip() for t in
                           metadata.get("tags", "").split(",")][:30],
            "categoryId":  "27",
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        t0 = time.time()
        req = youtube.videos().insert(
            part="snippet,status", body=body,
            media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True))
        resp = req.execute()
        vid = resp["id"]
        log(f"✅ Uploaded: https://youtu.be/{vid} ({time.time()-t0:.0f}s)")

        if metadata.get("pinned_comment"):
            try:
                youtube.commentThreads().insert(
                    part="snippet",
                    body={"snippet": {"videoId": vid, "topLevelComment": {
                        "snippet": {"textOriginal": metadata["pinned_comment"]}
                    }}}).execute()
                log("  ✅ Pinned comment set")
            except: pass

        # Auto-add to correct playlist
        topic_val   = metadata.get("topic", "")
        format_type = metadata.get("format", "default")
        add_video_to_playlist(youtube, vid, topic_val, format_type)

        # Register video_id in series tracker
        get_series_info(topic_val, video_id=vid)

        # Save video_id into metadata file for update checker
        safe = hashlib.md5(topic_val.encode()).hexdigest()[:10]
        meta_path = f"{METADATA_DIR}/{safe}.json"
        if os.path.exists(meta_path):
            try:
                m = json.loads(Path(meta_path).read_text())
                m["video_id"] = vid
                Path(meta_path).write_text(
                    json.dumps(m, ensure_ascii=False, indent=2))
            except: pass

        return vid
    except Exception as e:
        log(f"❌ Upload failed: {e}"); return None


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def process_video(topic=None, format_type=None, upload=False, privacy="public"):
    ensure_dirs()
    t_start = time.time()

    # Step 1: Decide topic
    if topic:
        config = {
            "topic":          topic,
            "format":         format_type or random.choice(CONTENT_FORMAT_TYPES),
            "pexels_keyword": "default",
            "hook_angle":     "இந்த முக்கியமான தகவல் உங்களுக்கு தெரியுமா?",
        }
    else:
        config = discover_daily_config()

    topic_val     = config["topic"]
    fmt           = config["format"]
    pexels_kw     = config.get("pexels_keyword", "default")
    hook_angle    = config.get("hook_angle", "")
    gender, _, _  = VOICE_ASSIGNMENT.get(fmt, VOICE_ASSIGNMENT["default"])

    log(f"{'='*55}")
    log(f"  {CHANNEL_NAME}")
    log(f"  Topic: {topic_val}")
    log(f"  Format: {fmt} | Voice: {gender}")
    log(f"{'='*55}")

    # Persist topic so future runs avoid repeating it
    save_used_topic(topic_val)

    # Step 2: Fetch images
    safe_name = hashlib.md5(topic_val.encode()).hexdigest()[:10]
    img_dir   = os.path.join(PEXELS_DIR, safe_name)
    log("📸 Fetching Pexels images...")
    images = fetch_pexels_images(pexels_kw, img_dir, count=5)
    if not images:
        ensure_fallback_image()
        images = ["image.png"] if os.path.exists("image.png") else []

    # Step 3: Generate BGM
    bgm_path = ensure_bgm(fmt)

    # Step 4: Generate script first (most critical), then metadata
    # Sequential not parallel — avoids double Groq 429 rate limit hits
    log("🤖 Step 1: Generating script...")
    script = generate_script(topic_val, fmt, hook_angle, gender)

    log("🤖 Step 2: Generating subtitles + metadata + MCQ (parallel)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        sf  = pool.submit(generate_subtitles, script)
        mf  = pool.submit(generate_metadata, topic_val, fmt, hook_angle)
        mcf = pool.submit(generate_mcq, topic_val, script)
        subtitle_lines = sf.result()
        metadata       = mf.result()
        mcq_text       = mcf.result()

    # Merge MCQ into pinned comment
    if mcq_text:
        existing_pin = metadata.get("pinned_comment", "")
        metadata["pinned_comment"] = f"{mcq_text}\n\n{existing_pin}".strip()
        log(f"  ✅ MCQ added to pinned comment")

    # Step 5: Save script + metadata
    title_short = metadata.get("title", topic_val)[:50]

    # Series detection — enrich description with series navigation
    part_num, series_len, series_title, prev_vid = get_series_info(topic_val)
    if part_num and part_num > 1:
        series_end = build_series_end_card(part_num, series_title, prev_vid)
        metadata["description"] = metadata.get("description", "") + series_end
        title_short = f"பாகம் {part_num}: {title_short}"
        log(f"  📚 Series: {series_title} — Part {part_num}")
    elif part_num == 1:
        log(f"  📚 New series started: {series_title}")

    # Source citation for trust overlay
    source_citation = get_source_citation(topic_val, fmt)

    with open(f"{SCRIPTS_DIR}/{safe_name}.txt", "w", encoding="utf-8") as f:
        f.write(f"TOPIC: {topic_val}\nFORMAT: {fmt}\n\n{script}")

    meta_data = {
        "topic": topic_val, "format": fmt, "title": metadata.get("title"),
        "description": metadata.get("description"),
        "tags": metadata.get("tags"),
        "pinned_comment": metadata.get("pinned_comment"),
        "thumbnail_concept": metadata.get("thumbnail_concept"),
        "created": datetime.datetime.now().isoformat(),
    }
    # Inject topic+format for playlist detection at upload time
    metadata["topic"]  = topic_val
    metadata["format"] = fmt
    with open(f"{METADATA_DIR}/{safe_name}.json", "w", encoding="utf-8") as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)

    log(f"  Title: {metadata.get('title','')[:60]}")
    log(f"  Thumbnail: {metadata.get('thumbnail_concept','')[:80]}")

    # Step 6: Create video
    log("🎬 Creating video...")
    video = create_video(
        script_text=script,
        english_subtitles=subtitle_lines,
        images_input=images,
        output_name=safe_name,
        format_type=fmt,
        title_short=title_short,
        bgm_path=bgm_path,
        source_citation=source_citation,
        topic_val=topic_val,
    )

    elapsed = time.time() - t_start
    if video:
        log(f"✅ VIDEO: {video}")
        log(f"✅ SHORT: {SHORTS_DIR}/{safe_name}_short.mp4")
        log(f"⏱️  Total: {elapsed:.0f}s")

        if upload:
            log("⬆️ Uploading to YouTube...")
            try:
                vid = upload_to_youtube(video, metadata, privacy)
                if vid:
                    log(f"✅ Live: https://youtu.be/{vid}")
            except Exception as e:
                log(f"⚠️ Upload failed (non-fatal): {e}")
    else:
        log(f"❌ Video creation failed ({elapsed:.0f}s)")

    return video


def auth_youtube():
    log("Authenticating YouTube...")
    svc = get_authenticated_service()
    if svc:
        log(f"✅ Token saved: {YOUTUBE_TOKEN_FILE}")
    return svc


# ═══════════════════════════════════════════════════════════════
# DAEMON
# ═══════════════════════════════════════════════════════════════

def daemon_mode():
    if not HAS_SCHEDULE:
        print("pip install schedule"); sys.exit(1)

    log("=" * 55)
    log(f"  {CHANNEL_NAME} BOT — DAEMON MODE")
    log(f"  Daily: 05:30 IST generate | 06:00 + 18:30 upload")
    log("=" * 55)

    def daily_job():
        log("⏰ Daily job triggered")
        video = process_video(upload=False)
        if video:
            q = load_queue()
            meta_files = sorted(Path(METADATA_DIR).glob("*.json"), reverse=True)
            meta = json.loads(meta_files[0].read_text()) if meta_files else {}
            q.append({"video_path": video, "metadata": meta,
                      "created": datetime.datetime.now().isoformat(),
                      "status": "pending"})
            save_queue(q)

    def upload_job():
        q = load_queue()
        pending = [x for x in q if x.get("status") == "pending"]
        for item in pending:
            if os.path.exists(item["video_path"]):
                vid = upload_to_youtube(item["video_path"], item.get("metadata", {}))
                if vid:
                    item["status"] = "uploaded"
                    item["video_id"] = vid
        save_queue(q)

    schedule.every().day.at("05:30").do(daily_job)
    schedule.every().day.at("06:00").do(upload_job)
    schedule.every().day.at("18:30").do(upload_job)

    daily_job()
    upload_job()

    while True:
        schedule.run_pending()
        time.sleep(30)


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def main():
    if not GEMINI_KEY and not GROQ_API_KEY:
        print("ERROR: Set GEMINI_KEY or GROQ_API_KEY"); sys.exit(1)

    parser = argparse.ArgumentParser(description="நிதி நீதி தமிழ் Bot v1.0")
    parser.add_argument("--day",          help="today / all")
    parser.add_argument("--topic",        help="Custom topic in Tamil")
    parser.add_argument("--format",       help="warning/explainer/rights/comparison/story/news")
    parser.add_argument("--upload",       action="store_true")
    parser.add_argument("--privacy",      default="public",
                        choices=["public", "unlisted", "private"])
    parser.add_argument("--daemon",       action="store_true")
    parser.add_argument("--auth-youtube", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  {CHANNEL_NAME} — Automation Bot v1.0")
    print(f"  2-min videos · English subs · Male+Female voices")
    print(f"{'='*55}\n")

    if args.auth_youtube:
        auth_youtube(); return

    if args.check_updates:
        run_update_checks(); return

    if args.daemon:
        daemon_mode(); return

    if args.topic:
        process_video(topic=args.topic, format_type=args.format,
                      upload=args.upload, privacy=args.privacy)
    elif args.day:
        process_video(upload=args.upload, privacy=args.privacy)
    else:
        print("Usage:")
        print("  python nidhi_neethi_bot.py --day today")
        print("  python nidhi_neethi_bot.py --day today --upload")
        print("  python nidhi_neethi_bot.py --topic 'CIBIL score எப்படி சரிசெய்வது'")
        print("  python nidhi_neethi_bot.py --daemon")
        print("  python nidhi_neethi_bot.py --auth-youtube")

    print(f"\n{'='*55}")
    print(f"  Done! Check: studio.youtube.com")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
