#!/usr/bin/env python3
"""
Mobility Weekly Email Automation
Fetches top mobility news from Google News RSS, deduplicates against sent history,
and sends a rich HTML email via Gmail SMTP.
Runs every Sunday at 8 PM IST via GitHub Actions.
"""

import os
import json
import hashlib
import smtplib
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

RECIPIENTS = ["shan@nammayatri.in", "rahul.shankar@nammayatri.in", "balaje@nammayatri.in"]

SEARCH_QUERIES = [
    "mobility tech news",
    "ride hailing app news",
    "Namma Yatri news",
    "Ola Uber India news",
    "public transit technology",
    "EV electric vehicle news India",
    "autonomous vehicle news",
    "micromobility scooter bike sharing",
    "transportation startup funding",
    "urban mobility policy India",
    "ONDC transport India",
    "Rapido bike taxi news",
    "metro rail expansion India",
    "last mile connectivity news",
    "mobility super app",
    "Southeast Asia ride hailing",
    "European mobility startup",
]

def load_sent_hashes():
    url = f"https://api.github.com/gists/{HISTORY_GIST_ID}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mobility-brief"
    })
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    content = data["files"]["sent_hashes.json"]["content"]
    return set(json.loads(content))

def save_sent_hashes(hashes):
    payload = json.dumps({
        "files": {
            "sent_hashes.json": {
                "content": json.dumps(list(hashes))
            }
        }
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{HISTORY_GIST_ID}",
        data=payload,
        method="PATCH",
        headers={
            "Authorization": f"token {GH_PAT}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "mobility-brief"
        }
    )
    with urllib.request.urlopen(req) as r:
        pass

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
            source_el = item.find("source")
            source = source_el.text.strip() if source_el is not None else ""
            stories.append({"title": title, "url": link, "pub_date_str": pub_date_str, "source": source})
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

def main():
    print("=== Mobility Weekly Brief ===")
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
    fresh_stories.sort(key=lambda x: x["pub_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    fresh_stories = fresh_stories[:60]
    print(f"Fresh stories this week: {len(fresh_stories)}")
    if not fresh_stories:
        print("No new stories — skipping email.")
        return
    week_label = datetime.now(timezone.utc).strftime("%b %d, %Y")
    rows_html = ""
    for i, s in enumerate(fresh_stories, 1):
        date_disp = s["pub_dt"].strftime("%b %d") if s["pub_dt"] else "Recent"
        rows_html += f'<tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px 8px;color:#6b7280;font-size:13px;width:40px;">{i}</td><td style="padding:12px 8px;"><a href="{s["url"]}" style="color:#1e40af;font-weight:600;text-decoration:none;font-size:15px;">{s["title"]}</a><div style="color:#6b7280;font-size:12px;margin-top:4px;">{s["source"]} &middot; {date_disp}</div></td></tr>'
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"><div style="max-width:700px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);"><div style="background:linear-gradient(135deg,#1e1b4b,#4338ca);padding:32px 40px;"><div style="font-size:22px;font-weight:700;color:#fff;">&#x1F680; Moving Tech Brief</div><div style="font-size:14px;color:#c7d2fe;margin-top:6px;">Weekly Mobility Intelligence &middot; Week of {week_label}</div></div><div style="padding:24px 40px 0;color:#374151;font-size:15px;">{len(fresh_stories)} fresh mobility stories from the last 7 days.</div><div style="padding:20px 40px 32px;"><table style="width:100%;border-collapse:collapse;">{rows_html}</table></div><div style="background:#f1f5f9;padding:20px 40px;font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;">Auto-generated by Moving Tech Brief &middot; GitHub Actions</div></div></body></html>"""
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
    updated_hashes = sent_hashes | new_hashes
    if len(updated_hashes) > 2000:
        updated_hashes = set(list(updated_hashes)[-2000:])
    save_sent_hashes(updated_hashes)
    print(f"Saved {len(updated_hashes)} hashes to Gist")
    print("=== Done ===")

if __name__ == "__main__":
    main()
