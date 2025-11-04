import os, re, json, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"

TITLE = "KO4Fun — Upcoming Events"
COLOR = 0x5865F2  # Discord blurple

# ---------- Render page ----------
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

# ---------- Parse helpers ----------
def parse_server_time(page_text: str) -> datetime:
    # The site shows “Server Time: HH:MM:SS” and a date like “November 04, 2025”
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', page_text)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', page_text)
    date_obj = datetime.strptime(m_date.group(0), "%B %d, %Y").date() if m_date else datetime.utcnow().date()
    h, m, s = map(int, hhmmss.split(":"))
    return datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s)

def parse_upcoming_items(page_text: str):
    # Prefer the “Upcoming Events” section
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec: scope = sec.group(0)

    # Matches “Santa Event (22:55)”
    pat = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    items = []
    for m in pat.finditer(scope):
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: continue
        if any(bad in name for bad in ("Server Time","Upcoming Events","See all pinned")): continue
        items.append((name, hhmm))

    # Fallback: scan whole page if section not found
    if not items:
        for m in pat.finditer(page_text):
            name = " ".join(m.group(1).split()); hhmm = m.group(2)
            if not name or len(name) < 2: continue
            if "Server Time" in name or "Upcoming Events" in name: continue
            items.append((name, hhmm))

    # De-dup while preserving order
    seen, out = set(), []
    for t in items:
        if t not in seen:
            seen.add(t); out.append(t)
    return out

def to_epoch(server_dt, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    t = server_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t < server_dt:
        t += timedelta(days=1)
    return int(t.timestamp())

# ---------- Webhook ----------
def send_embed(title: str, description: str):
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    headers = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": COLOR,
            "footer": {"text": "Source: ko4fun.net • auto-updated by GitHub Actions"}
        }]
    }
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req) as r:
        print("Webhook POST:", r.status); r.read()

# ---------- Main ----------
async def main():
    text = await get_rendered_text(EVENT_URL)
    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)

    if not items:
        print("[INFO] No upcoming events parsed."); return

    # Build a simple snapshot of the next few events (keep first 3–4)
    now_epoch = int(server_dt.timestamp())
    rows = []
    for name, hhmm in items[:4]:
        t_epoch = to_epoch(server_dt, hhmm)
        # Discord time tags: <t:EPOCH:t> = locale time, <t:EPOCH:R> = relative
        rows.append(f"• **{name}** — <t:{t_epoch}:t> • <t:{t_epoch}:R>")

    description = "\n".join(rows)
    try:
        send_embed(TITLE, description)
    except HTTPError as e:
        try:
            print("Webhook HTTPError:", e.code, e.read().decode())
        except Exception:
            print("Webhook HTTPError:", e.code)
        raise

if __name__ == "__main__":
    asyncio.run(main())
