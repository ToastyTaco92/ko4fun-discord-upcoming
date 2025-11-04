import os, re, math, time, asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL","https://ko4fun.net/Features/EventSchedule")
HDRS = {"Authorization": f"Bot {DISCORD_TOKEN}"}
API  = "https://discord.com/api/v10"
TITLE = "KO4Fun — Upcoming Events"

async def fetch(session, url):
  async with session.get(url, headers={"User-Agent":"Mozilla/5.0 KOEventAction"}, timeout=20) as r:
    r.raise_for_status()
    return await r.text()

def parse_server_time_and_upcoming(html: str):
  soup = BeautifulSoup(html, "lxml")
  # Grab visible text once
  txt = soup.get_text(" ", strip=True)

  # Server time like 18:36:19 and date like November 04, 2025 (fallback to UTC date)
  m_time = re.search(r'(\d{2}:\d{2}:\d{2})', txt)
  hhmmss = m_time.group(1) if m_time else "00:00:00"
  m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', txt)
  d = (datetime.utcnow().date() if not m_date
       else datetime.strptime(m_date.group(0), "%B %d, %Y").date())
  h,m,s = map(int, hhmmss.split(":"))
  server_dt = datetime(d.year, d.month, d.day, h, m, s)

  # Prefer the “Upcoming Events” panel if present; else use whole page text
  scope_txt = txt
  m_section = re.search(r'Upcoming Events(.+)', txt, re.I)
  if m_section:
    scope_txt = m_section.group(0)

  # Items like: "Raffle Event (20:05)"
  items = []
  for mm in re.finditer(r'([A-Za-z0-9\.\&\-\s]+?)\s*\((\d{2}:\d{2})\)', scope_txt):
    name = " ".join(mm.group(1).split())
    if not name or "Server" in name or "Time" in name:
      continue
    items.append((name, mm.group(2)))

  return server_dt, items[:10]

def epoch_from_server(server_dt: datetime, hhmm: str) -> int:
  eh, em = map(int, hhmm.split(":"))
  event_dt = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
  if event_dt < server_dt:
    event_dt += timedelta(days=1)
  return math.floor(time.time() + (event_dt - server_dt).total_seconds())

def build_embed(server_dt, items):
  if not items:
    desc = "Could not parse upcoming events."
  else:
    lines = []
    for name, hhmm in items:
      t = epoch_from_server(server_dt, hhmm)
      lines.append(f"• **{name}** — <t:{t}:t> • <t:{t}:R>")
    desc = "\n".join(lines)
  return {
    "title": TITLE,
    "description": desc,
    "color": 0xC81E1E,
    "footer": {"text":"Source: ko4fun.net • auto-updated by GitHub Actions"}
  }

async def get_pins(session):
  async with session.get(f"{API}/channels/{CHANNEL_ID}/pins", headers=HDRS) as r:
    r.raise_for_status();  return await r.json()

async def create_message(session, embed):
  payload = {"content":"", "embeds":[embed]}
  async with session.post(f"{API}/channels/{CHANNEL_ID}/messages", headers=HDRS, json=payload) as r:
    txt = await r.text()
    if r.status >= 400: raise RuntimeError(txt)
    msg = await r.json()
  await session.put(f"{API}/channels/{CHANNEL_ID}/pins/{msg['id']}", headers=HDRS)
  return msg["id"]

async def edit_message(session, mid, embed):
  payload = {"content":"", "embeds":[embed]}
  async with session.patch(f"{API}/channels/{CHANNEL_ID}/messages/{mid}", headers=HDRS, json=payload) as r:
    txt = await r.text()
    if r.status >= 400: raise RuntimeError(txt)

async def main():
  async with aiohttp.ClientSession() as session:
    html = await fetch(session, EVENT_URL)
    server_dt, items = parse_server_time_and_upcoming(html)
    embed = build_embed(server_dt, items)

    pins = await get_pins(session)
    mid = None
    for m in pins:
      if m.get("author",{}).get("bot") and any(e.get("title")==TITLE for e in m.get("embeds",[])):
        mid = m["id"]; break

    if mid: await edit_message(session, mid, embed)
    else:    await create_message(session, embed)

if __name__ == "__main__":
  asyncio.run(main())
