import asyncio
import io
import logging
import random

import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from discord import app_commands
from discord.ext import commands

from bot.economy_db import EconomyDB

logger = logging.getLogger(__name__)

MIN_BET = 10
MAX_BET = 1_000_000
TICK_INTERVAL = 2        # seconds between price updates
MIN_CRASH_TICK = 3       # crash no sooner than 3 ticks (6s)
MAX_CRASH_TICK = 15      # crash no later than 15 ticks (30s)

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(prices: list[float]) -> str:
    if len(prices) <= 1:
        return SPARK_CHARS[0]
    mn, mx = min(prices), max(prices)
    span = mx - mn or 0.001
    return "".join(
        SPARK_CHARS[min(7, int((p - mn) / span * 7.99))]
        for p in prices[-28:]
    )


def generate_curve(crash_tick: int) -> list[float]:
    """Pre-generate the full price curve. Index crash_tick+1 is the crash (0.0).

    Behaviour categories (chosen at game start):
      - 'bull'   (~40%): generally rises, can dip sharply but recovers
      - 'bear'   (~30%): starts dropping, may never break 1x
      - 'choppy' (~30%): large swings in either direction, very unpredictable
    """
    category = random.choices(["bull", "bear", "choppy"], weights=[40, 30, 30])[0]

    prices = [1.0]
    for i in range(crash_tick):
        prev = prices[-1]

        if category == "bull":
            drift = random.uniform(0.02, 0.09)
            # occasional sharp dips (~20% chance per tick)
            if random.random() < 0.20:
                shock = random.uniform(-0.18, -0.08)
            else:
                shock = random.uniform(-0.05, 0.05)
            noise = drift + shock

        elif category == "bear":
            # overall downward trend
            drift = random.uniform(-0.08, 0.01)
            # occasional spikes up to tease the player (~15% chance)
            if random.random() < 0.15:
                shock = random.uniform(0.06, 0.14)
            else:
                shock = random.uniform(-0.06, 0.03)
            noise = drift + shock

        else:  # choppy
            drift = random.uniform(-0.04, 0.06)
            # large random swings every tick
            shock = random.uniform(-0.15, 0.15)
            noise = drift + shock

        next_price = prev * (1 + noise)
        prices.append(max(0.02, next_price))

    prices.append(0.0)  # crash
    return prices


