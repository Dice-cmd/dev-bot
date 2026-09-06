# Discord Bot

A Python (discord.py) bot built with a cog-based architecture so multiple
people can add features independently without stepping on each other.

## Project structure

```
discord-bot/
├── bot/
│   ├── main.py        # entry point, loads cogs, syncs slash commands
│   ├── config.py       # reads settings from .env
│   └── cogs/
│       ├── general.py  # example commands: /ping, /uptime, /info
│       ├── admin.py    # owner-only /reload for fast dev iteration
│       ├── sound_prank.py # soundboard and automatic sound reactions
│       ├── text_prank.py  # targeted message deletion
│       └── leave_style.py # timed voice-channel clear
│       └── music.py      # URL-based music playback and queue
├── bot/control_panel.py   # private local Tkinter GUI
├── .env.example         # copy to .env and fill in
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup (each person does this locally)

1. **Clone the repo**

   ```bash
   git clone <repo-url>
   cd discord-bot
   ```
2. **Create a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate      # macOS/Linux
   venv\Scripts\activate         # Windows
   ```
3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```
4. **Set up your bot token**

   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Create an application (share the same app/bot across the team — one bot token, everyone tests against it, OR each person makes their own dev bot to avoid conflicts. Recommended: each person has their own test bot so you're not fighting over one bot's slash command state.)
   - Under **Bot**, enable these **Privileged Gateway Intents**: `Server Members Intent`, `Message Content Intent`
   - Copy the token
   - `cp .env.example .env` and paste your token into `DISCORD_TOKEN`
5. **Invite your bot to a test server**

   - In the Developer Portal, go to OAuth2 → URL Generator
   - Scopes: `bot`, `applications.commands`
   - Permissions: whatever you're testing (Administrator is fine for a private dev server)
   - Open the generated URL and add it to your test server
6. **Set DEV_GUILD_IDS in .env**

   - Right-click your test server → Copy Server ID (enable Developer Mode in Discord settings first)
   - This makes slash commands sync instantly instead of waiting up to an hour
7. **Run the bot**

   ```bash
   python -m bot.main
   ```

The normal command starts the bot without the prank GUI. To start the bot with
the private **Discord Prank Controls** desktop window, use:

```bash
python -m bot.main prank
```

In prank mode, choose the server at the top, then add Sound prank, Text
prank, or Leave-in-style tabs. Sound tabs target one member, while Text tabs can
select multiple members at once. Each tab has its own options, and tabs can be
closed independently. Multiple sound and text prank tabs can run at the same
time. The prank slash commands are removed before command synchronization,
so they do not appear in Discord. Closing the window hides the controls while
the bot continues running.

## Voice prank

In a voice channel, use `/sound` and choose one of Discord's built-in sounds or
a sound uploaded to that server. The bot sends the sound through Discord's
native soundboard API, so FFmpeg is not needed for this feature. It needs Speak
and Use Soundboard permissions, and the person using the command must be in a
voice channel.

Use `/autoprank user:@member` to turn on automatic reactions for one selected
member. Optionally choose `sound_1`, `sound_2`, and `sound_3`; one of those is
picked randomly each time. Leave them blank to use all available built-in
sounds. The bot ignores everyone else and observes the current cooldown before
reacting again. The confirmation uses plain text and does not mention or ping
the selected member. Run `/autoprank` again to turn it off. Voice receiving also
requires the DAVE-compatible dependency listed in `requirements.txt`.

Use `/textprank user:@member` to target one member's messages. Each message has
a 25% chance of being deleted. Run `/textprank` again to turn it off. The bot
needs the Manage Messages permission, and the confirmation does not mention or
ping the selected member.

Use `/leaveinstyle` to play `Sounds/outro-song_oqu8zAg.mp3`. After 15.3 seconds
by default, the bot disconnects members from that voice channel and then leaves.
Set `LEAVE_STYLE_DROP_SECONDS` in `.env` to match the song's beat drop. The bot
requires Connect, Speak, and Move Members permissions.

## Music

Use `/play url:<song name or URL>` while in a voice channel. Plain text is
searched on YouTube and the first result is played; YouTube URLs are also
supported. Additional `/play` commands stay in the server's queue. Use
`/queue` to show the current song and upcoming songs. The queue message
includes emoji buttons for next (`⏭️`), pause/resume (`⏸️`), repeat (`🔁`),
and shuffle (`🔀`). Shuffle only changes the order of upcoming songs, not the
song currently playing. The same controls are available through `/skip`,
`/pause`, `/resume`, `/repeat`, `/shuffle`, or `/stop`.
Music playback requires Connect and Speak permissions plus FFmpeg installed on
the machine running the bot. `FFMPEG_EXECUTABLE` can be set in `.env` when
FFmpeg is not on the system PATH.

## Adding a new feature (cog)

1. Create a new file in `bot/cogs/`, e.g. `bot/cogs/moderation.py`
2. Copy the structure from `general.py`:
   ```python
   from discord import app_commands
   from discord.ext import commands
   import discord

   class Moderation(commands.Cog):
       def __init__(self, bot: commands.Bot):
           self.bot = bot

       @app_commands.command(name="kick", description="Kick a member")
       async def kick(self, interaction: discord.Interaction, member: discord.Member):
           ...

   async def setup(bot: commands.Bot):
       await bot.add_cog(Moderation(bot))
   ```
3. It's picked up automatically on the next restart — or run `/reload moderation`
   if you're an owner and the bot is already running.

## Suggested git workflow (3 people)

- `main` branch stays stable/working at all times
- Each person branches per feature: `feature/moderation-cog`, `feature/economy-cog`, etc.
- One cog per branch/PR keeps merge conflicts near zero since cogs are separate files
- Open a PR into `main`, at least one other person reviews before merging
- Keep `bot/main.py` and `bot/config.py` changes small and communicated — those are the
  shared files everyone touches occasionally

## Roadmap / next steps

- [ ] Pick specific features (moderation? music? economy? leveling?)
- [ ] Decide persistence: SQLite (simplest, file-based) vs Postgres (better if the
  web dashboard and bot need to read/write the same data concurrently)
- [ ] Web dashboard: once we know what needs to be configurable (welcome messages,
  role permissions, feature toggles, etc.), we'll add either:
  - a shared database the bot and website both read/write, or
  - a small REST API in the bot process that the website calls
- [ ] Deployment: pick a host (VPS, Railway, a Raspberry Pi at home, etc.) and add a
  `Dockerfile` once we're ready to deploy
