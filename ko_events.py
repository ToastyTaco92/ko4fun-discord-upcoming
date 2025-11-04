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

# -------------------- RENDER PAGE (Playwright) --------------------
async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        # Some sites lazy-load the sidebar; give it a moment
        await page.wait_for_timeout(2500)
        txt = await page.evaluate("document.body.innerText")
        await browser.close()
        return txt

# -------------------- PARSE --------------------
def parse_server_time(page_text: str) -> datetime:
    # server clock like 18:36:19 and date like November 04, 2025 (fallback to UTC date)
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
    # Try to scope to "Upcoming Events" block if present
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec:
        scope = sec.group(0)

    # Robust regex: allow NBSP/odd whitespace, 1–2 digit hours; capture "Name (H:MM)" / "(HH:MM)"
    pattern = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    candidates = list(pattern.finditer(scope))
    items = []
    for m in candidates:
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: 
            continue
        if any(bad in name for bad in ("Server Time", "Upcoming Events", "See all pinned")):
            continue
        items.append((name, hhmm))

    # Fallback: scan whole page if nothing found
    if not items:
        for m in pattern.finditer(page_text):
            name = " ".join(m.group(1).split())
            hhmm = m.group(2)
            if not name or len(name) < 2: 
                continue
            if "Server Time" in name or "Upcoming Events" in name:
                continue
            items.append((name, hhmm))

    # Dedupe/trim
    seen = set()
    cleaned = []
    for tup in items:
        if tup not in seen:
            seen.add(tup)
            cleaned.append(tup)
    return cleaned[:10]

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

# -------------------- DISCORD REST --------------------
def http_json(method: str, url: str, payload=None, headers=HDR_JSON):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req) as r:
        return r.getcode(), json.loads(r.read().decode())

def list_recent_messages(limit=50):
    code, body = http_json("GET", f"{API_BASE}/channels/{CHANNEL_ID}/messages?limit={limit}", None, {"Authorization": f"Bot {DISCORD_TOKEN}"})
    return body

def post_message(content="", embed=None):
    payload = {"content": content}
    if embed is not None:
        payload["embeds"] = [embed]
    code, body = http_json("POST", f"{API_BASE}/channels/{CHANNEL_ID}/messages", payload)
    return body

def edit_message(mid: str, content="", embed=None):
    payload = {"content": content}
    if embed is not None:
        payload["embeds"] = [embed]
    http_json("PATCH", f"{API_BASE}/channels/{CHANNEL_ID}/messages/{mid}", payload)

def pin_try(mid: str):
    try:
        http_json("PUT", f"{API_BASE}/channels/{CHANNEL_ID}/pins/{mid}", None, {"Authorization": f"Bot {DISCORD_TOKEN}"})
    except Exception:
        pass

def post_or_edit_embed(embed):
    # Find existing message authored by this bot with our title
    msgs = list_recent_messages(50)
    target = None
    for m in msgs:
        if m.get("author", {}).get("bot") and any(e.get("title") == TITLE for e in m.get("embeds", [])):
            target = m["id"]
            break
    if target:
        edit_message(target, "", embed)
    else:
        msg = post_message("KO4Fun — Upcoming Events (initializing…)")
        pin_try(msg["id"])
        edit_message(msg["id"], "", embed)

# -------------------- MAIN --------------------
async def main():
    text = await get_rendered_text(EVENT_URL)
    # Debug line (first 400 chars) for logs; comment out if too chatty
    print("[DEBUG]", text[:400].replace("\n", " ")[:400])

    server_dt = parse_server_time(text)
    items = parse_upcoming_items(text)
    print(f"[INFO] Parsed items: {len(items)}")
    embed = build_embed(server_dt, items)
    post_or_edit_embed(embed)

if __name__ == "__main__":
    asyncio.run(main())
