#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          நிதி நீதி தமிழ் — FULLY AUTOMATED BOT v1.9            ║
║  Tamil Finance & Legal Rights YouTube Channel                   ║
║  Thumbnail · Comments · NRI · Analytics · Community tab        ║
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
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GH_MODEL       = "gpt-4o-mini"

GROQ_MODEL   = "llama-3.3-70b-versatile"
GEMINI_MODEL_ECONOMY  = "gemini-1.5-flash"
GEMINI_MODEL_STANDARD = "gemini-2.0-flash"
GEMINI_MODEL_PREMIUM  = "gemini-2.5-flash"
_QUOTA_EXHAUSTED = False
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
TARGET_MIN_CHARS = 3500
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

YOUTUBE RETENTION RULES (follow these — they affect algorithm ranking):
1. HOOK (0-15s): Must deliver EXACTLY what the title/thumbnail promises.
   Start with the most surprising fact or the exact answer preview.
   Bad: "வணக்கம், இன்று நாம் பேசப்போவது..."
   Good: "உங்கள் CIBIL score நேற்று இரவு drop ஆயிருக்கு. காரணம் தெரியுமா?"

2. PATTERN INTERRUPT (every 30s): Change energy, pace, or angle.
   Use phrases like "ஆனால் இதில் ஒரு twist இருக்கு..." or "இதை யாரும் சொல்ல மாட்டாங்க..."

3. OPEN LOOP: Create curiosity that isn't resolved until Beat 3.
   Example in Beat 1: "இந்த ஒரு mistake செய்தால் உங்கள் loan reject ஆகும் — Beat 3-ல் சொல்கிறேன்"

4. SPECIFIC NUMBERS: "73% of Indians", "₹2,340 கோடி", "exactly 48 hours"
   Vague content loses viewers. Specific numbers build trust.

5. CTA at Beat 4: Don't beg for likes. Create FOMO:
   "நாளை இதே தலைப்பில் part 2 — subscribe பண்ணாவிட்டால் miss ஆகும்"
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

MONETISATION-FOCUSED SEO RULES:

TITLE (critical for CTR — 60% of views come from title+thumbnail):
- Must create curiosity OR promise clear benefit
- Use numbers: "5 வழிகள்", "இந்த 1 mistake", "₹50,000 சேமிக்க"
- Question format gets 23% higher CTR: "CIBIL score drop ஆனால் என்ன நடக்கும்?"
- Power words: உண்மை, தெரியாத, இலவசம், உடனே, இப்பவே

DESCRIPTION LINE 1 (= Google/YouTube search snippet):
Write the hook question or key benefit here — viewers decide to click from this.

DESCRIPTION LINE 2 (= reinforces click decision):
"Learn [exact topic] in Tamil | Complete guide by நிதி நீதி தமிழ்"

CHAPTER TIMESTAMPS (YouTube shows these as "Key moments" in search):
Must match actual script beats. Use real times not placeholders.

