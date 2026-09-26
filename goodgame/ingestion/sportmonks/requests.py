"""Sportmonks Football API v3 request definitions.

This module owns endpoint paths, full include chains, filters, and pagination.
Response normalization belongs in responses.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from goodgame.ingestion.sportmonks.client import SportmonksClient


# Keep the include strings explicit. These are intentionally detailed because
# Sportmonks returns substantially richer nested payloads when includes are
# requested. Some fields still depend on subscription/competition coverage.
FIXTURE_INCLUDES = (
    "sport;round;stage;group;aggregate;league;season;coaches;tvStations;venue;"
    "state;weatherReport;lineups;lineups.player;lineups.position;"
    "lineups.detailedPosition;lineups.details.type;lineups.xGLineup;"
    "events;events.player;events.relatedPlayer;events.type;events.period;"
    "timeline;comments;trends;statistics;statistics.type;periods;participants;"
    "prematchNews;postmatchNews;metadata;sidelined;sidelined.sideline.player;"
    "sidelined.sideline.type;referees;formations;ballCoordinates;scores;"
    "xGFixture;pressure;expectedLineups"
)

PLAYER_INCLUDES = (
    "nationality;position;detailedPosition;metadata;teams;teams.team;"
    "statistics;statistics.details.type;statistics.team;"
    "statistics.season;statistics.season.league;latest;latest.fixture;"
    "latest.fixture.participants;latest.fixture.league;latest.fixture.scores;"
    "latest.details.type;trophies;trophies.trophy;trophies.team;"
    "trophies.league;trophies.season"
)

TEAM_INCLUDES = (
    "country;venue;coach;coaches;players;seasons;activeSeasons;latest;upcoming;"
    "statistics;statistics.details.type;sidelined;sidelined.sideline.player;"
    "sidelined.sideline.type;trophies;trophies.trophy;rivals"
)

LEAGUE_INCLUDES = (
    "country;currentSeason;seasons;latest;upcoming;today;stages"
)

SEASON_INCLUDES = (
    "league;stages;rounds;groups;fixtures;fixtures.participants;"
    "fixtures.scores;fixtures.state"
)

SQUAD_INCLUDES = (
    "player;position;detailedPosition;details.type"
)

STANDINGS_INCLUDES = "participant;details;details.type"


class SportmonksRequests:
    """Low-level, typed-by-purpose Sportmonks v3 request facade."""

    def __init__(self, client: SportmonksClient) -> None:
        self.client = client

    # Leagues
    def list_leagues(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "leagues", {"include": LEAGUE_INCLUDES, "per_page": 50}
        )

    def get_league(self, league_id: int) -> dict[str, Any]:
        return self._one(
            f"leagues/{league_id}", {"include": LEAGUE_INCLUDES}
        )

    def search_leagues(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/search/{quote(name.strip(), safe='')}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    # Seasons
    def list_seasons(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "seasons", {"include": "league", "per_page": 50}
        )

    def get_season(self, season_id: int) -> dict[str, Any]:
        return self._one(
            f"seasons/{season_id}", {"include": SEASON_INCLUDES}
        )

    # Teams
    def list_teams(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "teams", {"include": TEAM_INCLUDES, "per_page": 50}
        )

    def list_teams_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/seasons/{season_id}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def get_team(self, team_id: int) -> dict[str, Any]:
        return self._one(
            f"teams/{team_id}", {"include": TEAM_INCLUDES}
        )

    def search_teams(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/search/{quote(name.strip(), safe='')}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def get_team_current_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/{team_id}/current",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_all_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/{team_id}/leagues",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_squad(self, season_id: int, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"squads/seasons/{season_id}/teams/{team_id}",
            {"include": SQUAD_INCLUDES, "per_page": 50},
        )

    def get_team_season_statistics(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"statistics/seasons/teams/{team_id}",
            {"include": "season;details;details.type", "per_page": 50},
        )

    # Players
    def list_players(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "players", {"include": PLAYER_INCLUDES, "per_page": 50}
        )

    def get_player(self, player_id: int) -> dict[str, Any]:
        return self._one(
            f"players/{player_id}", {"include": PLAYER_INCLUDES}
        )

    def search_players(self, name: str) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            f"players/search/{quote(name.strip(), safe='')}",
            {"include": PLAYER_INCLUDES},
        )
        return self._many(payload.get("data"))

    # Fixtures / match API
    def list_fixtures(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "fixtures", {"include": FIXTURE_INCLUDES, "per_page": 50}
        )

    def get_fixture(self, fixture_id: int) -> dict[str, Any]:
        return self._one(
            f"fixtures/{fixture_id}", {"include": FIXTURE_INCLUDES}
        )

    def list_fixtures_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/seasons/{season_id}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_fixtures_by_date(self, fixture_date: str | date) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/date/{fixture_date}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_fixtures_between(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/between/{start_date}/{end_date}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_team_fixtures_between(
        self,
        team_id: int,
        start_date: str | date,
        end_date: str | date,
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/between/{start_date}/{end_date}/{team_id}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    # Live scores
    def get_inplay_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/inplay", {"include": FIXTURE_INCLUDES, "per_page": 50}
        )

    def get_all_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores", {"include": FIXTURE_INCLUDES, "per_page": 50}
        )

    def get_latest_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/latest", {"include": FIXTURE_INCLUDES, "per_page": 50}
        )

    # Standings
    def get_standings(self, season_id: int) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            f"standings/seasons/{season_id}",
            {"include": STANDINGS_INCLUDES},
        )
        return self._many(payload.get("data"))

    # Top scorers
    def get_topscorers(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"topscorers/seasons/{season_id}",
            {"include": "player;participant;type", "per_page": 50},
        )

    @staticmethod
    def _many(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        return []

    @staticmethod
    def _one_payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return next((row for row in value if isinstance(row, dict)), {})
        return {}

    def _one(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self.client.get_json(path, params)
        return self._one_payload(payload.get("data"))
