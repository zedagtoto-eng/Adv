# adv.py — adv worker + hardcoded proxy
import asyncio
import random
import aiohttp
from aiohttp_socks import ProxyConnector
import db

API = "https://discord.com/api/v10"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# ---- hardcoded proxy used for every account ----
DEFAULT_PROXY = "socks5://95a76697ee0ed845-geo-us:3ddc6cc67805b966@gate-eu.vaultproxies.com:80"

WORKERS = {}


def headers(token):
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": UA,
    }


def make_session(proxy):
    if proxy and proxy.startswith("socks"):
        connector = ProxyConnector.from_url(proxy)
        return aiohttp.ClientSession(connector=connector)
    return aiohttp.ClientSession()


async def send_msg(session, token, channel_id, content, proxy=None):
    url = f"{API}/channels/{channel_id}/messages"
    http_proxy = proxy if proxy and not proxy.startswith("socks") else None
    try:
        async with session.post(
            url, headers=headers(token), json={"content": content},
            proxy=http_proxy, timeout=15,
        ) as r:
            if r.status == 429:
                data = await r.json()
                await asyncio.sleep(data.get("retry_after", 5))
                return await send_msg(session, token, channel_id, content, proxy)
            if r.status == 403:
                print(f"[send] 403 — muted/locked in {channel_id}")
                return False
            if r.status not in (200, 201):
                print(f"[send] {r.status} in {channel_id}")
                return False
            return True
    except Exception as e:
        print(f"[send] err: {e}")
        return False


async def adv_worker(account_id, token, proxy, channels, ads, lo, hi, stop_event):
    session = make_session(proxy)
    try:
        async with session:
            while not stop_event.is_set():
                random.shuffle(channels)
                for ch in channels:
                    if stop_event.is_set():
                        return
                    msg = random.choice(ads)
                    await send_msg(session, token, ch, msg, proxy)
                    delay = random.uniform(lo, hi)
                    for _ in range(int(delay)):
                        if stop_event.is_set():
                            return
                        await asyncio.sleep(1)
    except Exception as e:
        print(f"[adv #{account_id}] worker died: {e}")


def start_worker(account_id, token, proxy, channels, ads, lo, hi):
    if account_id in WORKERS:
        return False
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        adv_worker(account_id, token, proxy, channels, ads, lo, hi, stop_event)
    )
    WORKERS[account_id] = (task, stop_event)
    return True


def stop_worker(account_id):
    if account_id not in WORKERS:
        return False
    task, stop_event = WORKERS.pop(account_id)
    stop_event.set()
    task.cancel()
    return True


def stop_all():
    n = len(WORKERS)
    for aid in list(WORKERS.keys()):
        stop_worker(aid)
    return n


async def launch(account_id):
    acc = await db.get_account(account_id)
    if not acc:
        return "not found"
    chans = await db.list_channels(account_id)
    ads = await db.list_ads(account_id)
    st = await db.get_settings(account_id)
    if not chans:
        return "no channels"
    if not ads:
        return "no ads"
    lo, hi = (st[0], st[1]) if st else (45, 180)
    proxy = acc["proxy"] or DEFAULT_PROXY
    ok = start_worker(account_id, acc["token"], proxy,
                      chans, ads, lo, hi)
    return "started" if ok else "already running"
