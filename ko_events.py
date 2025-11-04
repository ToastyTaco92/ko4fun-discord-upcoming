# ko_events.py
import os, re, json, asyncio
from urllib.request import Request, urlopen
from playwright.async_api import async_playwright

# ---- Config via secrets / env
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")

UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
TITLE  = "KO4Fun — Upcoming Events"
COLOR  = 0x5865F2

# patterns we need
RE_COUNTDOWN = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")
# Titles on KO4Fun typically look like: "Santa Event (22:55)" with countdown on the next line
RE_EVENT_ROW = re.compile(r"(?P<title>[A-Za-z0-9'().\- ]+?)\s*\(\d{1,2}:\d{2}\)\s*\n\s*(?P<cd>\d{1,2}:\d{2}:\d{2})")

def hhmmss_to_minutes(hhmmss: str) -> int | None:
    m = RE_COUNTDOWN.search(hhmmss or "")
    if not m:
        return None
    h, m_, s = map(int, m.groups())
    return (h * 3600 + m_ * 60 + s) // 60

def post_webhook(lines: list[str]) -> None:
    # One embed, each event on its own bullet line
    desc = "\n".join(lines) if lines else "_No upcoming events found._"
    url  = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    payload = {
        "embeds": [{
            "title": TITLE,
            "description": desc,
            "color": COLOR,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"},
        }]
    }
    req = Request(url, data=json.dumps(payload).encode(),
                  headers={"User-Agent": UA, "Content-Type": "application/json"},
                  method="POST")
    with urlopen(req) as r:
        r.read()
        print("Webhook POST:", r.status)

async def scrape_upcoming_text() -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()
        await page.set_extra_http_headers({"User-Agent": UA})
        await page.goto(EVENT_URL, wait_until="domcontentloaded", timeout=60000)

        # We’ll wait a touch so the right panel populates
        await page.wait_for_timeout(1500)

        # Grab the whole page text, then slice to the "UPCOMING EVENTS" section
        body_text = await page.inner_text("body")
        await browser.close()

    # Normalize whitespace to make matching stable
    text = re.sub(r"[ \t]+", " ", body_text)
    text = re.sub(r"\r", "", text)

    # Keep only the segment after the "UPCOMING EVENTS" header.
    # (This header is exactly what’s rendered above the right-hand panel.)
    if "UPCOMING EVENTS" not in text:
        return ""

    segment = text.split("UPCOMING EVENTS", 1)[1]
    # Stop at a strong delimiter if present (not strictly required, but keeps noise down)
    # Common anchors on the page include "CALENDAR", "EVENT SCHEDULE", etc.
    for stopper in ["CALENDAR", "EVENT SCHEDULE", "©", "KOFUN.NET", "SERVER TIME"]:
        if stopper in segment:
            segment = segment.split(stopper, 1)[0]

    return segment.strip()

def build_event_lines(panel_text: str) -> list[str]:
    """
    The right panel consists of:
      - Top card: 'Raffle Event' + 'NOW ACTIVE' line when active.
      - Following cards like 'Santa Event (22:55)' with a countdown '00:27:59' on the next line.
    We will:
      1) If we see 'Raffle Event' AND 'NOW ACTIVE' in the same panel, add 'Raffle Event : NOW ACTIVE'.
      2) For every 'Title (HH:MM)' followed by a 'HH:MM:SS' countdown, add 'Title : X minutes'.
    """
    lines: list[str] = []

    # 1) When the raffle card is live it shows a dedicated "NOW ACTIVE" line within the panel.
    if "Raffle Event" in panel_text and "NOW ACTIVE" in panel_text:
        # Make sure we only tag the raffle if "NOW ACTIVE" is actually nearby.
        # This keeps us from incorrectly labeling other cards.
        raffle_chunk = panel_text.split("Raffle Event", 1)[1][:120]  # look right after the title
        if "NOW ACTIVE" in raffle_chunk:
            lines.append("• Raffle Event : NOW ACTIVE")

    # 2) Parse every “Title (HH:MM)” + next-line “HH:MM:SS” countdown pair
    for m in RE_EVENT_ROW.finditer(panel_text):
        title = m.group("title").strip()
        # Avoid duplicating the Raffle “active” row if it accidentally has a time format nearby
        if title.lower().startswith("raffle event"):
            continue
        cd = m.group("cd").strip()
        mins = hhmmss_to_minutes(cd)
        if mins is None:
            continue
        if mins >= 60:
            hours = mins // 60
            rem   = mins % 60
            if rem == 0:
                nice = f"{hours} hour{'s' if hours != 1 else ''}"
            else:
                nice = f"{hours}h {rem}m"
        else:
            nice = f"{mins} minute{'s' if mins != 1 else ''}"

        lines.append(f"• {title} : {nice}")

    return lines

async def main():
    panel = await scrape_upcoming_text()
    lines = build_event_lines(panel)
    post_webhook(lines)

if __name__ == "__main__":
    asyncio.run(main())
