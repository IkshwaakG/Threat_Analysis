"""StatsBomb Open Data implementation of the normalized provider contract."""

from typing import Any, Mapping

from goodgame.ingestion.provider import MatchDataProvider
from goodgame.ingestion.statsbomb.client import StatsBombClient
from goodgame.ingestion.statsbomb.events import fetch_match_events, fetch_shots
from goodgame.ingestion.statsbomb.matches import find_match_record
from goodgame.ingestion.statsbomb.statistics import (
    get_player_statistics_all_leagues,
    get_player_statistics,
    get_team_statistics,
    get_team_standings,
    list_players,
    list_teams,
)
from goodgame.models.event import Event
from goodgame.models.match import Match


class StatsBombProvider(MatchDataProvider):
    def __init__(
        self,
        client: StatsBombClient | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
        creds: Mapping[str, str] | None = None,
    ) -> None:
        if (competition_id is None) != (season_id is None):
            raise ValueError("competition_id and season_id must be supplied together")
        if client is not None and creds is not None:
            raise ValueError("Pass credentials either to StatsBombProvider or its client, not both")
        self.client = client or StatsBombClient(creds=creds)
        self.competition_id = competition_id
        self.season_id = season_id
        self._matches: dict[int, Match] = {}

    def list_competitions(self) -> list[dict[str, Any]]:
        return self.client.get_competitions()

    def list_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_matches(competition_id, season_id)

    def _season_context(
        self, competition_id: int | None, season_id: int | None
    ) -> tuple[int, int]:
        competition_id = competition_id or self.competition_id
        season_id = season_id or self.season_id
        if competition_id is None or season_id is None:
            raise ValueError("competition_id and season_id are required for season statistics")
        return competition_id, season_id

    def list_teams(
        self, competition_id: int | None = None, season_id: int | None = None
    ) -> list[dict[str, Any]]:
        competition_id, season_id = self._season_context(competition_id, season_id)
        return list_teams(self.client, competition_id, season_id)

    def list_players(
        self,
        team: str | int | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> list[dict[str, Any]]:
        competition_id, season_id = self._season_context(competition_id, season_id)
        return list_players(self.client, competition_id, season_id, team)

    def get_team_statistics(
        self,
        team: str | int,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        competition_id, season_id = self._season_context(competition_id, season_id)
        return get_team_statistics(self.client, competition_id, season_id, team)

    def get_team_standings(
        self, competition_id: int | None = None, season_id: int | None = None
    ) -> list[dict[str, Any]]:
        competition_id, season_id = self._season_context(competition_id, season_id)
        return get_team_standings(self.client, competition_id, season_id)

    def get_player_statistics(
        self,
        player: str | int,
        team: str | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        competition_id, season_id = self._season_context(competition_id, season_id)
        return get_player_statistics(
            self.client, competition_id, season_id, player, team
        )

    def get_player_statistics_all_leagues(
        self,
        season_name: str,
        player: str | int,
        team: str | None = None,
    ) -> dict[str, Any]:
        return get_player_statistics_all_leagues(
            self.client, season_name, player, team
        )

    def get_match(self, match_id: int) -> Match:
        if match_id not in self._matches:
            record: dict[str, Any] = find_match_record(
                self.client,
                match_id,
                competition_id=self.competition_id,
                season_id=self.season_id,
            )
            self._matches[match_id] = Match.from_statsbomb_payload(record)
        return self._matches[match_id]

    def get_events(self, match_id: int) -> list[Event]:
        match = self.get_match(match_id)
        return fetch_match_events(self.client, match_id, match.home_team.name)

    def get_lineups(self, match_id: int) -> dict[str, Any]:
        return self.client.get_lineups(match_id)

    def get_shot_map(self, match_id: int) -> list[dict[str, Any]]:
        return fetch_shots(self.client, match_id)