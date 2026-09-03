"""Play sounds from Discord's built-in and server soundboards."""

import asyncio
import random
import threading
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, voice_recv

from bot.config import config


LEAVE_STYLE_SONG = Path(__file__).parents[2] / "Sounds" / "outro-song_oqu8zAg.mp3"


class AutoPrankSink(voice_recv.AudioSink):
    def __init__(self, bot: commands.Bot, channel_id: int, target_user_id: int, sounds: list[tuple[int, str, int | None]]):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        self.target_user_id = target_user_id
        self.sounds = sounds
        self.loop = bot.loop
        self.next_allowed = 0.0
        self.cooldown_lock = threading.Lock()

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data):
        pass

    @voice_recv.AudioSink.listener()
    def on_voice_member_speaking_start(self, member: discord.Member):
        if member.bot or member.id != self.target_user_id:
            return

        with self.cooldown_lock:
            now = time.monotonic()
            if now < self.next_allowed:
                return
            self.next_allowed = now + 1

        sound_id, sound_name, source_guild_id = random.choice(self.sounds)
        future = asyncio.run_coroutine_threadsafe(
            self._play_sound(sound_id, source_guild_id),
            self.loop,
        )
        future.add_done_callback(
            lambda result: self._report_error(result, sound_name)
        )

    async def _play_sound(self, sound_id: int, source_guild_id: int | None):
        payload = {"sound_id": sound_id}
        if source_guild_id is not None:
            payload["source_guild_id"] = source_guild_id
        await self.bot.http.send_soundboard_sound(self.channel_id, **payload)

    def _report_error(self, future, sound_name: str):
        try:
            future.result()
        except Exception as error:
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Automatic sound {sound_name!r} failed: {error}")

    def cleanup(self):
        pass


