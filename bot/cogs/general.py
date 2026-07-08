import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    """Basic slash commands included with the skeleton."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check if the bot is online.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! {latency_ms}ms")

    @app_commands.command(name="hello", description="Say hello.")
    async def hello(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"Hello, {interaction.user.mention}!")
    
    


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
