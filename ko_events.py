# ko_events.py
# Scrapes KO4Fun Upcoming Events and posts to Discord webhook.
# Robust posting: verifies webhook, uses ?wait=true, and falls back to plain text
# if an embed post is rejected (e.g., 403).

import os, re, json, math, asyncio, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule").strip()
TITLE       = "KO4Fun — Upcoming Events"
TIME_RE     = re.compile(r"\b(\d{2}):(\d{2}):(\d{2})\b", re.I)

def err_body(e: HTTPError) -> str:
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return "<no error body>"

def hhmmss_to_text(h:int, m:int, s:int) -> str:
    minutes = h * 60 + m + (1 if s >= 30 else 0)
    if minutes <= 0:
        return "NOW ACTIVE"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    mins  = minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minute{'s' if mins != 1 else ''}"

async def scrape_events() -> list[tuple[str, str]]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(EVENT_URL, timeout=60_000)
        await page.locator("text=/\\bUPCOMING\\s+EVENTS\\b/i").first.wait_for(timeout=60_000)

        items = await page.evaluate(
            """
            () => {
              const out = [];
              const header = [...document.querySelectorAll('*')]
                .find(el => /\\bUPCOMING\\s+EVENTS\\b/i.test(el.textContent||''));
              if (!header) return out;

              let root = header;
              for (let i=0; i<5 && root && root.children && root.children.length < 3; i++) {
                root = root.parentElement;
              }
              if (!root) root = header;

              const blocks = [];
              const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
              while (walker.nextNode()) {
                const el = walker.currentNode;
                const txt = (el.textContent || '').replace(/\\s+/g,' ').trim();
                if (!txt) continue;
                if (/NOW\\s+ACTIVE/i.test(txt) || /\\b\\d{2}:\\d{2}:\\d{2}\\b/.test(txt)) {
                  if (!/\\bUPCOMING\\s+EVENTS\\b/i.test(txt)) blocks.push(txt);
                }
              }

              const seen = new Set();
              for (const t of blocks) {
                const times = t.match(/\\b\\d{2}:\\d{2}:\\d{2}\\b/g);
                const hhmmss = times ? times[times.length-1] : null;
                const active = /NOW\\s+ACTIVE/i.test(t);

                let name = t.replace(/NOW\\s+ACTIVE/ig, '')
                            .replace(/\\b\\d{2}:\\d{2}:\\d{2}\\b/g, '')
                            .replace(/\\s+/g,' ').replace(/^[-•\\s:]+|[-•\\s:]+$/g,'');
                const paren = name.match(/^(.*?)(\\(\\d{2}:\\d{2}\\))$/);
                if (paren) name = paren[1].trim();

                if (/UPCOMING\\s+EVENTS/i.test(name) || /^SERVER\\s+TIME/i.test(name)) continue;
                if (!name || name.length < 2) continue;
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

    result : list[tuple[str,str]] = []
    for it in items:
        name   = it.get("name","").strip()
        active = bool(it.get("active"))
        hhmmss = it.get("hhmmss")
        if not name:
            continue
        if active:
            status = "NOW ACTIVE"
        elif hhmmss:
            try:
                h, m, s = map(int, hhmmss.split(":"))
            except Exception:
                continue
            status = hhmmss_to_text(h, m, s)
        else:
            continue
        result.append((name, status))
    return result

def build_lines(events: list[tuple[str,str]]) -> str:
    if not events:
        return "No events found."
    return "\n".join(f"• {n} : {s}" for n, s in events)

def http_post_json(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type":"application/json"})
    with urlopen(req) as r:
        return r.read()

def verify_webhook(url: str):
    # Simple GET to confirm it's a valid webhook (useful error if not)
    req = Request(url, method="GET")
    with urlopen(req) as r:
        r.read()

def post_webhook(webhook_url: str, description: str):
    # 1) Verify webhook URL (better error than a bare 403 later)
    try:
        verify_webhook(webhook_url)
    except HTTPError as e:
        print("Webhook GET failed:", e.code, err_body(e))
        raise
    except URLError as e:
        print("Webhook GET failed (network):", e)
        raise

    # 2) Try EMBED first (with ?wait=true for a synchronous response)
    embed_payload = {
        "embeds": [{
            "title": TITLE,
            "description": description,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
        }]
    }
    try:
        http_post_json(
            webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true",
            embed_payload
        )
        return
    except HTTPError as e:
        print("Embed POST failed:", e.code, err_body(e))

    # 3) Fallback to plain text (always under 1800 chars)
    text = f"**{TITLE}**\n{description}"
    if len(text) > 1800:
        text = text[:1797] + "…"
    try:
        http_post_json(
            webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true",
            {"content": text, "allowed_mentions": {"parse": []}}
        )
    except HTTPError as e:
        print("Plain-text POST failed:", e.code, err_body(e))
        raise

async def main():
    events = await scrape_events()
    desc   = build_lines(events[:10])  # cap for safety
    post_webhook(WEBHOOK_URL, desc)

if __name__ == "__main__":
    asyncio.run(main())
