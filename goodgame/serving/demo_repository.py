"""Packaged demo-data repository for offline/friend testing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SNAPSHOT = Path(
    os.environ.get(
        "GOODGAME_DEMO_SNAPSHOT",
        Path(__file__).resolve().parents[2] / "demo_data" / "snapshot.json",
    )
)


class DemoServingRepository:
    def __init__(self, snapshot_path: str | Path = DEFAULT_SNAPSHOT) -> None:
        path = Path(snapshot_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Demo snapshot not found: {path}. Generate/copy demo_data/snapshot.json first."
            )
        self.data = json.loads(path.read_text())

    def list_competitions(self) -> list[dict[str, Any]]:
        return list(self.data.get("competitions", []))

    def list_seasons(self, competition_id: int) -> list[dict[str, Any]]:
        return [
            row for row in self.data.get("seasons", [])
            if int(row.get("competition_id", -1)) == competition_id
        ]

    def list_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        return [
            row for row in self.data.get("matches", [])
            if int(row.get("competition_id", -1)) == competition_id
            and int(row.get("season_id", -1)) == season_id
        ]

    def list_teams(self, season_id: int, competition_id: int | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self.data.get("teams", [])
            if int(row.get("season_id", -1)) == season_id
            and (competition_id is None or int(row.get("competition_id", -1)) == competition_id)
        ]

    def list_players(self, season_id: int, competition_id: int | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self.data.get("players", [])
            if int(row.get("season_id", -1)) == season_id
            and (competition_id is None or int(row.get("competition_id", -1)) == competition_id)
        ]

    def search_entities(
        self,
        query: str,
        season_id: int | None = None,
        league_id: int | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        normalized = query.strip().casefold()
        if len(normalized) < 2:
            return []

        results: list[dict[str, Any]] = []
        for row in self.data.get("teams", []):
            name = str(row.get("name") or "")
            if normalized in name.casefold() and (
                season_id is None or int(row.get("season_id", -1)) == season_id
            ) and (
                league_id is None or int(row.get("competition_id", -1)) == league_id
            ):
                results.append({
                    "entity_type": "team",
                    "id": row.get("id"),
                    "name": name,
                    "subtitle": row.get("short_code"),
                    "image": row.get("image_path"),
                    "league_id": row.get("competition_id"),
                    "season_id": row.get("season_id"),
                })

        for row in self.data.get("players", []):
            name = str(row.get("name") or "")
            if normalized in name.casefold() and (
                season_id is None or int(row.get("season_id", -1)) == season_id
            ) and (
                league_id is None or int(row.get("competition_id", -1)) == league_id
            ):
                results.append({
                    "entity_type": "player",
                    "id": row.get("id"),
                    "name": name,
                    "subtitle": str(row.get("position_id") or ""),
                    "image": row.get("image_path"),
                    "league_id": row.get("competition_id"),
                    "season_id": row.get("season_id"),
                })

        results.sort(
            key=lambda row: (
                0 if str(row.get("name") or "").casefold() == normalized else 1,
                str(row.get("name") or "").casefold(),
            )
        )
        return results[: max(1, min(limit, 20))]

    def get_game_view(self, fixture_id: int) -> dict[str, Any]:
        value = self.data.get("game_views", {}).get(str(fixture_id))
        if value is None:
            raise LookupError(f"Fixture {fixture_id} is not packaged in the demo snapshot")
        result = dict(value)
        result.setdefault("head_to_head", [])
        return result

    def get_team_view(self, team_id: int, season_id: int, league_id: int | None = None) -> dict[str, Any]:
        key = f"{team_id}:{season_id}:{league_id or 'all'}"
        value = self.data.get("team_views", {}).get(key)
        if value is None:
            fallback = f"{team_id}:{season_id}:all"
            value = self.data.get("team_views", {}).get(fallback)
        if value is None:
            raise LookupError(f"Team {team_id} is not packaged in the demo snapshot")
        return value

    def get_player_view(self, player_id: int, season_id: int, league_id: int | None = None) -> dict[str, Any]:
        key = f"{player_id}:{season_id}:{league_id or 'all'}"
        value = self.data.get("player_views", {}).get(key)
        if value is None:
            fallback = f"{player_id}:{season_id}:all"
            value = self.data.get("player_views", {}).get(fallback)
        if value is None:
            raise LookupError(f"Player {player_id} is not packaged in the demo snapshot")
        return value

    def get_similar_players(
        self,
        player_id: int,
        season_id: int,
        league_id: int | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        return []

    def get_similar_teams(
        self,
        team_id: int,
        season_id: int,
        league_id: int | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        return []

