import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.economy_db import EconomyDB

logger = logging.getLogger(__name__)

MIN_BET = 10
MAX_BET = 500_000

# (emoji, display name, reel weight, 3-match multiplier)
REEL_DATA = [
    ("🍒", "Cherry",   36,   3),
    ("🍋", "Lemon",    28,   4),
    ("🍊", "Orange",   20,   5),
    ("🍇", "Grapes",   14,   8),
    ("🔔", "Bell",      8,  12),
    ("⭐", "Star",      5,  25),
    ("💎", "Diamond",   2,  75),
    ("7️⃣", "777",       1, 200),
]

EMOJIS  = [r[0] for r in REEL_DATA]
WEIGHTS = [r[2] for r in REEL_DATA]
PAYOUTS = {r[0]: r[3] for r in REEL_DATA}
NAMES   = {r[0]: r[1] for r in REEL_DATA}

SPIN = "🎰"

# Two-of-a-kind gives a partial return on these symbols
TWO_OF_A_KIND_REFUND = {
    "⭐": 0.25,   # refund 25% of bet
    "💎": 0.50,
    "7️⃣": 0.75,
}


def spin_reels() -> list[str]:
    return random.choices(EMOJIS, weights=WEIGHTS, k=3)


def evaluate(reels: list[str], bet: int) -> tuple[str, int]:
    """Returns (result_key, payout). Payout is amount returned to player."""
    a, b, c = reels

    if a == b == c:
        label = "jackpot" if a == "7️⃣" else "three_of_a_kind"
        return label, bet * PAYOUTS[a]

    # Two of a kind on a premium symbol
    counts = {s: reels.count(s) for s in set(reels)}
    for symbol, count in counts.items():
        if count == 2 and symbol in TWO_OF_A_KIND_REFUND:
            refund = int(bet * TWO_OF_A_KIND_REFUND[symbol])
            return "two_of_a_kind", refund

    return "lose", 0


def fmt_reels(reels: list[str], revealed: int) -> str:
    parts = [f"[ {reels[i]} ]" if i < revealed else f"[ {SPIN} ]" for i in range(3)]
    return "  ".join(parts)


def build_embed(
    reels: list[str],
    revealed: int,
    bet: int,
    result: str = "",
    payout: int = 0,
) -> discord.Embed:
    display = fmt_reels(reels, revealed)
    finished = revealed == 3

    if not finished:
        color = discord.Color.blurple()
        title = "🎰  Spinning..."
    elif result == "jackpot":
        color = discord.Color.gold()
        title = "🎰  J A C K P O T !!!"
    elif result == "three_of_a_kind":
        color = discord.Color.green()
        title = f"🎰  Three {NAMES[reels[0]]}s — Winner!"
    elif result == "two_of_a_kind":
        color = discord.Color.yellow()
        title = f"🎰  Two {NAMES[next(s for s in reels if reels.count(s) == 2)]}s — Partial Refund"
    else:
        color = discord.Color.red()
        title = "🎰  No Match"

    embed = discord.Embed(title=title, color=color)

    # Large reel display
    embed.add_field(name="\u200b", value=f"## {display}", inline=False)

    if finished:
        profit = payout - bet
        if result in ("jackpot", "three_of_a_kind"):
            embed.add_field(name="Won", value=f"**+${profit:,}**", inline=True)
        elif result == "two_of_a_kind":
            embed.add_field(name="Refunded", value=f"${payout:,}", inline=True)
            embed.add_field(name="Lost", value=f"−${bet - payout:,}", inline=True)
        else:
            embed.add_field(name="Lost", value=f"−${bet:,}", inline=True)
        embed.add_field(name="Bet", value=f"${bet:,}", inline=True)

        if result == "jackpot":
            embed.set_footer(text="🌟 You hit the jackpot! 200× your bet!")
        elif result == "three_of_a_kind":
            embed.set_footer(text=f"{PAYOUTS[reels[0]]}× payout on {NAMES[reels[0]]}")
        elif result == "two_of_a_kind":
            sym = next(s for s in reels if reels.count(s) == 2)
            embed.set_footer(text=f"Two {NAMES[sym]}s — partial refund of {int(TWO_OF_A_KIND_REFUND[sym]*100)}%")
        else:
            embed.set_footer(text="Use /slots paytable to see all payouts")
    else:
        embed.set_footer(text=f"Bet: ${bet:,}")

    return embed


def paytable_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎰  Slot Machine — Paytable",
        color=discord.Color.blurple(),
    )
    lines = []
    for emoji, name, _, mult in REEL_DATA:
        lines.append(f"{emoji} {emoji} {emoji}  →  **{mult}×**  _{name}_")
    embed.add_field(name="Three of a Kind", value="\n".join(lines), inline=False)

    premium_lines = []
    for sym, pct in TWO_OF_A_KIND_REFUND.items():
        premium_lines.append(f"{sym} {sym} ??  →  **{int(pct*100)}% refund**")
    embed.add_field(name="Two of a Kind (premium only)", value="\n".join(premium_lines), inline=False)
    embed.set_footer(text="All other combos = loss • Min bet $10 • Max bet $500,000")
    return embed


class Slots(commands.Cog):
    """Slot machine casino game."""

    slots_group = app_commands.Group(
        name="slots",
        description="Play the slot machine.",
    )

    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db

    @slots_group.command(name="spin", description="Spin the slot machine.")
    @app_commands.describe(bet="Amount to bet.")
    async def spin(self, interaction: discord.Interaction, bet: int) -> None:
        if bet < MIN_BET:
            await interaction.response.send_message(f"Minimum bet is ${MIN_BET:,}.", ephemeral=True)
            return
        if bet > MAX_BET:
            await interaction.response.send_message(f"Maximum bet is ${MAX_BET:,}.", ephemeral=True)
            return

        data = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        if data["balance"] < bet:
            await interaction.response.send_message(
                f"Insufficient funds. Balance: ${data['balance']:,}", ephemeral=True
            )
            return

        await self.db.update_balance(interaction.user.id, interaction.guild_id, -bet)

        reels = spin_reels()
        result, payout = evaluate(reels, bet)

        # Send spinning state
        await interaction.response.send_message(embed=build_embed(reels, 0, bet))

        # Reveal each reel with a delay
        for revealed in range(1, 4):
            await asyncio.sleep(0.85)
            if revealed < 3:
                await interaction.edit_original_response(embed=build_embed(reels, revealed, bet))

        # Final reveal with result
        await asyncio.sleep(0.85)
        if payout > 0:
            await self.db.update_balance(interaction.user.id, interaction.guild_id, payout)
        await interaction.edit_original_response(
            embed=build_embed(reels, 3, bet, result=result, payout=payout)
        )

    @slots_group.command(name="paytable", description="Show all slot machine payouts.")
    async def paytable(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=paytable_embed(), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Slots(bot, db))
