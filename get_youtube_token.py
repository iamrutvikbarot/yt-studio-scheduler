"""
One-Time YouTube Refresh Token Generator
Run this script locally on your PC once to authorize your YouTube channel
and get the YT_REFRESH_TOKEN to paste into GitHub Secrets.
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def generate_refresh_token():
    print("=======================================================")
    print("   YouTube OAuth Refresh Token Generator (One-Time)   ")
    print("=======================================================\n")

    client_id = input("Enter your YouTube OAuth Client ID: ").strip()
    client_secret = input("Enter your YouTube OAuth Client Secret: ").strip()

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("\n🌐 A browser tab will open automatically. Sign in with the Google Account that owns your YouTube channel and click 'Allow'...\n")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    print("\n=======================================================")
    print("✅ SUCCESS! Here are your credentials for GitHub Secrets:")
    print("=======================================================")
    print(f"YT_CLIENT_ID:     {client_id}")
    print(f"YT_CLIENT_SECRET: {client_secret}")
    print(f"YT_REFRESH_TOKEN: {creds.refresh_token}")
    print("=======================================================\n")
    print("👉 Copy 'YT_REFRESH_TOKEN' and add it to your GitHub Repository Secrets.")

if __name__ == "__main__":
    generate_refresh_token()
