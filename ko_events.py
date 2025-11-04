# ko_events.py
import os, re, json, math, asyncio
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule").strip()
TITLE       = "KO4Fun — Upcoming Events"

COUNTDOWN_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

def hhmmss_to_minutes(hhmmss: str) -> int:
    h, m, s = map(int, hhmmss.split(":"))
    return max(0, math.ceil((h*3600 + m*60 + s) / 60))

async def get_panel_text(page):
    # Find the "UPCOMING EVENTS" header, then take its nearest ancestor container.
    header = page.get_by_text("UPCOMING EVENTS", exact=True).first
    container = header.locator("xpath=ancestor::*[self::div or self::section][1]")
    # Grab raw inner text and normalize
    raw = await container.inner_text()
    # Some themes put the header text inside the same container, strip it out if present
    raw = raw.replace("UPCOMING EVENTS", "")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return lines

def extract_events(lines):
    """
    The panel appears as pairs of lines:
      <Event Name (maybe with time in parens)>
      NOW ACTIVE | 00:47:23
    We collapse to "<Event Name> : NOW ACTIVE | <N> minutes"
    """
    events = []
    i = 0
    while i < len(lines):
        name = lines[i]
        # Most cards have a status line next
        status = None
        if i + 1 < len(lines):
            nxt = lines[i+1]
            if nxt.upper().startswith("NOW ACTIVE"):
                status = "NOW ACTIVE"
                i += 2
            elif COUNTDOWN_RE.match(nxt):
                mins = hhmmss_to_minutes(nxt)
                status = f"{mins} minutes"
                i += 2
            else:
                # No obvious status line; just consume the name
                i += 1
        else:
            i += 1

        # Clean the name: drop any trailing "(HH:MM)" or similar decorations
        name = re.sub(r"\(\s*\d{1,2}:\d{2}\s*(?:AM|PM)?\s*\)", "", name).strip()
        # Sometimes “Event” is duplicated in lines above. Keep the first word-capitalized sentence.
        events.append((name, status or ""))

    # Remove obvious noise rows (site slogans etc.), keep items that look like event names
    cleaned = []
    for n, s in events:
        if len(n) < 3: 
            continue
        if n.upper() in {"SERVER TIME", "EVENT DAYS", "UPCOMING EVENTS"}:
            continue
        cleaned.append((n, s))
    return cleaned

def format_lines(items):
    # Keep first 4 items to avoid super long posts
    lines = [f"• {name} : {status}" if status else f"• {name}" for name, status in items[:4]]
    return "\n".join(lines) if lines else "• No events found"

def post_webhook(url: str, desc: str):
    payload = {
        "embeds": [{
            "title": TITLE,
            "description": desc,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
        }]
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req) as r:
        # 204 or 200 are both fine for webhooks
        if r.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {r.status}")

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(EVENT_URL, wait_until="domcontentloaded", timeout=60000)

        # The right panel is static text after the page builds; a small wait to be safe
        await page.wait_for_timeout(800)
        lines = await get_panel_text(page)
        await browser.close()

    items = extract_events(lines)
    desc = format_lines(items)
    post_webhook(WEBHOOK_URL, desc)

if __name__ == "__main__":
    asyncio.run(main())
