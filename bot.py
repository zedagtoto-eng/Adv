# bot.py — adv bot with panel
import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import db
import panel

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

if not BOT_TOKEN or not OWNER_ID:
    raise SystemExit("set BOT_TOKEN and OWNER_ID in env")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


@bot.event
async def on_ready():
    await db.init()
    await db.migrate()
    panel.setup(tree, OWNER_ID)

    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        print(f"online as {bot.user} — synced {len(synced)} cmds to guild {GUILD_ID}")
    else:
        synced = await tree.sync()
        print(f"online as {bot.user} — synced {len(synced)} cmds globally")


async def main():
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
