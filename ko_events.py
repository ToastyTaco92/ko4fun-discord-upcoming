# ko_events.py
# Scrapes https://ko4fun.net/Features/EventSchedule "UPCOMING EVENTS"
# and posts a clean list to a Discord webhook:
#   • Raffle Event : NOW ACTIVE
#   • Santa Event : 41 minutes
#   • Felankor (Hard) Time : 46 minutes
#   • Collection Race : 1 hour 16 minutes
#
# ENV:
#   DISCORD_WEBHOOK_URL   (required)
#   EVENT_URL             (optional; defaults to ko4fun schedule page)

import os, re, json, math, asyncio
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule").strip()
TITLE       = "KO4Fun — Upcoming Events"

TIME_RE = re.compile(r"\b(\d{2}):(\d{2}):(\d{2})\b", re.I)

def hhmmss_to_text(h:int, m:int, s:int) -> str:
    minutes = h * 60 + m + (1 if s >= 30 else 0)
    if minutes <= 0:
        return "NOW ACTIVE"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours  = minutes // 60
    mins   = minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minute{'s' if mins != 1 else ''}"

async def scrape_events() -> list[tuple[str, str]]:
    """
    Return a list of tuples (name, status_text) taken from the 'UPCOMING EVENTS' panel.
    status_text is either 'NOW ACTIVE' or 'X minutes'/'H hours M minutes'.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()
        await page.goto(EVENT_URL, timeout=60_000)
        # Wait until the 'UPCOMING EVENTS' header text is present anywhere
        await page.locator("text=/\\bUPCOMING\\s+EVENTS\\b/i").first.wait_for(timeout=60_000)

        # Do a robust DOM harvest in the page context so we don't rely on specific classes
        items = await page.evaluate(
            """
            () => {
              const out = [];
              // Find the header element that contains 'UPCOMING EVENTS'
              const header = [...document.querySelectorAll('*')]
                .find(el => /\\bUPCOMING\\s+EVENTS\\b/i.test(el.textContent||''));
              if (!header) return out;

              // Climb a bit to get the card container (defensive: move up until many children)
              let root = header;
              for (let i=0; i<5 && root && root.children && root.children.length < 3; i++) {
                root = root.parentElement;
              }
              if (!root) root = header;

              // Collect candidate chunks of text from likely card nodes
              const blocks = [];
              const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
              while (walker.nextNode()) {
                const el = walker.currentNode;
                const txt = (el.textContent || '').replace(/\\s+/g,' ').trim();
                if (!txt) continue;
                // A block that has either NOW ACTIVE or an hh:mm:ss looks like a card
                if (/NOW\\s+ACTIVE/i.test(txt) || /\\b\\d{2}:\\d{2}:\\d{2}\\b/.test(txt)) {
                  // Avoid adding parent containers whose text equals the whole panel
                  if (!/\\bUPCOMING\\s+EVENTS\\b/i.test(txt)) blocks.push(txt);
                }
              }

              // Extract name + status from each block; dedupe by name; keep order
              const seen = new Set();
              for (const t of blocks) {
                // Prefer the last hh:mm:ss in the block if any
                const timeMatch = t.match(/\\b\\d{2}:\\d{2}:\\d{2}\\b/g);
                const hhmmss = timeMatch ? timeMatch[timeMatch.length - 1] : null;
                const active = /NOW\\s+ACTIVE/i.test(t);

                // Try to produce a clean event name (remove obvious extras)
                let name = t;
                name = name.replace(/NOW\\s+ACTIVE/ig, '')
                           .replace(/\\b\\d{2}:\\d{2}:\\d{2}\\b/g, '')
                           .replace(/\\s+/g, ' ')
                           .replace(/^[-•\\s:]+|[-•\\s:]+$/g, '');

                // Reduce long marketing lines or headers that sneak in
                // Keep just the part before a countdown hint like "(22:55)" when present
                const paren = name.match(/^(.*?)(\\(\\d{2}:\\d{2}\\))$/);
                if (paren) name = paren[1].trim();

                // Some cards include tiny labels; shorten obvious boilerplate
                // E.g., "UPCOMING EVENTS" or "EVENT SCHEDULE" noise
                if (/UPCOMING\\s+EVENTS/i.test(name) || /^SERVER\\s+TIME/i.test(name)) continue;
                if (!name || name.length < 2) continue;

                // Deduplicate by name in display order
                const key = name.toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);

                out.push({ name, hhmmss, active });
              }

              return out;
            }
            """
        )

        await browser.close()

    # Convert to final (name, status_text)
    result : list[tuple[str, str]] = []
    for it in items:
        name   = it.get("name","").strip()
        active = bool(it.get("active"))
        hhmmss = it.get("hhmmss")
        if active:
            status = "NOW ACTIVE"
        elif hhmmss:
            h, m, s = map(int, hhmmss.split(":"))
            status  = hhmmss_to_text(h, m, s)
        else:
            # Fallback if neither was found; skip weird rows
            continue
        result.append((name, status))
    return result

def build_embed_lines(events: list[tuple[str,str]]) -> str:
    if not events:
        return "No events found."
    lines = [f"• {name} : {status}" for (name, status) in events]
    return "\n".join(lines)

def post_webhook(webhook_url: str, description: str):
    embed = {
        "title": TITLE,
        "description": description,
        "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
    }
    payload = {"embeds": [embed]}
    data = json.dumps(payload).encode("utf-8")
    req  = Request(webhook_url, data=data, method="POST",
                   headers={"Content-Type":"application/json"})
    with urlopen(req) as r:
        # A 200/204 indicates success; Discord usually returns the created message JSON
        r.read()

async def main():
    events = await scrape_events()
    desc   = build_embed_lines(events[:10])  # safety cap
    post_webhook(WEBHOOK_URL, desc)

if __name__ == "__main__":
    asyncio.run(main())
