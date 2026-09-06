"""
Entry point.

Run the normal bot with: python -m bot.main
Run the bot with the prank control panel with: python -m bot.main prank
"""

import asyncio
import logging
from pathlib import Path
import sys

import discord
from discord.ext import commands

from bot.config import config

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

COGS_DIR = Path(__file__).parent / "cogs"


class MyBot(commands.Bot):
    def __init__(self, prank_mode: bool = False):
        self.prank_mode = prank_mode
        intents = discord.Intents.default()
        intents.message_content = True  # needed if you add prefix commands later
        intents.members = True  # needed for member join/leave events, roles, etc.

        super().__init__(
            command_prefix="!",  # kept as a fallback; slash commands are primary
            intents=intents,
            owner_ids=set(config.OWNER_IDS) or None,
        )

    async def setup_hook(self):
        await self.load_all_cogs()
        await self.sync_commands()

    async def load_all_cogs(self):
        for file in COGS_DIR.glob("*.py"):
            if file.name.startswith("_"):
                continue
            extension = f"bot.cogs.{file.stem}"
            try:
                await self.load_extension(extension)
                log.info("Loaded cog: %s", extension)
            except Exception:
                log.exception("Failed to load cog: %s", extension)

    async def sync_commands(self):
        hidden_commands = {"sound", "autoprank", "textprank", "leaveinstyle"}
        for command_name in hidden_commands:
            self.tree.remove_command(command_name)
        if config.DEV_GUILD_IDS:
            # Instant sync to specific dev servers — use this while building.
            for guild_id in config.DEV_GUILD_IDS:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally (can take up to 1hr)", len(synced))

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Connected to %d guild(s)", len(self.guilds))
        if self.prank_mode and not getattr(self, "control_panel_started", False):
            from bot.control_panel import ControlPanel

            self.control_panel_started = True
            ControlPanel(self).start()


async def main():
    config.validate()
    prank_mode = sys.argv[1:] == ["prank"]
    bot = MyBot(prank_mode=prank_mode)
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
