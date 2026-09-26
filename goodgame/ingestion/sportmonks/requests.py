"""Sportmonks Football API v3 request definitions.

This module owns endpoint paths, full include chains, filters, and pagination.
Response normalization belongs in responses.py.

The include constants intentionally retain the detailed documented include chains
because GoodGame needs the richest response available to the account/plan.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from goodgame.ingestion.sportmonks.client import SportmonksClient


FIXTURE_INCLUDES = (
    "sport;round;stage;group;aggregate;league;season;coaches;tvStations;venue;"
    "state;weatherReport;lineups;lineups.player;lineups.position;"
    "lineups.detailedPosition;lineups.details.type;lineups.xGLineup;"
    "events;events.player;events.relatedPlayer;events.type;events.period;"
    "timeline;comments;trends;statistics;statistics.type;periods;participants;"
    "odds;premiumOdds;inplayOdds;prematchNews;postmatchNews;metadata;sidelined;"
    "sidelined.sideline.player;sidelined.sideline.type;predictions;referees;"
    "formations;ballCoordinates;scores;xGFixture;pressure;expectedLineups"
)

PLAYER_INCLUDES = (
    "sport;country;city;nationality;position;detailedPosition;transfers;"
    "pendingTransfers;teams;teams.team;statistics;statistics.details.type;"
    "statistics.team;statistics.season;statistics.season.league;latest;"
    "latest.fixture;latest.fixture.participants;latest.fixture.league;"
    "latest.fixture.scores;latest.details.type;lineups;trophies;"
    "trophies.trophy;trophies.team;trophies.league;trophies.season;metadata"
)

TEAM_INCLUDES = (
    "sport;country;venue;coaches;rivals;players;latest;upcoming;seasons;"
    "activeSeasons;sidelined;sidelinedHistory;statistics;"
    "statistics.details.type;trophies;socials;rankings"
)

LEAGUE_INCLUDES = (
    "sport;country;stages;latest;upcoming;inplay;today;currentSeason;seasons"
)

SEASON_INCLUDES = (
    "sport;league;teams;stages;currentStage;fixtures;groups;statistics;"
    "statistics.details.type;topscorers"
)

SQUAD_INCLUDES = (
    "team;player;player.statistics;player.statistics.details.type;"
    "position;detailedPosition;transfer;details.type"
)

STANDINGS_INCLUDES = "participant;details;details.type"
TOPSCORER_INCLUDES = "player;participant;type"


class SportmonksRequests:
    """Low-level Sportmonks v3 request facade.

    Every method maps to one resource endpoint. Rich includes are kept here so
    callers do not have to duplicate or accidentally truncate them.
    """

    def __init__(self, client: SportmonksClient) -> None:
        self.client = client

    # ---------- Leagues ----------

    def list_leagues(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "leagues", {"include": LEAGUE_INCLUDES, "per_page": 50}
        )

    def get_league(self, league_id: int) -> dict[str, Any]:
        return self._one(f"leagues/{league_id}", {"include": LEAGUE_INCLUDES})

    def search_leagues(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/search/{quote(name.strip(), safe='')}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_live_leagues(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "leagues/live", {"include": LEAGUE_INCLUDES, "per_page": 50}
        )

    def get_leagues_by_fixture_date(
        self, fixture_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/date/{fixture_date}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_current_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/teams/{team_id}/current",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_all_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/teams/{team_id}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    # ---------- Seasons ----------

    def list_seasons(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "seasons", {"include": SEASON_INCLUDES, "per_page": 50}
        )

    def get_season(self, season_id: int) -> dict[str, Any]:
        return self._one(f"seasons/{season_id}", {"include": SEASON_INCLUDES})

    def search_seasons(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"seasons/search/{quote(name.strip(), safe='')}",
            {"include": SEASON_INCLUDES, "per_page": 50},
        )

    # ---------- Teams ----------

    def list_teams(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "teams", {"include": TEAM_INCLUDES, "per_page": 50}
        )

    def list_teams_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/seasons/{season_id}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def list_teams_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/countries/{country_id}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def get_team(self, team_id: int) -> dict[str, Any]:
        return self._one(f"teams/{team_id}", {"include": TEAM_INCLUDES})

    def search_teams(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/search/{quote(name.strip(), safe='')}",
            {"include": TEAM_INCLUDES, "per_page": 50},
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

    # ---------- Players ----------

    def list_players(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "players", {"include": PLAYER_INCLUDES, "per_page": 50}
        )

    def list_players_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"players/countries/{country_id}",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    def get_player(self, player_id: int) -> dict[str, Any]:
        return self._one(f"players/{player_id}", {"include": PLAYER_INCLUDES})

    def search_players(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"players/search/{quote(name.strip(), safe='')}",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    def get_latest_players(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "players/latest",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    # ---------- Fixtures / match API ----------

    def list_fixtures(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "fixtures", {"include": FIXTURE_INCLUDES, "per_page": 50}
        )

    def get_fixture(self, fixture_id: int) -> dict[str, Any]:
        return self._one(
            f"fixtures/{fixture_id}", {"include": FIXTURE_INCLUDES}
        )

    def get_fixtures_by_ids(self, fixture_ids: list[int]) -> list[dict[str, Any]]:
        joined = ",".join(str(value) for value in fixture_ids)
        return self.client.get_all(
            f"fixtures/multi/{joined}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_fixtures_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/seasons/{season_id}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_fixtures_by_date(
        self, fixture_date: str | date
    ) -> list[dict[str, Any]]:
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

    def search_fixtures(self, query: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/search/{quote(query.strip(), safe='')}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def get_head_to_head(
        self, team_a_id: int, team_b_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/head-to-head/{team_a_id}/{team_b_id}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def get_latest_updated_fixtures(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "fixtures/latest",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    # ---------- Live scores ----------

    def get_inplay_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/inplay",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def get_all_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def get_latest_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/latest",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    # ---------- Standings / leaders ----------

    def get_standings(self, season_id: int) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            f"standings/seasons/{season_id}",
            {"include": STANDINGS_INCLUDES},
        )
        return self._many(payload.get("data"))

    def get_topscorers(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"topscorers/seasons/{season_id}",
            {"include": TOPSCORER_INCLUDES, "per_page": 50},
        )

    # ---------- Helpers ----------

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
