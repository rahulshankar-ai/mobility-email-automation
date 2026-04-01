#!/usr/bin/env python3
"""
Daily Mobility News Notifier
Runs every day at 8 AM IST via GitHub Actions.
If new mobility stories appeared in the last 24 hours,
sends a push notification to all registered Expo devices.
"""

import os, json, hashlib, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

GH_PAT = os.environ["GH_PAT"]
TOKEN_GIST_ID = os.environ["TOKEN_GIST_ID"]
NOTIF_HISTORY_GIST_ID = os.environ.get("NOTIF_HISTORY_GIST_ID", TOKEN_GIST_ID)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

SEARCH_QUERIES = [
    "Namma Yatri news",
    "Ola Uber India ride hailing",
    "Rapido bike taxi India",
    "mobility tech India news",
    "EV electric vehicle India news",
    "autonomous vehicle news",
    "Southeast Asia ride hailing Grab Gojek",
    "mobility startup funding",
    "metro rail expansion India",
    "Waymo Tesla robotaxi news",
]

def gist_get(gist_id, filename):
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json", "User-Agent": "mobility-notifier"}
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data["files"][filename]["content"]

def gist_patch(gist_id, filename, content):
    payload = json.dumps({"files": {filename: {"content": content}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        data=payload, method="PATCH",
        headers={"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json", "User-Agent": "mobility-notifier"}
    )
    with urllib.request.urlopen(req) as r:
        pass

def fetch_rss(query):
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read()
    except Exception as e:
        print(f"  RSS error: {e}")
        return b""

def parse_pub_date(s):
    for fmt in ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def fetch_fresh_stories(cutoff):
    seen_urls, stories = set(), []
    for query in SEARCH_QUERIES:
        xml = fetch_rss(query)
        try:
            root = ET.fromstring(xml)
            channel = root.find("channel")
            if not channel:
                continue
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_dt = parse_pub_date(item.findtext("pubDate") or "")
                source_el = item.find("source")
                source = source_el.text.strip() if source_el is not None else ""
                if not link or link in seen_urls:
                    continue
                if pub_dt and pub_dt < cutoff:
                    continue
                seen_urls.add(link)
                stories.append({"title": title, "url": link, "pub_dt": pub_dt, "source": source})
        except Exception:
            pass
    stories.sort(key=lambda x: x["pub_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return stories

def send_expo_notifications(tokens, title, body, data=None):
    if not tokens:
        print("No tokens registered — skipping push.")
        return
    messages = [{"to": t, "title": title, "body": body, "data": data or {}, "sound": "default"} for t in tokens]
    payload = json.dumps(messages).encode()
    req = urllib.request.Request(
        EXPO_PUSH_URL,
        data=payload,
        headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    print(f"Push result: {result}")

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    print(f"=== Daily Mobility Notifier === {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Looking for stories since {cutoff.strftime('%Y-%m-%d %H:%M UTC')}")

    # Load registered push tokens
    tokens = json.loads(gist_get(TOKEN_GIST_ID, "push_tokens.json"))
    print(f"Registered devices: {len(tokens)}")

    # Load notification history (hashes of stories already notified about)
    try:
        notif_hashes = set(json.loads(gist_get(NOTIF_HISTORY_GIST_ID, "notif_hashes.json")))
    except Exception:
        notif_hashes = set()
    print(f"Previously notified: {len(notif_hashes)} stories")

    # Fetch today's stories
    stories = fetch_fresh_stories(cutoff)
    print(f"Fresh stories today: {len(stories)}")

    # Filter out already-notified
    new_stories = []
    new_hashes = set()
    for s in stories:
        h = hashlib.md5(s["url"].encode()).hexdigest()
        if h not in notif_hashes:
            new_stories.append(s)
            new_hashes.add(h)

    print(f"New (not yet notified): {len(new_stories)}")

    if len(new_stories) < 2:
        print("Fewer than 2 new stories — skipping notification to avoid noise.")
        return

    # Build notification
    count = len(new_stories)
    top_title = new_stories[0]["title"][:80] + ("..." if len(new_stories[0]["title"]) > 80 else "")
    notif_title = f"\U0001F6A8 {count} new mobility {'story' if count == 1 else 'stories'} today"
    notif_body = top_title

    print(f"Sending: {notif_title}")
    print(f"Body: {notif_body}")

    send_expo_notifications(tokens, notif_title, notif_body, data={"screen": "Feed"})

    # Save updated hashes
    updated = list(notif_hashes | new_hashes)[-3000:]
    gist_patch(NOTIF_HISTORY_GIST_ID, "notif_hashes.json", json.dumps(updated))
    print(f"Saved {len(updated)} notification hashes")
    print("=== Done ===")

if __name__ == "__main__":
    main()
