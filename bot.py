import os
import sqlite3
import secrets
import string
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DB_FILE = "autoadv.sqlite3"

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True


# ============================================================
# DATABASE
# ============================================================

def db():
    return sqlite3.connect(DB_FILE)


def setup_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            duration INTEGER NOT NULL,
            max_accounts INTEGER NOT NULL,
            campaigns_each INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            key TEXT,
            expires_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            bot_id INTEGER,
            enabled INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            interval INTEGER NOT NULL,
            enabled INTEGER DEFAULT 0,
            next_send TEXT
        )
    """)

    con.commit()
    con.close()


setup_db()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc)


def parse_duration(value):
    value = value.lower().strip()

    match = re.fullmatch(r"(\d+)(m|h|d|w)", value)

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    multiplier = {
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800
    }

    return amount * multiplier[unit]


def make_key():
    chars = string.ascii_uppercase + string.digits

    return "-".join(
        "".join(secrets.choice(chars) for _ in range(6))
        for _ in range(3)
    )


def get_user(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT key, expires_at FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    con.close()

    if not result:
        return None

    expires = datetime.fromisoformat(result[1])

    if expires <= now():
        return None

    return result


def get_key_info(key):
    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT duration, max_accounts, campaigns_each, used
        FROM keys
        WHERE key=?
        """,
        (key,)
    )

    result = cur.fetchone()

    con.close()

    return result


def user_accounts(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT id, name, bot_id, enabled FROM accounts WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchall()

    con.close()

    return result


def account_campaigns(account_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, guild_id, channel_id, message,
               interval, enabled
        FROM campaigns
        WHERE account_id=?
        """,
        (account_id,)
    )

    result = cur.fetchall()

    con.close()

    return result


def is_owner(interaction):
    return interaction.user.id == OWNER_ID


# ============================================================
# BOT
# ============================================================

class AutoAdv(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        setup_db()
        self.campaign_loop.start()

        synced = await self.tree.sync()

        print(f"Synced {len(synced)} commands.")

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print(f"Bot ID: {self.user.id}")

    @tasks.loop(seconds=10)
    async def campaign_loop(self):

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT
                c.id,
                c.account_id,
                c.guild_id,
                c.channel_id,
                c.message,
                c.interval,
                c.next_send,
                a.user_id,
                a.enabled
            FROM campaigns c
            JOIN accounts a
                ON a.id = c.account_id
            WHERE c.enabled=1
              AND a.enabled=1
        """)

        campaigns = cur.fetchall()

        con.close()

        for campaign in campaigns:

            (
                campaign_id,
                account_id,
                guild_id,
                channel_id,
                message,
                interval,
                next_send,
                user_id,
                account_enabled
            ) = campaign

            access = get_user(user_id)

            if not access:
                self.disable_user_campaigns(user_id)
                continue

            if next_send:

                next_time = datetime.fromisoformat(next_send)

                if now() < next_time:
                    continue

            channel = self.get_channel(channel_id)

            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception:
                    continue

            try:

                await channel.send(message)

                next_time = now() + timedelta(
                    seconds=max(10, interval)
                )

                con = db()
                cur = con.cursor()

                cur.execute(
                    """
                    UPDATE campaigns
                    SET next_send=?
                    WHERE id=?
                    """,
                    (
                        next_time.isoformat(),
                        campaign_id
                    )
                )

                con.commit()
                con.close()

            except discord.HTTPException as e:
                print(f"Send error: {e}")

    def disable_user_campaigns(self, user_id):

        con = db()
        cur = con.cursor()

        cur.execute("""
            UPDATE campaigns
            SET enabled=0
            WHERE account_id IN (
                SELECT id
                FROM accounts
                WHERE user_id=?
            )
        """, (user_id,))

        con.commit()
        con.close()


bot = AutoAdv()


# ============================================================
# /GENKEY
# ============================================================

@bot.tree.command(
    name="genkey",
    description="Generate an Auto-Adv key."
)
@app_commands.describe(
    duration="Example: 7d, 30d, 90d",
    accounts="Maximum accounts allowed",
    campaigns="Maximum campaigns per account"
)
async def genkey(
    interaction: discord.Interaction,
    duration: str,
    accounts: app_commands.Range[int, 1, 100],
    campaigns: app_commands.Range[int, 1, 100]
):

    if not is_owner(interaction):
        await interaction.response.send_message(
            "❌ Owner only.",
            ephemeral=True
        )
        return

    seconds = parse_duration(duration)

    if seconds is None:
        await interaction.response.send_message(
            "❌ Invalid duration.\n"
            "Use `1d`, `7d`, `30d`, `90d`, etc.",
            ephemeral=True
        )
        return

    key = make_key()

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO keys
        (key, duration, max_accounts, campaigns_each, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            key,
            seconds,
            accounts,
            campaigns,
            now().isoformat()
        )
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"🔑 **KEY GENERATED**\n\n"
        f"```{key}```\n\n"
        f"⏳ Duration: **{duration}**\n"
        f"👤 Accounts: **{accounts}**\n"
        f"📢 Campaigns/account: **{campaigns}**",
        ephemeral=True
    )


