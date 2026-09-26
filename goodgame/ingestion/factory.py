"""Construct a configured match-data provider."""

import os

from goodgame.ingestion.provider import MatchDataProvider
from goodgame.ingestion.sportmonks.provider import SportmonksProvider
from goodgame.ingestion.statsbomb.provider import StatsBombProvider


def create_provider(name: str | None = None) -> MatchDataProvider:
    selected = (name or os.environ.get("GOODGAME_PROVIDER", "sportmonks")).strip().casefold()
    if selected == "sportmonks":
        return SportmonksProvider()
    if selected == "statsbomb":
        return StatsBombProvider()
    raise ValueError(
        f"Unknown provider {selected!r}; choose 'sportmonks' or 'statsbomb'"
    )