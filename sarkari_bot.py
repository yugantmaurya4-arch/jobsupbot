"""
Govt Jobs RSS -> Telegram channel auto-poster
Source: indgovtjobs.in (Blogger RSS feed)
Install: pip install feedparser requests beautifulsoup4
Env vars: BOT_TOKEN (secret), CHANNEL_ID (optional)
"""
import os
import json
import html
import time
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@govermentjobsupdatestelegram")

# ---- Config ----
FEEDS = [
    "http://www.indgovtjobs.in/feeds/posts/default?alt=rss",
]
SEEN_FILE = "seen.json"
MAX_POSTS_PER_RUN = 10
FIRST_RUN_TEST_POSTS = 1   # pehli run me sirf itni latest jobs post hongi, baaki yaad rakhi jayengi
KEYWORDS = ["total post", "vacancy", "vacancies", "last date", "start date",
            "age limit", "qualification", "salary", "pay scale", "application fee"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def fetch_feed(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return feedparser.parse(r.content)


def entry_html(entry):
    if entry.get("content"):
        return entry["content"][0].get("value", "")
    return entry.get("summary", "")


def extract(entry):
    """Entry ke content se details aur apply/official links nikalta hai."""
    soup = BeautifulSoup(entry_html(entry), "html.parser")
    own_domain = urlparse(entry.get("link", "")).netloc

    details = []
    for tr in soup.find_all("tr"):
        row = " ".join(c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"]))
        if any(k in row.lower() for k in KEYWORDS) and 8 < len(row) < 200:
            if row not in details:
                details.append(row)
        if len(details) >= 6:
            break
    if not details:  # table na mile to shuru ka text
        text = soup.get_text(" ", strip=True)
        if text:
            details = [text[:350].rsplit(" ", 1)[0] + "..."]

    apply_link = official_link = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = a["href"]
        if not href.startswith("http"):
            continue
        external = urlparse(href).netloc != own_domain
        if not apply_link and "apply" in text and external:
            apply_link = href
        if not official_link and external and (
                "official" in text or "notification" in text or "advertisement" in text):
            official_link = href
    return details, apply_link, official_link


def build_message(entry):
    title = html.escape(entry.get("title", "No title"))
    page = entry.get("link", "")
    details, apply_link, official = extract(entry)

    lines = [f"🔔 <b>{title}</b>", ""]
    if details:
        lines.append("📄 <b>Details:</b>")
        lines += [f"• {html.escape(d)}" for d in details]
        lines.append("")
    if apply_link:
        lines.append(f'✅ <a href="{apply_link}">Apply Online</a>')
    if official:
        lines.append(f'🌐 <a href="{official}">Official Notification</a>')
    lines.append(f'📎 <a href="{page}">Full Details</a>')
    return "\n".join(lines)[:4000]


def send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
        timeout=30,
    )
    r.raise_for_status()


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen = set()
    if not first_run:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = set(json.load(f))

    entries = []
    for url in FEEDS:
        entries += fetch_feed(url).entries  # feed me nayi pehle aati hain

    if first_run:
        # Latest FIRST_RUN_TEST_POSTS ko chhodke baaki ko seen mark karo
        for e in entries[FIRST_RUN_TEST_POSTS:]:
            seen.add(e.get("id") or e.get("link"))
        entries = entries[:FIRST_RUN_TEST_POSTS]

    new = [e for e in entries if (e.get("id") or e.get("link")) not in seen]
    new = new[:MAX_POSTS_PER_RUN]

    for e in reversed(new):  # purani pehle, nayi baad me
        try:
            send(build_message(e))
            seen.add(e.get("id") or e.get("link"))
            time.sleep(2)
        except Exception as ex:
            print("Send failed:", e.get("title"), ex)

    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


if __name__ == "__main__":
    main()
