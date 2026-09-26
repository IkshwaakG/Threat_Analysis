"""Sportmonks implementation of GoodGame's normalized provider contract.

HTTP request construction lives in requests.py.
Raw-response parsing/normalization lives in responses.py.
This provider coordinates the two layers and exposes GoodGame-friendly methods.
"""

from __future__ import annotations

from typing import Any

from goodgame.ingestion.provider import MatchDataProvider
from goodgame.ingestion.sportmonks.client import SportmonksClient
from goodgame.ingestion.sportmonks.requests import SportmonksRequests
from goodgame.ingestion.sportmonks.responses import (
    fixture_events,
    fixture_lineups,
    fixture_shots,
    fixture_to_match,
    integer,
    name,
    normalize_player_statistics,
    normalize_team_statistics,
    season_key,
    scalar_statistics,
)
from goodgame.models.event import Event
from goodgame.models.match import Match


class SportmonksProvider(MatchDataProvider):
    def __init__(
        self,
        client: SportmonksClient | None = None,
        requests_api: SportmonksRequests | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> None:
        self.client = client or SportmonksClient()
        self.api = requests_api or SportmonksRequests(self.client)
        self.competition_id = competition_id
        self.season_id = season_id
        self._fixtures: dict[int, dict[str, Any]] = {}
        self._matches: dict[int, Match] = {}

    # ---------- League / season ----------

    def list_leagues(self) -> list[dict[str, Any]]:
        return self.api.list_leagues()

    def get_league(self, league_id: int) -> dict[str, Any]:
        return self.api.get_league(league_id)

    def search_leagues(self, name_value: str) -> list[dict[str, Any]]:
        return self.api.search_leagues(name_value)

    def get_live_leagues(self) -> list[dict[str, Any]]:
        return self.api.get_live_leagues()

    def get_leagues_by_fixture_date(self, fixture_date: str) -> list[dict[str, Any]]:
        return self.api.get_leagues_by_fixture_date(fixture_date)

    def list_competitions(self) -> list[dict[str, Any]]:
        rows = self.api.list_seasons()
        return [
            {
                "competition_id": row.get("league_id"),
                "season_id": row.get("id"),
                "competition_name": name(row.get("league")) or row.get("league_name"),
                "season_name": row.get("name"),
            }
            for row in rows
            if row.get("league_id") is not None and row.get("id") is not None
        ]

    def get_season(self, season_id: int) -> dict[str, Any]:
        return self.api.get_season(season_id)

    # ---------- Team ----------

    def list_teams(self, season_id: int | None = None) -> list[dict[str, Any]]:
        selected_season = season_id or self.season_id
        if selected_season is not None:
            return self.api.list_teams_by_season(selected_season)
        return self.api.list_teams()

    def list_teams_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.api.list_teams_by_country(country_id)

    def get_team(self, team_id: int) -> dict[str, Any]:
        return self.api.get_team(team_id)

    def search_teams(self, team_name: str) -> list[dict[str, Any]]:
        return self.api.search_teams(team_name)

    def get_team_current_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.api.get_team_current_leagues(team_id)

    def get_team_all_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.api.get_team_all_leagues(team_id)

    def get_team_squad(
        self, team_id: int, season_id: int | None = None
    ) -> list[dict[str, Any]]:
        selected_season = season_id or self.season_id
        if selected_season is None:
            raise ValueError("season_id is required for squad retrieval")
        return self.api.get_team_squad(selected_season, team_id)

    def get_team_statistics(
        self,
        team: str | int,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        selected_season = season_id or self.season_id
        selected_competition = competition_id or self.competition_id
        if selected_season is None:
            raise ValueError("Choose a season before requesting team stats")

        standings = self.api.get_standings(selected_season)
        requested = str(team).strip().casefold()

        selected = next(
            (
                row
                for row in standings
                if isinstance(row, dict)
                and (
                    integer(team) == integer(row.get("participant_id"))
                    if str(team).strip().isdigit()
                    else str(name(row.get("participant")) or "")
                    .strip()
                    .casefold()
                    == requested
                )
            ),
            None,
        )
        if selected is None:
            raise LookupError(
                f"Team not found in Sportmonks season {selected_season}: {team}"
            )

        team_id = integer(selected.get("participant_id"))
        if team_id is None:
            raise LookupError(f"Sportmonks standing has no team ID for {team}")

        season_records = self.api.get_team_season_statistics(team_id)
        return normalize_team_statistics(
            selected,
            season_records,
            competition_id=selected_competition,
            season_id=selected_season,
            standings_count=len(standings),
            team_name=str(team),
        )

    # ---------- Player ----------

    def list_players(self) -> list[dict[str, Any]]:
        return self.api.list_players()

    def get_player(self, player_id: int) -> dict[str, Any]:
        return self.api.get_player(player_id)

    def search_players(self, player_name: str) -> list[dict[str, Any]]:
        return self.api.search_players(player_name)

    def list_players_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.api.list_players_by_country(country_id)

    def get_latest_players(self) -> list[dict[str, Any]]:
        return self.api.get_latest_players()

    def _resolve_player(self, player: str | int) -> dict[str, Any]:
        if isinstance(player, int) or str(player).strip().isdigit():
            return self.api.get_player(int(player))

        candidates = self.api.search_players(str(player))
        requested = " ".join(str(player).casefold().split())
        exact = [
            item
            for item in candidates
            if any(
                " ".join(str(item.get(field, "")).casefold().split()) == requested
                for field in ("name", "display_name", "common_name")
            )
        ]
        candidates = exact or candidates

        if not candidates:
            raise LookupError(
                f"Player not found in Sportmonks account coverage: {player}"
            )
        if len(candidates) > 1:
            names = ", ".join(
                str(item.get("name", item.get("id"))) for item in candidates[:5]
            )
            raise LookupError(
                f"Player search is ambiguous; select a player ID: {names}"
            )

        player_id = integer(candidates[0].get("id"))
        if player_id is None:
            raise LookupError(
                f"Sportmonks player search returned no player ID for {player}"
            )
        return self.api.get_player(player_id)

    def get_player_statistics(
        self,
        player: str | int,
        team: str | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        record = self._resolve_player(player)
        statistics = [
            row
            for row in (record.get("statistics", []) or [])
            if isinstance(row, dict)
        ]
        return normalize_player_statistics(
            record,
            statistics,
            team=team,
            competition_id=competition_id,
            season_id=season_id,
        )

    def get_player_statistics_all_leagues(
        self,
        season_name: str,
        player: str | int,
        team: str | None = None,
    ) -> dict[str, Any]:
        record = self._resolve_player(player)
        statistics = [
            row
            for row in (record.get("statistics", []) or [])
            if isinstance(row, dict)
        ]

        wanted_season = season_key(season_name)
        wanted_team = " ".join(team.casefold().split()) if team else None
        selected: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []

        for stat in statistics:
            season = stat.get("season") if isinstance(stat.get("season"), dict) else {}
            stat_team = stat.get("team") if isinstance(stat.get("team"), dict) else {}
            league = season.get("league") if isinstance(season.get("league"), dict) else {}

            if season_key(season.get("name", "")) != wanted_season:
                continue
            if wanted_team and " ".join(
                str(stat_team.get("name", "")).casefold().split()
            ) != wanted_team:
                continue
            selected.append((stat, season, stat_team, league))

        if not selected:
            raise LookupError(
                f"No Sportmonks statistics found for {player} in {season_name}"
            )

        merged: dict[str, Any] = {}
        competitions: set[str] = set()
        teams: set[str] = set()

        for stat, _season, stat_team, league in selected:
            competitions.add(
                str(league.get("name", league.get("id", "Unknown competition")))
            )
            if stat_team.get("name"):
                teams.add(str(stat_team["name"]))
            for key, value in scalar_statistics(stat.get("details")).items():
                if isinstance(value, (int, float)):
                    merged[key] = merged.get(key, 0) + value
                else:
                    merged[key] = value

        merged.update(
            player_id=record.get("id"),
            player_name=record.get("name") or record.get("display_name"),
            team_name=", ".join(sorted(teams)),
            season_name=season_name,
            competitions=sorted(competitions),
            competition_count=len(competitions),
        )
        return merged

    # ---------- Fixture / match ----------

    def list_matches(
        self, competition_id: int, season_id: int
    ) -> list[dict[str, Any]]:
        fixtures = self.api.list_fixtures_by_season(season_id)
        rows: list[dict[str, Any]] = []

        for fixture in fixtures:
            if integer(fixture.get("league_id")) not in {None, competition_id}:
                continue
            try:
                match = fixture_to_match(fixture)
            except (KeyError, TypeError, ValueError):
                continue

            self._fixtures[match.id] = fixture
            self._matches[match.id] = match
            rows.append(
                {
                    "match_id": match.id,
                    "match_date": fixture.get("starting_at", ""),
                    "home_team": match.home_team.name,
                    "away_team": match.away_team.name,
                    "home_score": match.home_score,
                    "away_score": match.away_score,
                }
            )

        return rows

    def get_fixtures_by_ids(self, fixture_ids: list[int]) -> list[dict[str, Any]]:
        return self.api.get_fixtures_by_ids(fixture_ids)

    def list_fixtures_by_date(self, fixture_date: str) -> list[dict[str, Any]]:
        return self.api.list_fixtures_by_date(fixture_date)

    def list_fixtures_between(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self.api.list_fixtures_between(start_date, end_date)

    def list_team_fixtures_between(
        self, team_id: int, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self.api.list_team_fixtures_between(
            team_id, start_date, end_date
        )

    def search_fixtures(self, query: str) -> list[dict[str, Any]]:
        return self.api.search_fixtures(query)

    def get_head_to_head(
        self, team_a_id: int, team_b_id: int
    ) -> list[dict[str, Any]]:
        return self.api.get_head_to_head(team_a_id, team_b_id)

    def get_latest_updated_fixtures(self) -> list[dict[str, Any]]:
        return self.api.get_latest_updated_fixtures()

    def get_fixture(self, match_id: int) -> dict[str, Any]:
        if match_id not in self._fixtures:
            self._fixtures[match_id] = self.api.get_fixture(match_id)
        return self._fixtures[match_id]

    def get_match(self, match_id: int) -> Match:
        if match_id not in self._matches:
            self._matches[match_id] = fixture_to_match(
                self.get_fixture(match_id)
            )
        return self._matches[match_id]

    def get_events(self, match_id: int) -> list[Event]:
        fixture = self.get_fixture(match_id)
        return fixture_events(fixture, self.get_match(match_id))

    def get_lineups(self, match_id: int) -> dict[str, Any]:
        fixture = self.get_fixture(match_id)
        return fixture_lineups(fixture, self.get_match(match_id))

    def get_shot_map(self, match_id: int) -> list[dict[str, Any]]:
        return fixture_shots(self.get_fixture(match_id))

    def get_fixture_statistics(self, match_id: int) -> list[dict[str, Any]]:
        return [
            row
            for row in (self.get_fixture(match_id).get("statistics", []) or [])
            if isinstance(row, dict)
        ]

    def get_fixture_xg(self, match_id: int) -> list[dict[str, Any]]:
        return [
            row
            for row in (self.get_fixture(match_id).get("expected", []) or [])
            if isinstance(row, dict)
        ]

    def get_fixture_ball_coordinates(
        self, match_id: int
    ) -> list[dict[str, Any]]:
        fixture = self.get_fixture(match_id)
        value = fixture.get("ballCoordinates") or fixture.get("ballcoordinates") or []
        return [row for row in value if isinstance(row, dict)]

    def get_fixture_pressure(self, match_id: int) -> list[dict[str, Any]]:
        value = self.get_fixture(match_id).get("pressure", []) or []
        return [row for row in value if isinstance(row, dict)]

    # ---------- Schedule / structure / expected data ----------

    def get_schedule_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.api.get_schedule_by_season(season_id)

    def get_schedule_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.api.get_schedule_by_team(team_id)

    def get_schedule_by_season_and_team(
        self, season_id: int, team_id: int
    ) -> list[dict[str, Any]]:
        return self.api.get_schedule_by_season_and_team(season_id, team_id)

    def get_stages_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.api.get_stages_by_season(season_id)

    def get_rounds_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.api.get_rounds_by_season(season_id)

    def get_expected_by_team(self) -> list[dict[str, Any]]:
        return self.api.get_expected_by_team()

    def get_expected_by_player(self) -> list[dict[str, Any]]:
        return self.api.get_expected_by_player()

    def get_expected_lineups_by_team(
        self, team_id: int
    ) -> list[dict[str, Any]]:
        return self.api.get_expected_lineups_by_team(team_id)

    def get_expected_lineups_by_player(
        self, player_id: int
    ) -> list[dict[str, Any]]:
        return self.api.get_expected_lineups_by_player(player_id)

    # ---------- Live / standings / leaders ----------

    def get_inplay_livescores(self) -> list[dict[str, Any]]:
        return self.api.get_inplay_livescores()

    def get_all_livescores(self) -> list[dict[str, Any]]:
        return self.api.get_all_livescores()

    def get_latest_livescores(self) -> list[dict[str, Any]]:
        return self.api.get_latest_livescores()

    def get_standings(self, season_id: int | None = None) -> list[dict[str, Any]]:
        selected_season = season_id or self.season_id
        if selected_season is None:
            raise ValueError("season_id is required for standings")
        return self.api.get_standings(selected_season)

    def get_topscorers(
        self, season_id: int | None = None
    ) -> list[dict[str, Any]]:
        selected_season = season_id or self.season_id
        if selected_season is None:
            raise ValueError("season_id is required for top scorers")
        return self.api.get_topscorers(selected_season)