TAGS: Mix Tamil search terms + English equivalents
Example: "CIBIL score" + "credit score tamil" + "how to improve cibil score in tamil"
"""

RESPONDED_COMMENTS_FILE = "responded_comments.json"

COMMENT_RESPONSE_PROMPT = """You are a friendly Indian Tamil YouTuber responding to viewer comments. Keep responses warm, grateful, and conversational in Tamil with occasional English (Tanglish). Be concise (1-3 sentences). Thank them genuinely. Avoid sounding robotic or promotional."""

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


def deduplicate_topic(topic):
    """Hard check: if topic was already used, append date to differentiate."""
    used = load_recent_topics(60)
    if topic in used:
        date_str = datetime.datetime.now().strftime("%d-%b-%Y")
        deduped = f"{topic} — {date_str}"
        log(f"  🚫 Topic already used → adjusted to: {deduped}")
        return deduped
    return topic


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


# ═══════════════════════════════════════════════════════════════
# LLM ROUTER — Groq reserved for scripts only
# Gemini Flash handles everything else (topic, metadata, MCQ etc)
# This keeps Groq usage under 15K tokens/day well within 100K limit
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# LLM ROUTER — Groq for scripts only, Gemini for everything else
# Keeps Groq daily usage ~26K/100K tokens (was 96K+)
# ═══════════════════════════════════════════════════════════════

def _call_gemini(prompt_text, model_name=GEMINI_MODEL_ECONOMY):
    global _QUOTA_EXHAUSTED
    if _QUOTA_EXHAUSTED:
        return ""
    import time
    import random
    if not GEMINI_KEY:
        raise Exception("GEMINI_KEY not set")
    client = genai.Client(api_key=GEMINI_KEY)
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            resp = client.models.generate_content(
                model=model_name, contents=prompt_text)
            return resp.text
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                _QUOTA_EXHAUSTED = True
                log(f"Quota exhausted on {model_name}. Attempt {attempt+1}/{max_attempts}")
                if attempt < max_attempts - 1:
                    sleep_time = random.uniform(15, 25) * (2 ** attempt)
                    log(f"Backing off {sleep_time:.0f}s before retry...")
                    time.sleep(sleep_time)
                    continue
            elif "404" in err_str or "NOT_FOUND" in err_str:
                log(f"Model {model_name} not found, skipping")
                return ""
            else:
                log(f"Gemini call failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(5)
                    continue
            return ""
    return ""


def _call_groq(prompt, max_retries=3):
    """Groq — quality model, used ONLY for script generation."""
    if not (GROQ_API_KEY and Groq):
        return None
    for attempt in range(max_retries):
        try:
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=GROQ_MODEL, temperature=0.85, max_tokens=4000,
            )
            return resp.choices[0].message.content
        except Exception as e:
            err = str(e)
            if "tokens per day" in err or "TPD" in err:
                log("⚠️ Groq daily token limit reached — falling back to Gemini")
                return None
            if "429" in err or "rate_limit" in err.lower():
                wait = 10 * (attempt + 1)
                log(f"⏳ Groq 429 retry {attempt+1}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                return None
    log("⚠️ Groq unavailable — falling back to Gemini")
    return None


def _call_github(prompt_text):
    if not GITHUB_TOKEN:
        return None
    import requests
    try:
        resp = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
            json={"model": GH_MODEL, "messages": [{"role": "user", "content": prompt_text}],
                  "temperature": 0.7, "max_tokens": 4000},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        if resp.status_code == 429:
            log("GitHub model rate limited")
        else:
            log(f"GitHub model returned {resp.status_code}")
        return None
    except Exception as e:
        log(f"GitHub model call failed: {e}")
        return None


def call_llm(prompt_text, prefer="gemini", max_tokens=2000):
    global _QUOTA_EXHAUSTED
    if _QUOTA_EXHAUSTED and task not in ("script", "topic"):
        log("Quota exhausted, skipping non-critical LLM call")
        return ""

    if task in ("script", "topic"):
        log(f"call_llm task={task}: trying Groq (LLaMA) first")
        try:
            result = _call_groq(prompt_text)
            if result and result.strip():
                return result
        except Exception as e:
            log(f"Groq failed for {task}: {e}")

    if task != "premium":
        result = _call_github(prompt_text)
        if result and result.strip():
            return result

    tier_map = {
        "economy":  [GEMINI_MODEL_ECONOMY,  GEMINI_MODEL_STANDARD, GEMINI_MODEL_PREMIUM],
        "standard": [GEMINI_MODEL_STANDARD, GEMINI_MODEL_PREMIUM],
        "premium":  [GEMINI_MODEL_PREMIUM],
    }
    models = tier_map.get(task, tier_map["economy"])
    for model_name in models:
        if _QUOTA_EXHAUSTED:
            log(f"Quota exhausted, skipping remaining models in tier")
            break
        log(f"call_llm task={task} model={model_name}")
        result = _call_gemini(prompt_text, model_name=model_name)
        if result and result.strip():
            return result
    return ""


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
    import datetime as _dt
    week_seed = int(_dt.datetime.now().strftime("%Y%W"))
    _rng = __import__('random').Random(week_seed)
    _rng.shuffle(queries)

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
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={f1}:duration=360",
        "-f", "lavfi", "-i", f"sine=frequency={f2}:duration=360",
        "-f", "lavfi", "-i", "anoisesrc=d=360:c=pink:r=44100:a=0.005",
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
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{channel}':fontsize=26:fontcolor=white@0.85:"
        f"x=30:y=28:shadowcolor=black@0.9:shadowx=2:shadowy=2",
        # Format badge — top right
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{fmt_label}':fontsize=20:fontcolor=yellow@0.9:"
        f"x=w-tw-30:y=28:shadowcolor=black@0.9:shadowx=2:shadowy=2",
    ]

    # Title fades in at 0.5s, holds 6s
    if title:
        overlays.append(
            f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{title}':fontsize=38:fontcolor=white@1.0:"
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
    """
    2s logo sting: intro_frame.png + bell sound.
    Audio padded to EXACT INTRO_DURATION to prevent concat truncation.
    All output: 25fps, 1920x1080, aac 44100Hz — matches content video.
    """
    if not os.path.exists(INTRO_FRAME):
        return None

    # Generate bell + pad to exactly INTRO_DURATION seconds
    bell = f"/tmp/brand_bell_{os.getpid()}.mp3"
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=880:duration={INTRO_DURATION}",
         "-f", "lavfi", "-i", f"sine=frequency=1320:duration={INTRO_DURATION}",
         "-filter_complex",
         f"[0:a]volume=0.5,afade=t=in:st=0:d=0.2,afade=t=out:st={INTRO_DURATION-0.5}:d=0.5[b1];"
         f"[1:a]volume=0.3,afade=t=out:st={INTRO_DURATION-0.5}:d=0.5[b2];"
         "[b1][b2]amix=inputs=2:duration=longest,"
         f"apad=pad_dur={INTRO_DURATION}[bell]",
         "-map", "[bell]", "-t", str(INTRO_DURATION), bell], timeout=15)

    has_bell = os.path.exists(bell)

    cmd = ["ffmpeg", "-y",
           "-loop", "1", "-t", str(INTRO_DURATION + 0.1), "-i", INTRO_FRAME]
    if has_bell:
        cmd.extend(["-i", bell])

    vf = (f"fps=25,scale=1920:1080:force_original_aspect_ratio=decrease,"
          f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={INTRO_DURATION-0.4}:d=0.4")

    cmd.extend(["-vf", vf])
    if has_bell:
        cmd.extend(["-map", "0:v", "-map", "1:a"])
    else:
        cmd.extend(["-map", "0:v",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-map", "2:a"])

    cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-t", str(INTRO_DURATION),  # hard cap at exact duration
                output_path])

    r = run(cmd, timeout=30)
    try:
        if os.path.exists(bell): os.remove(bell)
    except: pass
    if r.returncode != 0:
        log(f"  ⚠️ Intro clip failed: {r.stderr[-100:]}")
    return output_path if r.returncode == 0 else None


def make_outro_clip(output_path):
    """3s brand outro: banner frame with subscribe text."""
    if not os.path.exists(OUTRO_FRAME):
        return None
    text_filter = (
        "drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='Subscribe பண்ணுங்கள் 🔔':fontsize=52:"
        "fontcolor=white@0.95:x=(w-tw)/2:y=h-120:"
        "shadowcolor=black@0.9:shadowx=3:shadowy=3,"
        "drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='@NidhiNeethiTamil':fontsize=36:"
        "fontcolor=gold@0.9:x=(w-tw)/2:y=h-65:"
        "shadowcolor=black@0.8:shadowx=2:shadowy=2"
    )
    r = run(["ffmpeg", "-y",
             "-loop", "1", "-t", str(OUTRO_DURATION + 0.1), "-i", OUTRO_FRAME,
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-filter_complex",
             f"[0:v]fps=25,scale=1920:1080:force_original_aspect_ratio=decrease,"
             f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
             f"fade=t=in:st=0:d=0.4,"
             f"fade=t=out:st={OUTRO_DURATION-0.4}:d=0.4,"
             f"{text_filter}[v];"
             f"[1:a]apad=pad_dur={OUTRO_DURATION}[a]",
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", "-ac", "2",
             "-t", str(OUTRO_DURATION), output_path], timeout=30)
    return output_path if r.returncode == 0 else None


def concat_clips(clips, output_path):
    """
    Concatenate clips with re-encode to uniform specs.
    Uses -c copy only if all clips have identical codec/fps/resolution.
    Re-encodes otherwise to prevent silent truncation from stream mismatch.
    """
    flist = f"/tmp/concat_{os.path.basename(output_path)}.txt"
    with open(flist, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    # Re-encode to uniform 25fps 1920x1080 — prevents truncation from
    # fps/codec mismatch between intro(PNG-based) and content clips
    r = run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", flist,
             "-vf", "fps=25,scale=1920:1080:force_original_aspect_ratio=decrease,"
                    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", "-ac", "2",
             "-movflags", "+faststart",
             output_path], timeout=180)
    try: os.remove(flist)
    except: pass
    if r.returncode != 0:
        log(f"  ⚠️ Concat re-encode failed: {r.stderr[-100:]}")
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
            "[1:a]volume=0.07,afade=t=in:st=0:d=3,afade=t=out:st={bfo}:d=3[b];"
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
                "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-ar", "44100", "-ac", "2",
                "-avoid_negative_ts", "make_zero", raw_file])
    r = run(cmd, timeout=400)
    if r.returncode != 0:
        # Fallback single image
        r = run(["ffmpeg", "-y", "-loop", "1", "-i", images[0], "-i", audio,
                 "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                 "-pix_fmt", "yuv420p", "-c:a", "aac",
                  "-ar", "44100", "-ac", "2", raw_file],
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

    log("🔤 Step 7/8 Source citation + bilingual hook (single pass)...")

    # Combine BOTH overlays in ONE ffmpeg pass — prevents duration drift
    # from sequential re-encodes
    combined_file = f"/tmp/{output_name}_combined.mp4"

    hooks = {
        "warning":    "MUST WATCH before you apply for a loan",
        "explainer":  "Complete guide explained in Tamil",
        "rights":     "Know your legal rights — explained in Tamil",
        "comparison": "Which is better? Find out in Tamil",
        "story":      "Real story — what happened and what you can learn",
        "news":       "Breaking finance news explained in Tamil",
    }
    hook_phrase = hooks.get(format_type, "Tamil finance guide")
    safe_hook   = hook_phrase.replace("'", "").replace(":", " -")
    safe_src    = source_citation.replace("'", "").replace(":", " -")

    show_end = min(75, total_dur - 5)

    combined_vf = (
        # Bilingual hook: top center, first 5s
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{safe_hook}':fontsize=28:"
        f"fontcolor=yellow@0.95:x=(w-tw)/2:y=40:"
        f"shadowcolor=black@0.9:shadowx=2:shadowy=2:"
        f"enable='between(t,0,5)',"
        # Source citation: bottom left, 15s-75s
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{safe_src}':fontsize=18:"
        f"fontcolor=white@0.70:x=20:y=h-45:"
        f"shadowcolor=black@0.8:shadowx=1:shadowy=1:"
        f"enable='between(t,15,{show_end:.0f})'"
    )

    r_combined = run([
        "ffmpeg", "-y", "-i", video_file,
        "-vf", combined_vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "copy",   # audio copy — no drift here
        combined_file
    ], timeout=200)

    if r_combined.returncode == 0 and os.path.exists(combined_file):
        shutil.move(combined_file, video_file)
        log(f"  ✅ Source citation + bilingual hook (single pass)")
    else:
        log("  ⚠️ Combined overlay failed — using video as-is")
        for f in [combined_file]:
            try:
                if os.path.exists(f): os.remove(f)
            except: pass

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
    run(["ffmpeg", "-y", "-i", video_file, "-ss", "0", "-t", "40",
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

    # Inject analytics insights to boost best-performing formats
    insights = load_analytics_insights()
    if insights.get("best_format"):
        prompt += (
            f"\n\nANALYTICS INSIGHT: Based on past performance on this channel, "
            f"'{insights['best_format']}' format gets the most views. "
            f"Prefer '{insights.get('best_topic_group','')}' topic group if relevant today."
        )

    raw = call_llm(prompt, prefer="gemini", max_tokens=1000)
    try:
        data = parse_json_response(raw)
        data["topic"] = deduplicate_topic(data["topic"])
        log(f"  📌 Topic: {data['topic']}")
        log(f"  🎭 Format: {data['format']}")
        log(f"  💡 Reason: {data.get('reason','')}")
        return data
    except Exception as e:
        log(f"  ⚠️ JSON parse failed ({e}) — using random evergreen")
        return {

            "topic":           deduplicate_topic(random.choice(EVERGREEN_TOPICS)),
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

    if not text.strip():
        log("  ❌ Script generation failed — all attempts returned empty")
        return ""
    log(f"  ✅ Script: {len(text)} chars in {time.time()-t0:.0f}s")
    return text


def generate_mcq(topic):
    return [
        {"question": f"{topic} பற்றி மேலும் அறிய விரும்புகிறீர்களா?", "options": ["ஆம்", "இல்லை"], "answer": 0},
        {"question": "இந்த தகவல் உங்களுக்கு பயனுள்ளதாக இருந்ததா?", "options": ["மிகவும் பயனுள்ளது", "சரி", "பயனற்றது"], "answer": 0},
    ]


def generate_subtitles(script):
    import textwrap
    words = script.strip().split()
    lines = textwrap.wrap(' '.join(words), width=40)
    subtitles = []
    for i, line in enumerate(lines, 1):
        subtitles.append(f"{i}\\n{line}")
    return subtitles


def generate_metadata(topic, format_type, hook_angle):
    log("  📋 Generating metadata...")
    prompt = METADATA_PROMPT.format(
        topic=topic,
        format_type=format_type,
        hook_angle=hook_angle,
    )
    raw = call_llm_groq(prompt, max_retries=3)
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


def get_source_citation(topic):
    citations = {
        "ayurveda": "https://www.ayurveda.com",
        "panchangam": "https://www.drikpanchang.com",
        "nakshatra": "https://www.astrology.com",
        "vastu": "https://www.vastushastra.com",
        "yoga": "https://www.yogajournal.com",
        "meditation": "https://www.mindful.org",
        "puja": "https://www.templepurohit.com",
        "temple": "https://www.templepurohit.com",
        "hindu": "https://www.hinduismtoday.com",
    }
    topic_lower = topic.lower()
    for keyword, url in citations.items():
        if keyword in topic_lower:
            return url
    return "https://www.wikipedia.org"


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
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{safe_source}':fontsize=18:"
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
        f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf:text='{safe_hook}':fontsize=28:"
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
# FEATURE: AI THUMBNAIL GENERATOR
# Generates click-optimized thumbnail using Pillow + brand colors
# Background: urgent red or trust blue based on format
# Bold Tamil text + rupee/scale icon area
# ═══════════════════════════════════════════════════════════════


THUMBNAIL_FORMATS = {
    "warning":    {"bg": (160, 20,  20),  "accent": (255, 220, 0),  "badge": "WARNING"},
    "explainer":  {"bg": (10,  50,  100), "accent": (255, 215, 0),  "badge": "GUIDE"},
    "rights":     {"bg": (10,  60,  50),  "accent": (255, 215, 0),  "badge": "YOUR RIGHTS"},
    "comparison": {"bg": (20,  20,  80),  "accent": (255, 215, 0),  "badge": "VS"},
    "story":      {"bg": (80,  20,  80),  "accent": (255, 215, 0),  "badge": "TRUE STORY"},
    "news":       {"bg": (10,  10,  10),  "accent": (255,  60, 60), "badge": "BREAKING"},
    "default":    {"bg": (10,  50,  100), "accent": (255, 215, 0),  "badge": "MUST WATCH"},
}


def load_responded():
    if os.path.exists(RESPONDED_COMMENTS_FILE):
        with open(RESPONDED_COMMENTS_FILE) as f:
            return set(json.load(f))
    return set()


def save_responded(ids):
    with open(RESPONDED_COMMENTS_FILE, "w") as f:
        json.dump(list(ids), f)


def respond_to_comments():
    """
    Auto-reply to viewer comments on recent videos.
    Only responds to: questions (contains ?), genuine comments
    Skips: spam, already responded, bot comments
    Max 10 replies per run to avoid spam detection.
    """
    global _QUOTA_EXHAUSTED
    if _QUOTA_EXHAUSTED:
        log("Quota exhausted, skipping comment responses")
        return
    log("💬 Responding to viewer comments...")
    youtube = get_authenticated_service()
    if not youtube:
        log("⚠️ YouTube auth required"); return

    responded = load_responded()
    reply_count = 0

    # Get recent videos
    if not os.path.isdir(METADATA_DIR):
        log("No metadata found"); return

    for meta_file in sorted(Path(METADATA_DIR).glob("*.json"), reverse=True)[:5]:
        if reply_count >= 10:
            break
        try:
            meta = json.loads(meta_file.read_text())
            vid_id = meta.get("video_id", "")
            topic  = meta.get("topic", "")
            if not vid_id:
                continue

            # Get comments
            resp = youtube.commentThreads().list(
                part="snippet", videoId=vid_id,
                order="time", maxResults=20).execute()

            for item in resp.get("items", []):
                if reply_count >= 10:
                    break

                thread_id = item["id"]
                comment   = item["snippet"]["topLevelComment"]["snippet"]
                text      = comment.get("textDisplay", "")
                author    = comment.get("authorDisplayName", "")
                reply_cnt = item["snippet"].get("totalReplyCount", 0)

                # Skip: already responded, has replies, too short, spam-like
                if thread_id in responded:
                    continue
                if reply_cnt > 0:
                    continue
                if len(text) < 5:
                    continue
                if any(spam in text.lower() for spam in
                       ["subscribe", "check my", "visit my", "http", "www."]):
                    continue

                # Only reply to questions or meaningful comments
                is_question = "?" in text
                is_meaningful = len(text) > 20

                if not (is_question or is_meaningful):
                    continue

                # Generate reply
                try:
                    prompt = COMMENT_RESPONSE_PROMPT.format(
                        topic=topic[:80], comment=text[:200])
                    reply_text = call_llm(prompt).strip()

                    if not reply_text or len(reply_text) < 5:
                        continue

                    # Post reply
                    youtube.comments().insert(
                        part="snippet",
                        body={"snippet": {
                            "parentId":    thread_id,
                            "textOriginal": reply_text,
                        }}
                    ).execute()

                    responded.add(thread_id)
                    reply_count += 1
                    log(f"  ✅ Replied to @{author[:20]}: {reply_text[:50]}...")
                    time.sleep(2)  # rate limit

                except Exception as e:
                    log(f"  ⚠️ Reply failed: {e}")

        except Exception as e:
            log(f"  ⚠️ Comment fetch failed: {e}")

    save_responded(responded)
    log(f"✅ Comment responses: {reply_count} replies posted")


# ═══════════════════════════════════════════════════════════════
# FEATURE: NRI TAMIL TARGETING
# One video/week with NRI-specific finance problems
# Higher RPM ($15-30 vs $4-8 domestic)
# ═══════════════════════════════════════════════════════════════

NRI_TOPIC_PROMPT = """You are creating content for Tamil NRI (Non-Resident Indians) living abroad.

