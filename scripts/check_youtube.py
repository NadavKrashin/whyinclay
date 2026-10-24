"""Check that the app's YouTube connection works. Run on the Mac that runs the app:

    cd ~/daily-shorts && git pull && .venv/bin/python scripts/check_youtube.py

It uses the keys in .env (YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN), gets an
access token the way the app does, and asks YouTube which channel it belongs to (channels.list, one of
the endpoints declared in the API audit). It only reads; it never uploads. Secrets are never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from waitwhy.settings import secrets  # noqa: E402

TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
FIX = ("Fix: on this Mac run `python3 scripts/youtube_auth.py ~/Downloads/client_secret_*.json`, sign in and "
       "pick the Why in Clay channel, restart the app's services, then run this check again.")


def main() -> int:
    s = secrets()
    if not (s.youtube_client_id and s.youtube_client_secret and s.youtube_refresh_token):
        print(f"YouTube keys are missing from .env.\n{FIX}")
        return 1
    try:
        r = httpx.post(TOKEN_URL, data={"client_id": s.youtube_client_id, "client_secret": s.youtube_client_secret,
                                        "refresh_token": s.youtube_refresh_token, "grant_type": "refresh_token"},
                       timeout=30)
    except httpx.HTTPError as e:
        raise SystemExit(f"Could not reach Google ({type(e).__name__}). Check the Mac's internet connection.")
    if r.status_code != 200:
        err = r.json().get("error", f"HTTP {r.status_code}") if r.headers.get("content-type", "").startswith(
            "application/json") else f"HTTP {r.status_code}"
        why = " (the sign-in expired or was revoked)" if err == "invalid_grant" else ""
        print(f"The YouTube connection does NOT work: Google says {err}{why}.\n{FIX}")
        return 1
    access = r.json()["access_token"]
    c = httpx.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                  headers={"Authorization": f"Bearer {access}"}, timeout=30)
    items = c.json().get("items", []) if c.status_code == 200 else []
    if not items:
        print(f"Signed in, but YouTube returned no channel (HTTP {c.status_code}). Pick the Why in Clay "
              f"channel (the brand account) on the account chooser.\n{FIX}")
        return 1
    print(f"YouTube connection works: channel \"{items[0]['snippet']['title']}\".")
    print("All good: the app can upload to YouTube.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
