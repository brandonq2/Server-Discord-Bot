"""
Template for new cogs.

To add a new feature:
1. Copy this file to a new name (e.g. moderation.py)
2. Rename the class and update the docstring
3. Add slash commands with @app_commands.command
4. Register the cog in bot/main.py COG_EXTENSIONS
5. Restart the bot to sync new commands to Discord
"""

import discord
from discord import app_commands
from discord.ext import commands


class Template(commands.Cog):
    """Describe what this cog does."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # Slash command example
    # @app_commands.command(name="example", description="An example slash command.")
    # @app_commands.describe(name="Who to greet")
    # async def example(self, interaction: discord.Interaction, name: str) -> None:
    #     await interaction.response.send_message(f"Hello, {name}!")

    # Slash command with choices
    # @app_commands.command(name="color", description="Pick a color.")
    # @app_commands.choices(color=[
    #     app_commands.Choice(name="Red", value="red"),
    #     app_commands.Choice(name="Blue", value="blue"),
    # ])
    # async def color(
    #     self,
    #     interaction: discord.Interaction,
    #     color: app_commands.Choice[str],
    # ) -> None:
    #     await interaction.response.send_message(f"You picked {color.value}.")

    # Event listener example (enable message_content intent in bot/main.py if needed)
    # @commands.Cog.listener()
    # async def on_message(self, message: discord.Message) -> None:
    #     if message.author.bot:
    #         return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Template(bot))
