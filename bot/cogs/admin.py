"""
Owner-only utilities for development — reload cogs without restarting
the whole bot process. Handy with 3 people editing different cogs.
"""

import discord
from discord import app_commands
from discord.ext import commands


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.debug_mode = False

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not getattr(self.bot, "debug_mode", False):
            return

        joined_channel = after.channel
        left_channel = before.channel

        if left_channel is None and joined_channel is not None:
            print(f"[DEBUG] {member} joined voice channel: {joined_channel}")
        elif joined_channel is None and left_channel is not None:
            print(f"[DEBUG] {member} left voice channel: {left_channel}")

    @app_commands.command(name="debug", description="[Owner only] Toggle debug mode")
    async def debug(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        self.bot.debug_mode = not self.bot.debug_mode
        state = "ON" if self.bot.debug_mode else "OFF"
        print(f"[DEBUG] Debug mode toggled: {state}")
        await interaction.response.send_message(f"Debug mode is now **{state}**.", ephemeral=True)

    @app_commands.command(name="reload", description="[Owner only] Reload a cog by name")
    @app_commands.describe(cog="Cog filename without .py, e.g. 'general'")
    async def reload(self, interaction: discord.Interaction, cog: str):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        try:
            await self.bot.reload_extension(f"bot.cogs.{cog}")
            await interaction.response.send_message(f"✅ Reloaded `{cog}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to reload `{cog}`: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
