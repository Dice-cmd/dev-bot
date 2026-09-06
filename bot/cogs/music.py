"""URL-based music playback with a per-guild queue."""

import asyncio
from dataclasses import dataclass
import random
from urllib.parse import urlparse

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from bot.config import config


YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
@dataclass
class Track:
    title: str
    webpage_url: str
    stream_url: str
    requester: str


class MusicSession:
    def __init__(self):
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.starting_next = False
        self.repeat = False
        self.skip_requested = False


class MusicQueueView(discord.ui.View):
    def __init__(self, music: "Music", guild_id: int):
        super().__init__(timeout=3600)
        self.music = music
        self.guild_id = guild_id

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=self.music._queue_embed(self.guild_id),
            view=self.music._queue_view(self.guild_id),
        )

    @discord.ui.button(label="Next", emoji="⏭️", style=discord.ButtonStyle.primary)
    async def next_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.music._skip_current(self.guild_id):
            await self._refresh(interaction)
        else:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.music._voice_client(interaction.guild)
        if voice_client and voice_client.is_playing():
            voice_client.pause()
        elif voice_client and voice_client.is_paused():
            voice_client.resume()
        else:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        await self._refresh(interaction)

    @discord.ui.button(label="Repeat", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def repeat_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = self.music.sessions.get(self.guild_id)
        if not session or not session.current:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        session.repeat = not session.repeat
        await self._refresh(interaction)

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.music._shuffle_queue(self.guild_id):
            await interaction.response.send_message("There are no upcoming songs to shuffle.", ephemeral=True)
            return
        await self._refresh(interaction)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, MusicSession] = {}

    @app_commands.command(name="play", description="Play a YouTube song or add it to the queue")
    @app_commands.describe(url="A YouTube URL or the song name to search for")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return
        if not url.strip():
            await interaction.response.send_message("Enter a song name or a YouTube URL.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            track = await asyncio.to_thread(self._extract_track, url, interaction.user.display_name)
            voice_client = await self._connect_to_user_channel(interaction.guild, interaction.user.voice.channel)
            session = self.sessions.setdefault(interaction.guild.id, MusicSession())
            if voice_client.is_playing() or voice_client.is_paused() or session.current:
                session.queue.append(track)
                await interaction.followup.send(f"Queued **{track.title}** (position {len(session.queue)}).")
            else:
                await self._start_track(interaction.guild, voice_client, session, track)
                await interaction.followup.send(f"Now playing **{track.title}**.")
        except (discord.ClientException, discord.Forbidden, discord.HTTPException, OSError, RuntimeError, ValueError, yt_dlp.utils.DownloadError) as error:
            if getattr(self.bot, "debug_mode", False):
                print(f"[DEBUG] Music play failed: {error}")
            await interaction.followup.send("I could not find or play that song. Try a different song name or a direct YouTube URL.", ephemeral=True)

    @app_commands.command(name="skip", description="Skip the currently playing track")
    async def skip(self, interaction: discord.Interaction):
        if not interaction.guild or not await self._skip_current(interaction.guild.id):
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        await interaction.response.send_message("Skipped the current track.")

    @app_commands.command(name="pause", description="Pause the current track")
    async def pause(self, interaction: discord.Interaction):
        voice_client = self._voice_client(interaction.guild)
        if not voice_client or not voice_client.is_playing():
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        voice_client.pause()
        await interaction.response.send_message("Paused the music.")

    @app_commands.command(name="resume", description="Resume paused music")
    async def resume(self, interaction: discord.Interaction):
        voice_client = self._voice_client(interaction.guild)
        if not voice_client or not voice_client.is_paused():
            await interaction.response.send_message("Nothing is paused right now.", ephemeral=True)
            return
        voice_client.resume()
        await interaction.response.send_message("Resumed the music.")

    @app_commands.command(name="stop", description="Stop music, clear the queue, and leave voice")
    async def stop(self, interaction: discord.Interaction):
        voice_client = self._voice_client(interaction.guild)
        session = self.sessions.pop(interaction.guild.id, None) if interaction.guild else None
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("I'm not playing music right now.", ephemeral=True)
            return
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        await voice_client.disconnect()
        if session:
            session.queue.clear()
        await interaction.response.send_message("Stopped the music and left the voice channel.")

    @app_commands.command(name="queue", description="Show the current track and music queue")
    async def queue(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self._queue_embed(interaction.guild.id),
            view=self._queue_view(interaction.guild.id),
        )

    @app_commands.command(name="repeat", description="Toggle repeating the current track")
    async def repeat(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        session = self.sessions.get(interaction.guild.id)
        if not session or not session.current:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return
        session.repeat = not session.repeat
        state = "on" if session.repeat else "off"
        await interaction.response.send_message(f"Repeat is now **{state}**.")

    @app_commands.command(name="shuffle", description="Shuffle the upcoming songs in the queue")
    async def shuffle(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        if not self._shuffle_queue(interaction.guild.id):
            await interaction.response.send_message("There are no upcoming songs to shuffle.", ephemeral=True)
            return
        await interaction.response.send_message("Shuffled the upcoming songs in the queue.")

    async def _connect_to_user_channel(self, guild: discord.Guild, channel: discord.VoiceChannel):
        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            return voice_client
        return await channel.connect()

    async def _start_track(self, guild: discord.Guild, voice_client, session: MusicSession, track: Track):
        session.current = track
        source = discord.FFmpegPCMAudio(track.stream_url, executable=config.FFMPEG_EXECUTABLE, **FFMPEG_OPTIONS)
        voice_client.play(source, after=lambda error: self._track_finished(guild.id, error))

    async def _skip_current(self, guild_id: int) -> bool:
        guild = self.bot.get_guild(guild_id)
        voice_client = guild.voice_client if guild else None
        if not voice_client or not (voice_client.is_playing() or voice_client.is_paused()):
            return False
        session = self.sessions.get(guild_id)
        if session:
            session.skip_requested = True
        voice_client.stop()
        return True

    def _shuffle_queue(self, guild_id: int) -> bool:
        session = self.sessions.get(guild_id)
        if not session or len(session.queue) < 2:
            return False
        random.shuffle(session.queue)
        return True

    def _track_finished(self, guild_id: int, error: Exception | None):
        if error and getattr(self.bot, "debug_mode", False):
            print(f"[DEBUG] Music track failed: {error}")
        asyncio.run_coroutine_threadsafe(self._play_next(guild_id), self.bot.loop)

    async def _play_next(self, guild_id: int):
        session = self.sessions.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        voice_client = guild.voice_client if guild else None
        if not session or not guild or not voice_client or not voice_client.is_connected():
            self.sessions.pop(guild_id, None)
            return
        if session.starting_next or voice_client.is_playing() or voice_client.is_paused():
            return
        session.starting_next = True
        try:
            if session.current and session.repeat and not session.skip_requested:
                await self._start_track(guild, voice_client, session, session.current)
                return
            if session.current:
                session.queue.append(session.current)
            session.skip_requested = False
            if not session.queue:
                session.current = None
                await voice_client.disconnect()
                self.sessions.pop(guild_id, None)
                return
            await self._start_track(guild, voice_client, session, session.queue.pop(0))
        finally:
            session.starting_next = False

    def _queue_embed(self, guild_id: int) -> discord.Embed:
        session = self.sessions.get(guild_id)
        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blurple())
        if not session or not session.current:
            embed.description = "Nothing is playing. Use `/play` to add a song."
            return embed

        repeat_state = "on" if session.repeat else "off"
        lines = [f"🎶 **{session.current.title}**"]
        lines.append(f"🔁 Repeat: **{repeat_state}**")
        if session.queue:
            lines.append("")
            lines.extend(f"{index}. {track.title}" for index, track in enumerate(session.queue, start=1))
        else:
            lines.extend(["", "📭 Queue is empty."])
        embed.description = "\n".join(lines)
        return embed

    def _queue_view(self, guild_id: int) -> MusicQueueView:
        return MusicQueueView(self, guild_id)

    @staticmethod
    def _extract_track(url: str, requester: str) -> Track:
        source = url if Music._is_http_url(url) else f"ytsearch1:{url}"
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as downloader:
            info = downloader.extract_info(source, download=False)
        if info and info.get("entries"):
            info = next((entry for entry in info["entries"] if entry), None)
        if not info or not info.get("url"):
            raise ValueError("No playable audio was found")
        return Track(
            title=info.get("title", "Untitled track"),
            webpage_url=info.get("webpage_url", source),
            stream_url=info["url"],
            requester=requester,
        )

    @staticmethod
    def _is_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _voice_client(guild: discord.Guild | None):
        return guild.voice_client if guild else None


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))