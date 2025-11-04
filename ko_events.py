import os, re, math, time, asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"]
EVENT_URL      = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
BOT_HEADER     = {"Authorization": f"Bot {DISCORD_TOKEN}"}
API_BASE       = "https://discord.com/api/v10"
TITLE = "KO4Fun — Upcoming Events"

async def fetch(session, url):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20),
                           headers={"User-Agent":"Mozilla/5.0 KOEventAction"}) as r:
        r.raise_for_status()
        return await r.text()

def parse_server_time_and_upcoming(html: str):
    soup = BeautifulSoup(html, "lxml")
    txt = soup.get_text(" ", strip=True)

    # server clock like 18:36:19 and date like November 04, 2025
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', txt)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', txt)
    if m_date:
        d = datetime.strptime(m_date.group(0), "%B %d, %Y").date()
    else:
        d = datetime.utcnow().date()
    h,m,s = map(int, hhmmss.split(":"))
    server_dt = datetime(d.year, d.month, d.day, h, m, s)

    # right sidebar items: "Name (HH:MM)"
    items = []
    for m in re.finditer(r'([A-Za-z\.\&\-\s]+?)\s*\((\d{2}:\d{2})\)', txt):
        name = " ".join(m.group(1).split())
        if "Server" in name or "Time" in name or not name:
            continue
        items.append((name, m.group(2)))
    return server_dt, items[:10]

def event_epoch_from_server(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    event_dt = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if event_dt < server_dt:
        event_dt += timedelta(days=1)
    delta = (event_dt - server_dt).total_seconds()
    return math.floor(time.time() + max(0, delta))

def build_embed_desc(server_dt, items):
    if not items: return "Could not parse upcoming events."
    lines = []
    for name, hhmm in items:
        epoch = event_epoch_from_server(server_dt, hhmm)
        lines.append(f"• **{name}** — <t:{epoch}:t> • <t:{epoch}:R>")
    return "\n".join(lines)

async def get_pins(session):
    async with session.get(f"{API_BASE}/channels/{CHANNEL_ID}/pins", headers=BOT_HEADER) as r:
        r.raise_for_status()
        return await r.json()

async def create_message(session, embed):
    payload = {"content": "", "embeds":[embed]}
    async with session.post(f"{API_BASE}/channels/{CHANNEL_ID}/messages", headers=BOT_HEADER, json=payload) as r:
        r.raise_for_status()
        msg = await r.json()
    await session.put(f"{API_BASE}/channels/{CHANNEL_ID}/pins/{msg['id']}", headers=BOT_HEADER)
    return msg["id"]

async def edit_message(session, msg_id, embed):
    payload = {"content": "", "embeds":[embed]}
    async with session.patch(f"{API_BASE}/channels/{CHANNEL_ID}/messages/{msg_id}", headers=BOT_HEADER, json=payload) as r:
        r.raise_for_status()

async def main():
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, EVENT_URL)
        server_dt, items = parse_server_time_and_upcoming(html)
        desc = build_embed_desc(server_dt, items)
        embed = {
            "title": TITLE,
            "description": desc,
            "color": 0xC81E1E,
            "footer": {"text":"Source: ko4fun.net • auto-updated by GitHub Actions"}
        }

        pins = await get_pins(session)
        msg_id = None
        for m in pins:
            if (m.get("author",{}).get("bot") and
                any(e.get("title")==TITLE for e in m.get("embeds",[]))):
                msg_id = m["id"]; break

        if msg_id:
            await edit_message(session, msg_id, embed)
        else:
            await create_message(session, embed)

if __name__ == "__main__":
    asyncio.run(main())
