# ko_events.py
import os, re, json, asyncio
from urllib.request import Request, urlopen
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
UA          = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"

TITLE = "KO4Fun — Upcoming Events"
COLOR = 0x5865F2

COUNTDOWN_RE = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")

def to_minutes(hhmmss: str):
    m = COUNTDOWN_RE.search(hhmmss or "")
    if not m: return None
    h, m_, s = map(int, m.groups())
    return (h*3600 + m_*60 + s) // 60

def post_webhook(description: str):
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    payload = {
        "embeds": [{
            "title": TITLE,
            "description": description,
            "color": COLOR,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"},
        }]
    }
    req = Request(url, data=json.dumps(payload).encode(),
                  headers={"User-Agent": UA, "Content-Type":"application/json"}, method="POST")
    with urlopen(req) as r:
        r.read()
        print("Webhook POST:", r.status)

async def scrape():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()
        await page.set_extra_http_headers({"User-Agent": UA})
        await page.goto(EVENT_URL, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(1200)

        items = await page.evaluate("""
(() => {
  const norm = t => (t||"").replace(/\\s+/g,' ').trim();

  // 1) Find the *exact* "UPCOMING EVENTS" header
  const heading = Array.from(document.querySelectorAll('*, *:before, *:after'))
    .map(el => el instanceof Element ? el : null)
    .filter(Boolean)
    .find(el => /^UPCOMING\\s+EVENTS$/i.test(norm(el.textContent)));

  if (!heading) return [];

  // 2) Find a sensible container for the cards (walk up until it has many descendants)
  let column = heading;
  while (column && column.querySelectorAll('*').length < 15) column = column.parentElement;
  if (!column) column = heading.parentElement || heading;

  // 3) Within this column, grab blocks that look like those event cards:
  //    - First line: event name (no colon)
  //    - Second line: either "NOW ACTIVE" or HH:MM:SS
  const cards = [];
  for (const el of column.querySelectorAll('div')) {
    const lines = (el.innerText || '')
      .split('\\n').map(s => s.trim()).filter(Boolean);

    if (lines.length < 2 || lines.length > 8) continue;

    const first = lines[0];
    const second = lines[1];

    // Exclude headers like "SERVER TIME : ..." etc.
    if (/\\:/.test(first)) continue;

    const isNow = /\\bNOW\\s+ACTIVE\\b/i.test(second);
    const hasClock = /\\b\\d{1,2}:\\d{2}:\\d{2}\\b/.test(second);
    if (!isNow && !hasClock) continue;

    // Clean title (strip "(HH:MM)" if present)
    const name = first.replace(/\\(\\d{1,2}:\\d{2}\\)\\s*$/,'').trim();

    // Second line to return as-is
    cards.push({ name, status: isNow ? "NOW ACTIVE" : second });
  }

  // Deduplicate while preserving order
  const out = [];
  const seen = new Set();
  for (const c of cards) {
    const key = c.name + "|" + c.status;
    if (!c.name || seen.has(key)) continue;
    seen.add(key);
    out.push(c);
  }

  // The panel shows up to 4 lines; keep first 4
  return out.slice(0, 4);
})()
        """)

        await ctx.close()
        await browser.close()
        return items or []

async def main():
    items = await scrape()
    if not items:
        post_webhook("_No upcoming events found._")
        return

    lines = []
    for it in items:
        name   = it.get("name","").strip()
        status = it.get("status","").strip()
        if not name or not status: continue

        if status.upper() == "NOW ACTIVE":
            lines.append(f"{name} : NOW ACTIVE")
        else:
            mins = to_minutes(status)
            if mins is None:
                lines.append(f"{name} : {status}")
            else:
                unit = "minute" if mins == 1 else "minutes"
                lines.append(f"{name} : {mins} {unit}")

    post_webhook("\\n".join(lines) if lines else "_No upcoming events found._")

if __name__ == "__main__":
    asyncio.run(main())
