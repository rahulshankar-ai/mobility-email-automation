# Mobility Email Automation

Automated weekly mobility news digest sent every **Sunday at 8 PM IST** via GitHub Actions.

## What it does
- Fetches fresh mobility news from Google News RSS (17 search queries)
- Filters to last 7 days only
- Deduplicates against previously sent stories (stored in a private Gist)
- Sends a rich HTML email to the Namma Yatri mobility team

## Setup (already done)
The following secrets are configured in this repo:
- `GMAIL_USER` — Gmail address to send from
- `GMAIL_APP_PASS` — Gmail App Password (not your regular password)
- `HISTORY_GIST_ID` — Gist ID for tracking sent stories

## Manual trigger
Go to **Actions → Mobility Weekly Brief → Run workflow** to send immediately.

## Schedule
Runs automatically: `30 14 * * 0` (Sunday 14:30 UTC = 8:00 PM IST)

## Recipients
- shan@nammayatri.in
- rahul.shankar@nammayatri.in
- balaje@nammayatri.in
