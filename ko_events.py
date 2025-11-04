import os, re, json, time, math, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from playwright.async_api import async_playwright

WEBHOOK_URL   = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL     = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
TITLE         = "KO4Fun — Upcoming Events"

# ---------- Render page (JS content) ----------
async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(2500)  # let the sidebar populate
        txt = await page.evaluate("document.body.innerText")
        await browser.close()
        return txt

# ---------- Parse helpers ----------
def parse_server_time(page_text: str) -> datetime:
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', page_text)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', page_text)
    d = datetime.strptime(m_date.group(0), "%B %d, %Y").date() if m_date else datetime.utcnow().date()
    h, m, s = map(int, hhmmss.split(":"))
    return datetime(d.year, d.month, d.day, h, m, s)

def parse_upcoming_items(page_text: str):
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec: scope = sec.group(0)
    pat = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    items = []
    for m in pat.finditer(scope):
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: continue
        if any(b in name for b in ("Server Time","Upcoming Events","See all pinned")): continue
        items.append((name, hhmm))
    if not items:
        for m in pat.finditer(page_text):
            name = " ".join(m.group(1).split())
            hhmm = m.group(2)
            if not name or len(name) < 2: continue
            if "Server Time" in name or "Upcoming Events" in name: continue
            items.append((name, hhmm))
    seen=set(); out=[]
    for t in items:
        if t not in seen:
            seen.add(t); out.append(t)
    return out[:10]

def to_epoch(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    event_dt = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if event_dt < server_dt: event_dt += timedelta(days=1)
    return math.floor(time.time() + (event_dt - server_dt).total_seconds())

def build_embed(server_dt: datetime, items):
    if not items:
        desc = "Could not parse upcoming events."
    else:
        lines = []
        for name, hhmm in items:
            t = to_epoch(server_dt, hhmm)
            lines.append(f"• **{name}** — <t:{t}:t> • <t:{t}:R>")
        desc = "\n".join(lines)
    return {
        "title": TITLE,
        "description": desc,
        "color": 0xC81E1E,
        "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
    }

# ---------- Post via webhook (new message every run) ----------
def webhook_post(content="", embed=None):
    payload = {"content": content}
    if embed is not None:
        payload["embeds"] = [embed]
    req = Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as r:
        r.read()

# ---------- Main ----------
async def main():
    text = await get_rendered_text(EVENT_URL)
    print("[DEBUG]", text[:300].replace("\n", " "))
    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)
    print(f"[INFO] Parsed items: {len(items)}")
    embed = build_embed(server_dt, items)
    # Always post a brand-new message:
    webhook_post("", embed)

if __name__ == "__main__":
    asyncio.run(main())
