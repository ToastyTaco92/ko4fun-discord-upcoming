import os, re, math, time, asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup

DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL","https://ko4fun.net/Features/EventSchedule")

API  = "https://discord.com/api/v10"
HDRS_JSON = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json"
}
TITLE = "KO4Fun — Upcoming Events"

# ---------- scrape ----------
async def fetch(session, url):
    async with session.get(url, headers={"User-Agent":"Mozilla/5.0 KOEventAction"}, timeout=20) as r:
        print("[HTTP] GET page:", r.status); r.raise_for_status()
        return await r.text()

def parse_server_time_and_upcoming(html: str):
    soup = BeautifulSoup(html, "lxml")
    txt = soup.get_text(" ", strip=True)

    m_time = re.search(r'(\d{2}:\d{2}:\d{2})', txt)
    hhmmss = m_time.group(1) if m_time else "00:00:00"
    m_date = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', txt)
    d = (datetime.utcnow().date() if not m_date
         else datetime.strptime(m_date.group(0), "%B %d, %Y").date())
    h,m,s = map(int, hhmmss.split(":"))
    server_dt = datetime(d.year, d.month, d.day, h, m, s)

    scope_txt = txt
    sec = re.search(r'Upcoming Events(.+)', txt, re.I)
    if sec: scope_txt = sec.group(0)

    items = []
    for mm in re.finditer(r'([A-Za-z0-9\.\&\-\s]+?)\s*\((\d{2}:\d{2})\)', scope_txt):
        name = " ".join(mm.group(1).split())
        if not name or "Server" in name or "Time" in name: continue
        items.append((name, mm.group(2)))
    print(f"[PARSE] items: {len(items)}")
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
async def get_channel(session):
    url = f"{API}/channels/{CHANNEL_ID}"
    async with session.get(url, headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
        print("[HTTP] GET channel:", r.status)
        if r.status == 200:
            j = await r.json()
            print(f"[INFO] channel type={j.get('type')} id_len={len(CHANNEL_ID)}")
            return j
        txt = await r.text()
        raise RuntimeError(f"GET /channels/{CHANNEL_ID} -> {r.status} {txt}")

async def list_messages(session, limit=50):
    async with session.get(f"{API}/channels/{CHANNEL_ID}/messages?&limit={limit}",
                           headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
        print("[HTTP] LIST messages:", r.status); r.raise_for_status()
        return await r.json()

async def post_simple(session, text):
    async with session.post(f"{API}/channels/{CHANNEL_ID}/messages",
                            headers=HDRS_JSON, json={"content": text}) as r:
        print("[HTTP] POST simple:", r.status)
        txt = await r.text()
        if r.status >= 400: raise RuntimeError(txt)
        return await r.json()

async def post_embed(session, embed):
    async with session.post(f"{API}/channels/{CHANNEL_ID}/messages",
                            headers=HDRS_JSON, json={"content":"", "embeds":[embed]}) as r:
        print("[HTTP] POST embed:", r.status)
        txt = await r.text()
        if r.status >= 400: raise RuntimeError(txt)
        return await r.json()

async def pin_try(session, mid):
    async with session.put(f"{API}/channels/{CHANNEL_ID}/pins/{mid}",
                           headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
        print("[HTTP] PUT pin:", r.status)

async def edit_message(session, mid, embed):
    async with session.patch(f"{API}/channels/{CHANNEL_ID}/messages/{mid}",
                             headers=HDRS_JSON, json={"content":"", "embeds":[embed]}) as r:
        print("[HTTP] PATCH edit:", r.status)
        txt = await r.text()
        if r.status >= 400: raise RuntimeError(txt)

async def find_existing(session):
    # scan recent for our title
    msgs = await list_messages(session, 50)
    for m in msgs:
        if m.get("author",{}).get("bot") and any(e.get("title")==TITLE for e in m.get("embeds",[])):
            return m["id"]
    return None

# ---------- main ----------
async def main():
    async with aiohttp.ClientSession() as session:
        # sanity: can we see the channel?
        await get_channel(session)

        html = await fetch(session, EVENT_URL)
        server_dt, items = parse_server_time_and_upcoming(html)
        embed = build_embed(server_dt, items)

        mid = await find_existing(session)
        if mid:
            await edit_message(session, mid, embed)
            return

        # create flow: post a simple text first (same as diag), then edit with embed
        msg = await post_simple(session, "KO4Fun — Upcoming Events (initializing…)")
        mid = msg["id"]
        try:
            await pin_try(session, mid)  # may 403; that's fine
        except Exception as e:
            print("[WARN] pin failed:", e)
        await edit_message(session, mid, embed)

if __name__ == "__main__":
    print(f"[INFO] Using channel id length={len(CHANNEL_ID)}")
    asyncio.run(main())