def render_chart(
    curve: list[float],
    crash_tick: int,
    cash_tick: int | None,
    bet: int,
) -> io.BytesIO:
    """Generate a dark-themed stock chart as a PNG in a BytesIO buffer."""
    fig, ax = plt.subplots(figsize=(9, 4), facecolor="#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    pre = curve[:crash_tick + 1]
    x_pre = list(range(len(pre)))

    # Green line up to crash
    ax.plot(x_pre, pre, color="#00e676", linewidth=2.5, zorder=3)
    ax.fill_between(x_pre, pre, alpha=0.15, color="#00e676")

    # Red crash drop
    ax.plot(
        [crash_tick, crash_tick + 0.5],
        [curve[crash_tick], 0.0],
        color="#ff1744", linewidth=2.5, linestyle="--", zorder=3,
    )
    ax.scatter([crash_tick], [curve[crash_tick]], color="#ff1744", s=80, zorder=5)
    ax.annotate(
        "💥 CRASH",
        (crash_tick, curve[crash_tick]),
        xytext=(6, 8), textcoords="offset points",
        color="#ff1744", fontsize=9, fontweight="bold",
    )

    # Gold star for cash-out
    if cash_tick is not None:
        cp = curve[cash_tick]
        ax.scatter([cash_tick], [cp], color="#ffd600", s=160, marker="*", zorder=6)
        ax.annotate(
            f"★ SOLD\n{cp:.2f}x",
            (cash_tick, cp),
            xytext=(6, -24), textcoords="offset points",
            color="#ffd600", fontsize=9, fontweight="bold",
        )

    # Break-even reference
    ax.axhline(y=1.0, color="#555566", linewidth=1, linestyle=":", alpha=0.8)
    ax.text(
        0.01, 1.02, "1.00x  break-even",
        transform=ax.get_yaxis_transform(),
        color="#555566", fontsize=8,
    )

    # Axes styling
    ax.set_xlabel("Time", color="#888899", fontsize=9)
    ax.set_ylabel("Multiplier", color="#888899", fontsize=9)
    ax.set_title(
        f"📈  MAPLE CORP STONKS —  Invested ${bet:,}",
        color="#ffffff", fontsize=12, fontweight="bold", pad=10,
    )
    ax.tick_params(colors="#888899", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#333344")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2fx"))
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


class StockGame:
    def __init__(self, user_id: int, guild_id: int, bet: int) -> None:
        self.user_id = user_id
        self.guild_id = guild_id
        self.bet = bet
        self.tick = 0
        self.cashed_out = False
        self.crashed = False
        self.cash_tick: int | None = None
        self.crash_tick = random.randint(MIN_CRASH_TICK, MAX_CRASH_TICK)
        self.curve = generate_curve(self.crash_tick)

    @property
    def price(self) -> float:
        return self.curve[min(self.tick, len(self.curve) - 1)]

    @property
    def value(self) -> int:
        return int(self.bet * self.price)

    @property
    def profit(self) -> int:
        return self.value - self.bet

    @property
    def history(self) -> list[float]:
        return self.curve[:self.tick + 1]


class StockView(discord.ui.View):
    def __init__(self, game: StockGame) -> None:
        super().__init__(timeout=MAX_CRASH_TICK * TICK_INTERVAL + 10)
        self.game = game

    @discord.ui.button(label="💰  Sell Shares", style=discord.ButtonStyle.green)
    async def sell(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        if self.game.cashed_out or self.game.crashed:
            await interaction.response.send_message("The game is already over.", ephemeral=True)
            return

        self.game.cashed_out = True
        self.game.cash_tick = self.game.tick
        button.disabled = True
        button.label = "✅  Sold!"
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


def live_embed(game: StockGame) -> discord.Embed:
    spark = sparkline(game.history)
    sign = "+" if game.profit >= 0 else ""
    color = discord.Color.green() if game.price >= 1.0 else discord.Color.orange()

    embed = discord.Embed(title="📈  STOCKS INC — LIVE", color=color)
    embed.add_field(name="Price", value=f"`{game.price:.3f}x`", inline=True)
    embed.add_field(name="Value", value=f"${game.value:,}", inline=True)
    embed.add_field(name="P/L", value=f"`{sign}${game.profit:,}`", inline=True)
    embed.add_field(name="Chart", value=f"`{spark}`", inline=False)
    embed.set_footer(text=f"Invested ${game.bet:,} · Sell before it crashes!")
    return embed


def result_embed(game: StockGame, payout: int) -> discord.Embed:
    spark = sparkline(game.curve[:game.crash_tick + 1])
    profit = payout - game.bet

    if game.cashed_out:
        color = discord.Color.green() if profit >= 0 else discord.Color.orange()
        title = "📤  Shares Sold!"
        sell_price = game.curve[game.cash_tick]
        body = (
            f"Sold at **{sell_price:.3f}x** — "
            f"{'profit' if profit >= 0 else 'loss'} of "
            f"**{'+'if profit >= 0 else ''}{profit:,}**\n"
            f"Received: **${payout:,}**"
        )
    else:
        color = discord.Color.red()
        title = "💥  Stock Crashed!"
        body = f"You didn't sell in time. Lost **${game.bet:,}**."

    embed = discord.Embed(title=title, description=body, color=color)
    embed.add_field(name="Peak Price", value=f"`{max(game.curve[:game.crash_tick+1]):.3f}x`", inline=True)
    embed.add_field(name="Duration", value=f"{game.crash_tick * TICK_INTERVAL}s", inline=True)
    embed.add_field(name="Full Chart", value=f"`{spark}`", inline=False)
    embed.set_footer(text="Full chart attached below ↓")
    return embed


class Stocks(commands.Cog):
    """Stock crash investing mini-game."""

    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db
        self.active_games: dict[int, StockGame] = {}

    @app_commands.command(
        name="stock",
        description="Invest in a volatile stock — the price rises until it suddenly crashes to $0!",
    )
    @app_commands.describe(amount="How much to invest.")
    async def stock(self, interaction: discord.Interaction, amount: int) -> None:
        if amount < MIN_BET:
            await interaction.response.send_message(f"Minimum investment is ${MIN_BET:,}.", ephemeral=True)
            return
        if amount > MAX_BET:
            await interaction.response.send_message(f"Maximum investment is ${MAX_BET:,}.", ephemeral=True)
            return
        if interaction.user.id in self.active_games:
            await interaction.response.send_message(
                "You already have an active stock game! Wait for it to finish.", ephemeral=True
            )
            return

        data = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        if data["balance"] < amount:
            await interaction.response.send_message(
                f"Insufficient funds. Balance: ${data['balance']:,}", ephemeral=True
            )
            return

        await self.db.update_balance(interaction.user.id, interaction.guild_id, -amount)

        game = StockGame(user_id=interaction.user.id, guild_id=interaction.guild_id, bet=amount)
        self.active_games[interaction.user.id] = game

        view = StockView(game)
        await interaction.response.send_message(embed=live_embed(game), view=view)
        asyncio.create_task(self._run_game(interaction, game, view))

    async def _run_game(
        self, interaction: discord.Interaction, game: StockGame, view: StockView
    ) -> None:
        try:
            while game.tick < game.crash_tick:
                await asyncio.sleep(TICK_INTERVAL)

                if game.cashed_out:
                    break

                game.tick += 1

                # Live embed update every tick
                if not game.cashed_out:
                    try:
                        await interaction.edit_original_response(embed=live_embed(game))
                    except discord.HTTPException:
                        pass

            if not game.cashed_out:
                game.crashed = True
                game.tick = game.crash_tick

            # Calculate payout
            if game.cashed_out:
                payout = int(game.bet * game.curve[game.cash_tick])
                await self.db.update_balance(game.user_id, game.guild_id, payout)
            else:
                payout = 0

            # Disable button and show result
            for item in view.children:
                item.disabled = True
            try:
                await interaction.edit_original_response(
                    embed=result_embed(game, payout), view=view
                )
            except discord.HTTPException:
                pass

            # Send final matplotlib chart
            try:
                buf = await asyncio.to_thread(
                    render_chart,
                    game.curve,
                    game.crash_tick,
                    game.cash_tick,
                    game.bet,
                )
                await interaction.followup.send(file=discord.File(buf, filename="stock_chart.png"))
            except Exception:
                logger.exception("Failed to generate stock chart for user %s", game.user_id)

        except Exception:
            logger.exception("Unhandled error in stock game for user %s", game.user_id)
        finally:
            self.active_games.pop(game.user_id, None)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Stocks(bot, db))
