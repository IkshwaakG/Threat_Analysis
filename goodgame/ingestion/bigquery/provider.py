"""Read normalized GoodGame football data from BigQuery."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import bigquery

from goodgame.ingestion.provider import MatchDataProvider
from goodgame.models.event import Event
from goodgame.models.match import Match, Team


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gg-football-data")
CORE_DATASET = os.environ.get("BIGQUERY_CORE_DATASET", "football_core")
BQ_LOCATION = os.environ.get("BIGQUERY_LOCATION", "US")


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row.items()) if hasattr(row, "items") else dict(row)


class BigQueryProvider(MatchDataProvider):
    """Provider backed by football_core BigQuery tables."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        dataset: str = CORE_DATASET,
        client: bigquery.Client | None = None,
    ) -> None:
        self.project_id = project_id
        self.dataset = dataset
        self.client = client or bigquery.Client(project=project_id, location=BQ_LOCATION)

    def _table(self, name: str) -> str:
        return f"`{self.project_id}.{self.dataset}.{name}`"

    def _query(self, sql: str, params: list[bigquery.ScalarQueryParameter] | None = None) -> list[dict[str, Any]]:
        config = bigquery.QueryJobConfig(query_parameters=params or [])
        return [_row_dict(row) for row in self.client.query(sql, job_config=config).result()]

    def list_competitions(self) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT
              l.league_id AS competition_id,
              l.name AS competition_name,
              s.season_id,
              s.name AS season_name
            FROM {self._table("leagues")} l
            JOIN {self._table("seasons")} s USING (league_id)
            WHERE EXISTS (
              SELECT 1
              FROM {self._table("fixtures")} f
              WHERE f.league_id = l.league_id
                AND f.season_id = s.season_id
            )
            ORDER BY l.name, s.starting_at DESC, s.season_id DESC
            """
        )
        return rows

    def list_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        return self._query(
            f"""
            WITH participants AS (
              SELECT
                fp.fixture_id,
                MAX(IF(fp.location = 'home', t.name, NULL)) AS home_team,
                MAX(IF(fp.location = 'away', t.name, NULL)) AS away_team
              FROM {self._table("fixture_participants")} fp
              LEFT JOIN {self._table("teams")} t
                ON t.team_id = fp.team_id
               AND t.league_id = fp.league_id
               AND t.season_id = fp.season_id
              WHERE fp.league_id = @league_id
                AND fp.season_id = @season_id
              GROUP BY fp.fixture_id
            )
            SELECT
              f.fixture_id AS match_id,
              CAST(f.starting_at AS STRING) AS match_date,
              COALESCE(p.home_team, SPLIT(f.name, ' vs ')[SAFE_OFFSET(0)], 'Home') AS home_team,
              COALESCE(p.away_team, SPLIT(f.name, ' vs ')[SAFE_OFFSET(1)], 'Away') AS away_team,
              NULL AS home_score,
              NULL AS away_score
            FROM {self._table("fixtures")} f
            LEFT JOIN participants p USING (fixture_id)
            WHERE f.league_id = @league_id
              AND f.season_id = @season_id
            ORDER BY f.starting_at DESC, f.fixture_id DESC
            """,
            [
                bigquery.ScalarQueryParameter("league_id", "INT64", competition_id),
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
            ],
        )

    def _fixture_record(self, match_id: int) -> dict[str, Any]:
        rows = self._query(
            f"""
            SELECT *
            FROM {self._table("fixtures")}
            WHERE fixture_id = @fixture_id
            LIMIT 1
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )
        if not rows:
            raise LookupError(f"Fixture {match_id} not found in BigQuery")
        return rows[0]

    def _participants(self, match_id: int) -> list[dict[str, Any]]:
        return self._query(
            f"""
            SELECT
              fp.fixture_id,
              fp.team_id,
              fp.location,
              fp.winner,
              fp.position,
              t.name,
              t.short_code,
              t.image_path
            FROM {self._table("fixture_participants")} fp
            LEFT JOIN {self._table("teams")} t
              ON t.team_id = fp.team_id
             AND t.league_id = fp.league_id
             AND t.season_id = fp.season_id
            WHERE fp.fixture_id = @fixture_id
            ORDER BY IF(fp.location = 'home', 0, 1), fp.team_id
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )

    def get_match(self, match_id: int) -> Match:
        fixture = self._fixture_record(match_id)
        participants = self._participants(match_id)
        home = next((row for row in participants if row.get("location") == "home"), None)
        away = next((row for row in participants if row.get("location") == "away"), None)
        if home is None or away is None:
            raise LookupError(f"Fixture {match_id} is missing home/away participants in BigQuery")

        started = fixture.get("starting_at")
        timestamp = int(started.timestamp()) if started is not None and hasattr(started, "timestamp") else fixture.get("starting_at_timestamp")

        return Match(
            id=int(fixture["fixture_id"]),
            home_team=Team(id=int(home["team_id"]), name=str(home.get("name") or "Home")),
            away_team=Team(id=int(away["team_id"]), name=str(away.get("name") or "Away")),
            home_score=None,
            away_score=None,
            status=str(fixture.get("result_info") or fixture.get("state_id") or "unknown"),
            start_timestamp=int(timestamp) if timestamp is not None else None,
            tournament_id=int(fixture["league_id"]),
            season_id=int(fixture["season_id"]),
        )

    def get_events(self, match_id: int) -> list[Event]:
        match = self.get_match(match_id)
        rows = self._query(
            f"""
            SELECT
              e.*,
              ty.name AS type_name
            FROM {self._table("fixture_events")} e
            LEFT JOIN {self._table("types")} ty USING (type_id)
            WHERE e.fixture_id = @fixture_id
            ORDER BY e.minute, e.extra_minute, e.event_id
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )

        events: list[Event] = []
        for row in rows:
            type_name = str(row.get("type_name") or row.get("info") or "event")
            normalized = type_name.casefold()
            incident_type = (
                "goal" if "goal" in normalized
                else "substitution" if "substitution" in normalized
                else "card" if "card" in normalized
                else "shot" if "shot" in normalized
                else normalized.replace(" ", "_")
            )
            team_id = row.get("team_id")
            events.append(
                Event(
                    id=row.get("event_id"),
                    minute=row.get("minute"),
                    incident_type=incident_type,
                    text=str(row.get("info") or row.get("addition") or type_name),
                    is_home=(int(team_id) == match.home_team.id) if team_id is not None else None,
                    player=row.get("player_name"),
                    player_in=row.get("related_player_name") if incident_type == "substitution" else None,
                    player_out=row.get("player_name") if incident_type == "substitution" else None,
                    incident_class=row.get("result"),
                    raw=row.get("raw_event") or {},
                )
            )
        return events

    def get_lineups(self, match_id: int) -> dict[str, Any]:
        match = self.get_match(match_id)
        rows = self._query(
            f"""
            SELECT
              l.*,
              p.name,
              p.display_name,
              p.common_name
            FROM {self._table("fixture_lineups")} l
            LEFT JOIN {self._table("players")} p
              ON p.player_id = l.player_id
             AND p.league_id = l.league_id
             AND p.season_id = l.season_id
            WHERE l.fixture_id = @fixture_id
            ORDER BY l.team_id, l.formation_position, l.player_id
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )
        result = {match.home_team.name: [], match.away_team.name: []}
        for row in rows:
            team_id = int(row["team_id"])
            target = match.home_team.name if team_id == match.home_team.id else match.away_team.name
            result[target].append(
                {
                    **row,
                    "player": {
                        "id": row.get("player_id"),
                        "name": row.get("name"),
                        "display_name": row.get("display_name"),
                        "common_name": row.get("common_name"),
                    },
                    "type_id": row.get("lineup_type_id"),
                }
            )
        return result

    def get_shot_map(self, match_id: int) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT e.raw_event
            FROM {self._table("fixture_events")} e
            LEFT JOIN {self._table("types")} ty USING (type_id)
            WHERE e.fixture_id = @fixture_id
              AND LOWER(COALESCE(ty.name, '')) LIKE '%shot%'
            ORDER BY e.minute, e.event_id
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )
        return [row.get("raw_event") or {} for row in rows]

    def get_fixture_statistics(self, match_id: int) -> list[dict[str, Any]]:
        return self._query(
            f"""
            SELECT
              s.*,
              ty.name AS type_name,
              ty.developer_name,
              ty.stat_group
            FROM {self._table("statistics")} s
            LEFT JOIN {self._table("types")} ty USING (type_id)
            WHERE s.fixture_id = @fixture_id
            ORDER BY s.entity_type, s.entity_id, s.type_id
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", match_id)],
        )

    def get_fixture_xg(self, match_id: int) -> list[dict[str, Any]]:
        return [
            row for row in self.get_fixture_statistics(match_id)
            if "expected" in str(row.get("type_name") or "").casefold()
            or "xg" in str(row.get("developer_name") or "").casefold()
        ]

    def get_fixture(self, match_id: int) -> dict[str, Any]:
        fixture = self._fixture_record(match_id)
        participants = self._participants(match_id)
        lineups = []
        for rows in self.get_lineups(match_id).values():
            lineups.extend(rows)
        league_rows = self._query(
            f"""
            SELECT name
            FROM {self._table("leagues")}
            WHERE league_id = @league_id
            LIMIT 1
            """,
            [bigquery.ScalarQueryParameter("league_id", "INT64", int(fixture["league_id"]))],
        )
        return {
            **fixture,
            "participants": [
                {
                    "id": row["team_id"],
                    "name": row.get("name"),
                    "short_code": row.get("short_code"),
                    "image_path": row.get("image_path"),
                    "meta": {"location": row.get("location")},
                }
                for row in participants
            ],
            "lineups": lineups,
            "events": [event.raw for event in self.get_events(match_id)],
            "statistics": self.get_fixture_statistics(match_id),
            "league": {"id": fixture.get("league_id"), "name": league_rows[0]["name"] if league_rows else None},
        }