class VoicePrank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_sessions: dict[int, AutoPrankSink] = {}
        self.text_prank_targets: dict[int, int] = {}
        self.leave_style_tasks: dict[int, asyncio.Task] = {}

    @app_commands.command(name="sound", description="Play a sound from this server's soundboard")
    @app_commands.describe(sound="Choose a soundboard sound")
    async def sound(self, interaction: discord.Interaction, sound: str):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return

        try:
            sounds = await self._get_sounds(interaction)
        except discord.HTTPException:
            await interaction.response.send_message("I could not load Discord's soundboard sounds.", ephemeral=True)
            return

        selected = next((item for item in sounds if str(item.id) == sound), None)
        if selected is None:
            await interaction.response.send_message("That sound is no longer available.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        await interaction.response.defer()
        try:
            payload = {"sound_id": selected.id}
            if isinstance(selected, discord.SoundboardSound):
                payload["source_guild_id"] = selected.guild.id
            await interaction.client.http.send_soundboard_sound(channel.id, **payload)
            await interaction.followup.send(f"Playing **{selected.name}**.")
        except discord.HTTPException:
            await interaction.followup.send("I could not play that sound.", ephemeral=True)

    @app_commands.command(name="autoprank", description="Toggle random sounds when a selected user talks")
    @app_commands.describe(
        user="Select the member whose voice should trigger sounds",
        sound_1="First sound to use",
        sound_2="Optional second sound to use",
        sound_3="Optional third sound to use",
    )
    async def autoprank(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        sound_1: str | None = None,
        sound_2: str | None = None,
        sound_3: str | None = None,
    ):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        existing_sink = self.auto_sessions.pop(guild_id, None)
        if existing_sink:
            voice_client = interaction.guild.voice_client
            if isinstance(voice_client, voice_recv.VoiceRecvClient):
                voice_client.stop_listening()
                await voice_client.disconnect()
            await interaction.response.send_message("Automatic sound reactions are now off.")
            return
        if user is None:
            await interaction.response.send_message("Select a member to prank.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("Choose a real member, not a bot.", ephemeral=True)
            return

        try:
            sounds = await self._get_sounds(interaction)
        except discord.HTTPException:
            await interaction.response.send_message("I could not load Discord's soundboard sounds.", ephemeral=True)
            return

        default_sounds = [item for item in sounds if isinstance(item, discord.SoundboardDefaultSound)]
        selected_ids = [sound_id for sound_id in (sound_1, sound_2, sound_3) if sound_id]
        available_sounds = {str(item.id): item for item in sounds}
        selected_sounds = [available_sounds[sound_id] for sound_id in selected_ids if sound_id in available_sounds]
        if len(selected_sounds) != len(selected_ids):
            await interaction.response.send_message("One of those sounds is no longer available.", ephemeral=True)
            return
        if not default_sounds and not selected_sounds:
            await interaction.response.send_message("No built-in Discord sounds are available.", ephemeral=True)
            return
        sounds_to_play = selected_sounds or default_sounds

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
        channel = interaction.user.voice.channel
        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        sink = AutoPrankSink(
            self.bot,
            channel.id,
            user.id,
            [
                (item.id, item.name, item.guild.id if isinstance(item, discord.SoundboardSound) else None)
                for item in sounds_to_play
            ],
        )
        self.auto_sessions[guild_id] = sink
        voice_client.listen(sink)
        await interaction.response.send_message(
            f"Automatic sound reactions are now on for {user.display_name} (ID: {user.id})."
        )

    @app_commands.command(name="textprank", description="Toggle 25% message deletion for a selected user")
    @app_commands.describe(user="Select the member whose messages should be targeted")
    async def textprank(self, interaction: discord.Interaction, user: discord.Member | None = None):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        if guild_id in self.text_prank_targets:
            self.text_prank_targets.pop(guild_id)
            await interaction.response.send_message("Text prank mode is now off.")
            return

        if user is None:
            await interaction.response.send_message("Select a member to target.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("Choose a real member, not a bot.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "I need the Manage Messages permission to use text prank mode.",
                ephemeral=True,
            )
            return

        self.text_prank_targets[guild_id] = user.id
        await interaction.response.send_message(
            f"Text prank mode is now on for {user.display_name} (ID: {user.id})."
        )

    @app_commands.command(name="leaveinstyle", description="Play the leave song, then clear the voice channel")
    async def leaveinstyle(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        if not LEAVE_STYLE_SONG.is_file():
            await interaction.response.send_message("The leave-in-style song file is missing.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.move_members:
            await interaction.response.send_message(
                "I need the Move Members permission to clear the voice channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        old_task = self.leave_style_tasks.pop(interaction.guild.id, None)
        if old_task and not old_task.done():
            old_task.cancel()

        try:
            channel = interaction.user.voice.channel
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_connected():
                if voice_client.channel != channel:
                    await voice_client.move_to(channel)
            else:
                voice_client = await channel.connect()

            voice_client.play(
                discord.FFmpegPCMAudio(str(LEAVE_STYLE_SONG), executable=config.FFMPEG_EXECUTABLE)
            )
            self.leave_style_tasks[interaction.guild.id] = asyncio.create_task(
                self._clear_voice_channel(interaction.guild, channel, voice_client)
            )
            await interaction.followup.send("Leave-in-style sequence started.")
        except (discord.ClientException, discord.Forbidden, discord.HTTPException, OSError) as error:
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Leave-in-style failed: {error}")
            await interaction.followup.send(
                "I could not start the leave-in-style sequence. Check that FFmpeg and voice permissions are available.",
                ephemeral=True,
            )

    async def _clear_voice_channel(self, guild: discord.Guild, channel: discord.VoiceChannel, voice_client):
        try:
            await asyncio.sleep(max(0, config.LEAVE_STYLE_DROP_SECONDS))
            for member in list(channel.members):
                if member.id == self.bot.user.id:
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if self.text_prank_targets.get(message.guild.id) != message.author.id:
            return
        if random.random() >= 0.25:
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

    @sound.autocomplete("sound")
    async def sound_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []

        try:
            sounds = await self._get_sounds(interaction)
        except discord.HTTPException:
            return []

        current = current.lower()
        matches = [item for item in sounds if current in item.name.lower()]
        return [app_commands.Choice(name=item.name[:100], value=str(item.id)) for item in matches[:25]]

    @autoprank.autocomplete("sound_1")
    @autoprank.autocomplete("sound_2")
    @autoprank.autocomplete("sound_3")
    async def autoprank_sound_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.sound_autocomplete(interaction, current)

    async def _get_sounds(self, interaction: discord.Interaction):
        default_data = await interaction.client.http.get_soundboard_default_sounds()
        default_sounds = [
            discord.SoundboardDefaultSound(state=interaction.client._connection, data=item)
            for item in default_data
        ]
        guild_sounds = await interaction.guild.fetch_soundboard_sounds()
        return default_sounds + guild_sounds


async def setup(bot: commands.Bot):
    await bot.add_cog(VoicePrank(bot))