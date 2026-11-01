"""
Sarkari Result -> Telegram channel auto-poster
Install: pip install requests beautifulsoup4
Env vars: BOT_TOKEN, CHANNEL_ID
"""
import os
import re
import json
import html
import time
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@govermentjobsupdatestelegram")

# ---- Config (site badle to yahan change karo) ----
BASE_URL = "https://www.sarkariresult.com/"
SECTION_TEXT = "Latest Jobs"      # homepage pe jis box se jobs uthani hain
MAX_POSTS_PER_RUN = 10
SKIP_OLD_ON_FIRST_RUN = True      # pehli run me purani jobs post nahi hongi
SEEN_FILE = "seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
KEYWORDS = ["total post", "vacancy", "last date", "start date",
            "age limit", "qualification", "salary", "application fee"]


def get_soup(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def get_latest_jobs():
    """Homepage ke 'Latest Jobs' box se (title, url) list nikalta hai."""
    soup = get_soup(BASE_URL)
    heading = soup.find(string=re.compile(re.escape(SECTION_TEXT), re.I))
    if not heading:
        print("Section nahi mila. SECTION_TEXT check karo.")
        return []
    container = heading.parent
    links = []
    for _ in range(4):  # upar ke parents me tab tak jao jab tak links mil jaye
        links = container.find_all("a", href=True)
        if len(links) >= 5:
            break
        if container.parent is None:
            break
        container = container.parent
    jobs, seen_urls = [], set()
    for a in links:
        title = a.get_text(" ", strip=True)
        url = requests.compat.urljoin(BASE_URL, a["href"])
        if title and url not in seen_urls:
            seen_urls.add(url)
            jobs.append((title, url))
    return jobs


def get_details(url):
    """Job page se important details aur apply link nikalta hai."""
    soup = get_soup(url)
    details = []
    for tr in soup.find_all("tr"):
        row = " ".join(c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"]))
        if any(k in row.lower() for k in KEYWORDS) and 10 < len(row) < 200:
            if row not in details:
                details.append(row)
        if len(details) >= 6:
            break

    apply_link = official_link = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = requests.compat.urljoin(url, a["href"])
        if not apply_link and "apply online" in text:
            apply_link = href
        if not official_link and ("official website" in text or "notification" in text):
            official_link = href
    return details, apply_link, official_link


def build_message(title, page_url, details, apply_link, official_link):
    lines = [f"🔔 <b>{html.escape(title)}</b>", ""]
    if details:
        lines.append("📄 <b>Details:</b>")
        lines += [f"• {html.escape(d)}" for d in details]
        lines.append("")
    if apply_link:
        lines.append(f'✅ <a href="{apply_link}">Apply Online</a>')
    if official_link:
        lines.append(f'🌐 <a href="{official_link}">Official Website / Notification</a>')
    lines.append(f'📎 <a href="{page_url}">Full Details</a>')
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
    seen = set(json.load(open(SEEN_FILE))) if not first_run else set()

    jobs = get_latest_jobs()
    if first_run and SKIP_OLD_ON_FIRST_RUN:
        seen.update(url for _, url in jobs)
        json.dump(sorted(seen), open(SEEN_FILE, "w"))
        print(f"First run: {len(jobs)} purani jobs ko seen mark kiya.")
        return

    new_jobs = [(t, u) for t, u in jobs if u not in seen][:MAX_POSTS_PER_RUN]
    for title, url in reversed(new_jobs):  # purani pehle, nayi baad me
        try:
            details, apply_link, official = get_details(url)
            send(build_message(title, url, details, apply_link, official))
            seen.add(url)
            time.sleep(2)
        except Exception as e:
            print("Failed:", title, e)

    json.dump(sorted(seen), open(SEEN_FILE, "w"))


if __name__ == "__main__":
    main()
