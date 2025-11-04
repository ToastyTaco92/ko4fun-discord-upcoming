import os, re, math, time, asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL","https://ko4fun.net/Features/EventSchedule")

API  = "https://discord.com/api/v10"
HDRS = {"Authorization": f"Bot {DISCORD_TOKEN}"}
TITLE = "KO4Fun — Upcoming Events"

# ---------- scrape helpers ----------
async def fetch(session, url):
    async with session.get(url, headers={"User-Agent":"Mozilla/5.0 KOEventAction"}, timeout=20) as r:
        r.raise_for_status()
        return await r.text()

def parse_server_time_and_upcoming(html: str):
    soup = BeautifulSoup(html, "lxml")
    txt = soup.get_text(" ", strip=True)

    tmatch = re.search(r'(\d{2}:\d{2}:\d{2})', txt)
    hhmmss = tmatch.group(1) if tmatch else "00:00:00"
    dmatch = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', txt)
    d = (datetime.utcnow().date() if not dmatch
         else datetime.strptime(dmatch.group(0), "%B %d, %Y").date())
    h,m,s = map(int, hhmmss.split(":"))
    server_dt = datetime(d.year, d.month, d.day, h, m, s)

    scope_txt = txt
    m_section = re.search(r'Upcoming Events(.+)', txt, re.I)
    if m_section:
        scope_txt = m_section.group(0)

    items = []
    for mm in re.finditer(r'([A-Za-z0-9\.\&\-\s]+?)\s*\((\d{2}:\d{2})\)', scope_txt):
        name = " ".join(mm.group(1).split())
        if not name or "Server" in name or "Time" in name:
            continue
        items.append((name, mm.group(2)))
    return server_dt, items[:10]

def to_epoch(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    ed = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if ed < server_dt: ed += timedelta(days=1)
    return math.floor(time.time() + (ed - server_dt).total_seconds())

def build_embed(server_dt, items):
    if not items:
        desc = "Could not parse upcoming events."
    else:
        lines = [f"• **{n}** — <t:{to_epoch(server_dt,t)}:t> • <t:{to_epoch(server_dt,t)}:R>"
                 for n,t in items]
        desc = "\n".join(lines)
    return {
        "title": TITLE,
        "description": desc,
        "color": 0xC81E1E,
        "footer": {"text":"Source: ko4fun.net • auto-updated by GitHub Actions"}
    }

# ---------- discord helpers ----------
async def get_pins(session):
    # Some servers return 404 for pins; treat that as "no pins" and fallback.
    async with session.get(f"{API}/channels/{CHANNEL_ID}/pins", headers=HDRS) as r:
        if r.status == 404:
            return []  # fallback to recent messages
        r.raise_for_status()
        return await r.json()

async def list_recent_messages(session, limit=50):
    async with session.get(f"{API}/channels/{CHANNEL_ID}/messages?limit={limit}", headers=HDRS) as r:
        r.raise_for_status()
        return await r.json()

async def create_message(session, embed, pin_try=True):
    payload = {"content":"", "embeds":[embed]}
    async with session.post(f"{API}/channels/{CHANNEL_ID}/messages", headers=HDRS, json=payload) as r:
        txt = await r.text()
        if r.status >= 400: raise RuntimeError(txt)
        msg = await r.json()
    if pin_try:
        await session.put(f"{API}/channels/{CHANNEL_ID}/pins/{msg['id']}", headers=HDRS)
    return msg["id"]

async def edit_message(session, mid, embed):
    payload = {"content":"", "embeds":[embed]}
    async with session.patch(f"{API}/channels/{CHANNEL_ID}/messages/{mid}", headers=HDRS, json=payload) as r:
        txt = await r.text()
        if r.status >= 400: raise RuntimeError(txt)

async def find_existing_message_id(session):
    # 1) Try pins first
    try:
        pins = await get_pins(session)
        for m in pins or []:
            if m.get("author",{}).get("bot") and any(e.get("title")==TITLE for e in m.get("embeds",[])):
                return m["id"]
    except Exception:
        pass
    # 2) Fallback: scan recent messages
    try:
        msgs = await list_recent_messages(session, limit=50)
        for m in msgs:
            if m.get("author",{}).get("bot") and any(e.get("title")==TITLE for e in m.get("embeds",[])):
                return m["id"]
    except Exception:
        pass
    return None

# ---------- main ----------
async def main():
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, EVENT_URL)
        server_dt, items = parse_server_time_and_upcoming(html)
        embed = build_embed(server_dt, items)

        mid = await find_existing_message_id(session)
        if mid:
            await edit_message(session, mid, embed)
        else:
            try:
                await create_message(session, embed, pin_try=True)
            except Exception:
                # If pin fails (permissions), still create the message without pinning
                await create_message(session, embed, pin_try=False)

if __name__ == "__main__":
    asyncio.run(main())