Locations: USA, UK, Canada, Australia, Singapore, UAE, Germany
Audience: Tamil people aged 25-45, working abroad, earning in USD/GBP/SGD

Generate ONE highly specific NRI Tamil finance/legal topic.

NRI pain points:
- Money transfer to India (exchange rates, fees, best apps)
- NRE/NRO account differences
- Double taxation (DTAA)
- Sending money for parents, property, family
- Indian property ownership from abroad
- FEMA rules, RBI guidelines for NRIs
- EPF/PPF while abroad
- Indian credit card/CIBIL while NRI
- OCI card benefits
- ITR filing for NRI income

Today: {date}

Return ONLY a specific Tamil topic sentence (not too technical, viewer-friendly).
Example: "அமெரிக்காவில் இருந்து India-க்கு பணம் அனுப்ப best app எது — 2026 comparison"
"""


def generate_nri_video():
    """Generate NRI-specific video with English-heavy script for higher RPM."""
    log("🌍 Generating NRI-targeted video...")
    now = datetime.datetime.now()

    # NRI topic
    topic = call_llm(NRI_TOPIC_PROMPT.format(
        date=now.strftime("%Y-%m-%d"))).strip().strip('"')
    log(f"  NRI Topic: {topic}")

    # NRI config — English-forward, comparison format
    config = {
        "topic":          topic,
        "format":         "comparison",
        "pexels_keyword": "investment",
        "hook_angle":     "இது தெரியாமல் NRI-கள் ஆயிரக்கணக்கில் இழக்கிறார்கள்",
    }
    return process_video(
        topic=topic,
        format_type="comparison",
        upload=True,
        privacy="public",
    )


# ═══════════════════════════════════════════════════════════════
# FEATURE: COMMUNITY TAB AUTO-POSTER
# Posts weekly poll + daily finance tip on Community tab
# ═══════════════════════════════════════════════════════════════

COMMUNITY_POLL_PROMPT = """Generate a Tamil finance community tab post for "நிதி நீதி தமிழ்".