# ============================================================
# /REDEEMKEY
# ============================================================

@bot.tree.command(
    name="redeemkey",
    description="Redeem an Auto-Adv key."
)
@app_commands.describe(key="Your key")
async def redeemkey(
    interaction: discord.Interaction,
    key: str
):

    key = key.upper().strip()

    if get_user(interaction.user.id):

        await interaction.response.send_message(
            "❌ You already have an active key.",
            ephemeral=True
        )
        return

    info = get_key_info(key)

    if not info:

        await interaction.response.send_message(
            "❌ Invalid key.",
            ephemeral=True
        )
        return

    duration, max_accounts, campaigns_each, used = info

    if used >= max_accounts:

        await interaction.response.send_message(
            "❌ This key has no account slots remaining.",
            ephemeral=True
        )
        return

    expires = now() + timedelta(seconds=duration)

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT OR REPLACE INTO users
        (user_id, key, expires_at)
        VALUES (?, ?, ?)
        """,
        (
            interaction.user.id,
            key,
            expires.isoformat()
        )
    )

    cur.execute(
        """
        UPDATE keys
        SET used=used+1
        WHERE key=?
        """,
        (key,)
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"✅ **KEY REDEEMED**\n\n"
        f"⏳ Expires <t:{int(expires.timestamp())}:R>\n"
        f"👤 Account slot: **{used + 1}/{max_accounts}**\n"
        f"📢 Campaigns/account: **{campaigns_each}**\n\n"
        f"You can now use `/panel`.",
        ephemeral=True
    )


# ============================================================
# PANEL VIEW
# ============================================================

class PanelView(discord.ui.View):

    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ This isn't your panel.",
                ephemeral=True
            )

            return False

        if not get_user(self.user_id):

            await interaction.response.send_message(
                "❌ Your key has expired.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Accounts",
        emoji="👤",
        style=discord.ButtonStyle.primary
    )
    async def accounts(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "Use `/addaccount` to add an authorized bot account.\n"
            "Use `/removeaccount` to remove one.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Manage",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary
    )
    async def manage(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "Use `/addcampaign` to create a campaign.\n"
            "Use `/campaigns` to view your campaigns.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.success
    )
    async def pause_resume(
        self,
        interaction,
        button
    ):

        con = db()
        cur = con.cursor()

        cur.execute("""
            SELECT id
            FROM accounts
            WHERE user_id=?
        """, (interaction.user.id,))

        account_ids = [x[0] for x in cur.fetchall()]

        if account_ids:

            placeholders = ",".join("?" * len(account_ids))

            cur.execute(
                f"""
                UPDATE campaigns
                SET enabled =
                    CASE
                        WHEN enabled=1 THEN 0
                        ELSE 1
                    END
                WHERE account_id IN ({placeholders})
                """,
                account_ids
            )

        con.commit()
        con.close()

        await interaction.response.send_message(
            "⏯️ Campaign states toggled.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Delete All",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete_all(
        self,
        interaction,
        button
    ):

        con = db()
        cur = con.cursor()

        cur.execute("""
            DELETE FROM campaigns
            WHERE account_id IN (
                SELECT id
                FROM accounts
                WHERE user_id=?
            )
        """, (interaction.user.id,))

        con.commit()
        con.close()

        await interaction.response.send_message(
            "🗑️ All your campaigns were deleted.",
            ephemeral=True
        )


# ============================================================
# /PANEL
# ============================================================

@bot.tree.command(
    name="panel",
    description="Open your Auto-Adv control panel."
)
async def panel(interaction):

    access = get_user(interaction.user.id)

    if not access:

        await interaction.response.send_message(
            "🔒 **Access denied.**\n\n"
            "Redeem a key with `/redeemkey` first.",
            ephemeral=True
        )
        return

    key, expires_raw = access

    expires = datetime.fromisoformat(expires_raw)

    info = get_key_info(key)

    duration, max_accounts, campaigns_each, used = info

    accounts = user_accounts(interaction.user.id)

    running = 0

    for account in accounts:

        campaigns = account_campaigns(account[0])

        for campaign in campaigns:

            if campaign[5] == 1:
                running += 1

    embed = discord.Embed(
        title="⭐ Control Panel",
        description="Manage your Auto-Adv campaigns.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Type",
        value="Paid",
        inline=True
    )

    embed.add_field(
        name="Accounts",
        value=f"{len(accounts)} / {max_accounts}",
        inline=True
    )

    embed.add_field(
        name="Campaigns / Account",
        value=str(campaigns_each),
        inline=True
    )

    embed.add_field(
        name="Expires",
        value=f"<t:{int(expires.timestamp())}:R>",
        inline=False
    )

    if accounts:

        account_text = []

        for index, account in enumerate(accounts, 1):

            name = account[1]

            status = "🟢 Enabled" if account[3] else "🔴 Disabled"

            account_text.append(
                f"**Account {index} · {name}**\n"
                f"{status}"
            )

        embed.add_field(
            name="Accounts",
            value="\n\n".join(account_text),
            inline=False
        )

    else:

        embed.add_field(
            name="Accounts",
            value="No accounts added.",
            inline=False
        )

    embed.add_field(
        name="Campaigns",
        value=f"🟢 Active campaigns: **{running}**",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        view=PanelView(interaction.user.id),
        ephemeral=True
    )


# ============================================================
# /ADDACCOUNT
# ============================================================

@bot.tree.command(
    name="addaccount",
    description="Add an authorized Discord bot account."
)
@app_commands.describe(
    name="Name for the account",
    bot_id="Discord bot ID"
)
async def addaccount(
    interaction,
    name: str,
    bot_id: str
):

    access = get_user(interaction.user.id)

    if not access:

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    key = access[0]

    info = get_key_info(key)

    _, max_accounts, _, _ = info

    accounts = user_accounts(interaction.user.id)

    if len(accounts) >= max_accounts:

        await interaction.response.send_message(
            f"❌ Account limit reached: **{max_accounts}**.",
            ephemeral=True
        )
        return

    if not bot_id.isdigit():

        await interaction.response.send_message(
            "❌ Bot ID must be a numeric Discord ID.",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO accounts
        (user_id, name, bot_id, enabled)
        VALUES (?, ?, ?, 1)
        """,
        (
            interaction.user.id,
            name[:80],
            int(bot_id)
        )
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"✅ Added **{name}**.\n"
        f"Accounts: **{len(accounts) + 1}/{max_accounts}**",
        ephemeral=True
    )


