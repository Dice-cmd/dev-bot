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
    def __init__(self, bot: commands.Bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        self.target_sounds: dict[int, list[tuple[int, str, int | None]]] = {}
        self.loop = bot.loop
        self.next_allowed = 0.0
        self.cooldown_lock = threading.Lock()

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data):
        pass

    @voice_recv.AudioSink.listener()
    def on_voice_member_speaking_start(self, member: discord.Member):
        if member.bot or member.id not in self.target_sounds:
            return

        with self.cooldown_lock:
            now = time.monotonic()
            if now < self.next_allowed:
                return
            self.next_allowed = now + 1

        sound_id, sound_name, source_guild_id = random.choice(self.target_sounds[member.id])
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

    def add_target(self, user_id: int, sounds: list[tuple[int, str, int | None]]):
        self.target_sounds[user_id] = sounds

    def remove_target(self, user_id: int):
        self.target_sounds.pop(user_id, None)


class VoicePrank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_sessions: dict[int, AutoPrankSink] = {}
        self.text_prank_targets: dict[int, set[int]] = {}
        self.leave_style_tasks: dict[int, asyncio.Task] = {}

    async def gui_get_sounds(self, guild: discord.Guild):
        sounds = await self._get_sounds_from_guild(guild)
        return [
            (item.id, item.name, item.guild.id if isinstance(item, discord.SoundboardSound) else None)
            for item in sounds
        ]

    async def gui_play_sound(self, guild: discord.Guild, sound_id: int):
        channel = self._gui_voice_channel(guild)
        if channel is None:
            raise RuntimeError("The bot or target member must be in a voice channel")
        sounds = await self._get_sounds_from_guild(guild)
        selected = next((item for item in sounds if item.id == sound_id), None)
        if selected is None:
            raise RuntimeError("That sound is no longer available")
        payload = {"sound_id": selected.id}
        if isinstance(selected, discord.SoundboardSound):
            payload["source_guild_id"] = selected.guild.id
        await self.bot.http.send_soundboard_sound(channel.id, **payload)

    async def gui_toggle_autoprank(self, guild: discord.Guild, target: discord.Member, sound_ids: list[int]):
        channel = target.voice.channel if target.voice else None
        if channel is None:
            raise RuntimeError("The target member must be in a voice channel")
        sounds = await self._get_sounds_from_guild(guild)
        available = {item.id: item for item in sounds}
        selected = [available[sound_id] for sound_id in sound_ids if sound_id in available]
        if sound_ids and len(selected) != len(sound_ids):
            raise RuntimeError("One of the selected sounds is no longer available")
        sounds_to_play = selected or [item for item in sounds if isinstance(item, discord.SoundboardDefaultSound)]
        if not sounds_to_play:
            raise RuntimeError("No built-in Discord sounds are available")

        voice_client = guild.voice_client
        sink = self.auto_sessions.get(guild.id)
        if sink and target.id in sink.target_sounds:
            sink.remove_target(target.id)
            if not sink.target_sounds:
                self.auto_sessions.pop(guild.id, None)
                if isinstance(voice_client, voice_recv.VoiceRecvClient):
                    voice_client.stop_listening()
                    await voice_client.disconnect()
            return f"Automatic sound reactions are now off for {target.display_name}."
        if voice_client and voice_client.is_connected() and voice_client.channel != channel:
            raise RuntimeError("All automatic voice prank targets must be in the same voice channel")
        if not voice_client or not voice_client.is_connected():
            voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
            sink = AutoPrankSink(self.bot, channel.id)
            self.auto_sessions[guild.id] = sink
            voice_client.listen(sink)
        sink.add_target(target.id, [
            (item.id, item.name, item.guild.id if isinstance(item, discord.SoundboardSound) else None)
            for item in sounds_to_play
        ])
        return f"Automatic sound reactions are now on for {target.display_name}."

    async def gui_toggle_textprank(self, guild: discord.Guild, target: discord.Member):
        targets = self.text_prank_targets.setdefault(guild.id, set())
        if target.id in targets:
            targets.remove(target.id)
            if not targets:
                self.text_prank_targets.pop(guild.id)
            return "Text prank mode is now off."
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_messages:
            raise RuntimeError("The bot needs Manage Messages permission")
        targets.add(target.id)
        return f"Text prank mode is now on for {target.display_name}."

    async def gui_toggle_textprank_many(self, guild: discord.Guild, targets: list[discord.Member]):
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_messages:
            raise RuntimeError("The bot needs Manage Messages permission")
        target_ids = {target.id for target in targets}
        active_targets = self.text_prank_targets.setdefault(guild.id, set())
        if target_ids.issubset(active_targets):
            active_targets.difference_update(target_ids)
            if not active_targets:
                self.text_prank_targets.pop(guild.id)
            return f"Text prank mode is now off for {len(targets)} selected members."
        active_targets.update(target_ids)
        names = ", ".join(target.display_name for target in targets)
        return f"Text prank mode is now on for: {names}."

    async def gui_leaveinstyle(self, guild: discord.Guild, target: discord.Member):
        if not LEAVE_STYLE_SONG.is_file():
            raise RuntimeError("The leave-in-style song file is missing")
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.move_members:
            raise RuntimeError("The bot needs Move Members permission")
        channel = target.voice.channel if target.voice else self._gui_voice_channel(guild)
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
        old_task = self.leave_style_tasks.pop(guild.id, None)
        if old_task and not old_task.done():
            old_task.cancel()
        self.leave_style_tasks[guild.id] = asyncio.create_task(
            self._clear_voice_channel(guild, channel, voice_client)
        )
        return "Leave-in-style sequence started."

    @staticmethod
    def _gui_voice_channel(guild: discord.Guild):
        return guild.me.voice.channel if guild.me and guild.me.voice else None

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
        channel = interaction.user.voice.channel
        sink = self.auto_sessions.get(guild_id)
        if voice_client and voice_client.is_connected() and voice_client.channel != channel:
            await interaction.response.send_message("The bot is already listening in another voice channel.", ephemeral=True)
            return
        if not voice_client or not voice_client.is_connected():
            voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
            sink = AutoPrankSink(self.bot, channel.id)
            self.auto_sessions[guild_id] = sink
            voice_client.listen(sink)
        sink.add_target(user.id, [
            (item.id, item.name, item.guild.id if isinstance(item, discord.SoundboardSound) else None)
            for item in sounds_to_play
        ])
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
        targets = self.text_prank_targets.setdefault(guild_id, set())
        if user.id in targets:
            targets.remove(user.id)
            if not targets:
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

        targets.add(user.id)
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
        if message.author.id not in self.text_prank_targets.get(message.guild.id, set()):
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
        return await self._get_sounds_from_guild(interaction.guild)

    async def _get_sounds_from_guild(self, guild: discord.Guild):
        default_data = await self.bot.http.get_soundboard_default_sounds()
        default_sounds = [
            discord.SoundboardDefaultSound(state=self.bot._connection, data=item)
            for item in default_data
        ]
        guild_sounds = await guild.fetch_soundboard_sounds()
        return default_sounds + guild_sounds


async def setup(bot: commands.Bot):
    await bot.add_cog(VoicePrank(bot))