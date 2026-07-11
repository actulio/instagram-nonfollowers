# 📷 Instagram Non-Followers Checker

Lists accounts you follow on Instagram that don't follow you back.
Personal use, designed to run rarely (e.g., every 6 months) and slowly enough
to not trip bot detection.

## Two modes

### Mode 1 — cookie (automated, default)

Uses your existing browser session — no login event, just slow paged reads of
the same API your browser calls.

**Get your cookies (~1 minute):**

1. Open [instagram.com](https://www.instagram.com) in Chrome, logged in.
2. DevTools (`Cmd+Opt+I`) → **Application** tab → **Cookies** → `https://www.instagram.com`.
3. Copy the values of `sessionid` and `ds_user_id`.

```bash
cp .env.example .env   # then paste the two values
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python check.py
```

Expect ~5–15 minutes for a typical account — the delays are intentional.
Interrupted (Ctrl-C, rate limit, challenge)? Just re-run: progress is cached in
`state/` and it resumes. Use `--fresh` to force a full re-fetch.

> ⚠️ This mode uses Instagram's private web API (against ToS). Read-only +
> your own session + twice a year keeps practical risk very low. If Instagram
> ever complains, use mode 2.

### Mode 2 — official data export (zero risk)

1. Instagram → **Accounts Center** → **Your information and permissions** →
   **Download your information** → select only **Followers and following**,
   format **JSON**.
2. Wait for the email, download the ZIP.

```bash
python check.py --from-export ~/Downloads/instagram-xxxx.zip
```

## Output

`exports/nonfollowers_YYYY-MM-DD.json`:

```json
{
  "generated_at": "2026-07-11T12:00:00+00:00",
  "mode": "cookie",
  "following": 412,
  "followers": 389,
  "not_following_back_count": 23,
  "not_following_back": [
    {"username": "someuser", "profile_url": "https://instagram.com/someuser", "full_name": "Some User"}
  ]
}
```

`full_name` appears only when the API returned it in the same response
(export mode has usernames/links only). The script never makes extra
per-user requests.
