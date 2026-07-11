# Instagram Non-Followers Checker — Design

Date: 2026-07-11 · Status: approved by user

## Purpose

Personal-use script (run ~2x/year) that lists Instagram accounts the user follows
that do not follow back. Output: JSON with profile links. Must be slow/gentle to
avoid bot detection.

## Approach (user chose: both modes)

**Mode 1 — cookie (default):** `python check.py`
- Auth: `IG_SESSIONID` + `IG_DS_USER_ID` cookies from the user's logged-in browser, stored in `.env`.
- Calls Instagram's internal web API (`/api/v1/friendships/<id>/following/` and `/followers/`), 100 per page, browser-identical headers, no login event.
- Pacing: random 8–25 s between pages; extra 60–120 s pause every 10 pages.
- Resume: every page is persisted to `state/session_state.json`; a run interrupted by Ctrl-C, 429, or a challenge continues where it left off (state valid for 24 h; `--fresh` discards it).
- On 401/403/429/`challenge_required`: save state, exit with a clear message pointing at mode 2.

**Mode 2 — official export (zero risk):** `python check.py --from-export <zip>`
- Parses `followers_*.json` / `following.json` from Instagram's official
  "Download your information" ZIP (JSON format). No network calls.

## Data policy (user requirement)

Save `username` and `profile_url` always. Save other fields (`full_name`) **only
when returned in the same request/file** — never make additional requests to
enrich user data. Export mode therefore has no `full_name`.

## Output

`exports/nonfollowers_YYYY-MM-DD.json`:

```json
{
  "generated_at": "ISO-8601",
  "mode": "cookie | export",
  "following": 412,
  "followers": 389,
  "not_following_back_count": 23,
  "not_following_back": [
    {"username": "someuser", "full_name": "Some User", "profile_url": "https://instagram.com/someuser"}
  ]
}
```

Terminal prints summary counts + the username list.

## Components

- `check.py` — single file: env loading, cookie-mode fetcher (paged, stateful), export-mode parser, differ, writer.
- `.env.example`, `README.md` (where to find the cookies), `requirements.txt` (`requests`, `python-dotenv`), `.gitignore` (`.env`, `state/`, `exports/`, `venv/`).

## Error handling

- Missing/expired cookies → actionable message (how to re-grab sessionid).
- Rate limit / challenge → save state, exit non-zero, suggest waiting or mode 2.
- Malformed export ZIP → say which expected file was not found.

## Testing

- Export mode: end-to-end against a synthetic ZIP fixture.
- Cookie mode: pagination/diff/state logic exercised with a mocked HTTP session (no real Instagram calls during development).

## Known caveat

Mode 1 uses Instagram's private web API (against ToS). Read-only, own session,
2x/year → practical risk very low; mode 2 is the zero-risk fallback.