# ============================================================
# /REMOVEACCOUNT
# ============================================================

@bot.tree.command(
    name="removeaccount",
    description="Remove one of your accounts."
)
@app_commands.describe(
    account_id="Database account ID"
)
async def removeaccount(
    interaction,
    account_id: int
):

    if not get_user(interaction.user.id):

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT id
        FROM accounts
        WHERE id=? AND user_id=?
        """,
        (
            account_id,
            interaction.user.id
        )
    )

    result = cur.fetchone()

    if not result:

        con.close()

        await interaction.response.send_message(
            "❌ Account not found.",
            ephemeral=True
        )
        return

    cur.execute(
        """
        DELETE FROM campaigns
        WHERE account_id=?
        """,
        (account_id,)
    )

    cur.execute(
        """
        DELETE FROM accounts
        WHERE id=? AND user_id=?
        """,
        (
            account_id,
            interaction.user.id
        )
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        "✅ Account removed.",
        ephemeral=True
    )


# ============================================================
# /ADD CAMPAIGN
# ============================================================

@bot.tree.command(
    name="addcampaign",
    description="Create an Auto-Adv campaign."
)
@app_commands.describe(
    account_id="Your account ID",
    channel="Channel to send to",
    message="Advertisement message",
    interval="Seconds between messages"
)
async def addcampaign(
    interaction,
    account_id: int,
    channel: discord.TextChannel,
    message: str,
    interval: app_commands.Range[int, 10, 86400]
):

    access = get_user(interaction.user.id)

    if not access:

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    key = access[0]

    _, _, campaigns_each, _ = get_key_info(key)

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT id
        FROM accounts
        WHERE id=? AND user_id=?
        """,
        (
            account_id,
            interaction.user.id
        )
    )

    account = cur.fetchone()

    if not account:

        con.close()

        await interaction.response.send_message(
            "❌ Account not found.",
            ephemeral=True
        )
        return

    cur.execute(
        """
        SELECT COUNT(*)
        FROM campaigns
        WHERE account_id=?
        """,
        (account_id,)
    )

    count = cur.fetchone()[0]

    if count >= campaigns_each:

        con.close()

        await interaction.response.send_message(
            f"❌ Campaign limit reached: "
            f"**{campaigns_each} per account**.",
            ephemeral=True
        )
        return

    cur.execute(
        """
        INSERT INTO campaigns
        (
            account_id,
            guild_id,
            channel_id,
            message,
            interval,
            enabled
        )
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            account_id,
            interaction.guild.id,
            channel.id,
            message,
            interval
        )
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"✅ Campaign created.\n"
        f"📍 {channel.mention}\n"
        f"⏱️ Every **{interval}s**\n"
        f"▶️ Start it from `/panel`.",
        ephemeral=True
    )


# ============================================================
# /CAMPAIGNS
# ============================================================

@bot.tree.command(
    name="campaigns",
    description="List your campaigns."
)
async def campaigns(interaction):

    if not get_user(interaction.user.id):

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    accounts = user_accounts(interaction.user.id)

    if not accounts:

        await interaction.response.send_message(
            "You don't have any accounts.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📢 Your Campaigns",
        color=discord.Color.blurple()
    )

    for account in accounts:

        campaigns_list = account_campaigns(account[0])

        if not campaigns_list:
            text = "No campaigns."
        else:

            lines = []

            for campaign in campaigns_list:

                cid = campaign[0]
                channel_id = campaign[2]
                interval = campaign[4]
                enabled = campaign[5]

                status = "🟢" if enabled else "🔴"

                lines.append(
                    f"{status} `#{cid}` "
                    f"<#{channel_id}> — {interval}s"
                )

            text = "\n".join(lines)

        embed.add_field(
            name=f"Account {account[0]} · {account[1]}",
            value=text,
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# /START
# ============================================================

@bot.tree.command(
    name="start",
    description="Start a campaign."
)
@app_commands.describe(
    campaign_id="Campaign ID"
)
async def start(
    interaction,
    campaign_id: int
):

    if not get_user(interaction.user.id):

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT c.id
        FROM campaigns c
        JOIN accounts a
            ON a.id=c.account_id
        WHERE c.id=? AND a.user_id=?
        """,
        (
            campaign_id,
            interaction.user.id
        )
    )

    if not cur.fetchone():

        con.close()

        await interaction.response.send_message(
            "❌ Campaign not found.",
            ephemeral=True
        )
        return

    cur.execute(
        """
        UPDATE campaigns
        SET enabled=1,
            next_send=?
        WHERE id=?
        """,
        (
            now().isoformat(),
            campaign_id
        )
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"▶️ Campaign `{campaign_id}` started.",
        ephemeral=True
    )


