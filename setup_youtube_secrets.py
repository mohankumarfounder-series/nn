#!/usr/bin/env python3
"""
YouTube OAuth Setup Script
--------------------------
Run this ONCE locally to:
1. Authenticate with YouTube (opens browser)
2. Generate youtube_token.pickle
3. Print YOUTUBE_TOKEN_BASE64 and CLIENT_SECRETS_BASE64
   → Copy these values into GitHub Secrets

Requirements:
  pip install google-api-python-client google-auth-oauthlib

Usage:
  python setup_youtube_secrets.py

Before running:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or use existing)
  3. Enable "YouTube Data API v3"
  4. APIs & Services → Credentials → Create → OAuth 2.0 Client ID
  5. Application type: Desktop App
  6. Download JSON → save as client_secrets.json in this folder
"""

import base64
import os
import pickle
import sys

def check_deps():
    try:
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("❌ Missing dependencies. Run:")
        print("   pip install google-api-python-client google-auth-oauthlib")
        sys.exit(1)

def main():
    check_deps()

    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    CLIENT_SECRETS = "client_secrets.json"
    TOKEN_FILE     = "youtube_token.pickle"
    SCOPES         = [
        "https://www.googleapis.com/auth/youtube",            # Full management
        "https://www.googleapis.com/auth/youtube.upload",     # Upload videos
        "https://www.googleapis.com/auth/youtube.force-ssl",  # Comments + metadata
        "https://www.googleapis.com/auth/youtube.readonly",   # Read channel info
    ]

    print("\n" + "="*55)
    print("  நிதி நீதி தமிழ் — YouTube OAuth Setup")
    print("="*55)

    # ── Step 1: Check client_secrets.json exists
    if not os.path.exists(CLIENT_SECRETS):
        print(f"\n❌ {CLIENT_SECRETS} not found!")
        print("\nTo get it:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create project → Enable 'YouTube Data API v3'")
        print("  3. APIs & Services → Credentials")
        print("  4. Create → OAuth 2.0 Client ID → Desktop App")
        print("  5. Download JSON → save as client_secrets.json here")
        sys.exit(1)

    print(f"\n✅ Found {CLIENT_SECRETS}")

    # ── Step 2: Run OAuth flow
    print("\n🌐 Opening browser for YouTube authentication...")
    print("   Sign in with the YouTube channel account (@NidhiNeethiTamil)\n")

    try:
        flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
        creds = flow.run_local_server(port=8080, open_browser=True)
    except Exception as e:
        print(f"\n❌ OAuth failed: {e}")
        print("\nTry running on a machine with a browser.")
        sys.exit(1)

    # ── Step 3: Save token pickle
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    print(f"✅ Token saved: {TOKEN_FILE}")

    # ── Step 4: Verify it works
    print("\n🔍 Verifying YouTube access...")
    try:
        youtube  = build("youtube", "v3", credentials=creds)
        response = youtube.channels().list(part="snippet", mine=True).execute()
        channels = response.get("items", [])
        if channels:
            name = channels[0]["snippet"]["title"]
            print(f"✅ Connected to channel: {name}")
        else:
            print("⚠️  No channel found — make sure you logged in with the right account")
    except Exception as e:
        print(f"⚠️  Verification failed: {e}")
        print("   Token may still work for upload — continuing...")

    # ── Step 5: Encode both files to base64
    print("\n" + "="*55)
    print("  GITHUB SECRETS — copy these values exactly")
    print("="*55)

    with open(TOKEN_FILE, "rb") as f:
        token_b64 = base64.b64encode(f.read()).decode("utf-8")

    with open(CLIENT_SECRETS, "rb") as f:
        secrets_b64 = base64.b64encode(f.read()).decode("utf-8")

    print("\n1️⃣  Secret name:  YOUTUBE_TOKEN_BASE64")
    print("   Secret value:")
    print(f"\n{token_b64}\n")

    print("─"*55)

    print("\n2️⃣  Secret name:  CLIENT_SECRETS_BASE64")
    print("   Secret value:")
    print(f"\n{secrets_b64}\n")

    print("─"*55)
    print("\n📋 How to add to GitHub:")
    print("  1. Go to github.com/mohankumarfounder-series/nn")
    print("  2. Settings → Secrets and variables → Actions")
    print("  3. New repository secret")
    print("  4. Paste name + value for each secret above")
    print("\n✅ Done! Run daily workflow to test upload.")
    print("="*55 + "\n")


if __name__ == "__main__":
    main()
