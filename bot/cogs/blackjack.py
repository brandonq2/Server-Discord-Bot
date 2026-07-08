import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from bot.economy_db import EconomyDB

logger = logging.getLogger(__name__)

MIN_BET = 10
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
VALUES = {
    "A": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10,
}


def new_deck() -> list[tuple[str, str]]:
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def hand_value(hand: list[tuple[str, str]]) -> int:
    total = sum(VALUES[r] for r, _ in hand)
    aces = sum(1 for r, _ in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def fmt_hand(hand: list[tuple[str, str]], hide_hole: bool = False) -> str:
    if hide_hole and len(hand) >= 2:
        return f"`{hand[0][0]}{hand[0][1]}` `🂠`"
    return " ".join(f"`{r}{s}`" for r, s in hand)


def is_blackjack(hand: list[tuple[str, str]]) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


class BlackjackGame:
    def __init__(self, bet: int, user_id: int, guild_id: int) -> None:
        self.bet = bet
        self.user_id = user_id
        self.guild_id = guild_id
        self.deck = new_deck()
        self.player: list[tuple[str, str]] = [self.deck.pop(), self.deck.pop()]
        self.dealer: list[tuple[str, str]] = [self.deck.pop(), self.deck.pop()]
        self.first_action = True

    def hit(self) -> None:
        self.player.append(self.deck.pop())
        self.first_action = False

    def dealer_play(self) -> None:
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())

    def resolve(self) -> tuple[str, int]:
        """Returns (result_key, payout). Payout is amount returned to player (0 = lose all)."""
        pv = hand_value(self.player)

        if pv > 21:
            return "bust", 0

        if is_blackjack(self.player) and not is_blackjack(self.dealer):
            return "blackjack", int(self.bet * 2.5)  # 3:2 payout

        self.dealer_play()
        dv = hand_value(self.dealer)

        if is_blackjack(self.dealer) and not is_blackjack(self.player):
            return "dealer_bj", 0

        if dv > 21 or pv > dv:
            return "win", self.bet * 2
        elif pv == dv:
            return "push", self.bet
        else:
            return "lose", 0


def build_embed(
    game: BlackjackGame,
    hide_hole: bool = True,
    result: str = "",
    payout: int = 0,
) -> discord.Embed:
    pv = hand_value(game.player)
    dv_display = "?" if hide_hole else str(hand_value(game.dealer))

    COLORS = {
        "blackjack": discord.Color.gold(),
        "win": discord.Color.green(),
        "push": discord.Color.greyple(),
        "bust": discord.Color.red(),
        "lose": discord.Color.red(),
        "dealer_bj": discord.Color.red(),
    }
    TITLES = {
        "blackjack": "🃏 Blackjack! Natural 21!",
        "win": "✅ You Win!",
        "push": "🤝 Push — Tie!",
        "bust": "💥 Bust! Over 21",
        "lose": "❌ You Lose",
        "dealer_bj": "❌ Dealer Blackjack!",
    }

    color = COLORS.get(result, discord.Color.blurple())
    title = TITLES.get(result, "🃏 Blackjack")
    embed = discord.Embed(title=title, color=color)

    embed.add_field(name=f"Your Hand  [{pv}]", value=fmt_hand(game.player), inline=False)
    embed.add_field(name=f"Dealer's Hand  [{dv_display}]", value=fmt_hand(game.dealer, hide_hole=hide_hole), inline=False)
    embed.add_field(name="Bet", value=f"${game.bet:,}", inline=True)

    if result:
        profit = payout - game.bet
        if result == "push":
            embed.add_field(name="Result", value="Returned your bet", inline=True)
        elif payout > 0:
            embed.add_field(name="Result", value=f"+${profit:,}", inline=True)
        else:
            embed.add_field(name="Result", value=f"-${game.bet:,}", inline=True)
    else:
        embed.set_footer(text="Hit to draw a card • Stand to end your turn • Double to double your bet and draw once")

    return embed


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Blackjack", game: BlackjackGame) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == "⚡ Double":
                item.disabled = not self.game.first_action

    async def _finish(self, interaction: discord.Interaction) -> None:
        result, payout = self.game.resolve()
        if payout > 0:
            await self.cog.db.update_balance(self.game.user_id, self.game.guild_id, payout)
        self.cog.active_games.pop(self.game.user_id, None)
        for item in self.children:
            item.disabled = True
        embed = build_embed(self.game, hide_hole=False, result=result, payout=payout)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _auto_finish_if_done(self, interaction: discord.Interaction) -> bool:
        pv = hand_value(self.game.player)
        if pv > 21 or pv == 21:
            await self._finish(interaction)
            return True
        return False

    @discord.ui.button(label="👆 Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        self.game.hit()
        if await self._auto_finish_if_done(interaction):
            return
        self._refresh_buttons()
        embed = build_embed(self.game)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        await self._finish(interaction)

    @discord.ui.button(label="⚡ Double", style=discord.ButtonStyle.danger)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        data = await self.cog.db.get_balance(self.game.user_id, self.game.guild_id)
        if data["balance"] < self.game.bet:
            await interaction.response.send_message("Not enough funds to double down!", ephemeral=True)
            return
        await self.cog.db.update_balance(self.game.user_id, self.game.guild_id, -self.game.bet)
        self.game.bet *= 2
        self.game.hit()
        await self._finish(interaction)

    async def on_timeout(self) -> None:
        self.cog.active_games.pop(self.game.user_id, None)
        for item in self.children:
            item.disabled = True


class Blackjack(commands.Cog):
    def __init__(self, bot: commands.Bot, db: EconomyDB) -> None:
        self.bot = bot
        self.db = db
        self.active_games: dict[int, BlackjackGame] = {}

    @app_commands.command(name="blackjack", description="Play a hand of Blackjack against the dealer.")
    @app_commands.describe(bet="Amount to bet.")
    async def blackjack(self, interaction: discord.Interaction, bet: int) -> None:
        if bet < MIN_BET:
            await interaction.response.send_message(f"Minimum bet is ${MIN_BET:,}.", ephemeral=True)
            return
        if interaction.user.id in self.active_games:
            await interaction.response.send_message("You already have a game in progress!", ephemeral=True)
            return

        data = await self.db.get_balance(interaction.user.id, interaction.guild_id)
        if data["balance"] < bet:
            await interaction.response.send_message(
                f"Insufficient funds. Balance: ${data['balance']:,}", ephemeral=True
            )
            return

        await self.db.update_balance(interaction.user.id, interaction.guild_id, -bet)
        game = BlackjackGame(bet=bet, user_id=interaction.user.id, guild_id=interaction.guild_id)

        # Instant blackjack on deal
        if is_blackjack(game.player):
            result, payout = game.resolve()
            if payout > 0:
                await self.db.update_balance(interaction.user.id, interaction.guild_id, payout)
            embed = build_embed(game, hide_hole=False, result=result, payout=payout)
            await interaction.response.send_message(embed=embed)
            return

        self.active_games[interaction.user.id] = game
        view = BlackjackView(self, game)
        embed = build_embed(game)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    db: EconomyDB = bot.economy_db  # type: ignore[attr-defined]
    await bot.add_cog(Blackjack(bot, db))
