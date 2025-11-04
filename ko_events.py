import os, re, json, time, math, base64, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from playwright.async_api import async_playwright

# ---- env ----
DISCORD_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID     = os.environ["DISCORD_CHANNEL_ID"].strip()
EVENT_URL      = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
API_BASE       = "https://discord.com/api/v10"
HDR_JSON       = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}

# GitHub state file (stores message id)
GH_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GH_REPO        = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"
STATE_PATH     = ".ko4fun_state.json"
TITLE          = "KO4Fun — Upcoming Events"

# -------------------- RENDER PAGE --------------------
async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(2500)
        txt = await page.evaluate("document.body.innerText")
        await browser.close()
        return txt

# -------------------- PARSE --------------------
def parse_server_time(page_text: str) -> datetime:
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
    scope = page_text
    sec = re.search(r'Upcoming\s+Events(.+)', page_text, re.I | re.S)
    if sec:
        scope = sec.group(0)

    pattern = re.compile(r'([A-Za-z0-9\.\&\-\/\s]+?)\s*(?:\u00A0|\s)*\(\s*(\d{1,2}:\d{2})\s*\)')
    items = []
    for m in pattern.finditer(scope):
        name = " ".join(m.group(1).split())
        hhmm = m.group(2)
        if not name or len(name) < 2: continue
        if any(b in name for b in ("Server Time", "Upcoming Events", "See all pinned")): continue
        items.append((name, hhmm))

    if not items:
        for m in pattern.finditer(page_text):
            name = " ".join(m.group(1).split())
            hhmm = m.group(2)
            if not name or len(name) < 2: continue
            if "Server Time" in name or "Upcoming Events" in name: continue
            items.append((name, hhmm))

    seen = set(); cleaned = []
    for tup in items:
        if tup not in seen:
            seen.add(tup); cleaned.append(tup)
    return cleaned[:10]

def to_epoch(server_dt: datetime, hhmm: str) -> int:
    eh, em = map(int, hhmm.split(":"))
    event_dt = server_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if event_dt < server_dt: event_dt += timedelta(days=1)
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

def post_message(content="", embed=None):
    payload = {"content": content}
    if embed is not None: payload["embeds"] = [embed]
    code, body = http_json("POST", f"{API_BASE}/channels/{CHANNEL_ID}/messages", payload)
    return body

def edit_message(mid: str, content="", embed=None):
    payload = {"content": content}
    if embed is not None: payload["embeds"] = [embed]
    http_json("PATCH", f"{API_BASE}/channels/{CHANNEL_ID}/messages/{mid}", payload)

def pin_try(mid: str):
    try:
        http_json("PUT", f"{API_BASE}/channels/{CHANNEL_ID}/pins/{mid}", None, {"Authorization": f"Bot {DISCORD_TOKEN}"})
    except Exception:
        pass

# -------------------- GITHUB STATE --------------------
def gh_headers():
    return {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}

def gh_get_state():
    if not GH_TOKEN or not GH_REPO: return None, None
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{STATE_PATH}"
    req = Request(url, headers=gh_headers(), method="GET")
    try:
        with urlopen(req) as r:
            body = json.loads(r.read().decode())
            content = base64.b64decode(body["content"]).decode()
            data = json.loads(content)
            return data.get("channel_id"), (data.get("message_id"), body["sha"])
    except HTTPError as e:
        if e.code == 404: return None, (None, None)
        raise

def gh_put_state(message_id: str):
    if not GH_TOKEN or not GH_REPO: return
    content_obj = {"channel_id": CHANNEL_ID, "message_id": message_id}
    b64 = base64.b64encode(json.dumps(content_obj, indent=2).encode()).decode()
    # check if exists to use correct SHA
    _, state = gh_get_state()
    prev_sha = state[1] if state else None
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{STATE_PATH}"
    payload = {
        "message": "chore: update KO4Fun message id",
        "content": b64
    }
    if prev_sha: payload["sha"] = prev_sha
    req = Request(url, data=json.dumps(payload).encode(), headers=gh_headers(), method="PUT")
    with urlopen(req) as r:
        r.read()

def get_saved_message_id():
    ch, state = gh_get_state()
    if state is None: return None
    mid, _sha = state
    if ch == CHANNEL_ID and mid: return mid
    return None

# -------------------
