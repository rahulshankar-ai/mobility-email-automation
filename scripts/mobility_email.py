#!/usr/bin/env python3
"""
Mobility Weekly Email Automation + App Sync
Every Sunday 8 PM IST:
  1. Fetches mobility news from Google News RSS
  2. Deduplicates vs previously-sent stories
  3. Sends rich HTML email to team
  4. Writes the same stories to the app's stories.json Gist
     so the Netlify web app always mirrors the email
"""

import os
import re
import json
import hashlib
import smtplib
import html as html_lib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
GH_PAT = os.environ["GH_PAT"]
HISTORY_GIST_ID = os.environ["HISTORY_GIST_ID"]
STORIES_GIST_ID = os.environ.get("STORIES_GIST_ID", "0d71237881e03fbfa0ca095f13d4e003")

RECIPIENTS = ["shan@nammayatri.in", "rahul.shankar@nammayatri.in", "balaje@nammayatri.in"]

SEARCH_QUERIES = [
    "Namma Yatri news",
    "Ola Uber India ride hailing",
    "Rapido bike taxi India",
    "mobility tech India news",
    "public transit technology India",
    "EV electric vehicle India news",
    "autonomous vehicle news",
    "micromobility scooter bike sharing",
    "transportation startup funding India",
    "urban mobility policy India",
    "ONDC transport India",
    "metro rail expansion India",
    "last mile connectivity India",
    "Southeast Asia ride hailing Grab Gojek",
    "European mobility startup",
    "Waymo Tesla robotaxi news",
    "mobility super app global",
]

# ── Category + Region detection ───────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "ev_charging": ["EV", "electric vehicle", "Tesla", "battery", "charging", "electr"],
    "ride_hailing": ["ride-hail", "ridehail", "Uber", "Ola ", "Rapido", "Namma Yatri",
                     "Lyft", "Grab", "Gojek", "Didi", "taxi", "cab", "auto-rickshaw",
                     "ride sharing", "ridesharing"],
    "public_transit": ["metro", "bus rapid", "BRT", "train", "rail transit", "subway",
                       "public transport", "BMTC", "BEST ", "BRTS", "tram"],
    "autonomous_vehicles": ["autonomous", "self-driving", "AV ", "robotaxi",
                             "driverless", "Waymo", "Cruise", "Nuro"],
    "micromobility": ["scooter", "e-scooter", "micromobility", "cycling", "bike shar",
                      "Tier ", "Lime ", "Bird "],
    "regulations": ["regulat", "policy", "law ", "government", "ban ", "permit",
                    "license", "rule ", "ministry", "NITI"],
    "startups": ["startup", "funding", "invest", "raise", "IPO", "unicorn",
                 "Series A", "Series B", "seed round", "valuation"],
}

REGION_KEYWORDS = {
    "india": ["India", "Bengaluru", "Bangalore", "Mumbai", "Delhi", "Chennai",
              "Hyderabad", "Kolkata", "Namma Yatri", "Ola ", "Rapido", "ONDC",
              "BMTC", "Indian ", "rupee", "crore", "lakh"],
    "se_asia": ["Southeast Asia", "Singapore", "Malaysia", "Indonesia", "Thailand",
                "Vietnam", "Philippines", "Grab", "Gojek", "GoTo"],
    "europe": ["Europe", "European", "UK ", "Germany", "France", "Netherlands",
               "Spain", "Italy", "Tier ", "Voi ", "Bolt "],
    "north_america": ["US ", "USA", "America", "New York", "California", "Tesla",
                      "Waymo", "Lyft", "Cruise", "Nuro", "Uber Tech", "American "],
    "global": ["global", "worldwide", "international"],
}

def detect_category(text):
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text.lower() for kw in keywords):
            return cat
    return "ride_hailing"

def detect_region(text):
    for region, keywords in REGION_KEYWORDS.items():
        if any(kw.lower() in text.lower() for kw in keywords):
            return region
    return "india"

# ── Gist helpers ─────────────────────────────────────────────────────────────

def gist_get(gist_id, filename):
    url = f"https://api.github.com/gists/{gist_id}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mobility-brief"
    })
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data["files"][filename]["content"]

