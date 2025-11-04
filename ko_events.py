# ko_events.py
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

# ---------- Browser render ----------
async def grab_dom_snapshot(url: str):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.set_extra_http_headers({"User-Agent": UA})
        await page.goto(url, wait_until="networkidle", timeout=45000)
        # small settle so async timers/render finish
        await page.wait_for_timeout(2500)

        # Extract Server Time (top clock) and the "UPCOMING EVENTS" cards via DOM
        data = await page.evaluate("""
(() => {
  const out = { serverTime: null, serverDate: null, events: [] };

  // --- Server time/date (top header) ---
  const bodyText = document.body.innerText;
  const mTime = bodyText.match(/\\b(\\d{2}:\\d{2}:\\d{2})\\b/);
  const mDate = bodyText.match(/(January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s+\\d{4}/);
  out.serverTime = mTime ? mTime[1] : null;
  out.serverDate = mDate ? mDate[0] : null;

  // --- Find the UPCOMING EVENTS panel ---
  const panel = Array.from(document.querySelectorAll('*'))
    .find(el => /\\bUPCOMING\\s+EVENTS\\b/i.test(el.textContent || ''));

  if (!panel) return out;

  // helper: tidy a name (strip extra spaces, leading numbering, etc.)
  const clean = (s) => (s || '')
    .replace(/[\\u00A0\\s]+/g, ' ')
    .replace(/^\\d+\\s+/, '')
    .trim();

  // 1) Future events with explicit "(HH:MM)" in the same node text
  const seen = new Set();
  panel.querySelectorAll('*').forEach(el => {
    const t = (el.innerText || '').trim();
    const m = t.match(/\\((\\d{1,2}:\\d{2})\\)/);
    if (!m) return;
    // take text before '(' as the event title (same line)
    let name = clean(t.split('(')[0]);
    if (!name || /^(Time|Server Time)$/i.test(name)) return;
    const hhmm = m[1];
    const key = name + '|' + hhmm;
    if (!seen.has(key)) {
      seen.add(key);
      out.events.push({ name, hhmm, active: false });
    }
  });

  // 2) NOW ACTIVE card (no HH:MM); usually within same card block
  //    Look for elements that say "NOW ACTIVE" and grab the first line of the card as the name.
  panel.querySelectorAll('*').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!/\\bNOW\\s+ACTIVE\\b/i.test(t)) return;
    const card = el.closest('div');
    if (!card) return;
    const lines = (card.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    // example lines: ["Raffle Event", "NOW ACTIVE", "00:47:23"]
    const firstLine = lines[0] || '';
    const name = clean(firstLine);
    if (!name || /^(Time|Server Time)$/i.test(name)) return;
    if (!out.events.find(e => e.name === name)) {
      out.events.unshift({ name, hhmm: null, active: true });
    }
  });

  // return at most a few items
  out.events = out.events.slice(0, 4);
  return out;
})()
        """)
        await ctx.close(); await browser.close()
        return data

# ---------- Time helpers ----------
def parse_server_dt(server_date: str, server_time: str) -> datetime:
    # fallback to UTC date/time if not found
    date_obj = datetime.utcnow().date()
    if server_date:
        try:
            date_obj = datetime.strptime(server_date, "%B %d, %Y").date()
        except Exception:
            pass
    hh, mm, ss = 0, 0, 0
    if server_time:
        try:
            hh, mm, ss = map(int, server_time.split(":"))
        except Exception:
            pass
    return datetime(date_obj.year, date_obj.month, date_obj.day, hh, mm, ss)

def to_epoch(server_dt: datetime, hhmm: str) -> int:
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
    snap = await grab_dom_snapshot(EVENT_URL)

    server_dt = parse_server_dt(snap.get("serverDate"), snap.get("serverTime"))
    events = snap.get("events") or []

    if not events:
        print("[INFO] No upcoming events parsed."); return

    rows = []
    for ev in events:
        name = ev["name"]
        if ev.get("active"):
            rows.append(f"• **NOW ACTIVE {name}**")
        elif ev.get("hhmm"):
            epoch = to_epoch(server_dt, ev["hhmm"])
            rows.append(f"• **{name}** — <t:{epoch}:t> • <t:{epoch}:R>")
        # ignore otherwise

    description = "\n".join(rows) if rows else "_No upcoming events found._"

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
