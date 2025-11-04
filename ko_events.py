import os, re, json, time, math, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from playwright.async_api import async_playwright

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")

API_BASE = "https://discord.com/api/v10"
HDR_JSON = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
TITLE = "KO4Fun — Upcoming Events"

# ---------- Render the page (JS content) ----------
async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        # allow lazy sections to populate
        await page.wait_for_timeout(2500)
        txt = await page.evaluate("document.body.innerText")
        await browser.close()
        return txt

# ---------- Parse helpers ----------
def parse_server_time(page_text: str) -> datetime:
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', page_text)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', page_text)
    if m_date:
        d = datetime.strptime(m_date.group(0), "%B %d, %Y").date()
    else:
        d = datetime.utcnow().date()
    h, m, s = map(int, hhmmss.split(":"))
    return datetime(d.year, d.month, d.day, h, m, s)

def parse_upcoming_items(page_text: str):
    # Prefer “Upcoming Events …” block if present
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec:
        scope = sec.group(0)

    # Allow NBSP and flexible spacing; capture "Name (H:MM)" or "(HH:MM)"
    pat = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    items = []
    for m in pat.finditer(scope):
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: continue
        if any(b in name for b in ("Server Time", "Upcoming Events", "See all pinned")): continue
        items.append((name, hhmm))

    if not items:
        for m in pat.finditer(page_text):
            name = " ".join(m.group(1).split())
            hhmm = m.group(2)
            if not name or len(name) < 2: continue
            if "Server Time" in name or "Upcoming Events" in name: continue
            items.append((name, hhmm))

    # dedupe/trim
    seen = set(); out = []
    for tup in items:
        if tup not in seen:
            seen.add(tup); out.append(tup)
    return out[:10]

def to_epoch(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    event_dt = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if event_dt < server_dt:
        event_dt += timedelta(days=1)
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
        "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"},
    }

# ---------- Discord REST ----------
def post_message(content="", embed=None):
    payload = {"content": content}
    if embed is not None:
        payload["embeds"] = [embed]
    req = Request(f"{API_BASE}/channels/{CHANNEL_ID}/messages",
                  data=json.dumps(payload).encode(),
                  headers=HDR_JSON, method="POST")
    with urlopen(req) as r:
        return json.loads(r.read().decode())

# ---------- Main ----------
async def main():
    text = await get_rendered_text(EVENT_URL)
    print("[DEBUG]", text[:300].replace("\n", " "))
    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)
    print(f"[INFO] Parsed items: {len(items)}")
    embed = build_embed(server_dt, items)
    # always create a NEW message each run:
    post_message("", embed)

if __name__ == "__main__":
    asyncio.run(main())