def gist_patch(gist_id, filename, content):
    payload = json.dumps({"files": {filename: {"content": content}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        data=payload, method="PATCH",
        headers={
            "Authorization": f"token {GH_PAT}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "mobility-brief"
        }
    )
    with urllib.request.urlopen(req) as r:
        pass

def load_sent_hashes():
    return set(json.loads(gist_get(HISTORY_GIST_ID, "sent_hashes.json")))

def save_sent_hashes(hashes):
    updated = list(hashes)[-2000:]
    gist_patch(HISTORY_GIST_ID, "sent_hashes.json", json.dumps(updated))

# ── RSS fetch ─────────────────────────────────────────────────────────────────

def fetch_rss(query):
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception as e:
        print(f"  RSS error for '{query}': {e}")
        return b""

def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()

def parse_rss(xml_bytes):
    stories = []
    try:
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return stories
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date_str = (item.findtext("pubDate") or "").strip()
            desc = strip_html(html_lib.unescape(item.findtext("description") or ""))
            source_el = item.find("source")
            source = source_el.text.strip() if source_el is not None else ""
            stories.append({
                "title": title, "url": link, "pub_date_str": pub_date_str,
                "description": desc[:300] if desc else "",
                "source": source
            })
    except Exception as e:
        print(f"  Parse error: {e}")
    return stories

def parse_pub_date(date_str):
    for fmt in ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

# ── App Gist update ───────────────────────────────────────────────────────────

def update_app_stories(fresh_stories):
    """Write stories to the app's stories.json Gist so Netlify mirrors the email."""
    app_stories = []
    for i, s in enumerate(fresh_stories, 1):
        combined = s["title"] + " " + s.get("description", "") + " " + s.get("source", "")
        category = detect_category(combined)
        region = detect_region(combined)
        date_disp = s["pub_dt"].strftime("%b %d") if s.get("pub_dt") else "Recent"
        summary = s.get("description") or s["title"]
        app_stories.append({
            "id": i,
            "title": s["title"],
            "summary": summary,
            "source": s["source"],
            "url": s["url"],
            "date": date_disp,
            "category": category,
            "region": region,
        })
    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stories": app_stories
    }
    gist_patch(STORIES_GIST_ID, "stories.json", json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Updated app stories.json Gist with {len(app_stories)} stories")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Mobility Weekly Brief ===")
    print(f"Run time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    sent_hashes = load_sent_hashes()
    print(f"Previously sent: {len(sent_hashes)} stories")

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    print(f"Cutoff: {cutoff.strftime('%Y-%m-%d')}")

    all_stories = []
    for query in SEARCH_QUERIES:
        print(f"  Fetching: {query}")
        xml = fetch_rss(query)
        all_stories.extend(parse_rss(xml))
    print(f"Total raw stories: {len(all_stories)}")

    seen_urls = set()
    fresh_stories = []
    new_hashes = set()
    for s in all_stories:
        url = s["url"]
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in sent_hashes or url in seen_urls:
            continue
        pub_dt = parse_pub_date(s["pub_date_str"])
        if pub_dt and pub_dt < cutoff:
            continue
        seen_urls.add(url)
        new_hashes.add(url_hash)
        fresh_stories.append({**s, "pub_dt": pub_dt})

    fresh_stories.sort(
        key=lambda x: x["pub_dt"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )
    fresh_stories = fresh_stories[:60]
    print(f"Fresh stories this week: {len(fresh_stories)}")

    if not fresh_stories:
        print("No new stories — skipping email.")
        return

    # Build email HTML
    week_label = datetime.now(timezone.utc).strftime("%b %d, %Y")
    rows_html = ""
    for i, s in enumerate(fresh_stories, 1):
        date_disp = s["pub_dt"].strftime("%b %d") if s["pub_dt"] else "Recent"
        combined = s["title"] + " " + s.get("description", "") + " " + s.get("source", "")
        cat = detect_category(combined)
        cat_emoji = {
            "ride_hailing": "🚗", "ev_charging": "⚡", "public_transit": "🚌",
            "autonomous_vehicles": "🤖", "micromobility": "🛴", "regulations": "📋",
            "startups": "🚀"
        }.get(cat, "📰")
        rows_html += f'<tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px 8px;color:#6b7280;font-size:13px;width:40px;">{i}</td><td style="padding:12px 8px;"><a href="{s["url"]}" style="color:#1e40af;font-weight:600;text-decoration:none;font-size:15px;">{s["title"]}</a><div style="color:#6b7280;font-size:12px;margin-top:4px;">{cat_emoji} {s["source"]} &middot; {date_disp}</div></td></tr>'

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"><div style="max-width:700px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
<div style="background:linear-gradient(135deg,#1e1b4b,#4338ca);padding:32px 40px;"><div style="font-size:22px;font-weight:700;color:#fff;">&#x1F680; Moving Tech Brief</div><div style="font-size:14px;color:#c7d2fe;margin-top:6px;">Weekly Mobility Intelligence &middot; Week of {week_label}</div></div>
<div style="padding:20px 40px 0;color:#374151;font-size:15px;">{len(fresh_stories)} fresh mobility stories from the last 7 days. <a href="https://mobility-mti.netlify.app/" style="color:#4338ca;">View in browser &rarr;</a></div>
<div style="padding:16px 40px 32px;"><table style="width:100%;border-collapse:collapse;">{rows_html}</table></div>
<div style="background:#f1f5f9;padding:20px 40px;font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;">Auto-generated every Sunday 8 PM IST by Moving Tech Brief &middot; <a href="https://mobility-mti.netlify.app/" style="color:#6366f1;">mobility-mti.netlify.app</a></div>
</div></body></html>"""

    # Send email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"\U0001F680 Moving Tech Brief \u2014 Week of {week_label} ({len(fresh_stories)} stories)"
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html"))
    print("Sending email...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())
    print(f"Sent to {len(RECIPIENTS)} recipients")

    # Update app Gist so Netlify app mirrors email
    update_app_stories(fresh_stories)

    # Save hashes to prevent resend
    updated_hashes = sent_hashes | new_hashes
    save_sent_hashes(updated_hashes)
    print(f"Saved {len(updated_hashes)} hashes")
    print("=== Done ===")

if __name__ == "__main__":
    main()