Today: {date} ({day})
Recent video topic: {recent_topic}

Create ONE of these (pick based on day):
- Monday: Weekly poll question (4 options, Tamil finance topic)
- Wednesday: Quick finance tip (1 fact, 2-3 lines)
- Friday: "Did you know?" interesting finance fact
- Sunday: Weekly quiz question

Return JSON:
{{
  "type": "poll" or "post",
  "text": "<main text — Tamil, under 500 chars>",
  "options": ["option1", "option2", "option3", "option4"]  // only for polls
}}"""


def post_community_content():
    """Post weekly poll/tip to YouTube Community tab."""
    log("📢 Posting community tab content...")
    youtube = get_authenticated_service()
    if not youtube:
        log("⚠️ YouTube auth required"); return

    now   = datetime.datetime.now()
    day   = now.strftime("%A")
    recent = load_recent_topics(1)
    recent_topic = recent[0] if recent else "personal finance tips"

    prompt = COMMUNITY_POLL_PROMPT.format(
        date=now.strftime("%Y-%m-%d"),
        day=day,
        recent_topic=recent_topic,
    )

    try:
        raw  = call_llm(prompt)
        data = parse_json_response(raw)
        text = data.get("text", "")
        opts = data.get("options", [])

        if not text:
            log("  ⚠️ No community content generated")
            return

        if data.get("type") == "poll" and len(opts) >= 2:
            # Post poll
            body = {
                "snippet": {
                    "channelId": "",  # filled by API
                    "multipleChoicePoll": {
                        "question": {"runs": [{"text": text}]},
                        "answers": [
                            {"answerText": {"runs": [{"text": o}]}}
                            for o in opts[:4]
                        ],
                    }
                }
            }
            log(f"  ✅ Community poll: {text[:60]}")
        else:
            # Post text
            body = {
                "snippet": {
                    "text": text
                }
            }
            log(f"  ✅ Community post: {text[:60]}")

        # Note: Community posts require special API scope
        # This will be posted via youtube.communityPosts().insert()
        # Currently in beta — fallback to printing the content
        log(f"  📝 Community content ready: {text[:80]}")
        # Save for manual posting if API unavailable
        cp_file = f"community_posts/{now.strftime('%Y%m%d')}.txt"
        os.makedirs("community_posts", exist_ok=True)
        with open(cp_file, "w", encoding="utf-8") as f:
            f.write(f"Type: {data.get('type')}\n")
            f.write(f"Text: {text}\n")
            if opts:
                f.write(f"Options: {opts}\n")
        log(f"  ✅ Saved to {cp_file}")

    except Exception as e:
        log(f"  ⚠️ Community post failed: {e}")


# ═══════════════════════════════════════════════════════════════
# FEATURE: ANALYTICS FEEDBACK LOOP
# Reads YouTube Analytics, identifies best/worst performing videos
# Feeds insights back into topic selection prompt
# ═══════════════════════════════════════════════════════════════

ANALYTICS_FILE = "analytics_insights.json"


def fetch_video_analytics(youtube, video_id):
    """Fetch views, CTR, avg watch time for a video."""
    try:
        from googleapiclient.discovery import build as yt_build
        analytics = yt_build("youtubeAnalytics", "v2",
                             credentials=youtube._http.credentials)
        now   = datetime.datetime.now().strftime("%Y-%m-%d")
        start = (datetime.datetime.now() -
                 datetime.timedelta(days=30)).strftime("%Y-%m-%d")

        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=now,
            metrics="views,estimatedMinutesWatched,averageViewDuration,clickThroughRate",
            filters=f"video=={video_id}",
            dimensions="video",
        ).execute()

        rows = resp.get("rows", [])
        if rows:
            return {
                "views":        int(rows[0][1]),
                "watch_mins":   float(rows[0][2]),
                "avg_dur_sec":  float(rows[0][3]),
                "ctr":          float(rows[0][4]),
            }
    except Exception as e:
        log(f"  ⚠️ Analytics fetch failed: {e}")
    return None


def run_analytics_loop():
    """
    Read analytics for recent videos.
    Identify: best format, best topic group, best posting time.
    Save insights — used by discover_daily_config() to improve picks.
    """
    log("📊 Running analytics feedback loop...")
    youtube = get_authenticated_service()
    if not youtube:
        log("⚠️ YouTube auth required"); return

    insights = {}
    format_performance = {}
    topic_group_performance = {}

    for meta_file in sorted(Path(METADATA_DIR).glob("*.json"), reverse=True)[:20]:
        try:
            meta    = json.loads(meta_file.read_text())
            vid_id  = meta.get("video_id", "")
            topic   = meta.get("topic", "")
            fmt     = meta.get("format", "")
            if not vid_id:
                continue

            stats = fetch_video_analytics(youtube, vid_id)
            if not stats:
                continue

            log(f"  {topic[:40]}: {stats['views']} views, CTR {stats['ctr']:.1%}, "
                f"avg {stats['avg_dur_sec']:.0f}s")

            # Track format performance
            if fmt:
                if fmt not in format_performance:
                    format_performance[fmt] = []
                format_performance[fmt].append(stats["views"])

            # Track topic group
            grp = detect_series_group(topic)
            if grp:
                if grp not in topic_group_performance:
                    topic_group_performance[grp] = []
                topic_group_performance[grp].append(stats["views"])

        except Exception as e:
            log(f"  ⚠️ {e}")

    # Compute averages
    fmt_avg   = {f: sum(v)/len(v) for f, v in format_performance.items() if v}
    topic_avg = {t: sum(v)/len(v) for t, v in topic_group_performance.items() if v}

    best_format = max(fmt_avg, key=fmt_avg.get) if fmt_avg else "explainer"
    best_topic  = max(topic_avg, key=topic_avg.get) if topic_avg else "cibil"

    insights = {
        "best_format":       best_format,
        "best_topic_group":  best_topic,
        "format_avg_views":  fmt_avg,
        "topic_avg_views":   topic_avg,
        "updated":           datetime.datetime.now().isoformat(),
    }

    with open(ANALYTICS_FILE, "w") as f:
        json.dump(insights, f, indent=2)

    log(f"  ✅ Best format: {best_format} | Best topic: {best_topic}")
    log(f"  ✅ Insights saved to {ANALYTICS_FILE}")

    # Commit to git
    try:
        run(["git", "add", ANALYTICS_FILE])
        run(["git", "commit", "-m", f"chore: analytics update {datetime.datetime.now():%Y-%m-%d}"])
        run(["git", "push"])
    except:
        pass

    return insights


def load_analytics_insights():
    """Load previously computed analytics insights."""
    if os.path.exists(ANALYTICS_FILE):
        try:
            with open(ANALYTICS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

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




def validate_script(text, lang="tamil"):
    """
    Quality check on generated script.
    Returns (is_valid, cleaned_text, reason).
    """
    if not text or len(text) < 500:
        return False, text, "too short"

    # Strip markdown artifacts
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)      # bold/italic
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)     # bullets
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
    text = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL)      # code blocks
    text = re.sub(r"\\[BEAT \\d+[^\\]]*\\]", "", text)                  # [BEAT 1] labels
    text = re.sub(r"\\[[A-Z][A-Z ]+\\]", "", text)                     # [HOOK] [CTA] labels
    text = re.sub(r"^\\s*\\*{2,}.*?\\*{2,}\\s*$", "", text, flags=re.MULTILINE) # **headers**
    text = re.sub(r"^-{3,}\\s*$", "", text, flags=re.MULTILINE)         # --- dividers
    text = re.sub(r"\\n{3,}", "\\n\\n", text)                            # excess blank lines
    text = text.strip()

    # Check Tamil character ratio (should be >40% for Tamil scripts)
    tamil_chars = len(re.findall(r"[\u0B80-\u0BFF]", text))
    total_chars = len(text.replace(" ","").replace("\n",""))
    if total_chars > 0:
        tamil_ratio = tamil_chars / total_chars
        if tamil_ratio < 0.30:
            return False, text, f"Tamil ratio too low: {tamil_ratio:.0%}"

    return True, text, "ok"


def failure_alert(message):
    """GitHub Actions error annotation."""
    print(f"::error title=நிதி நீதி தமிழ் Bot Error::{message}")
    log(f"❌ ALERT: {message}")

def validate_tags(tags_str):
    """YouTube max: 500 chars total, max 30 tags."""
    tags = [t.strip() for t in tags_str.split(",") if t.strip()][:30]
    result, total = [], 0
    for tag in tags:
        if total + len(tag) + 1 <= 490:
            result.append(tag)
            total += len(tag) + 1
        else:
            break
    return ", ".join(result)


THUMBNAIL_DIR = "thumbnails"
TAMIL_BOLD_FONT = "/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf"
TAMIL_REG_FONT  = "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf"
ENG_BOLD_FONT   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

NN_THUMB_FORMATS = {
    "warning":    {"c1":(88,5,5),   "c2":(22,0,0),  "acc":(255,55,55),  "bb":(185,0,0),   "badge":"⚠ WARNING"},
    "explainer":  {"c1":(5,18,72),  "c2":(0,5,32),  "acc":(75,152,255), "bb":(22,88,192), "badge":"GUIDE"},
    "rights":     {"c1":(0,52,18),  "c2":(0,16,5),  "acc":(0,202,92),   "bb":(0,142,52),  "badge":"RIGHTS"},
    "comparison": {"c1":(36,0,72),  "c2":(11,0,32), "acc":(172,72,255), "bb":(112,32,192),"badge":"VS"},
    "story":      {"c1":(52,20,0),  "c2":(20,5,0),  "acc":(255,132,0),  "bb":(172,82,0),  "badge":"STORY"},
    "news":       {"c1":(5,5,22),   "c2":(0,0,8),   "acc":(255,192,0),  "bb":(172,132,0), "badge":"BREAKING"},
    "default":    {"c1":(5,18,48),  "c2":(0,5,22),  "acc":(255,192,45), "bb":(172,132,0), "badge":"FINANCE"},
}

def generate_thumbnail(title, format_type, output_name):
    """Premium finance thumbnail — Tamil + English smart font selection."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)

        W, H = 1280, 720
        cfg = NN_THUMB_FORMATS.get(format_type, NN_THUMB_FORMATS["default"])
        img = Image.new("RGB",(W,H),cfg["c1"])
        d   = ImageDraw.Draw(img)

        def is_tamil(text):
            return any("\u0B80" <= c <= "\u0BFF" for c in text)

        def load_font(text, size, bold=True):
            try:
                if is_tamil(text):
                    return ImageFont.truetype(TAMIL_BOLD_FONT, size)
                return ImageFont.truetype(ENG_BOLD_FONT, size)
            except: return ImageFont.load_default()

        def bg_grad():
            for y in range(H):
                t=y/H
                col=tuple(int(cfg["c1"][j]+(cfg["c2"][j]-cfg["c1"][j])*t) for j in range(3))
                d.line([(0,y),(W,y)],fill=col)

        def shadow_text(x,y,text,size,fill):
            font=load_font(text,size)
            for ox,oy in [(3,3),(-2,-2),(2,-2),(-2,2)]:
                d.text((x+ox,y+oy),text,font=font,fill=(0,0,0))
            d.text((x,y),text,font=font,fill=fill)

        def wrap(text, n=15):
            words=text.split()
            lines,line=[],""
            for w in words:
                if len(line+w)<=n: line+=w+" "
                else:
                    if line: lines.append(line.strip())
                    line=w+" "
            if line: lines.append(line.strip())
            return lines[:3]

        bg_grad()

        px=int(W*0.66)
        for x in range(px,W):
            t=(x-px)/(W-px)
            col=tuple(max(0,int(c*(1-t*0.45))) for c in cfg["c2"])
            d.line([(x,0),(x,H)],fill=col)
        d.polygon([(px-32,0),(px+32,0),(px-32,H),(px-85,H)],fill=cfg["c2"])

        icon_map={"warning":"₹?","explainer":"₹","rights":"⚖","comparison":"VS","story":"★","news":"📢","default":"₹"}
        icon=icon_map.get(format_type,"₹")
        ifont=load_font(icon,72)
        d.text((px+(W-px)//2-38,H//2-42),icon,font=ifont,
               fill=tuple(min(255,c+32) for c in cfg["c2"]))

        d.rectangle([0,0,W,10],fill=cfg["acc"])
        d.rectangle([0,H-10,W,H],fill=cfg["acc"])

        btext=cfg["badge"]
        bw=len(btext)*15+42
        bfont=load_font(btext,23)
        d.rounded_rectangle([W-bw-18,16,W-18,62],radius=7,fill=cfg["bb"])
        d.text((W-bw//2-18,39),btext,font=bfont,fill=(255,255,255),anchor="mm")

        cnfont=load_font("நிதி நீதி தமிழ்",24)
        d.text((22,18),"நிதி நீதி தமிழ்",font=cnfont,fill=(200,200,200))

        lines=wrap(title,14)
        ty=100
        for i,line in enumerate(lines):
            col=(255,255,255) if i==0 else (222,218,240)
            shadow_text(22,ty,line,68 if i==0 else 48,col)
            ty+=(80 if i==0 else 58)

        d.rectangle([22,ty+5,min(22+380,px-15),ty+11],fill=cfg["acc"])

        out=f"{THUMBNAIL_DIR}/{output_name}_thumb.png"
        img.save(out)
        log(f"  ✅ Thumbnail: {out}")
        return out
    except Exception as e:
        log(f"  ⚠️ Thumbnail failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# RESILIENT LLM ROUTER — 5-provider waterfall
# Priority: Groq (fast) → Gemini (reliable) → GitHub Models (free)
#           → Cerebras (fast free) → Groq fallback models
#
# All providers use OpenAI-compatible SDK for consistency.
# GitHub Models: uses GITHUB_TOKEN (auto-set in Actions — zero config)
# Cerebras: uses CEREBRAS_API_KEY secret (optional, add if available)
# ═══════════════════════════════════════════════════════════════════

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
CEREBRAS_KEY    = os.environ.get("CEREBRAS_API_KEY", "")

# ── Provider configs ────────────────────────────────────────────────
PROVIDERS = [
    # name, base_url, api_key, model, use_for
    ("groq",     "https://api.groq.com/openai/v1",         GROQ_API_KEY,  "llama-3.3-70b-versatile",        "script"),
    ("gemini",   None,                                       GEMINI_KEY,    "gemini-2.5-flash",               "all"),
    ("github",   "https://models.inference.ai.azure.com",  GITHUB_TOKEN,  "gpt-4o-mini",                    "all"),
    ("cerebras", "https://api.cerebras.ai/v1",              CEREBRAS_KEY,  "llama-3.3-70b",                  "all"),
    ("groq_fb",  "https://api.groq.com/openai/v1",         GROQ_API_KEY,  "llama3-8b-8192",                 "fallback"),
]

def _call_provider(name, base_url, api_key, model, prompt, max_tokens=4000):
    """Call a single provider. Returns text or raises."""
    if not api_key:
        raise Exception(f"{name}: no API key")

    if name == "gemini":
        # Gemini uses its own SDK
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model, contents=prompt)
        return resp.text
    else:
        # All others: OpenAI-compatible
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.85,
        )
        return resp.choices[0].message.content


def _is_retryable(err_str):
    """True if the error is transient (rate limit / server overload)."""
    return any(c in err_str for c in [
        "429", "503", "502", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
        "high demand", "overloaded", "ServiceUnavailable",
        "rate_limit", "tokens per day", "TPD", "Internal",
        "timeout", "timed out",
    ])


def call_llm(prompt, max_retries=3, prefer="gemini", max_tokens=4000):
    """
    Resilient multi-provider router.
    Tries each provider in priority order.
    On transient errors → retry with backoff.
    On permanent errors → skip to next provider immediately.
    """
    # Build provider order based on preference
    if prefer == "groq":
        order = ["groq", "gemini", "github", "cerebras", "groq_fb"]
    else:
        order = ["gemini", "groq", "github", "cerebras", "groq_fb"]

    provider_map = {p[0]: p for p in PROVIDERS}
    last_error = ""

    for provider_name in order:
        if provider_name not in provider_map:
            continue
        name, base_url, api_key, model, _ = provider_map[provider_name]
        if not api_key:
            continue   # skip providers with no key configured

        for attempt in range(max_retries):
            try:
                result = _call_provider(name, base_url, api_key, model, prompt, max_tokens)
                if result and result.strip():
                    if attempt > 0 or provider_name != order[0]:
                        log(f"  ✅ LLM: {name}/{model.split('-')[0]}")
                    return result.strip()
            except Exception as e:
                err = str(e)
                last_error = err
                if _is_retryable(err):
                    # Daily limit hit — skip provider entirely
                    if "tokens per day" in err or "TPD" in err or "daily" in err.lower():
                        log(f"  ⚠️ {name}: daily limit — trying next provider")
                        break
                    wait = min(10 * (2 ** attempt), 60)
                    log(f"  ⏳ {name} retry {attempt+1}/{max_retries} in {wait}s ({err[:60]})")
                    time.sleep(wait)
                else:
                    # Non-retryable (auth, invalid model etc) — skip provider
                    log(f"  ⚠️ {name}: {err[:80]} — skipping")
                    break

    raise Exception(f"All LLM providers failed. Last: {last_error[:150]}")


def call_llm_groq(prompt, max_retries=3):
    """Script generation — prefers Groq for quality, all providers as fallback."""
    return call_llm(prompt, max_retries=max_retries, prefer="groq", max_tokens=4000)


def call_llm_gemini(prompt, max_retries=3):
    """Explicit Gemini — but falls back gracefully to other providers."""
    return call_llm(prompt, max_retries=max_retries, prefer="gemini", max_tokens=2000)


# Keep _call_gemini and _call_groq for backward compatibility
def _call_gemini(prompt, max_retries=5):
    return call_llm(prompt, max_retries=max_retries, prefer="gemini")

def _call_groq(prompt, max_retries=3):
    return call_llm(prompt, max_retries=max_retries, prefer="groq")


UPLOAD_QUEUE_FILE = "upload_queue.json"


def is_quota_exceeded(err_str):
    """Check if error is YouTube quota exceeded."""
    return any(x in str(err_str).lower() for x in
               ["quotaexceeded", "quota exceeded", "usageexceeded",
                "403", "dailylimitexceeded"])


def queue_for_retry(video_path, metadata, privacy="public"):
    """Save failed upload to queue for next run."""
    try:
        queue = []
        if os.path.exists(UPLOAD_QUEUE_FILE):
            with open(UPLOAD_QUEUE_FILE) as f:
                queue = json.load(f)
        queue.append({
            "video_path": video_path,
            "metadata":   metadata,
            "privacy":    privacy,
            "queued_at":  datetime.datetime.now().isoformat(),
        })
        with open(UPLOAD_QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        log(f"  📋 Queued for retry: {os.path.basename(video_path)}")
        # Commit queue to git so it persists
        try:
            run(["git", "config", "user.email", "bot@channel.com"])
            run(["git", "config", "user.name",  "Bot"])
            run(["git", "add", UPLOAD_QUEUE_FILE])
            run(["git", "commit", "-m", "chore: queue video for upload retry"])
            run(["git", "push"])
        except: pass
    except Exception as e:
        log(f"  ⚠️ Queue save failed: {e}")


def upload_pending_from_queue():
    """Upload any videos queued from previous failed runs."""
    if not os.path.exists(UPLOAD_QUEUE_FILE):
        return
    try:
        with open(UPLOAD_QUEUE_FILE) as f:
            queue = json.load(f)
        if not queue:
            return
        log(f"📤 Processing upload queue ({len(queue)} pending)...")
        youtube = get_authenticated_service()
        if not youtube:
            return
        remaining = []
        for item in queue:
            path = item.get("video_path", "")
            if not os.path.exists(path):
                log(f"  ⚠️ Queued file missing: {path} — skipping")
                continue
            try:
                vid = upload_to_youtube(path, item.get("metadata", {}),
                                        item.get("privacy", "public"))
                if vid:
                    log(f"  ✅ Queued upload succeeded: {vid}")
                else:
                    remaining.append(item)
            except Exception as e:
                if is_quota_exceeded(e):
                    log(f"  ⚠️ Still quota exceeded — keeping in queue")
                    remaining.append(item)
                else:
                    log(f"  ⚠️ Queue upload failed: {e}")
        with open(UPLOAD_QUEUE_FILE, "w") as f:
            json.dump(remaining, f, indent=2, ensure_ascii=False)
        if not remaining:
            try:
                run(["git", "add", UPLOAD_QUEUE_FILE])
                run(["git", "commit", "-m", "chore: clear upload queue"])
                run(["git", "push"])
            except: pass
    except Exception as e:
        log(f"  ⚠️ Queue processing failed: {e}")


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
                           validate_tags(metadata.get("tags","")).split(",")][:30],
            "categoryId":  "22",
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

        # Upload custom thumbnail if generated
        thumb = metadata.get("thumbnail_path", "")
        if thumb and os.path.exists(thumb):
            try:
                youtube.thumbnails().set(
                    videoId=vid,
                    media_body=MediaFileUpload(thumb, mimetype="image/png")
                ).execute()
                log("  ✅ Custom thumbnail uploaded")
            except Exception as e:
                log(f"  ⚠️ Thumbnail upload failed: {e}")

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
        err = str(e)
        if is_quota_exceeded(err):
            log(f"❌ YouTube quota exceeded — queuing for retry")
            queue_for_retry(video_path, metadata, privacy)
        else:
            log(f"❌ Upload failed: {err[:150]}")
        return None


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
    if not script or not script.strip():
        log("  ❌ Script empty — aborting pipeline")
        return None

    log("🤖 Step 2: Generating subtitles + metadata + MCQ (parallel)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        sf  = pool.submit(generate_subtitles, script)
        mf  = pool.submit(generate_metadata, topic_val, fmt, hook_angle)
        mcf = pool.submit(generate_mcq, topic_val)
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
    source_citation = get_source_citation(topic_val)

    with open(f"{SCRIPTS_DIR}/{safe_name}.txt", "w", encoding="utf-8") as f:
        f.write(f"TOPIC: {topic_val}\nFORMAT: {fmt}\n\n{script}")

    # Generate thumbnail
    thumb_path = generate_thumbnail(metadata.get("title", topic_val), fmt, safe_name)
    if thumb_path:
        metadata["thumbnail_path"] = thumb_path

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
                log(f"⚠️ Main video upload failed: {e}")

            # ── Short upload (fully independent) ──
            try:
                short_path = f"{SHORTS_DIR}/{safe_name}_short.mp4"
                if os.path.exists(short_path):
                    _yt2 = get_authenticated_service()
                    if _yt2:
                        upload_short_to_youtube(
                            short_path,
                            metadata.get("title", ""),
                            metadata.get("description", ""),
                            metadata.get("tags", ""),
                            _yt2
                        )
                        log("✅ Short uploaded independently")
                    else:
                        log("  ⚠️ Short: YouTube auth unavailable")
                else:
                    log(f"  ℹ️ Short not found: {short_path}")
            except Exception as short_err:
                log(f"  ⚠️ Short upload failed (main video unaffected): {short_err}")
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
    parser.add_argument("--auth-youtube",     action="store_true")
    parser.add_argument("--check-updates",    action="store_true",
                        help="Check old videos for outdated facts")
    parser.add_argument("--respond-comments", action="store_true",
                        help="Auto-reply to viewer comments")
    parser.add_argument("--analytics",        action="store_true",
                        help="Run analytics feedback loop")
    parser.add_argument("--community-post",   action="store_true",
                        help="Post to Community tab")
    parser.add_argument("--nri-video",        action="store_true",
                        help="Generate NRI-targeted video")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  {CHANNEL_NAME} — Automation Bot v1.0")
    print(f"  2-min videos · English subs · Male+Female voices")
    print(f"{'='*55}\n")

    if args.auth_youtube:
        auth_youtube(); return

    if args.check_updates:
        run_update_checks(); return

    if args.respond_comments:
        respond_to_comments(); return

    if args.analytics:
        run_analytics_loop(); return

    if args.community_post:
        post_community_content(); return

    if args.nri_video:
        generate_nri_video(); return

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
