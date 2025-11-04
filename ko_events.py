import os, re, json, time, math, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"

TITLE_PREFIX = "KO4Fun — Event Reminder"
COLOR = 0xC81E1E

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
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', page_text)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', page_text)
    d = datetime.strptime(m_date.group(0), "%B %d, %Y").date() if m_date else datetime.utcnow().date()
    h, m, s = map(int, hhmmss.split(":"))
    return datetime(d.year, d.month, d.day, h, m, s)

def parse_upcoming_items(page_text: str):
    # Prefer the "Upcoming Events" section if present
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec: scope = sec.group(0)

    pat = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')  # "Name (HH:MM)"
    items = []
    for m in pat.finditer(scope):
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: continue
        if any(bad in name for bad in ("Server Time","Upcoming Events","See all pinned")): continue
        items.append((name, hhmm))

    # Fallback search if section parse failed
    if not items:
        for m in pat.finditer(page_text):
            name = " ".join(m.group(1).split()); hhmm = m.group(2)
            if not name or len(name) < 2: continue
            if "Server Time" in name or "Upcoming Events" in name: continue
            items.append((name, hhmm))

    # Dedup, keep order
    seen = set(); out = []
    for t in items:
        if t not in seen:
            seen.add(t); out.append(t)
    return out

def event_epoch_from_hhmm(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    ev = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if ev < server_dt:
        ev += timedelta(days=1)
    return int(ev.timestamp())

# ---------- Webhook ----------
def send_embed(title: str, description: str):
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
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

# ---------- Main logic ----------
THRESHOLDS = [30, 10]   # minutes before
WINDOW = 2              # ± minutes tolerance to catch with 5-min cron

def within_window(mins_left: float, target: int, window: int = WINDOW) -> bool:
    return abs(mins_left - target) <= window

async def main():
    text = await get_rendered_text(EVENT_URL)
    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)

    if not items:
        print("[INFO] No upcoming items parsed; exiting quietly.")
        return

    # Pick the next event (soonest event time >= now)
    candidates = []
    for name, hhmm in items:
        t_epoch = event_epoch_from_hhmm(server_dt, hhmm)
        delta_min = (t_epoch - int(server_dt.timestamp())) / 60.0
        if delta_min >= 0:
            candidates.append((t_epoch, name, hhmm, delta_min))
    if not candidates:
        print("[INFO] No future events in parsed list; exiting.")
        return

    t_epoch, name, hhmm, mins_left = sorted(candidates, key=lambda x: x[0])[0]
    print(f"[INFO] Next event: {name} at {hhmm} (in {mins_left:.1f} min)")

    # Fire only at ~30m or ~10m before
    label = None
    for thr in THRESHOLDS:
        if within_window(mins_left, thr):
            label = f"{thr} minutes"
            break

    if not label:
        print("[INFO] Not within 30m/10m window; no post.")
        return

    description = (
        f"**{name}** — <t:{t_epoch}:t> • <t:{t_epoch}:R>\n"
        f"Reminder: starts in **{label}**."
    )
    title = f"{TITLE_PREFIX} ({label})"
    try:
        send_embed(title, description)
    except HTTPError as e:
        try:
            print("Webhook HTTPError:", e.code, e.read().decode())
        except Exception:
            print("Webhook HTTPError:", e.code)
        raise

if __name__ == "__main__":
    asyncio.run(main())
