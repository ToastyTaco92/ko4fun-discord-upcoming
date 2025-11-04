import os, re, math, time, asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL","https://ko4fun.net/Features/EventSchedule")

API  = "https://discord.com/api/v10"
HDRS_JSON = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
TITLE = "KO4Fun — Upcoming Events"

# ---------- scrape ----------
async def fetch(session, url):
    async with session.get(url, headers={"User-Agent":"Mozilla/5.0 KOEventAction"}, timeout=25) as r:
        print("[HTTP] GET page:", r.status)
        r.raise_for_status()
        return await r.text()

def parse_server_time_and_upcoming(html: str):
    soup = BeautifulSoup(html, "lxml")
    txt = soup.get_text(" ", strip=True)
    print("[DEBUG] First 800 chars of text:")
    print(txt[:800])

    # Server clock (fallback if not found)
    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', txt)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', txt)
    d = (datetime.utcnow().date() if not m_date
         else datetime.strptime(m_date.group(0), "%B %d, %Y").date())
    h,m,s = map(int, hhmmss.split(":"))
    server_dt = datetime(d.year, d.month, d.day, h, m, s)

    # Prefer an Upcoming section if present
    scope_txt = txt
    sec = re.search(r'Upcoming\s+Events(.+)', txt, re.I)
    if sec:
        scope_txt = sec.group(0)

    # Robust regex: allow NBSP/extra whitespace and 1–2 digit hours
    # capture "Event Name (H:MM)" or "(HH:MM)"
    pattern = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    matches = list(pattern.finditer(scope_txt))

    items = []
    for mobj in matches:
        name = " ".join(mobj.group(1).split())
        time_part = mobj.group(2)
        # filter out obvious noise
        if not name or len(name) < 2: 
            continue
        bad = ("Server Time", "Server", "Upcoming Events", "See all pinned")
        if any(b in name for b in bad):
            continue
        items.append((name, time_part))

    # If nothing found, try the whole page as a fallback
    if not items:
        matches = list(pattern.finditer(txt))
        for mobj in matches:
            name = " ".join(mobj.group(1).split())
            time_part = mobj.group(2)
            if not name or len(name) < 2: 
                continue
            if any(b in name for b in ("Server Time","Upcoming Events")):
                continue
            items.append((name, time_part))

    # Dedupe while preserving order
    seen = set(); cleaned = []
    for nm, tm in items:
        key = (nm, tm)
        if key not in seen:
            seen.add(key); cleaned.append(key)

    print(f"[PARSE] found {len(cleaned)} candidate items")
    return server_dt, cleaned[:10]

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
    return {"title": TITLE, "description": desc, "color": 0xC81E1E,
            "footer": {"text":"Source: ko4fun.net • auto-updated by GitHub Actions"}}

# ---------- discord ----------
async def post_or_edit(session, embed):
    # list last 50 messages, edit our own if present
    async with session.get(f"{API}/channels/{CHANNEL_ID}/messages?limit=50",
                           headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
        r.raise_for_status()
        msgs = await r.json()
    mid = None
    for m in msgs:
        if m.get("author",{}).get("bot") and any(e.get("title")==TITLE for e in m.get("embeds",[])):
            mid = m["id"]; break
    if mid:
        async with session.patch(f"{API}/channels/{CHANNEL_ID}/messages/{mid}",
                                 headers=HDRS_JSON, json={"content":"", "embeds":[embed]}) as r:
            print("[HTTP] PATCH edit:", r.status); r.raise_for_status()
    else:
        async with session.post(f"{API}/channels/{CHANNEL_ID}/messages",
                                headers=HDRS_JSON, json={"content":"", "embeds":[embed]}) as r:
            print("[HTTP] POST embed:", r.status); r.raise_for_status()
            msg = await r.json()
        # best-effort pin
        try:
            async with session.put(f"{API}/channels/{CHANNEL_ID}/pins/{msg['id']}",
                                   headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
                print("[HTTP] PUT pin:", r.status)
        except Exception as e:
            print("[WARN] pin failed:", e)

async def main():
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, EVENT_URL)
        server_dt, items = parse_server_time_and_upcoming(html)
        embed = build_embed(server_dt, items)
        await post_or_edit(session, embed)

if __name__ == "__main__":
    asyncio.run(main())
