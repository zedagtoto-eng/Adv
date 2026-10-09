# db.py — sqlite for adv bot
import os
import time
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "advbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL UNIQUE,
    proxy       TEXT,
    label       TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    added_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    channel_id  TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    content     TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
    account_id  INTEGER PRIMARY KEY,
    min_delay   INTEGER NOT NULL DEFAULT 45,
    max_delay   INTEGER NOT NULL DEFAULT 180,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
"""


async def init():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def migrate():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.commit()


async def add_account(token, proxy=None, label=None):
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            cur = await conn.execute(
                "INSERT INTO accounts (token, proxy, label, added_at) VALUES (?,?,?,?)",
                (token, proxy, label, int(time.time())),
            )
            aid = cur.lastrowid
            await conn.execute(
                "INSERT INTO settings (account_id, min_delay, max_delay) VALUES (?,45,180)",
                (aid,),
            )
            await conn.commit()
            return aid
        except aiosqlite.IntegrityError:
            return None


async def list_accounts():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT id, token, proxy, label, enabled FROM accounts"
        ) as c:
            return await c.fetchall()


async def get_account(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def delete_account(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        await conn.commit()


async def add_channel(account_id, channel_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO channels (account_id, channel_id) VALUES (?,?)",
            (account_id, str(channel_id)),
        )
        await conn.commit()


async def list_channels(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT channel_id FROM channels WHERE account_id=?", (account_id,)
        ) as c:
            return [r[0] for r in await c.fetchall()]


async def clear_channels(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM channels WHERE account_id=?", (account_id,)
        )
        await conn.commit()


async def add_ad(account_id, content):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO ads (account_id, content) VALUES (?,?)",
            (account_id, content),
        )
        await conn.commit()


async def list_ads(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT content FROM ads WHERE account_id=?", (account_id,)
        ) as c:
            return [r[0] for r in await c.fetchall()]


async def clear_ads(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM ads WHERE account_id=?", (account_id,))
        await conn.commit()


async def set_delays(account_id, lo, hi):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO settings (account_id, min_delay, max_delay) VALUES (?,?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "min_delay=excluded.min_delay, max_delay=excluded.max_delay",
            (account_id, lo, hi),
        )
        await conn.commit()


async def get_settings(account_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT min_delay, max_delay FROM settings WHERE account_id=?",
            (account_id,),
        ) as c:
            return await c.fetchone()
