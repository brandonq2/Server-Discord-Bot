import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE_PATH = PROJECT_ROOT / "data" / "mirrors.json"


@dataclass
class MirrorConfig:
    id: str
    source_channel_id: int
    destination_channel_id: int
    filter_bot_id: Optional[int] = None
    bots_only: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "MirrorConfig":
        return cls(
            id=data["id"],
            source_channel_id=int(data["source_channel_id"]),
            destination_channel_id=int(data["destination_channel_id"]),
            filter_bot_id=int(data["filter_bot_id"]) if data.get("filter_bot_id") else None,
            bots_only=bool(data.get("bots_only", True)),
        )


class MirrorStore:
    def __init__(self, path: Path = DEFAULT_STORE_PATH) -> None:
        self.path = path
        self._mirrors: list[MirrorConfig] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._mirrors = []
            return

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._mirrors = [MirrorConfig.from_dict(item) for item in raw.get("mirrors", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"mirrors": [asdict(mirror) for mirror in self._mirrors]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_all(self) -> list[MirrorConfig]:
        return list(self._mirrors)

    def get_for_source(self, source_channel_id: int) -> list[MirrorConfig]:
        return [mirror for mirror in self._mirrors if mirror.source_channel_id == source_channel_id]

    def add(
        self,
        source_channel_id: int,
        destination_channel_id: int,
        filter_bot_id: Optional[int] = None,
        bots_only: bool = True,
    ) -> MirrorConfig:
        mirror = MirrorConfig(
            id=uuid.uuid4().hex[:8],
            source_channel_id=source_channel_id,
            destination_channel_id=destination_channel_id,
            filter_bot_id=filter_bot_id,
            bots_only=bots_only,
        )
        self._mirrors.append(mirror)
        self.save()
        return mirror

    def remove(self, mirror_id: str) -> Optional[MirrorConfig]:
        for index, mirror in enumerate(self._mirrors):
            if mirror.id == mirror_id:
                removed = self._mirrors.pop(index)
                self.save()
                return removed
        return None

    def find_duplicate(
        self,
        source_channel_id: int,
        destination_channel_id: int,
        filter_bot_id: Optional[int],
    ) -> Optional[MirrorConfig]:
        for mirror in self._mirrors:
            if (
                mirror.source_channel_id == source_channel_id
                and mirror.destination_channel_id == destination_channel_id
                and mirror.filter_bot_id == filter_bot_id
            ):
                return mirror
        return None
