"""Soundboard playback and targeted automatic sound reactions."""

import asyncio
import random
import threading
import time

import discord
from discord import app_commands
from discord.ext import commands, voice_recv


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
        future = asyncio.run_coroutine_threadsafe(self._play_sound(sound_id, source_guild_id), self.loop)
        future.add_done_callback(lambda result: self._report_error(result, sound_name))

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

    def add_target(self, user_id: int, sounds: list[tuple[int, str, int | None]]):
        self.target_sounds[user_id] = sounds

    def remove_target(self, user_id: int):
        self.target_sounds.pop(user_id, None)

    def cleanup(self):
        pass


class SoundPrank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_sessions: dict[int, AutoPrankSink] = {}

    async def gui_get_sounds(self, guild: discord.Guild):
        sounds = await self._get_sounds_from_guild(guild)
        return [(item.id, item.name, getattr(getattr(item, "guild", None), "id", None)) for item in sounds]

    async def gui_play_sound(self, guild: discord.Guild, sound_id: int):
        channel = self._voice_channel(guild)
        if channel is None:
            raise RuntimeError("The bot must be in a voice channel")
        sounds = await self._get_sounds_from_guild(guild)
        selected = next((item for item in sounds if item.id == sound_id), None)
        if selected is None:
            raise RuntimeError("That sound is no longer available")
        await self._send_sound(channel.id, selected)

    async def gui_toggle_autoprank(self, guild: discord.Guild, target: discord.Member, sound_ids: list[int]):
        channel = target.voice.channel if target.voice else None
        if channel is None:
            raise RuntimeError("The target member must be in a voice channel")
        sounds = await self._get_sounds_from_guild(guild)
        available = {item.id: item for item in sounds}
        selected = [available[sound_id] for sound_id in sound_ids if sound_id in available]
        if len(selected) != len(sound_ids):
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
            (item.id, item.name, getattr(getattr(item, "guild", None), "id", None))
            for item in sounds_to_play
        ])
        return f"Automatic sound reactions are now on for {target.display_name}."

    @app_commands.command(name="sound", description="Play a sound from this server's soundboard")
    @app_commands.describe(sound="Choose a soundboard sound")
    async def sound(self, interaction: discord.Interaction, sound: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        try:
            sounds = await self._get_sounds_from_guild(interaction.guild)
            selected = next(item for item in sounds if str(item.id) == sound)
            await interaction.response.defer()
            await self._send_sound(interaction.user.voice.channel.id, selected)
            await interaction.followup.send(f"Playing **{selected.name}**.")
        except (discord.HTTPException, StopIteration):
            if interaction.response.is_done():
                await interaction.followup.send("I could not play that sound.", ephemeral=True)
            else:
                await interaction.response.send_message("That sound is no longer available.", ephemeral=True)

    @sound.autocomplete("sound")
    async def sound_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        try:
            sounds = await self._get_sounds_from_guild(interaction.guild)
        except discord.HTTPException:
            return []
        return [app_commands.Choice(name=item.name[:100], value=str(item.id)) for item in sounds if current.lower() in item.name.lower()][:25]

    async def _send_sound(self, channel_id: int, sound):
        payload = {"sound_id": sound.id}
        if isinstance(sound, discord.SoundboardSound):
            payload["source_guild_id"] = sound.guild.id
        await self.bot.http.send_soundboard_sound(channel_id, **payload)

    async def _get_sounds_from_guild(self, guild: discord.Guild):
        default_data = await self.bot.http.get_soundboard_default_sounds()
        defaults = [discord.SoundboardDefaultSound(state=self.bot._connection, data=item) for item in default_data]
        return defaults + await guild.fetch_soundboard_sounds()

    @staticmethod
    def _voice_channel(guild: discord.Guild):
        return guild.me.voice.channel if guild.me and guild.me.voice else None


async def setup(bot: commands.Bot):
    await bot.add_cog(SoundPrank(bot))
