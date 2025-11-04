# ko_events.py — fetch KO4Fun event box and post to Discord via webhook (POST only)
import os, re, json, asyncio, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule").strip()
TITLE       = "KO4Fun — Upcoming Events"

# ----------------- scraping -----------------
EVENT_BOX_TITLE = re.compile(r"\bUPCOMING\s+EVENTS\b", re.I)
NOW_ACTIVE_RE   = re.compile(r"\bNOW\s+ACTIVE\b", re.I)
TIMER_RE        = re.compile(r"\b(\d{2}):(\d{2}):(\d{2})\b")   # 00:35:12
NAME_TIME_RE    = re.compile(r"^(.*?)[(（]\s*(\d{1,2}:\d{2})\s*[)）]\s*$")  # "Santa Event (22:55)"

async def get_event_box_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)

        # Grab the first element that contains "UPCOMING EVENTS" and read its text
        # (works against the current KO4Fun layout without extra deps)
        box = await page.locator("text=UPCOMING EVENTS").first.element_handle()
        if not box:
            # fallback: read whole page
            text = await page.inner_text("body")
        else:
            # parent card container text
            text = await (await box.get_property("parentElement")).inner_text()

        await browser.close()
        return text

def human_from_timer(timer_text: str) -> str:
    """
    KO4Fun shows 00:MM:SS counting down. Convert to 'X minutes' (round up).
    """
    m = TIMER_RE.search(timer_text)
    if not m:
        return timer_text.strip()
    hh, mm, ss = map(int, m.groups())
    total = hh*3600 + mm*3600//60 + ss  # lenient, but we only need minutes feel
    minutes = (hh*60) + mm + (1 if ss > 0 else 0)
    if minutes <= 1:
        return "1 minute"
    return f"{minutes} minutes"

def parse_events(box_text: str):
    """
    Parse the 3 cards under UPCOMING EVENTS:
      - First line: 'Raffle Event' + line with 'NOW ACTIVE' or timer
      - Then next cards e.g. 'Santa Event (22:55)' with a below-line timer '00:47:12'
    We produce tuples: (name, status_or_minutes)
    """
    # Normalize whitespace, keep line breaks to detect blocks
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in box_text.splitlines()]
    lines = [ln for ln in lines if ln]  # drop empty
    # find index of title
    try:
        idx = next(i for i,ln in enumerate(lines) if EVENT_BOX_TITLE.search(ln))
    except StopIteration:
        return []

    content = lines[idx+1:]  # everything after the heading
    out = []
    i = 0
    # We walk and try to catch pattern: name line + either NOW ACTIVE or a 00:MM:SS line
    while i < len(content):
        name = content[i]
        stat = None
        # skip obvious separators if any
        if NOW_ACTIVE_RE.search(name):
            # edge: a lone "NOW ACTIVE" shouldn't start an item
            i += 1
            continue

        # Lookahead for status/timer line
        nxt = content[i+1] if i+1 < len(content) else ""

        if NOW_ACTIVE_RE.search(nxt):
            stat = "NOW ACTIVE"
            i += 2
        elif TIMER_RE.search(nxt):
            stat = human_from_timer(nxt)
            i += 2
        else:
            # sometimes the timer is on same line or the name contains (HH:MM)
            tm_inline = TIMER_RE.search(name)
            if tm_inline:
                stat = human_from_timer(tm_inline.group(0))
                # strip timer from name
                name = NAME_TIME_RE.sub(lambda m: m.group(1).strip(), name)
                i += 1
            else:
                # no status/timer; move on
                i += 1
                continue

        # Clean name like "Santa Event (22:55)" → "Santa Event"
        name = NAME_TIME_RE.sub(lambda m: m.group(1).strip(), name)
        # Remove any “•” bullets or labels
        name = name.lstrip("• ").strip()
        out.append((name, stat))

    return out

# ----------------- discord webhook -----------------
def post_webhook(webhook_url: str, items: list):
    """
    POST-only (no GET verification). Adds `?wait=true` for immediate failures.
    """
    if not items:
        desc = "No upcoming events found."
    else:
        desc_lines = [f"• {name} : {status}" for name, status in items]
        desc = "\n".join(desc_lines)

    embed = {
        "title": TITLE,
        "description": desc,
        "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
    }

    url = webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true"
    req = Request(
        url,
        data=json.dumps({"embeds": [embed]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as r:
        print("Webhook POST:", r.status)

async def main():
    box = await get_event_box_text(EVENT_URL)
    items = parse_events(box)
    post_webhook(WEBHOOK_URL, items)

if __name__ == "__main__":
    asyncio.run(main())
