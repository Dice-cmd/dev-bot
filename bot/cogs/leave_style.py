"""Leave-in-style voice prank."""

import asyncio
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import config


LEAVE_STYLE_SONG = Path(__file__).parents[2] / "Sounds" / "outro-song_oqu8zAg.mp3"


class LeaveStyle(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}

    async def gui_start(self, guild: discord.Guild, target: discord.Member):
        if not LEAVE_STYLE_SONG.is_file():
            raise RuntimeError("The leave-in-style song file is missing")
        if guild.me is None or not guild.me.guild_permissions.move_members:
            raise RuntimeError("The bot needs Move Members permission")
        channel = target.voice.channel if target.voice else None
        if channel is None:
            raise RuntimeError("The selected member must be in a voice channel")
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)
        if voice_client.is_playing():
            voice_client.stop()
        voice_client.play(discord.FFmpegPCMAudio(str(LEAVE_STYLE_SONG), executable=config.FFMPEG_EXECUTABLE))
        old_task = self.tasks.pop(guild.id, None)
        if old_task and not old_task.done():
            old_task.cancel()
        self.tasks[guild.id] = asyncio.create_task(self._clear_channel(channel, voice_client))
        return "Leave-in-style sequence started."

    @app_commands.command(name="leaveinstyle", description="Play the leave song, then clear the voice channel")
    async def leaveinstyle(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            result = await self.gui_start(interaction.guild, interaction.user)
            await interaction.followup.send(result)
        except (discord.ClientException, discord.Forbidden, discord.HTTPException, OSError, RuntimeError) as error:
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Leave-in-style failed: {error}")
            await interaction.followup.send("I could not start the leave-in-style sequence.", ephemeral=True)

    async def _clear_channel(self, channel: discord.VoiceChannel, voice_client):
        try:
            await asyncio.sleep(max(0, config.LEAVE_STYLE_DROP_SECONDS))
            for member in list(channel.members):
                if self.bot.user and member.id == self.bot.user.id:
                    continue
                try:
                    await member.move_to(None, reason="Leave-in-style prank")
                except (discord.Forbidden, discord.HTTPException) as error:
                    if getattr(self.bot, "debug_mode", False):
                        print(f"[DEBUG] Could not disconnect {member.id}: {error}")
            if voice_client.is_connected():
                await voice_client.disconnect()
        except asyncio.CancelledError:
            if voice_client.is_playing():
                voice_client.stop()
            raise


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaveStyle(bot))
