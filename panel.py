# panel.py — adv bot interactive panel
import asyncio
import discord
import db
import adv


class AddAccountModal(discord.ui.Modal, title="Add Account"):
    token = discord.ui.TextInput(label="Token", required=True, max_length=200)
    label = discord.ui.TextInput(label="Label", required=False, max_length=40)

    async def on_submit(self, interaction: discord.Interaction):
        aid = await db.add_account(
            self.token.value.strip(),
            None,
            self.label.value.strip() or None,
        )
        if aid is None:
            await interaction.response.send_message("already added.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"account #{aid} added.", ephemeral=True
        )


class SetChannelsModal(discord.ui.Modal, title="Set Channels"):
    account_id = discord.ui.TextInput(label="Account ID", required=True, max_length=10)
    channels = discord.ui.TextInput(
        label="Channel IDs (one per line)",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            aid = int(self.account_id.value)
        except ValueError:
            await interaction.response.send_message("bad id.", ephemeral=True)
            return
        await db.clear_channels(aid)
        for ch in [c.strip() for c in self.channels.value.splitlines() if c.strip()]:
            await db.add_channel(aid, ch)
        await interaction.response.send_message(
            f"channels set for #{aid}.", ephemeral=True
        )


class SetAdsModal(discord.ui.Modal, title="Set Ads"):
    account_id = discord.ui.TextInput(label="Account ID", required=True, max_length=10)
    ads = discord.ui.TextInput(
        label="Ads (one per line)",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=3000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            aid = int(self.account_id.value)
        except ValueError:
            await interaction.response.send_message("bad id.", ephemeral=True)
            return
        await db.clear_ads(aid)
        for a in [x.strip() for x in self.ads.value.splitlines() if x.strip()]:
            await db.add_ad(aid, a)
        await interaction.response.send_message(f"ads set for #{aid}.", ephemeral=True)


class DelayModal(discord.ui.Modal, title="Set Delays"):
    account_id = discord.ui.TextInput(label="Account ID", required=True, max_length=10)
    min_d = discord.ui.TextInput(label="Min seconds", required=True, max_length=6)
    max_d = discord.ui.TextInput(label="Max seconds", required=True, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            aid = int(self.account_id.value)
            lo = int(self.min_d.value)
            hi = int(self.max_d.value)
        except ValueError:
            await interaction.response.send_message("numbers only.", ephemeral=True)
            return
        if lo < 15 or hi <= lo:
            await interaction.response.send_message(
                "min >= 15 and max > min.", ephemeral=True
            )
            return
        await db.set_delays(aid, lo, hi)
        await interaction.response.send_message(
            f"#{aid} delay {lo}-{hi}s.", ephemeral=True
        )


class StartModal(discord.ui.Modal, title="Start Account"):
    account_id = discord.ui.TextInput(label="Account ID (or 'all')",
                                      required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.account_id.value.strip().lower()
        if v == "all":
            rows = await db.list_accounts()
            started = 0
            for rid, *_ in rows:
                res = await adv.launch(rid)
                if res == "started":
                    started += 1
                await asyncio.sleep(2)
            await interaction.response.send_message(
                f"started {started}/{len(rows)}.", ephemeral=True
            )
            return
        try:
            aid = int(v)
        except ValueError:
            await interaction.response.send_message("bad id.", ephemeral=True)
            return
        res = await adv.launch(aid)
        await interaction.response.send_message(res, ephemeral=True)


class StopModal(discord.ui.Modal, title="Stop Account"):
    account_id = discord.ui.TextInput(label="Account ID (or 'all')",
                                      required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.account_id.value.strip().lower()
        if v == "all":
            n = adv.stop_all()
            await interaction.response.send_message(f"stopped {n}.", ephemeral=True)
            return
        try:
            aid = int(v)
        except ValueError:
            await interaction.response.send_message("bad id.", ephemeral=True)
            return
        ok = adv.stop_worker(aid)
        await interaction.response.send_message(
            "stopped." if ok else "not running.", ephemeral=True
        )


class DeleteModal(discord.ui.Modal, title="Delete Account"):
    account_id = discord.ui.TextInput(label="Account ID", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            aid = int(self.account_id.value)
        except ValueError:
            await interaction.response.send_message("bad id.", ephemeral=True)
            return
        adv.stop_worker(aid)
        await db.delete_account(aid)
        await interaction.response.send_message(f"deleted #{aid}.", ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Add Account", style=discord.ButtonStyle.green, row=0)
    async def add_acc(self, interaction, button):
        await interaction.response.send_modal(AddAccountModal())

    @discord.ui.button(label="Set Channels", style=discord.ButtonStyle.blurple, row=0)
    async def set_ch(self, interaction, button):
        await interaction.response.send_modal(SetChannelsModal())

    @discord.ui.button(label="Set Ads", style=discord.ButtonStyle.blurple, row=1)
    async def set_ads(self, interaction, button):
        await interaction.response.send_modal(SetAdsModal())

    @discord.ui.button(label="Set Delays", style=discord.ButtonStyle.gray, row=1)
    async def set_delay(self, interaction, button):
        await interaction.response.send_modal(DelayModal())

    @discord.ui.button(label="Start", style=discord.ButtonStyle.green, row=2)
    async def start_btn(self, interaction, button):
        await interaction.response.send_modal(StartModal())

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.red, row=2)
    async def stop_btn(self, interaction, button):
        await interaction.response.send_modal(StopModal())

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.red, row=2)
    async def del_btn(self, interaction, button):
        await interaction.response.send_modal(DeleteModal())

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.gray, row=3)
    async def refresh(self, interaction, button):
        embed = await build_panel_embed()
        await interaction.response.edit_message(embed=embed, view=self)


async def build_panel_embed():
    rows = await db.list_accounts()
    running = set(adv.WORKERS.keys())
    embed = discord.Embed(title="Auto Adv Panel", color=0x5865F2)

    if not rows:
        embed.description = "no accounts yet — click **Add Account**."
        return embed

    lines = []
    for rid, tok, proxy, label, en in rows:
        mask = tok[:6] + "..." + tok[-4:]
        run = "▶" if rid in running else "·"
        tag = label or "unnamed"
        lines.append(f"{run} `#{rid}` {tag} `{mask}`")

    embed.description = "\n".join(lines[:20])
    if len(lines) > 20:
        embed.description += f"\n… +{len(lines)-20} more"
    embed.set_footer(text=f"{len(running)} running / {len(rows)} total")
    return embed


def setup(tree, owner_id):

    @tree.command(name="panel", description="open the adv panel")
    async def panel_cmd(interaction: discord.Interaction):
        if interaction.user.id != owner_id:
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        embed = await build_panel_embed()
        await interaction.response.send_message(
            embed=embed, view=PanelView(), ephemeral=True
        )
