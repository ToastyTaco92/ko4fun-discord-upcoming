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
    # Some ser
