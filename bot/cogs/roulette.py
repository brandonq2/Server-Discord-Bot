import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.economy_db import EconomyDB

logger = logging.getLogger(__name__)

MIN_BET = 10

# European roulette (single zero)
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
    11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
    22, 18, 29, 7, 28, 12, 35, 3, 26,
]


def number_color_emoji(n: int) -> str:
    if n == 0:
        return "🟢"
    return "🔴" if n in RED_NUMBERS else "⚫"


def check_win(bet_type: str, result: int, chosen_number: int | None = None) -> bool:
    match bet_type:
        case "number":  return result == chosen_number
        case "red":     return result in RED_NUMBERS
        case "black":   return result in BLACK_NUMBERS
        case "odd":     return result != 0 and result % 2 == 1
        case "even":    return result != 0 and result % 2 == 0
        case "low":     return 1 <= result <= 18
        case "high":    return 19 <= result <= 36
        case "dozen1":  return 1 <= result <= 12
        case "dozen2":  return 13 <= result <= 24
        case "dozen3":  return 25 <= result <= 36
        case _:         return False


MULTIPLIERS = {
    "number": 36, "red": 2, "black": 2, "odd": 2, "even": 2,
    "low": 2, "high": 2, "dozen1": 3, "dozen2": 3, "dozen3": 3,
}


class Roulette(commands.Cog):
    """Roulette betting games."""

    roulette_group = app_commands.Group(
        name="roulette",
        description="Bet on the roulette wheel.",
    )

    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db

    async def _spin(
        self,
        interaction: discord.Interaction,
        bet_type: str,
        amount: int,
        label: str,
        chosen_number: int | None = None,
    ) -> None:
        if amount < MIN_BET:
            await interaction.response.send_message(f"Minimum bet is ${MIN_BET:,}.", ephemeral=True)
            return

        data = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        if data["balance"] < amount:
            await interaction.response.send_message(
                f"Insufficient funds. Balance: ${data['balance']:,}", ephemeral=True
            )
            return

        await self.db.update_balance(interaction.user.id, interaction.guild_id, -amount)
        await interaction.response.defer()

        result = random.choice(WHEEL)
        color_emoji = number_color_emoji(result)
        won = check_win(bet_type, result, chosen_number)
        multiplier = MULTIPLIERS[bet_type]

        if won:
            payout = amount * multiplier
            await self.db.update_balance(interaction.user.id, interaction.guild_id, payout)
            profit = payout - amount
            result_str = f"**WIN!** +${profit:,}"
            embed_color = discord.Color.green()
        else:
            result_str = f"**LOSE** −${amount:,}"
            embed_color = discord.Color.red()

        data_after = await self.db.get_balance(interaction.user.id, interaction.guild_id)

        embed = discord.Embed(
            title=f"🎡 Roulette — {color_emoji} **{result}**",
            color=embed_color,
        )
        embed.add_field(name="Your Bet", value=f"{label}", inline=True)
        embed.add_field(name="Wagered", value=f"${amount:,}", inline=True)
        embed.add_field(name="Result", value=result_str, inline=True)
        embed.add_field(name="New Balance", value=f"${data_after['balance']:,}", inline=True)
        embed.set_footer(
            text=f"Payout: {multiplier}x | European roulette (0–36, single zero)"
        )
        await interaction.followup.send(embed=embed)

    # ── Bet commands ────────────────────────────────────────────────── #

    @roulette_group.command(name="color", description="Bet on Red or Black — 2x payout.")
    @app_commands.describe(color="Color to bet on.", amount="Amount to bet.")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red 🔴", value="red"),
        app_commands.Choice(name="Black ⚫", value="black"),
    ])
    async def bet_color(
        self,
        interaction: discord.Interaction,
        color: app_commands.Choice[str],
        amount: int,
    ) -> None:
        await self._spin(interaction, color.value, amount, label=color.name)

    @roulette_group.command(name="parity", description="Bet on Odd or Even — 2x payout.")
    @app_commands.describe(parity="Parity to bet on.", amount="Amount to bet.")
    @app_commands.choices(parity=[
        app_commands.Choice(name="Odd", value="odd"),
        app_commands.Choice(name="Even", value="even"),
    ])
    async def bet_parity(
        self,
        interaction: discord.Interaction,
        parity: app_commands.Choice[str],
        amount: int,
    ) -> None:
        await self._spin(interaction, parity.value, amount, label=parity.name)

    @roulette_group.command(name="half", description="Bet on Low (1–18) or High (19–36) — 2x payout.")
    @app_commands.describe(half="Half of the board to bet on.", amount="Amount to bet.")
    @app_commands.choices(half=[
        app_commands.Choice(name="Low (1–18)", value="low"),
        app_commands.Choice(name="High (19–36)", value="high"),
    ])
    async def bet_half(
        self,
        interaction: discord.Interaction,
        half: app_commands.Choice[str],
        amount: int,
    ) -> None:
        await self._spin(interaction, half.value, amount, label=half.name)

    @roulette_group.command(name="dozen", description="Bet on a dozen — 3x payout.")
    @app_commands.describe(dozen="Dozen to bet on.", amount="Amount to bet.")
    @app_commands.choices(dozen=[
        app_commands.Choice(name="1st Dozen (1–12)", value="dozen1"),
        app_commands.Choice(name="2nd Dozen (13–24)", value="dozen2"),
        app_commands.Choice(name="3rd Dozen (25–36)", value="dozen3"),
    ])
    async def bet_dozen(
        self,
        interaction: discord.Interaction,
        dozen: app_commands.Choice[str],
        amount: int,
    ) -> None:
        await self._spin(interaction, dozen.value, amount, label=dozen.name)

    @roulette_group.command(name="number", description="Bet on a single number (0–36) — 36x payout.")
    @app_commands.describe(number="Number between 0 and 36.", amount="Amount to bet.")
    async def bet_number(
        self,
        interaction: discord.Interaction,
        number: int,
        amount: int,
    ) -> None:
        if not 0 <= number <= 36:
            await interaction.response.send_message("Number must be between 0 and 36.", ephemeral=True)
            return
        await self._spin(interaction, "number", amount, label=f"Number {number}", chosen_number=number)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Roulette(bot, db))
