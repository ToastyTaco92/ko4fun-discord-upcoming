import os, re, json, time, math, asyncio
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.async_api import async_playwright

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
EVENT_URL   = os.environ.get("EVENT_URL", "https://ko4fun.net/Features/EventSchedule")
TITLE       = "KO4Fun — Upcoming Events"

async def get_rendered_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await pw.chromium.launch(headless=True)
        # correction: launch browser once
PY
