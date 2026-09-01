"""
General-purpose commands. Good place to start when testing that the
bot is alive and wired up correctly.
"""

import time

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{latency_ms}ms`")

    @app_commands.command(name="uptime", description="How long the bot has been running")
    async def uptime(self, interaction: discord.Interaction):
        uptime_seconds = round(time.time() - self.bot.start_time) if hasattr(self.bot, "start_time") else 0
        await interaction.response.send_message(f"⏱️ Uptime: {uptime_seconds}s")

    @app_commands.command(name="info", description="Basic info about the bot")
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Bot Info", color=discord.Color.blurple())
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="join", description="Join the voice channel you're currently in")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel first.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_connected():
            if voice_client.channel == channel:
                await interaction.response.send_message(f"I'm already in {channel.mention}.", ephemeral=True)
                return
            await voice_client.move_to(channel)
            await interaction.response.send_message(f"Moved to {channel.mention}.")
            return

        await channel.connect()
        await interaction.response.send_message(f"Joined {channel.mention}.")

    @app_commands.command(name="leave", description="Leave the current voice channel")
    async def leave(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("I'm not in a voice channel right now.", ephemeral=True)
            return

        channel = voice_client.channel
        await voice_client.disconnect()
        await interaction.response.send_message(f"Left {channel.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
