"""
Central config loader.

Everything the bot needs (token, IDs, feature flags) should be read
from environment variables and exposed here — never hardcode secrets
in cog files. Later, when we hook up the web dashboard, this is the
file that will start pulling some of these values from a database
instead of .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_int_list(env_var: str) -> list[int]:
    raw = os.getenv(env_var, "")
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]


class Config:
    # Required
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    # Optional — used for instant slash command sync during development.
    # Leave empty to sync globally (can take up to 1hr to propagate).
    DEV_GUILD_IDS: list[int] = _get_int_list("DEV_GUILD_IDS")

    # Bot owner(s) — useful for owner-only commands (e.g. reload cogs)
    OWNER_IDS: list[int] = _get_int_list("OWNER_IDS")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


    @classmethod
    def validate(cls) -> None:
        if not cls.DISCORD_TOKEN:
            raise RuntimeError(
                "DISCORD_TOKEN is missing. Copy .env.example to .env "
                "and fill in your bot token."
            )


config = Config()
