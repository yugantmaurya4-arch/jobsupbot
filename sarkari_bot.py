"""
Govt Jobs RSS -> Telegram channel auto-poster (photo + salary + details)
Source: indgovtjobs.in (Blogger RSS feed)
Install: pip install feedparser requests beautifulsoup4
Env vars: BOT_TOKEN (secret), CHANNEL_ID (optional)
"""
import os
import re
import json
import html
import time
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@govermentjobsupdatestelegram")
CHANNEL_TAG = "@govermentjobsupdatestelegram"

# ---- Config ----
FEEDS = [
    "http://www.indgovtjobs.in/feeds/posts/default?alt=rss",
]
SEEN_FILE = "seen.json"
MAX_POSTS_PER_RUN = 10
FIRST_RUN_TEST_POSTS = 1   # pehli run me sirf itni latest jobs post hongi

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# (key, emoji, label, keywords jo table ke label me dhundhe jayenge)
FIELDS = [
    ("posts", "📌", "Total Posts",
     ["total post", "vacancy", "vacancies", "no. of post", "number of post", "no of post"]),
    ("qual", "🎓", "Qualification",
     ["qualification", "educational", "eligibility"]),
    ("salary", "💰", "Salary",
     ["salary", "pay scale", "pay level", "pay matrix", "stipend", "remuneration",
      "emolument", "honorarium", "consolidated pay", "monthly pay", "pay band"]),
    ("age", "🎂", "Age Limit", ["age limit", "maximum age", "age"]),
    ("fee", "💳", "Application Fee", ["application fee", "exam fee", "fee"]),
    ("start", "🗓", "Start Date", ["start date", "opening date", "starting date"]),
    ("last", "⏰", "Last Date", ["last date", "closing date", "end date"]),
]
SALARY_WORDS = ["salary", "stipend", "pay scale", "pay level", "remuneration",
                "per month", "p.m", "pay matrix", "emolument", "honorarium"]


