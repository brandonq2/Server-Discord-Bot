import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands

from bot.config import load_config
from bot.economy_db import EconomyDB
from bot.logging_setup import setup_logging

logger = logging.getLogger(__name__)

# Add cog module paths here when you create new features.
COG_EXTENSIONS = [
    "bot.cogs.general",
    "bot.cogs.mirror",
    "bot.cogs.economy",
    # "bot.cogs.moderation",
    # "bot.cogs.music",
]


class Bot(commands.Bot):
    def __init__(self, guild_id: Optional[int] = None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # required to read embeds in guild messages

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.guild_id = guild_id
        self.economy_db = EconomyDB()

    async def setup_hook(self) -> None:
        await self.economy_db.connect()
        logger.info("Economy database connected")

        for extension in COG_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info("Loaded extension: %s", extension)
            except Exception:
                logger.exception("Failed to load extension: %s", extension)
                raise

        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d slash command(s) to guild %s", len(synced), self.guild_id)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global slash command(s)", len(synced))

    async def close(self) -> None:
        await self.economy_db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "unknown")


async def main() -> None:
    setup_logging()
    config = load_config()

    bot = Bot(guild_id=config.guild_id)

    async with bot:
        await bot.start(config.token)


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")


if __name__ == "__main__":
    run()