# ============================================================
# /STOP
# ============================================================

@bot.tree.command(
    name="stop",
    description="Stop a campaign."
)
@app_commands.describe(
    campaign_id="Campaign ID"
)
async def stop(
    interaction,
    campaign_id: int
):

    if not get_user(interaction.user.id):

        await interaction.response.send_message(
            "🔒 Redeem a key first.",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        UPDATE campaigns
        SET enabled=0
        WHERE id=?
        AND account_id IN (
            SELECT id
            FROM accounts
            WHERE user_id=?
        )
        """,
        (
            campaign_id,
            interaction.user.id
        )
    )

    changed = cur.rowcount

    con.commit()
    con.close()

    if not changed:

        await interaction.response.send_message(
            "❌ Campaign not found.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⏹️ Campaign `{campaign_id}` stopped.",
        ephemeral=True
    )


# ============================================================
# /MYKEY
# ============================================================

@bot.tree.command(
    name="mykey",
    description="View your key information."
)
async def mykey(interaction):

    access = get_user(interaction.user.id)

    if not access:

        await interaction.response.send_message(
            "❌ No active key.",
            ephemeral=True
        )
        return

    key, expires_raw = access

    expires = datetime.fromisoformat(expires_raw)

    info = get_key_info(key)

    _, max_accounts, campaigns_each, used = info

    await interaction.response.send_message(
        f"🔑 Key: `{key}`\n"
        f"⏳ Expires: <t:{int(expires.timestamp())}:F>\n"
        f"👤 Accounts used: **{used}/{max_accounts}**\n"
        f"📢 Campaigns/account: **{campaigns_each}**",
        ephemeral=True
    )


# ============================================================
# OWNER: /REVOKE
# ============================================================

@bot.tree.command(
    name="revoke",
    description="Revoke a user's access."
)
@app_commands.describe(
    user="User to revoke"
)
async def revoke(
    interaction,
    user: discord.User
):

    if not is_owner(interaction):

        await interaction.response.send_message(
            "❌ Owner only.",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM users WHERE user_id=?",
        (user.id,)
    )

    cur.execute(
        """
        UPDATE campaigns
        SET enabled=0
        WHERE account_id IN (
            SELECT id
            FROM accounts
            WHERE user_id=?
        )
        """,
        (user.id,)
    )

    con.commit()
    con.close()

    await interaction.response.send_message(
        f"✅ Revoked {user.mention}.",
        ephemeral=True
    )


# ============================================================
# RUN
# ============================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not configured."
    )

bot.run(TOKEN)
