#!/usr/bin/env python3
"""
MovingTech Brief - Daily Push Notifier
Runs daily at 8 AM IST via GitHub Actions.
Sends Web Push notifications when >= 2 new mobility stories found.
"""
import os, json, hashlib, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

GH_PAT            = os.environ["GH_PAT"]
TOKEN_GIST_ID     = os.environ["TOKEN_GIST_ID"]
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_PUBLIC_KEY  = os.environ["VAPID_PUBLIC_KEY"]
VAPID_SUBJECT     = os.environ.get("VAPID_SUBJECT", "mailto:rahul.shankar@nammayatri.in")

HEADERS = {
    "Authorization": f"token {GH_PAT}",
    "Accept": "application/vnd.github.v3+json",
    "Content-Type": "application/json",
    "User-Agent": "mobility-notifier/1.0",
}

QUERIES = [
    "Namma Yatri OR Rapido OR Ola ride hailing India",
    "Uber Ola Rapido India 2026",
    "electric vehicle EV India 2026",
    "ONDC mobility India",
    "Grab GoTo Southeast Asia ride hailing",
    "autonomous robotaxi 2026",
    "ride hailing gig worker regulations 2026",
    "public transit metro rail India 2026",
    "mobility startup funding 2026",
    "DiDi Bolt inDrive Latin America Africa",
]

def fetch_rss(query, hours=24):
    url = (f"https://news.google.com/rss/search?"
           f"q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            tree = ElementTree.parse(r)
    except Exception as e:
        print(f"  RSS error: {e}")
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stories = []
    for item in tree.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        try:
            pub_dt = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = datetime.now(timezone.utc)
        if pub_dt < cutoff:
            continue
        stories.append({"title": title, "url": link, "pub_dt": pub_dt})
    return stories

def gist_get(gist_id):
    req = urllib.request.Request(f"https://api.github.com/gists/{gist_id}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def gist_patch(gist_id, files):
    payload = json.dumps({"files": files}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        data=payload, headers=HEADERS, method="PATCH")
    with urllib.request.urlopen(req) as r:
        print(f"  Gist patch -> {r.status}")

def read_json_file(gist_data, filename, default):
    f = gist_data.get("files", {}).get(filename)
    if not f:
        return default
    try:
        req = urllib.request.Request(f["raw_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)
    except Exception as e:
        print(f"  Error reading {filename}: {e}")
        return default

def send_web_push(subscription, title, body, url):
    try:
        from pywebpush import webpush
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={
                "sub": VAPID_SUBJECT,
                "exp": int((datetime.now(timezone.utc) + timedelta(hours=12)).timestamp()),
            },
        )
        return True
    except Exception as e:
        print(f"  Web push error: {e}")
        return False

def main():
    print(f"=== Daily Notifier - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")
    gist_data     = gist_get(TOKEN_GIST_ID)
    subscriptions = read_json_file(gist_data, "push_subs.json",    [])
    notif_hashes  = set(read_json_file(gist_data, "notif_hashes.json", []))
    print(f"  Subscriptions: {len(subscriptions)}, Known hashes: {len(notif_hashes)}")

    if not subscriptions:
        print("No push subscriptions - nothing to send.")
        return

    print("Fetching RSS...")
    seen, fresh = set(), []
    for q in QUERIES:
        for s in fetch_rss(q, hours=24):
            if s["url"] not in seen:
                seen.add(s["url"])
                fresh.append(s)
    print(f"  Raw stories: {len(fresh)}")

    new_stories, new_hashes = [], set()
    for s in fresh:
        h = hashlib.md5(s["url"].encode()).hexdigest()
        if h not in notif_hashes:
            new_stories.append(s)
            new_hashes.add(h)
    print(f"  New stories: {len(new_stories)}")

    if len(new_stories) < 2:
        print("< 2 new stories - skipping.")
        return

    new_stories.sort(key=lambda x: x["pub_dt"], reverse=True)
    title = f"\U0001f6a8 {len(new_stories)} new mobility stories today"
    body  = new_stories[0]["title"][:100]
    url   = "https://mobility-mti.netlify.app/"
    print(f"Sending: {title}")

    ok, fail, dead = 0, 0, []
    for i, sub in enumerate(subscriptions):
        if send_web_push(sub, title, body, url):
            ok += 1
        else:
            fail += 1
            dead.append(i)
    print(f"  ok={ok} fail={fail}")

    if dead:
        subscriptions = [s for i, s in enumerate(subscriptions) if i not in dead]
        print(f"  Pruned {len(dead)} dead sub(s)")

    updated = list(notif_hashes | new_hashes)[-5000:]
    gist_patch(TOKEN_GIST_ID, {
        "push_subs.json":    {"content": json.dumps(subscriptions, indent=2)},
        "notif_hashes.json": {"content": json.dumps(updated,       indent=2)},
    })
    print("Done.")

if __name__ == "__main__":
    main()
