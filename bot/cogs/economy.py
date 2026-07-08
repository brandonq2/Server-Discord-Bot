import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.economy_db import (
    PASSIVE_INTERVAL,
    PASSIVE_RATE,
    STARTING_BALANCE,
    EconomyDB,
)

logger = logging.getLogger(__name__)

MIN_BET = 10
MAX_BET = 1_000_000


def fmt(amount: int) -> str:
    return f"${amount:,}"


def fmt_duration(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def wallet_embed(
    user: discord.User | discord.Member,
    balance: int,
    pending: int,
    guild_name: str,
) -> discord.Embed:
    embed = discord.Embed(title=f"{user.display_name}'s Wallet", color=discord.Color.gold())
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Balance", value=fmt(balance), inline=True)
    if pending > 0:
        embed.add_field(name="Uncollected Income", value=fmt(pending), inline=True)
        embed.add_field(name="Total if Collected", value=fmt(balance + pending), inline=True)
    embed.set_footer(text=f"{guild_name} economy")
    return embed


class Economy(commands.Cog):
    """Per-server economy: balances, passive income, transfers, leaderboard, and games."""

    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db

    # ------------------------------------------------------------------ #
    #  Wallet commands
    # ------------------------------------------------------------------ #

    @app_commands.command(name="balance", description="Check your wallet balance.")
    @app_commands.describe(user="Check another member's balance (default: yourself).")
    async def balance(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        target = user or interaction.user
        data = await self.db.get_balance(target.id, interaction.guild_id)
        embed = wallet_embed(target, data["balance"], data["pending"], interaction.guild.name)
        await interaction.response.send_message(embed=embed, ephemeral=(user is None))

    @app_commands.command(
        name="collect",
        description=f"Collect passive income (+${PASSIVE_RATE} every {PASSIVE_INTERVAL // 60} min).",
    )
    async def collect(self, interaction: discord.Interaction) -> None:
        result = await self.db.collect_passive(interaction.user.id, interaction.guild_id)

        if result["collected"] == 0:
            await interaction.response.send_message(
                f"Nothing to collect yet. Next {fmt(PASSIVE_RATE)} in **{fmt_duration(result['next_in'])}**.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Income Collected!",
            description=(
                f"Collected **{fmt(result['collected'])}** in passive income.\n"
                f"New balance: **{fmt(result['balance'])}**\n"
                f"Next batch ready in: **{fmt_duration(result['next_in'])}**"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Passive income: {fmt(PASSIVE_RATE)} every {PASSIVE_INTERVAL // 60} min — no cap, collect whenever you like")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="transfer", description="Send money to another member.")
    @app_commands.describe(
        recipient="Member to send money to.",
        amount="Amount to send.",
    )
    async def transfer(
        self,
        interaction: discord.Interaction,
        recipient: discord.Member,
        amount: int,
    ) -> None:
        if amount <= 0:
            await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
            return
        if recipient.id == interaction.user.id:
            await interaction.response.send_message("You can't transfer to yourself.", ephemeral=True)
            return
        if recipient.bot:
            await interaction.response.send_message("You can't transfer to a bot.", ephemeral=True)
            return

        try:
            result = await self.db.transfer(
                interaction.user.id, recipient.id, interaction.guild_id, amount
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        embed = discord.Embed(
            title="Transfer Complete",
            description=(
                f"Sent **{fmt(amount)}** to {recipient.mention}.\n"
                f"Your new balance: **{fmt(result['from_balance'])}**"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------ #
    #  Leaderboard
    # ------------------------------------------------------------------ #

    @app_commands.command(name="leaderboard", description="Top 10 richest members in this server.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        rows = await self.db.leaderboard(interaction.guild_id, limit=10)

        if not rows:
            await interaction.followup.send("No one has a balance yet. Use `/balance` to create an account.")
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines: list[str] = []
        caller_rank: int | None = None

        for rank, row in enumerate(rows, start=1):
            if row["user_id"] == interaction.user.id:
                caller_rank = rank
            medal = medals.get(rank, f"`#{rank}`")
            member = interaction.guild.get_member(row["user_id"])
            name = member.display_name if member else f"<@{row['user_id']}>"
            lines.append(f"{medal} **{name}** — {fmt(row['balance'])}")

        embed = discord.Embed(
            title=f"🏦 {interaction.guild.name} — Rich List",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )

        if caller_rank:
            embed.set_footer(text=f"You are ranked #{caller_rank}")
        else:
            embed.set_footer(text="You are not in the top 10")

        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    #  Economy help
    # ------------------------------------------------------------------ #

    @app_commands.command(name="economy", description="How the economy system works.")
    async def economy_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="💰 Economy Guide",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Getting Started",
            value=(
                f"Every member starts with **{fmt(STARTING_BALANCE)}**.\n"
                "Your account is created automatically the first time you use any economy command."
            ),
            inline=False,
        )

        embed.add_field(
            name="Passive Income",
            value=(
                f"You earn **{fmt(PASSIVE_RATE)}** every **{PASSIVE_INTERVAL // 60} minutes** automatically.\n"
                "Income accumulates indefinitely — collect it all at once whenever you like."
            ),
            inline=False,
        )

        embed.add_field(
            name="Commands",
            value=(
                "`/balance` — view your wallet (or anyone else's)\n"
                "`/collect` — claim your passive income\n"
                "`/transfer @user amount` — send money to a member\n"
                "`/leaderboard` — top 10 richest in the server\n"
                "`/economy` — this help page"
            ),
            inline=False,
        )

        embed.add_field(
            name="Games",
            value=(
                f"`/coinflip heads/tails amount` — 50/50 bet, win **2×** your bet\n"
                f"Minimum bet: **{fmt(MIN_BET)}** — Maximum bet: **{fmt(MAX_BET)}**\n"
                "More games coming soon!"
            ),
            inline=False,
        )

        embed.set_footer(text="Balances are per-server — each server has its own economy.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Coin flip
    # ------------------------------------------------------------------ #

    @app_commands.command(name="coinflip", description="Bet on a coin flip — win 2× your bet.")
    @app_commands.describe(
        side="Which side to bet on.",
        amount=f"Amount to bet ({fmt(MIN_BET)}–{fmt(MAX_BET)}).",
    )
    @app_commands.choices(side=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def coinflip(
        self,
        interaction: discord.Interaction,
        side: app_commands.Choice[str],
        amount: int,
    ) -> None:
        if amount < MIN_BET:
            await interaction.response.send_message(
                f"Minimum bet is **{fmt(MIN_BET)}**.", ephemeral=True
            )
            return
        if amount > MAX_BET:
            await interaction.response.send_message(
                f"Maximum bet is **{fmt(MAX_BET)}**.", ephemeral=True
            )
            return

        data = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        if data["balance"] < amount:
            await interaction.response.send_message(
                f"You don't have enough. Balance: **{fmt(data['balance'])}**.", ephemeral=True
            )
            return

        result = random.choice(["heads", "tails"])
        won = result == side.value

        coin_emoji = "🪙"
        result_emoji = "👑" if result == "heads" else "🦅"

        if won:
            new_balance = await self.db.update_balance(
                interaction.user.id, interaction.guild_id, +amount
            )
            embed = discord.Embed(
                title=f"{coin_emoji} You Won!",
                description=(
                    f"The coin landed on **{result.capitalize()}** {result_emoji}\n"
                    f"You bet **{side.name}** — correct!\n\n"
                    f"**+{fmt(amount)}** → New balance: **{fmt(new_balance)}**"
                ),
                color=discord.Color.green(),
            )
        else:
            new_balance = await self.db.update_balance(
                interaction.user.id, interaction.guild_id, -amount
            )
            embed = discord.Embed(
                title=f"{coin_emoji} You Lost",
                description=(
                    f"The coin landed on **{result.capitalize()}** {result_emoji}\n"
                    f"You bet **{side.name}** — wrong!\n\n"
                    f"**-{fmt(amount)}** → New balance: **{fmt(new_balance)}**"
                ),
                color=discord.Color.red(),
            )

        embed.set_footer(text=f"Bet: {fmt(amount)} | House edge: none — true 50/50")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Economy(bot, db))
