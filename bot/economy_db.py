"""Async SQLite database for the per-guild economy system."""

import time
from pathlib import Path
from typing import Optional

import aiosqlite

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "economy.db"

STARTING_BALANCE = 10_000
PASSIVE_RATE = 50           # dollars per interval
PASSIVE_INTERVAL = 15 * 60  # seconds (15 minutes)
MAX_PASSIVE_HOURS = 24       # passive income caps after this many hours idle
MAX_PASSIVE = int(MAX_PASSIVE_HOURS * 3600 / PASSIVE_INTERVAL) * PASSIVE_RATE


class EconomyDB:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id     INTEGER NOT NULL,
                guild_id    INTEGER NOT NULL,
                balance     INTEGER NOT NULL DEFAULT 10000,
                last_collected INTEGER NOT NULL,
                created_at  INTEGER NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self._db.commit()

    async def _ensure_account(self, user_id: int, guild_id: int) -> None:
        now = int(time.time())
        await self._db.execute("""
            INSERT OR IGNORE INTO balances (user_id, guild_id, balance, last_collected, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, STARTING_BALANCE, now, now))
        await self._db.commit()

    def _pending_passive(self, last_collected: int) -> int:
        elapsed = int(time.time()) - last_collected
        intervals = elapsed // PASSIVE_INTERVAL
        return min(intervals * PASSIVE_RATE, MAX_PASSIVE)

    async def get_balance(self, user_id: int, guild_id: int) -> dict:
        await self._ensure_account(user_id, guild_id)
        async with self._db.execute(
            "SELECT balance, last_collected FROM balances WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cursor:
            row = await cursor.fetchone()

        pending = self._pending_passive(row["last_collected"])
        return {
            "balance": row["balance"],
            "pending": pending,
            "last_collected": row["last_collected"],
        }

    async def collect_passive(self, user_id: int, guild_id: int) -> dict:
        await self._ensure_account(user_id, guild_id)
        async with self._db.execute(
            "SELECT balance, last_collected FROM balances WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cursor:
            row = await cursor.fetchone()

        pending = self._pending_passive(row["last_collected"])
        if pending == 0:
            next_in = PASSIVE_INTERVAL - ((int(time.time()) - row["last_collected"]) % PASSIVE_INTERVAL)
            return {"collected": 0, "balance": row["balance"], "next_in": next_in}

        now = int(time.time())
        intervals_used = pending // PASSIVE_RATE
        new_last = row["last_collected"] + intervals_used * PASSIVE_INTERVAL
        new_balance = row["balance"] + pending

        await self._db.execute("""
            UPDATE balances SET balance=?, last_collected=?
            WHERE user_id=? AND guild_id=?
        """, (new_balance, new_last, user_id, guild_id))
        await self._db.commit()

        next_in = PASSIVE_INTERVAL - ((now - new_last) % PASSIVE_INTERVAL)
        return {"collected": pending, "balance": new_balance, "next_in": next_in}

    async def update_balance(self, user_id: int, guild_id: int, delta: int) -> int:
        """Add (or subtract) delta from a user's balance. Returns new balance. Raises ValueError if insufficient funds."""
        await self._ensure_account(user_id, guild_id)
        async with self._db.execute(
            "SELECT balance FROM balances WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cursor:
            row = await cursor.fetchone()

        new_balance = row["balance"] + delta
        if new_balance < 0:
            raise ValueError(f"Insufficient funds. Balance: ${row['balance']:,}")

        await self._db.execute(
            "UPDATE balances SET balance=? WHERE user_id=? AND guild_id=?",
            (new_balance, user_id, guild_id),
        )
        await self._db.commit()
        return new_balance

    async def transfer(self, from_user: int, to_user: int, guild_id: int, amount: int) -> dict:
        await self._ensure_account(from_user, guild_id)
        await self._ensure_account(to_user, guild_id)

        async with self._db.execute(
            "SELECT balance FROM balances WHERE user_id=? AND guild_id=?",
            (from_user, guild_id),
        ) as cursor:
            row = await cursor.fetchone()

        if row["balance"] < amount:
            raise ValueError(f"Insufficient funds. You have ${row['balance']:,}.")

        await self._db.execute(
            "UPDATE balances SET balance=balance-? WHERE user_id=? AND guild_id=?",
            (amount, from_user, guild_id),
        )
        await self._db.execute(
            "UPDATE balances SET balance=balance+? WHERE user_id=? AND guild_id=?",
            (amount, to_user, guild_id),
        )
        await self._db.commit()

        async with self._db.execute(
            "SELECT balance FROM balances WHERE user_id=? AND guild_id=?",
            (from_user, guild_id),
        ) as cursor:
            from_row = await cursor.fetchone()

        return {"from_balance": from_row["balance"], "amount": amount}

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        async with self._db.execute("""
            SELECT user_id, balance FROM balances
            WHERE guild_id=?
            ORDER BY balance DESC
            LIMIT ?
        """, (guild_id, limit)) as cursor:
            rows = await cursor.fetchall()
        return [{"user_id": row["user_id"], "balance": row["balance"]} for row in rows]