def fetch_feed(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return feedparser.parse(r.content)


def entry_html(entry):
    if entry.get("content"):
        return entry["content"][0].get("value", "")
    return entry.get("summary", "")


def clean_value(v, limit=150):
    v = re.sub(r"\s+", " ", v).strip(" :-–|")
    return v[:limit].rsplit(" ", 1)[0] + "..." if len(v) > limit else v


def match_field(label):
    label = label.lower().strip(" :")
    for key, _, _, kws in FIELDS:
        for kw in kws:
            if kw == "age":
                if label.startswith("age") or "age limit" in label:
                    return key
            elif kw == "fee":
                if "fee" in label:
                    return key
            elif kw in label:
                return key
    return None


def extract_fields(entry, soup):
    found = {}

    # 1) Table rows: label | value
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            key = match_field(cells[0])
            if key and key not in found:
                found[key] = clean_value(" ".join(cells[1:]))
        elif len(cells) == 1 and ":" in cells[0]:
            label, _, value = cells[0].partition(":")
            key = match_field(label)
            if key and value.strip() and key not in found:
                found[key] = clean_value(value)

    # 2) Text lines "Label: value"
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for l in lines:
        if ":" in l and len(l) < 300:
            label, _, value = l.partition(":")
            key = match_field(label)
            if key and value.strip() and key not in found:
                found[key] = clean_value(value)

    # 3) Salary fallback: koi bhi line jisme salary shabd + number/rupee ho
    if "salary" not in found:
        for l in lines:
            low = l.lower()
            if (any(w in low for w in SALARY_WORDS)
                    and re.search(r"\d|₹|rs\.?", low) and len(l) < 250):
                found["salary"] = clean_value(re.sub(r"(?i)^.*?(salary|stipend)\s*[:\-]?\s*", "", l) or l)
                break

    # 4) Title se posts aur last date
    title = entry.get("title", "")
    if "posts" not in found:
        m = re.search(r"(\d[\d,]*)\s*(?:Posts?|Vacanc)", title, re.I)
        if m:
            found["posts"] = m.group(1)
    if "last" not in found:
        m = re.search(r"Last Date\s*[:\-]?\s*([\d]{1,2}[-/][\d]{1,2}[-/][\d]{2,4})", title, re.I)
        if m:
            found["last"] = m.group(1)
    return found


def extract_links(entry, soup):
    own = urlparse(entry.get("link", "")).netloc
    apply_link = official = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = a["href"]
        if not href.startswith("http") or urlparse(href).netloc == own:
            continue
        if not apply_link and "apply" in text:
            apply_link = href
        if not official and any(w in text for w in ("official", "notification", "advertisement")):
            official = href
    return apply_link, official


def upscale(url):
    url = re.sub(r"/s\d+(-c)?/", "/s1280/", url)
    url = re.sub(r"=s\d+(-c)?$", "=s1280", url)
    return url


def find_image(entry, soup):
    for key in ("media_thumbnail", "media_content"):
        items = entry.get(key) or []
        if items and items[0].get("url"):
            return upscale(items[0]["url"])
    for enc in entry.get("enclosures", []) or []:
        if "image" in enc.get("type", "") and enc.get("href"):
            return upscale(enc["href"])
    img = soup.find("img", src=True)
    if img and img["src"].startswith("http"):
        return upscale(img["src"])
    return None


def build_message(entry, soup):
    title = html.escape(entry.get("title", "No title"))
    fields = extract_fields(entry, soup)
    apply_link, official = extract_links(entry, soup)
    page = entry.get("link", "")

    lines = [f"🔔 <b>{title}</b>", ""]
    for key, emoji, label, _ in FIELDS:
        if key in fields:
            lines.append(f"{emoji} <b>{label}:</b> {html.escape(fields[key])}")
    if len(lines) == 2:  # kuch bhi structured na mile to short summary
        text = clean_value(soup.get_text(" ", strip=True), 350)
        if text:
            lines.append(f"📄 {html.escape(text)}")
    lines.append("")
    if apply_link:
        lines.append(f'✅ <a href="{apply_link}">Apply Online</a>')
    if official:
        lines.append(f'🌐 <a href="{official}">Official Notification</a>')
    lines.append(f'📎 <a href="{page}">Full Details</a>')
    lines.append("")
    lines.append(f"📢 Join: {CHANNEL_TAG}")
    return "\n".join(lines)[:4000], html.escape(entry.get("title", ""))


def tg(method, **data):
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                      data={"chat_id": CHANNEL_ID, "parse_mode": "HTML", **data}, timeout=60)
    r.raise_for_status()


def plain_len(msg):
    return len(html.unescape(re.sub(r"<[^>]+>", "", msg)))


def send_job(entry):
    soup = BeautifulSoup(entry_html(entry), "html.parser")
    msg, short_title = build_message(entry, soup)
    image = find_image(entry, soup)

    if image:
        try:
            if plain_len(msg) <= 1000:
                tg("sendPhoto", photo=image, caption=msg)
                return
            tg("sendPhoto", photo=image, caption=f"🔔 <b>{short_title}</b>")
            tg("sendMessage", text=msg, disable_web_page_preview=True)
            return
        except Exception as e:
            print("Photo failed, text bhej raha hoon:", e)
    tg("sendMessage", text=msg)


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen = set()
    if not first_run:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = set(json.load(f))

    entries = []
    for url in FEEDS:
        entries += fetch_feed(url).entries  # feed me nayi pehle aati hain

    uid = lambda e: e.get("id") or e.get("link")

    if first_run:
        for e in entries[FIRST_RUN_TEST_POSTS:]:
            seen.add(uid(e))
        entries = entries[:FIRST_RUN_TEST_POSTS]

    new = [e for e in entries if uid(e) not in seen][:MAX_POSTS_PER_RUN]

    for e in reversed(new):  # purani pehle, nayi baad me
        try:
            send_job(e)
            seen.add(uid(e))
            time.sleep(2)
        except Exception as ex:
            print("Send failed:", e.get("title"), ex)

    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


if __name__ == "__main__":
    main()
