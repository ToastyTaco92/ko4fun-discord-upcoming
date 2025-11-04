# ko_events.py — scrape KO4Fun Upcoming Events and post to Discord via webhook
import os, re, math, asyncio, json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule").strip()

TITLE = "KO4Fun — Upcoming Events"

def _plural(v, s):
    return f"{v} {s}{'' if v==1 else 's'}"

def hhmmss_to_minutes(s: str) -> int:
    # Accept 00:27:35 or 27:35 (just in case)
    m = re.search(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b", s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2))
    secs = int(m.group(3))
    total = h*3600 + mins*60 + secs
    return max(1, math.ceil(total/60.0))

def pick_title(raw: str) -> str:
    # Clean noisy suffixes like "(22:55)"
    t = re.sub(r"\s*\(\d{1,2}:\d{2}\)\s*$", "", raw).strip()
    return t

async def fetch_upcoming() -> list[tuple[str, str]]:
    """
    Returns a list of (name, status) where status is either 'NOW ACTIVE' or 'X minutes'
    pulled strictly from the UPCOMING EVENTS panel.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(EVENT_URL, timeout=45000)
        # Find the "UPCOMING EVENTS" header, then take its closest panel container.
        header = page.get_by_text("UPCOMING EVENTS", exact=False).first
        await header.wait_for(timeout=20000)
        # The panel is the header's closest ancestor section/card; grab its inner text.
        panel = await header.evaluate_handle(
            """(node) => node.closest('section,div,article')"""
        )
        text = await panel.evaluate("(n)=>n.innerText")
        await ctx.close(); await browser.close()

    # Parse the panel text line by line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Remove the header line itself
    if lines and "UPCOMING EVENTS" in lines[0].upper():
        lines = lines[1:]

    events = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Heuristic: a title line tends to contain 'Event', 'Time', 'Race', 'Santa', 'Felankor', 'Collection'
        if re.search(r"(Event|Time|Race|Santa|Felankor|Collection)", line, re.I):
            name = pick_title(line)
            status = None
            # Look ahead a few lines in this card for NOW ACTIVE or a timer
            for j in range(i+1, min(i+5, len(lines))):
                nxt = lines[j]
                if "NOW ACTIVE" in nxt.upper():
                    status = "NOW ACTIVE"
                    i = j
                    break
                mins = hhmmss_to_minutes(nxt)
                if mins:
                    status = f"{_plural(mins, 'minute')}"
                    i = j
                    break
            if status:
                events.append((name, status))
        i += 1
    return events

def post_webhook(webhook_url: str, items: list[tuple[str, str]]) -> None:
    if not items:
        desc = "_No upcoming events listed on the site._"
    else:
        desc = "\n".join([f"• **{name}** : {status}" for name, status in items])

    payload = {
        "embeds": [{
            "title": TITLE,
            "description": desc,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
        }]
    }
    req = Request(webhook_url, data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req) as r:
        r.read()  # drain

async def main():
    items = await fetch_upcoming()
    post_webhook(WEBHOOK_URL, items)

if __name__ == "__main__":
    asyncio.run(main())
