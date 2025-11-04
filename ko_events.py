import os, re, json, time, math, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
TITLE       = "KO4Fun — Upcoming Events"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"

# ----------- Render page (JS content) -----------
async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_extra_http_headers({"User-Agent": UA, "Accept": "text/html"})
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(2500)
        text = await page.evaluate("document.body.innerText")
        await context.close()
        await browser.close()
        return text

# ----------- Parsing helpers -----------
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
            name = " ".join(m.group(1).split()); hhmm = m.group(2)
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

# ----------- Webhook sender (with headers, text then embed) -----------
def webhook_post(content: str = "", embed: dict | None = None):
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if not content and embed is None:
        content = " "

    def send(payload: dict):
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(req) as r:
            print("Webhook POST:", r.status); r.read()

    send({"content": content or " "})
    if embed is not None:
        send({"embeds": [embed]})

# ----------- Main -----------
async def main():
    text = await get_rendered_text(EVENT_URL)
    print("[DEBUG]", text[:300].replace("\n"," "))
    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)
    print(f"[INFO] Parsed items: {len(items)}")
    embed = build_embed(server_dt, items)
    try:
        webhook_post("", embed)
    except HTTPError as e:
        try:
            print("Webhook HTTPError:", e.code, e.read().decode())
        except Exception:
            print("Webhook HTTPError:", e.code)
        raise

if __name__ == "__main__":
    asyncio.run(main())
