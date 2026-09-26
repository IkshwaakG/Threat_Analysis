"""Provider contract for normalized match data."""

from abc import ABC, abstractmethod
from typing import Any

from goodgame.models.event import Event
from goodgame.models.match import Match


class MatchDataProvider(ABC):
    @abstractmethod
    def get_match(self, match_id: int) -> Match:
        """Return normalized metadata for one match."""

    @abstractmethod
    def get_events(self, match_id: int) -> list[Event]:
        """Return normalized events for one match."""

    def get_lineups(self, match_id: int) -> dict[str, Any]:
        return {}

    def get_shot_map(self, match_id: int) -> list[dict[str, Any]]:
        return []