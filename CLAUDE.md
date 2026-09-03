# CLAUDE.md

## Project overview
This repository is a Python Discord bot built with discord.py and organized around cog-based features.

The bot entry point is `bot/main.py`. It loads extension modules from `bot/cogs/*.py` automatically and syncs slash commands to Discord on startup. After login it starts the local Tkinter control panel in `bot/control_panel.py`.

## Current project status
As of 2026-09-02, the bot is a small dev/test bot with working slash commands for:
- `/ping`
- `/uptime`
- `/info`
- `/join`
- `/leave`
- `/debug` (owner only)
- `/reload` (owner only)
- `/sound` for playing a server soundboard sound
- `/autoprank user:@member sound_1:<sound> sound_2:<sound> sound_3:<sound>` for targeted random sound reactions
- `/textprank user:@member` for targeted message deletion with a 25% chance
- `/leaveinstyle` to play the leave song and disconnect voice members at the configured drop time

The bot also includes debug logging for voice state changes when debug mode is enabled.

## Architecture
- `bot/main.py`
  - creates the bot client
  - enables message and member intents
  - loads all cogs from `bot/cogs/`
  - syncs slash commands to the configured guild
- `bot/config.py`
  - reads environment variables from `.env`
  - exposes `DISCORD_TOKEN`, `DEV_GUILD_IDS`, `OWNER_IDS`, `LOG_LEVEL`
- `bot/cogs/general.py`
  - user-facing slash commands such as ping/info/join/leave
- `bot/cogs/admin.py`
  - owner-only tools such as `/reload` and `/debug`
- `bot/cogs/sound_prank.py`
  - soundboard playback and targeted automatic sound reactions
- `bot/cogs/text_prank.py`
  - targeted message deletion
- `bot/cogs/leave_style.py`
  - timed song playback and voice-channel clearing
- `bot/control_panel.py`
  - local tabbed desktop controls for the prank features

## Runtime behavior
- Bot startup command:
  `python -m bot.main`
- The bot expects a `.env` file with the Discord token.
- `DEV_GUILD_IDS` should be set to the server ID when testing slash commands locally so updates appear quickly instead of waiting for global sync.

## Current voice features
The bot supports basic voice join/leave behavior.

- `/join`: joins the user's current voice channel
- `/leave`: leaves whatever voice channel the bot is in
- `on_voice_state_update` logs join/leave events to the terminal when debug mode is enabled

The voice prank cog fetches built-in and server soundboard sounds and plays the
selected clip with `/sound` through Discord's native soundboard API. `/autoprank`
uses DAVE-compatible voice receiving to detect speaking starts for one selected
member and trigger a random built-in sound at most once every 1 second per
guild.

`/textprank` targets one selected member and deletes their messages with a 25%
chance. It requires the bot to have Manage Messages permission.

The local control panel supports multiple simultaneous sound and text prank
targets using independent tabs. Text tabs can select multiple members at once.

`/leaveinstyle` plays `Sounds/outro-song_oqu8zAg.mp3`, disconnects members at
`LEAVE_STYLE_DROP_SECONDS`, and then leaves the voice channel. It requires Move
Members permission.

## Debug mode
The bot has an owner-only `/debug` command that toggles a debug flag.

When debug mode is on, the bot prints voice events to the terminal, for example:
- `[DEBUG] UserName#1234 joined voice channel: General`

## Dependencies
The project currently depends on:
- `discord.py`
- `python-dotenv`
- `PyNaCl`
- `davey`

Voice features require the voice libraries to be installed in the same Python environment that runs the bot.

## Important notes for future AI agents
- Keep command features in separate cog files inside `bot/cogs/`.
- The prank slash commands are hidden from Discord; control them from the local GUI.
- Do not put feature logic directly in `bot/main.py` unless it is truly shared/global setup.
- When editing slash commands, restart the bot so Discord re-syncs command definitions.
- If duplicate slash commands appear in Discord, stale app-command registrations are usually the cause. The common fix is to use a clean test guild or re-invite the bot after removing stale commands.
- Do not hardcode secrets. Store tokens and local configuration in `.env` and keep `.env` out of version control.

## Working conventions
- Use a cog-per-feature workflow.
- Keep new features isolated in their own files under `bot/cogs/`.
- Prefer owner-only debug and reload commands for development.
- Use `DEV_GUILD_IDS` while testing so slash commands update quickly.

## Suggested next tasks
- Add a proper welcome message system for new members
- Add a leave command confirmation flow if needed
- Add a music or moderation cog if wanted
- Consider a cleaner command reset flow for stale Discord slash commands
