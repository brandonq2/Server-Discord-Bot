import logging

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


def fmt_dollars(amount: int) -> str:
    return f"${amount:,}"


def fmt_duration(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    if minutes == 0:
        return f"{secs}s"
    return f"{minutes}m {secs}s"


def balance_embed(
    user: discord.User | discord.Member,
    balance: int,
    pending: int,
    guild_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{user.display_name}'s Wallet",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Balance", value=fmt_dollars(balance), inline=True)
    if pending > 0:
        embed.add_field(name="Uncollected Income", value=fmt_dollars(pending), inline=True)
        embed.add_field(
            name="Total if Collected",
            value=fmt_dollars(balance + pending),
            inline=True,
        )
    embed.set_footer(text=f"{guild_name} economy")
    return embed


class Economy(commands.Cog):
    """Per-server economy: balances, passive income, transfers, and leaderboard."""

    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db

    @app_commands.command(name="balance", description="Check your wallet balance.")
    @app_commands.describe(user="Check another member's balance (default: yourself).")
    async def balance(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        target = user or interaction.user
        data = await self.db.get_balance(target.id, interaction.guild_id)
        embed = balance_embed(
            target,
            data["balance"],
            data["pending"],
            interaction.guild.name,
        )
        await interaction.response.send_message(embed=embed, ephemeral=(user is None))

    @app_commands.command(
        name="collect",
        description=f"Collect your passive income (+{fmt_dollars(PASSIVE_RATE)} every {PASSIVE_INTERVAL // 60} min).",
    )
    async def collect(self, interaction: discord.Interaction) -> None:
        result = await self.db.collect_passive(interaction.user.id, interaction.guild_id)

        if result["collected"] == 0:
            next_in = fmt_duration(result["next_in"])
            await interaction.response.send_message(
                f"Nothing to collect yet. Next {fmt_dollars(PASSIVE_RATE)} in **{next_in}**.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Income Collected!",
            description=(
                f"You collected **{fmt_dollars(result['collected'])}** in passive income.\n"
                f"New balance: **{fmt_dollars(result['balance'])}**\n"
                f"Next collection available in: **{fmt_duration(result['next_in'])}**"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(
            text=f"Passive income: {fmt_dollars(PASSIVE_RATE)} every {PASSIVE_INTERVAL // 60} min"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="transfer", description="Send money to another member.")
    @app_commands.describe(
        recipient="The member to send money to.",
        amount="Amount to transfer (must be a positive whole number).",
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
            await interaction.response.send_message("You can't transfer money to yourself.", ephemeral=True)
            return
        if recipient.bot:
            await interaction.response.send_message("You can't transfer money to a bot.", ephemeral=True)
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
                f"Sent **{fmt_dollars(amount)}** to {recipient.mention}.\n"
                f"Your new balance: **{fmt_dollars(result['from_balance'])}**"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Top 10 richest members in this server.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        rows = await self.db.leaderboard(interaction.guild_id)

        if not rows:
            await interaction.followup.send("No balances recorded yet. Use `/balance` to start.")
            return

        embed = discord.Embed(
            title=f"{interaction.guild.name} — Rich List",
            color=discord.Color.gold(),
        )

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines: list[str] = []
        for rank, row in enumerate(rows, start=1):
            medal = medals.get(rank, f"`#{rank}`")
            user = self.bot.get_user(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            lines.append(f"{medal} **{name}** — {fmt_dollars(row['balance'])}")

        embed.description = "\n".join(lines)
        embed.set_footer(text="Balances update when members interact with the bot.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Economy(bot, db))
