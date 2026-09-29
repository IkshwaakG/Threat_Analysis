"""BigQuery read models optimized for frontend serving.

Each public method executes exactly one BigQuery query job. The query may
return multiple row kinds; Python assembles those rows into the API response.
This avoids N+1/nested BigQuery calls while keeping football_core normalized.
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import bigquery


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gg-football-data")
CORE_DATASET = os.environ.get("BIGQUERY_CORE_DATASET", "football_core")
BQ_LOCATION = os.environ.get("BIGQUERY_LOCATION", "US")


def _payload(row: Any) -> dict[str, Any]:
    value = row["payload"]
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    return dict(value or {})


def _stat_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, dict):
        for key in ("total", "value", "count", "average"):
            if key in value:
                return value[key]
    return value


def _rank_stats(
    rows: list[dict[str, Any]],
    keywords: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        label = str(
            row.get("developer_name")
            or row.get("name")
            or row.get("code")
            or row.get("type_id")
            or ""
        )
        normalized = label.casefold().replace("_", " ").replace("-", " ")
        priority = next(
            (index for index, keyword in enumerate(keywords) if keyword in normalized),
            len(keywords) + 1,
        )
        item = {
            "type_id": row.get("type_id"),
            "name": row.get("name") or row.get("developer_name") or row.get("code"),
            "developer_name": row.get("developer_name"),
            "group": row.get("stat_group"),
            "value": _stat_value(row.get("value")),
        }
        ranked.append((priority, label, item))

    ranked.sort(key=lambda current: (current[0], current[1]))
    return [item for _, _, item in ranked[:limit]]


class BigQueryServingRepository:
    """Purpose-built read repository for GoodGame web/Quest clients."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        dataset: str = CORE_DATASET,
        client: bigquery.Client | None = None,
    ) -> None:
        self.project_id = project_id
        self.dataset = dataset
        self.client = client or bigquery.Client(
            project=project_id,
            location=BQ_LOCATION,
        )

    def _table(self, name: str) -> str:
        return f"`{self.project_id}.{self.dataset}.{name}`"

    def _query(
        self,
        sql: str,
        params: list[bigquery.ScalarQueryParameter],
    ) -> list[Any]:
        config = bigquery.QueryJobConfig(query_parameters=params)
        return list(self.client.query(sql, job_config=config).result())

    def get_game_view(self, fixture_id: int) -> dict[str, Any]:
        """Return everything the game screen needs using one BigQuery job."""

        rows = self._query(
            f"""
            WITH fixture AS (
              SELECT *
              FROM {self._table("fixtures")}
              WHERE fixture_id = @fixture_id
              LIMIT 1
            ),
            participants AS (
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
            ),
            lineup AS (
              SELECT
                l.fixture_id,
                l.team_id,
                l.player_id,
                l.position_id,
                l.detailed_position_id,
                l.lineup_type_id,
                l.jersey_number,
                l.formation_field,
                l.formation_position,
                COALESCE(
                  p.display_name,
                  p.name,
                  p.common_name,
                  l.player_name
                ) AS player_name,
                p.image_path AS player_image,
                participant.location AS team_location,
                participant.name AS team_name
              FROM {self._table("fixture_lineups")} l
              LEFT JOIN {self._table("players")} p
                ON p.player_id = l.player_id
               AND p.league_id = l.league_id
               AND p.season_id = l.season_id
              LEFT JOIN participants participant
                ON participant.team_id = l.team_id
              WHERE l.fixture_id = @fixture_id
            ),
            stats AS (
              SELECT
                s.fixture_id,
                s.team_id,
                s.player_id,
                s.entity_type,
                s.entity_id,
                s.type_id,
                s.value,
                ty.name,
                ty.code,
                ty.developer_name,
                ty.stat_group
              FROM {self._table("statistics")} s
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE s.fixture_id = @fixture_id
            ),
            goals AS (
              SELECT e.team_id, COUNT(*) AS goals
              FROM {self._table("fixture_events")} e
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE e.fixture_id = @fixture_id
                AND LOWER(COALESCE(ty.name, ty.developer_name, '')) LIKE '%goal%'
              GROUP BY e.team_id
            )
            SELECT
              'fixture' AS row_kind,
              TO_JSON_STRING(STRUCT(
                f.fixture_id AS id,
                f.league_id AS competition_id,
                f.season_id,
                f.name,
                CAST(f.starting_at AS STRING) AS starting_at,
                f.starting_at_timestamp,
                f.state_id,
                f.result_info,
                l.name AS competition_name
              )) AS payload
            FROM fixture f
            LEFT JOIN {self._table("leagues")} l USING (league_id)

            UNION ALL

            SELECT
              'team' AS row_kind,
              TO_JSON_STRING(STRUCT(
                p.team_id AS id,
                p.location,
                p.name,
                p.short_code,
                p.image_path AS logo,
                p.winner,
                p.position,
                COALESCE(g.goals, 0) AS goals
              )) AS payload
            FROM participants p
            LEFT JOIN goals g USING (team_id)

            UNION ALL

            SELECT
              'player' AS row_kind,
              TO_JSON_STRING(STRUCT(
                l.player_id,
                l.player_name AS name,
                l.player_image AS image,
                l.team_id,
                l.team_name,
                l.team_location,
                l.jersey_number,
                l.position_id,
                l.detailed_position_id,
                l.lineup_type_id,
                l.formation_field,
                l.formation_position
              )) AS payload
            FROM lineup l

            UNION ALL

            SELECT
              CASE
                WHEN s.player_id IS NOT NULL THEN 'player_stat'
                WHEN s.team_id IS NOT NULL THEN 'team_stat'
                ELSE 'game_stat'
              END AS row_kind,
              TO_JSON_STRING(STRUCT(
                s.team_id,
                s.player_id,
                s.entity_type,
                s.entity_id,
                s.type_id,
                s.name,
                s.code,
                s.developer_name,
                s.stat_group,
                s.value
              )) AS payload
            FROM stats s
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", fixture_id)],
        )

        fixture: dict[str, Any] | None = None
        teams_by_location: dict[str, dict[str, Any]] = {}
        players_by_id: dict[int, dict[str, Any]] = {}
        team_stats: dict[int, list[dict[str, Any]]] = {}
        player_stats: dict[int, list[dict[str, Any]]] = {}
        game_stats: list[dict[str, Any]] = []

        for row in rows:
            kind = row["row_kind"]
            data = _payload(row)
            if kind == "fixture":
                fixture = data
            elif kind == "team":
                location = str(data.get("location") or "")
                data["profile_url"] = f"/teams/{data['id']}"
                teams_by_location[location] = data
            elif kind == "player":
                player_id = int(data["player_id"])
                data["profile_url"] = f"/players/{player_id}"
                players_by_id[player_id] = data
            elif kind == "team_stat" and data.get("team_id") is not None:
                team_stats.setdefault(int(data["team_id"]), []).append(data)
            elif kind == "player_stat" and data.get("player_id") is not None:
                player_stats.setdefault(int(data["player_id"]), []).append(data)
            elif kind == "game_stat":
                game_stats.append(data)

        if fixture is None:
            raise LookupError(f"Fixture {fixture_id} not found in BigQuery")

        home = teams_by_location.get("home")
        away = teams_by_location.get("away")
        if home is None or away is None:
            raise LookupError(
                f"Fixture {fixture_id} is missing home/away participants in BigQuery"
            )

        team_keywords = (
            "goal",
            "expected goal",
            "xg",
            "possession",
            "shot",
            "pass",
            "corner",
            "foul",
            "offside",
            "save",
        )
        player_keywords = (
            "rating",
            "minute",
            "goal",
            "assist",
            "expected goal",
            "xg",
            "shot",
            "pass",
            "key pass",
            "duel",
            "tackle",
            "interception",
            "clearance",
            "save",
        )

        for team in (home, away):
            team["stats"] = _rank_stats(
                team_stats.get(int(team["id"]), []),
                team_keywords,
                10,
            )

        players = []
        for player in players_by_id.values():
            player["match_stats"] = _rank_stats(
                player_stats.get(int(player["player_id"]), []),
                player_keywords,
                10,
            )
            players.append(player)

        players.sort(
            key=lambda player: (
                0 if player.get("team_location") == "home" else 1,
                player.get("formation_position") or 999,
                player.get("jersey_number") or 999,
            )
        )

        return {
            "fixture": fixture,
            "home_team": home,
            "away_team": away,
            "game_stats": _rank_stats(
                game_stats,
                ("attendance", "duration", "weather", "goal", "shot"),
                10,
            ),
            "players": players,
            "source": "bigquery",
        }

    def get_team_view(
        self,
        team_id: int,
        season_id: int,
        league_id: int | None = None,
    ) -> dict[str, Any]:
        """Return team profile + concise stats + players + 10 recent fixtures."""

        rows = self._query(
            f"""
            WITH selected_team AS (
              SELECT *
              FROM {self._table("teams")}
              WHERE team_id = @team_id
                AND season_id = @season_id
                AND (@league_id IS NULL OR league_id = @league_id)
              QUALIFY ROW_NUMBER() OVER (
                ORDER BY source_fetched_at DESC, updated_at DESC
              ) = 1
            ),
            team_stats AS (
              SELECT
                s.type_id,
                s.value,
                ty.name,
                ty.code,
                ty.developer_name,
                ty.stat_group
              FROM {self._table("statistics")} s
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE s.team_id = @team_id
                AND s.season_id = @season_id
                AND s.fixture_id IS NULL
                AND (@league_id IS NULL OR s.league_id = @league_id)
            ),
            team_players AS (
              SELECT
                p.player_id,
                COALESCE(p.display_name, p.name, p.common_name) AS name,
                p.position_id,
                p.image_path
              FROM {self._table("players")} p
              WHERE p.season_id = @season_id
                AND (@league_id IS NULL OR p.league_id = @league_id)
                AND p.player_id IN (
                  SELECT DISTINCT player_id
                  FROM {self._table("fixture_lineups")}
                  WHERE team_id = @team_id
                    AND season_id = @season_id
                    AND (@league_id IS NULL OR league_id = @league_id)
                )
              QUALIFY ROW_NUMBER() OVER (
                PARTITION BY p.player_id
                ORDER BY p.updated_at DESC
              ) = 1
            ),
            recent_fixture_ids AS (
              SELECT f.fixture_id
              FROM {self._table("fixtures")} f
              WHERE f.season_id = @season_id
                AND (@league_id IS NULL OR f.league_id = @league_id)
                AND EXISTS (
                  SELECT 1
                  FROM {self._table("fixture_participants")} fp
                  WHERE fp.fixture_id = f.fixture_id
                    AND fp.team_id = @team_id
                )
              ORDER BY f.starting_at DESC
              LIMIT 10
            ),
            recent_fixtures AS (
              SELECT
                f.fixture_id,
                f.name,
                CAST(f.starting_at AS STRING) AS starting_at,
                f.league_id,
                f.season_id,
                MAX(IF(fp.location = 'home', fp.team_id, NULL)) AS home_team_id,
                MAX(IF(fp.location = 'home', t.name, NULL)) AS home_team,
                MAX(IF(fp.location = 'away', fp.team_id, NULL)) AS away_team_id,
                MAX(IF(fp.location = 'away', t.name, NULL)) AS away_team
              FROM recent_fixture_ids r
              JOIN {self._table("fixtures")} f USING (fixture_id)
              LEFT JOIN {self._table("fixture_participants")} fp USING (fixture_id)
              LEFT JOIN {self._table("teams")} t
                ON t.team_id = fp.team_id
               AND t.league_id = fp.league_id
               AND t.season_id = fp.season_id
              GROUP BY f.fixture_id, f.name, f.starting_at, f.league_id, f.season_id
            )
            SELECT
              'team' AS row_kind,
              TO_JSON_STRING(STRUCT(
                team_id AS id,
                name,
                short_code,
                image_path AS logo,
                league_id AS competition_id,
                season_id
              )) AS payload
            FROM selected_team

            UNION ALL

            SELECT
              'stat' AS row_kind,
              TO_JSON_STRING(STRUCT(
                type_id,
                name,
                code,
                developer_name,
                stat_group,
                value
              )) AS payload
            FROM team_stats

            UNION ALL

            SELECT
              'player' AS row_kind,
              TO_JSON_STRING(STRUCT(
                player_id,
                name,
                position_id,
                image_path AS image
              )) AS payload
            FROM team_players

            UNION ALL

            SELECT
              'fixture' AS row_kind,
              TO_JSON_STRING(STRUCT(
                fixture_id AS id,
                name,
                starting_at,
                league_id AS competition_id,
                season_id,
                home_team_id,
                home_team,
                away_team_id,
                away_team
              )) AS payload
            FROM recent_fixtures
            """,
            [
                bigquery.ScalarQueryParameter("team_id", "INT64", team_id),
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
                bigquery.ScalarQueryParameter("league_id", "INT64", league_id),
            ],
        )

        team: dict[str, Any] | None = None
        stats: list[dict[str, Any]] = []
        players: list[dict[str, Any]] = []
        fixtures: list[dict[str, Any]] = []

        for row in rows:
            kind = row["row_kind"]
            data = _payload(row)
            if kind == "team":
                team = data
                team["profile_url"] = f"/teams/{team_id}"
            elif kind == "stat":
                stats.append(data)
            elif kind == "player":
                data["profile_url"] = f"/players/{data['player_id']}"
                players.append(data)
            elif kind == "fixture":
                data["profile_url"] = f"/games/{data['id']}"
                fixtures.append(data)

        if team is None:
            raise LookupError(f"Team {team_id} not found for season {season_id}")

        return {
            "team": team,
            "stats": _rank_stats(
                stats,
                (
                    "point",
                    "goal",
                    "expected goal",
                    "xg",
                    "possession",
                    "shot",
                    "pass",
                    "clean sheet",
                    "win",
                    "draw",
                    "loss",
                ),
                12,
            ),
            "players": sorted(players, key=lambda player: str(player.get("name") or "")),
            "recent_fixtures": fixtures,
            "source": "bigquery",
        }

    def get_player_view(
        self,
        player_id: int,
        season_id: int,
        league_id: int | None = None,
    ) -> dict[str, Any]:
        """Return player profile + concise stats + team + 10 recent fixtures."""

        rows = self._query(
            f"""
            WITH selected_player AS (
              SELECT *
              FROM {self._table("players")}
              WHERE player_id = @player_id
                AND season_id = @season_id
                AND (@league_id IS NULL OR league_id = @league_id)
              QUALIFY ROW_NUMBER() OVER (
                ORDER BY source_fetched_at DESC, updated_at DESC
              ) = 1
            ),
            player_stats AS (
              SELECT
                s.type_id,
                s.value,
                ty.name,
                ty.code,
                ty.developer_name,
                ty.stat_group
              FROM {self._table("statistics")} s
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE s.player_id = @player_id
                AND s.season_id = @season_id
                AND s.fixture_id IS NULL
                AND (@league_id IS NULL OR s.league_id = @league_id)
            ),
            player_teams AS (
              SELECT DISTINCT
                t.team_id,
                t.name,
                t.short_code,
                t.image_path AS logo
              FROM {self._table("fixture_lineups")} l
              JOIN {self._table("teams")} t
                ON t.team_id = l.team_id
               AND t.league_id = l.league_id
               AND t.season_id = l.season_id
              WHERE l.player_id = @player_id
                AND l.season_id = @season_id
                AND (@league_id IS NULL OR l.league_id = @league_id)
            ),
            recent_fixture_ids AS (
              SELECT f.fixture_id
              FROM {self._table("fixtures")} f
              WHERE f.season_id = @season_id
                AND (@league_id IS NULL OR f.league_id = @league_id)
                AND EXISTS (
                  SELECT 1
                  FROM {self._table("fixture_lineups")} l
                  WHERE l.fixture_id = f.fixture_id
                    AND l.player_id = @player_id
                )
              ORDER BY f.starting_at DESC
              LIMIT 10
            ),
            recent_fixtures AS (
              SELECT
                f.fixture_id,
                f.name,
                CAST(f.starting_at AS STRING) AS starting_at,
                f.league_id,
                f.season_id,
                MAX(IF(fp.location = 'home', fp.team_id, NULL)) AS home_team_id,
                MAX(IF(fp.location = 'home', t.name, NULL)) AS home_team,
                MAX(IF(fp.location = 'away', fp.team_id, NULL)) AS away_team_id,
                MAX(IF(fp.location = 'away', t.name, NULL)) AS away_team
              FROM recent_fixture_ids r
              JOIN {self._table("fixtures")} f USING (fixture_id)
              LEFT JOIN {self._table("fixture_participants")} fp USING (fixture_id)
              LEFT JOIN {self._table("teams")} t
                ON t.team_id = fp.team_id
               AND t.league_id = fp.league_id
               AND t.season_id = fp.season_id
              GROUP BY f.fixture_id, f.name, f.starting_at, f.league_id, f.season_id
            )
            SELECT
              'player' AS row_kind,
              TO_JSON_STRING(STRUCT(
                player_id AS id,
                COALESCE(display_name, name, common_name) AS name,
                image_path AS image,
                position_id,
                detailed_position_id,
                height,
                weight,
                CAST(date_of_birth AS STRING) AS date_of_birth,
                nationality_id,
                league_id AS competition_id,
                season_id
              )) AS payload
            FROM selected_player

            UNION ALL

            SELECT
              'stat' AS row_kind,
              TO_JSON_STRING(STRUCT(
                type_id,
                name,
                code,
                developer_name,
                stat_group,
                value
              )) AS payload
            FROM player_stats

            UNION ALL

            SELECT
              'team' AS row_kind,
              TO_JSON_STRING(STRUCT(
                team_id AS id,
                name,
                short_code,
                logo
              )) AS payload
            FROM player_teams

            UNION ALL

            SELECT
              'fixture' AS row_kind,
              TO_JSON_STRING(STRUCT(
                fixture_id AS id,
                name,
                starting_at,
                league_id AS competition_id,
                season_id,
                home_team_id,
                home_team,
                away_team_id,
                away_team
              )) AS payload
            FROM recent_fixtures
            """,
            [
                bigquery.ScalarQueryParameter("player_id", "INT64", player_id),
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
                bigquery.ScalarQueryParameter("league_id", "INT64", league_id),
            ],
        )

        player: dict[str, Any] | None = None
        stats: list[dict[str, Any]] = []
        teams: list[dict[str, Any]] = []
        fixtures: list[dict[str, Any]] = []

        for row in rows:
            kind = row["row_kind"]
            data = _payload(row)
            if kind == "player":
                player = data
                player["profile_url"] = f"/players/{player_id}"
            elif kind == "stat":
                stats.append(data)
            elif kind == "team":
                data["profile_url"] = f"/teams/{data['id']}"
                teams.append(data)
            elif kind == "fixture":
                data["profile_url"] = f"/games/{data['id']}"
                fixtures.append(data)

        if player is None:
            raise LookupError(f"Player {player_id} not found for season {season_id}")

        return {
            "player": player,
            "stats": _rank_stats(
                stats,
                (
                    "rating",
                    "appearance",
                    "minute",
                    "goal",
                    "assist",
                    "expected goal",
                    "xg",
                    "shot",
                    "pass",
                    "key pass",
                    "tackle",
                    "interception",
                    "duel",
                    "save",
                    "clean sheet",
                ),
                12,
            ),
            "teams": teams,
            "recent_fixtures": fixtures,
            "source": "bigquery",
        }
