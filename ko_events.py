# ko_events.py
import os, re, json, asyncio, math
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
UA          = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"

TITLE = "KO4Fun — Upcoming Events"
COLOR = 0x5865F2

COUNTDOWN_RE = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b", re.I)

def to_minutes(hhmmss: str) -> int:
    m = COUNTDOWN_RE.search(hhmmss or "")
    if not m:
        return None
    h, m_, s = map(int, m.groups())
    total = h * 3600 + m_ * 60 + s
    return total // 60

async def scrape_upcoming():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()
        await page.set_extra_http_headers({"User-Agent": UA})
        await page.goto(EVENT_URL, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(1200)

        data = await page.evaluate("""
(() => {
  // Find the element that contains the 'UPCOMING EVENTS' header text
  const root = Array.from(document.querySelectorAll('*'))
    .find(el => /\\bUPCOMING\\s+EVENTS\\b/i.test(el.textContent || ''));
  if (!root) return {items: []};

  // Heuristic: each card in that column is a block that contains 2+ non-empty lines:
  // line0: event name (e.g., "Santa Event (22:55)")
  // line1: either "NOW ACTIVE" or a countdown "HH:MM:SS"
  const blocks = [];
  // grab direct descendants that look like cards (divs with some text)
  const candidates = Array.from(root.querySelectorAll('div'));

  for (const el of candidates) {
    const lines = (el.innerText || '')
      .split('\\n')
      .map(s => s.trim())
      .filter(Boolean);

    if (lines.length < 2) continue;

    // Must have either a NOW ACTIVE line or a HH:MM:SS line to qualify
    const hasNowActive = lines.some(t => /\\bNOW\\s+ACTIVE\\b/i.test(t));
    const hasClock     = lines.some(t => /\\b\\d{1,2}:\\d{2}:\\d{2}\\b/.test(t));

    if (!hasNowActive && !hasClock) continue;

    // First non-empty line is our name candidate
    let name = lines[0] || "";
    // Remove any trailing "(HH:MM)" from the name line
    name = name.replace(/\\(\\d{1,2}:\\d{2}\\)\\s*$/,'').trim();

    // Find the first status/countdown line
    let statusLine = lines.slice(1).find(t => /\\bNOW\\s+ACTIVE\\b/i.test(t) || /\\b\\d{1,2}:\\d{2}:\\d{2}\\b/.test(t)) || "";

    // Normalize multi-part "NOW ACTIVE" lines (sometimes there's a colored dot)
    if (/\\bNOW\\s+ACTIVE\\b/i.test(statusLine)) statusLine = "NOW ACTIVE";

    blocks.push({ name, status: statusLine });
  }

  // Deduplicate and keep order
  const seen = new Set();
  const items = [];
  for (const b of blocks) {
    const key = b.name + "|" + b.status;
    if (!b.name || seen.has(key)) continue;
    seen.add(key);
    items.push(b);
  }

  // Limit to the top 4 like the site
  return { items: items.slice(0, 4) };
})()
        """)

        await ctx.close()
        await browser.close()
        return data.get("items", [])

def build_lines(items):
    lines = []
    for it in items:
        name   = it.get("name","").strip()
        status = it.get("status","").strip()

        if not name or not status:
            continue

        if "NOW ACTIVE" in status.upper():
            lines.append(f"{name} : NOW ACTIVE")
        else:
            mins = to_minutes(status)
            if mins is None:
                # fallback: just print the raw status if we couldn't parse time
                lines.append(f"{name} : {status}")
            else:
                unit = "minute" if mins == 1 else "minutes"
                lines.append(f"{name} : {mins} {unit}")
    return lines

def post_webhook(description: str):
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    headers = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "embeds": [{
            "title": TITLE,
            "description": description,
            "color": COLOR,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
        }]
    }
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req) as r:
        r.read()
        print("Webhook POST:", r.status)

async def main():
    items = await scrape_upcoming()
    if not items:
        post_webhook("_No upcoming events found._")
        return

    lines = build_lines(items)
    if not lines:
        post_webhook("_No upcoming events found._")
        return

    post_webhook("\n".join(lines))

if __name__ == "__main__":
    asyncio.run(main())
