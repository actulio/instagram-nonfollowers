#!/usr/bin/env python3
"""Find Instagram accounts you follow that don't follow you back.

Modes:
  python check.py                        # cookie mode (needs .env, slow on purpose)
  python check.py --from-export data.zip # parse official "Download your information" ZIP

Output: exports/nonfollowers_YYYY-MM-DD.json
"""

import argparse
import json
import random
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state" / "session_state.json"
EXPORTS_DIR = BASE_DIR / "exports"

PAGE_SIZE = 100
PAGE_DELAY = (8, 25)          # seconds between pages
LONG_PAUSE_EVERY = 10         # pages
LONG_PAUSE = (60, 120)        # seconds
STATE_MAX_AGE_HOURS = 24

API_BASE = "https://i.instagram.com/api/v1/friendships"


class ChallengeError(Exception):
    """Instagram asked for verification or rate-limited us."""


# ---------------------------------------------------------------- cookie mode

def load_env():
    env = {}
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def build_session(sessionid, ds_user_id):
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    })
    session.cookies.set("sessionid", sessionid, domain=".instagram.com")
    session.cookies.set("ds_user_id", ds_user_id, domain=".instagram.com")
    return session


def load_state(fresh):
    if fresh or not STATE_FILE.exists():
        return {"started_at": datetime.now(timezone.utc).isoformat()}
    state = json.loads(STATE_FILE.read_text())
    started = datetime.fromisoformat(state["started_at"])
    age_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    if age_hours > STATE_MAX_AGE_HOURS:
        print(f"Cached state is {age_hours:.0f}h old, starting fresh.")
        return {"started_at": datetime.now(timezone.utc).isoformat()}
    print("Resuming from cached state (use --fresh to discard).")
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def fetch_list(session, user_id, kind, state):
    """Fetch full 'following' or 'followers' list, resumable via state.

    Returns dict username -> {username, full_name, profile_url}.
    Only fields present in the API response itself are kept.
    """
    key = kind  # "following" | "followers"
    part = state.setdefault(key, {"users": {}, "next_max_id": None, "done": False})
    if part["done"]:
        print(f"{kind}: {len(part['users'])} (from cache)")
        return part["users"]

    page = 0
    while True:
        params = {"count": PAGE_SIZE}
        if part["next_max_id"]:
            params["max_id"] = part["next_max_id"]

        resp = session.get(f"{API_BASE}/{user_id}/{kind}/", params=params, timeout=30)

        if resp.status_code in (401, 403):
            raise ChallengeError(
                f"HTTP {resp.status_code}: session rejected. Your sessionid cookie is "
                "likely expired — grab a fresh one (see README), or use --from-export.")
        if resp.status_code == 429:
            raise ChallengeError(
                "HTTP 429: rate limited. Progress is saved — wait a few hours and "
                "re-run to resume, or use --from-export.")
        resp.raise_for_status()

        data = resp.json()
        if data.get("message") == "challenge_required":
            raise ChallengeError(
                "Instagram raised a verification challenge. Open instagram.com in your "
                "browser, complete it, then re-run (progress is saved) — or use --from-export.")

        for user in data.get("users", []):
            entry = {
                "username": user["username"],
                "profile_url": f"https://instagram.com/{user['username']}",
            }
            if user.get("full_name"):
                entry["full_name"] = user["full_name"]
            part["users"][user["username"].lower()] = entry

        part["next_max_id"] = data.get("next_max_id")
        save_state(state)
        page += 1
        print(f"{kind}: {len(part['users'])} fetched...", flush=True)

        if not part["next_max_id"]:
            part["done"] = True
            save_state(state)
            return part["users"]

        if page % LONG_PAUSE_EVERY == 0:
            pause = random.uniform(*LONG_PAUSE)
            print(f"  long pause {pause:.0f}s (anti-detection)...", flush=True)
        else:
            pause = random.uniform(*PAGE_DELAY)
        time.sleep(pause)


def run_cookie_mode(fresh):
    env = load_env()
    sessionid = env.get("IG_SESSIONID")
    ds_user_id = env.get("IG_DS_USER_ID")
    if not sessionid or not ds_user_id:
        sys.exit("Missing IG_SESSIONID / IG_DS_USER_ID in .env — see README.md.")

    session = build_session(sessionid, ds_user_id)
    state = load_state(fresh)
    try:
        following = fetch_list(session, ds_user_id, "following", state)
        followers = fetch_list(session, ds_user_id, "followers", state)
    except ChallengeError as exc:
        sys.exit(f"\nStopped: {exc}")
    STATE_FILE.unlink(missing_ok=True)  # clean run, no resume needed
    return following, followers, "cookie"


# ---------------------------------------------------------------- export mode

def parse_export_entries(payload):
    """Yield user entries from the export's string_list_data structure."""
    for item in payload:
        for entry in item.get("string_list_data", []):
            username = entry.get("value")
            href = entry.get("href", "")
            if not username and href:
                username = href.rstrip("/").rsplit("/", 1)[-1]
            if username:
                yield {
                    "username": username,
                    "profile_url": href or f"https://instagram.com/{username}",
                }


def run_export_mode(zip_path):
    zf = zipfile.ZipFile(zip_path)
    names = zf.namelist()

    follower_files = sorted(n for n in names
                            if re.search(r"followers(_\d+)?\.json$", Path(n).name)
                            and "close_friends" not in n)
    following_files = [n for n in names if Path(n).name == "following.json"]

    if not follower_files or not following_files:
        sys.exit("Could not find followers_*.json / following.json in the ZIP. "
                 "Request the export in JSON format (not HTML) and include "
                 "'Followers and following'.")

    followers = {}
    for name in follower_files:
        payload = json.loads(zf.read(name))
        if isinstance(payload, dict):  # some export versions wrap the list
            payload = next(iter(payload.values()))
        for entry in parse_export_entries(payload):
            followers[entry["username"].lower()] = entry

    following = {}
    for name in following_files:
        payload = json.loads(zf.read(name))
        if isinstance(payload, dict):
            payload = payload.get("relationships_following", [])
        for entry in parse_export_entries(payload):
            following[entry["username"].lower()] = entry

    return following, followers, "export"


# --------------------------------------------------------------------- output

def write_report(following, followers, mode):
    not_back = [following[u] for u in sorted(set(following) - set(followers))]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "following": len(following),
        "followers": len(followers),
        "not_following_back_count": len(not_back),
        "not_following_back": not_back,
    }
    EXPORTS_DIR.mkdir(exist_ok=True)
    out = EXPORTS_DIR / f"nonfollowers_{datetime.now():%Y-%m-%d}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"\nFollowing: {len(following)} | Followers: {len(followers)} | "
          f"Not following you back: {len(not_back)}\n")
    for entry in not_back:
        print(f"  {entry['username']:<30} {entry['profile_url']}")
    print(f"\nSaved: {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-export", metavar="ZIP",
                        help="parse an official Instagram data export ZIP instead of the API")
    parser.add_argument("--fresh", action="store_true",
                        help="discard cached resume state and start over")
    args = parser.parse_args()

    if args.from_export:
        following, followers, mode = run_export_mode(args.from_export)
    else:
        following, followers, mode = run_cookie_mode(args.fresh)

    write_report(following, followers, mode)


if __name__ == "__main__":
    main()
