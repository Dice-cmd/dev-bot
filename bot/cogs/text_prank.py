"""Targeted text message deletion prank."""

import random

import discord
from discord import app_commands
from discord.ext import commands


class TextPrank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.targets: dict[int, set[int]] = {}

    async def gui_toggle(self, guild: discord.Guild, targets: list[discord.Member]):
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_messages:
            raise RuntimeError("The bot needs Manage Messages permission")
        target_ids = {target.id for target in targets}
        active = self.targets.setdefault(guild.id, set())
        if target_ids.issubset(active):
            active.difference_update(target_ids)
            if not active:
                self.targets.pop(guild.id)
            return f"Text prank mode is now off for {len(targets)} selected members."
        active.update(target_ids)
        return f"Text prank mode is now on for: {', '.join(target.display_name for target in targets)}."

    @app_commands.command(name="textprank", description="Toggle 25% message deletion for a selected user")
    @app_commands.describe(user="Select the member whose messages should be targeted")
    async def textprank(self, interaction: discord.Interaction, user: discord.Member | None = None):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if user is None:
            await interaction.response.send_message("Select a member to target.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("Choose a real member, not a bot.", ephemeral=True)
            return
        result = await self.gui_toggle(interaction.guild, [user])
        await interaction.response.send_message(result)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.author.id not in self.targets.get(message.guild.id, set()) or random.random() >= 0.25:
            return
        try:
            await message.delete()
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Deleted a message from user ID {message.author.id} in #{message.channel}")
        except discord.Forbidden:
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Could not delete message from user ID {message.author.id}: missing permission")
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(TextPrank(bot))
