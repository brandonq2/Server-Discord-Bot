import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: Optional[int] = None


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ValueError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your token.")

    guild_id: Optional[int] = None
    guild_id_raw = os.getenv("GUILD_ID", "").strip()
    if guild_id_raw:
        guild_id = int(guild_id_raw)

    return Config(token=token, guild_id=guild_id)
