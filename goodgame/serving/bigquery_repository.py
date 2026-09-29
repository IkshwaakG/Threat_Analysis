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
BQ_MAX_BYTES_BILLED = int(
    os.environ.get("GOODGAME_BIGQUERY_MAX_BYTES_BILLED", "1000000000")
)
BQ_QUERY_TIMEOUT_SECONDS = float(
    os.environ.get("GOODGAME_BIGQUERY_TIMEOUT_SECONDS", "20")
)


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


def _profile_stat_value(value: Any, label: str = "", matches_played: int | None = None) -> Any:
    """Flatten Sportmonks season-stat objects into a meaningful display scalar."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            cleaned = value.strip().rstrip("%")
            try:
                return float(cleaned) if "." in cleaned else int(cleaned)
            except ValueError:
                return value

    normalized = label.casefold().replace("_", " ").replace("-", " ")

    if isinstance(value, dict):
        # Season statistics frequently arrive as {"all": {...}, "home": {...}, "away": {...}}.
        if isinstance(value.get("all"), dict):
            all_value = value["all"]
            prefer_average = any(
                token in normalized
                for token in (
                    "possession",
                    "percentage",
                    "accuracy",
                    "rating",
                    "average",
                    "per game",
                    "per match",
                )
            )
            preferred_keys = (
                ("average", "percentage", "value", "count", "total")
                if prefer_average
                else ("count", "total", "value", "average", "percentage")
            )
            for key in preferred_keys:
                if key in all_value and not isinstance(all_value[key], (dict, list)):
                    return all_value[key]

        prefer_average = any(
            token in normalized
            for token in (
                "possession",
                "percentage",
                "accuracy",
                "rating",
                "average",
                "per game",
                "per match",
            )
        )
        preferred_keys = (
            ("average", "percentage", "value", "count", "total")
            if prefer_average
            else ("count", "total", "value", "average", "percentage")
        )
        for key in preferred_keys:
            if key in value and not isinstance(value[key], (dict, list)):
                return value[key]

        return None

    scalar = _stat_value(value)
    if (
        isinstance(scalar, (int, float))
        and matches_played
        and matches_played > 0
        and "possession" in normalized
        and scalar > 100
    ):
        return round(float(scalar) / matches_played, 2)
    return scalar


def _coordinate_pair(value: Any) -> tuple[float, float] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        if "x" in value and "y" in value:
            try:
                x = float(value["x"])
                y = float(value["y"])
            except (TypeError, ValueError):
                return None
        else:
            for key in ("coordinates", "location", "position", "point"):
                if key in value:
                    pair = _coordinate_pair(value.get(key))
                    if pair is not None:
                        return pair
            return None
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            x = float(value[0])
            y = float(value[1])
        except (TypeError, ValueError):
            return None
    else:
        return None

    if abs(x) <= 1.5 and abs(y) <= 1.5:
        x *= 100.0
        y *= 100.0
    elif x <= 120.0 and y <= 80.0 and (x > 100.0 or y > 100.0):
        x = x / 120.0 * 100.0
        y = y / 80.0 * 100.0

    return (
        round(max(0.0, min(100.0, x)), 3),
        round(max(0.0, min(100.0, y)), 3),
    )


def _event_ball_path(raw: Any, *, is_home: bool | None, event_type: str) -> dict[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, dict):
        return None

    shot = raw.get("shot") if isinstance(raw.get("shot"), dict) else {}

    start = None
    for candidate in (
        raw.get("coordinates"),
        raw.get("location"),
        raw.get("start_coordinates"),
        raw.get("start_location"),
        shot.get("coordinates"),
        shot.get("location"),
    ):
        start = _coordinate_pair(candidate)
        if start is not None:
            break

    end = None
    for candidate in (
        raw.get("end_coordinates"),
        raw.get("end_location"),
        raw.get("goal_coordinates"),
        raw.get("target_coordinates"),
        shot.get("end_coordinates"),
        shot.get("end_location"),
        shot.get("goal_coordinates"),
    ):
        end = _coordinate_pair(candidate)
        if end is not None:
            break

    normalized = event_type.casefold()
    if start is not None and end is None and "goal" in normalized and is_home is not None:
        end = (100.0 if is_home else 0.0, 50.0)

    if start is None:
        return None

    return {
        "start": {"x": start[0], "y": start[1]},
        "end": {"x": end[0], "y": end[1]} if end is not None else None,
    }


def _event_player_positions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, dict):
        return []

    candidates = raw.get("player_positions") or raw.get("positions") or raw.get("tracking")
    if not isinstance(candidates, list):
        return []

    result: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        pair = _coordinate_pair(item)
        player_id = item.get("player_id") or item.get("id")
        if pair is None or player_id is None:
            continue
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            continue
        result.append({"player_id": player_id, "x": pair[0], "y": pair[1]})
    return result

def _event_detail(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}

    shot = raw.get("shot") if isinstance(raw.get("shot"), dict) else {}

    def first(*values: Any) -> Any:
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return None

    def scalar(value: Any) -> Any:
        if isinstance(value, dict):
            return first(
                value.get("value"),
                value.get("name"),
                value.get("label"),
                value.get("display_name"),
                value.get("developer_name"),
            )
        return value

    result = {
        "xg": scalar(first(raw.get("xg"), raw.get("expected_goals"), shot.get("xg"), shot.get("expected_goals"))),
        "xgot": scalar(first(raw.get("xgot"), raw.get("expected_goals_on_target"), shot.get("xgot"), shot.get("expected_goals_on_target"))),
        "body_part": scalar(first(raw.get("body_part"), raw.get("bodypart"), shot.get("body_part"), shot.get("bodypart"))),
        "situation": scalar(first(raw.get("situation"), raw.get("play_pattern"), shot.get("situation"), shot.get("play_pattern"))),
        "outcome": scalar(first(raw.get("outcome"), raw.get("result"), shot.get("outcome"), shot.get("result"))),
        "shot_type": scalar(first(raw.get("shot_type"), shot.get("type"), raw.get("type"))),
    }
    return {key: value for key, value in result.items() if value not in (None, "")}



def _profile_stat_rows(
    rows: list[dict[str, Any]],
    *,
    matches_played: int | None = None,
) -> list[dict[str, Any]]:
    """Prefer season totals and flatten provider composites; otherwise aggregate fixtures."""
    season_rows = [row for row in rows if row.get("fixture_id") is None]
    if season_rows:
        cleaned: list[dict[str, Any]] = []
        for row in season_rows:
            current = dict(row)
            label = str(
                current.get("developer_name")
                or current.get("name")
                or current.get("code")
                or ""
            )
            current["value"] = _profile_stat_value(
                current.get("value"),
                label,
                matches_played,
            )
            if current["value"] is not None:
                cleaned.append(current)
        return cleaned

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(
            row.get("type_id")
            or row.get("developer_name")
            or row.get("name")
            or row.get("code")
            or "stat"
        )
        grouped.setdefault(key, []).append(row)

    aggregate_rows: list[dict[str, Any]] = []
    for group in grouped.values():
        base = dict(group[0])
        label = str(
            base.get("developer_name")
            or base.get("name")
            or base.get("code")
            or ""
        ).casefold().replace("_", " ").replace("-", " ")

        values: list[float] = []
        for row in group:
            value = _profile_stat_value(row.get("value"), label, matches_played)
            if isinstance(value, bool):
                values.append(1.0 if value else 0.0)
            elif isinstance(value, (int, float)):
                values.append(float(value))
            elif isinstance(value, str):
                cleaned = value.strip().rstrip("%")
                try:
                    values.append(float(cleaned))
                except ValueError:
                    pass

        if values:
            should_average = any(
                token in label
                for token in (
                    "rating",
                    "average",
                    "accuracy",
                    "percentage",
                    "possession",
                    "per game",
                    "per match",
                )
            )
            value = sum(values) / len(values) if should_average else sum(values)
            if all(float(item).is_integer() for item in values) and not should_average:
                value = int(value)
            else:
                value = round(value, 2)
            base["value"] = value
        else:
            base["value"] = _profile_stat_value(base.get("value"), label, matches_played)

        base["fixture_id"] = None
        aggregate_rows.append(base)

    return aggregate_rows


def _comparison_stats(
    home_rows: list[dict[str, Any]],
    away_rows: list[dict[str, Any]],
    keywords: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    def keyed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(
                row.get("developer_name")
                or row.get("name")
                or row.get("code")
                or row.get("type_id")
                or ""
            ).casefold()
            if key:
                result[key] = row
        return result

    home = keyed(home_rows)
    away = keyed(away_rows)
    comparisons: list[dict[str, Any]] = []

    for keyword in keywords:
        match_key = next(
            (
                key
                for key in list(home.keys()) + list(away.keys())
                if keyword in key.replace("_", " ").replace("-", " ")
            ),
            None,
        )
        if match_key is None:
            continue
        home_row = home.get(match_key, {})
        away_row = away.get(match_key, {})
        label = (
            home_row.get("name")
            or away_row.get("name")
            or home_row.get("developer_name")
            or away_row.get("developer_name")
            or keyword.title()
        )
        comparisons.append(
            {
                "type_id": home_row.get("type_id") or away_row.get("type_id"),
                "name": label,
                "developer_name": home_row.get("developer_name")
                or away_row.get("developer_name"),
                "group": home_row.get("stat_group") or away_row.get("stat_group"),
                "value": f"{_stat_value(home_row.get('value')) if home_row else '–'} - "
                f"{_stat_value(away_row.get('value')) if away_row else '–'}",
            }
        )
        if len(comparisons) >= limit:
            break

    return comparisons


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
            "period_id": row.get("period_id"),
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
        config = bigquery.QueryJobConfig(
            query_parameters=params,
            maximum_bytes_billed=BQ_MAX_BYTES_BILLED,
            use_query_cache=True,
        )
        job = self.client.query(sql, job_config=config)
        return list(job.result(timeout=BQ_QUERY_TIMEOUT_SECONDS))

    def list_competitions(self) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT DISTINCT
              l.league_id AS id,
              l.name
            FROM {self._table("leagues")} l
            WHERE EXISTS (
              SELECT 1
              FROM {self._table("fixtures")} f
              WHERE f.league_id = l.league_id
            )
            ORDER BY l.name
            """,
            [],
        )
        return [{"id": int(row["id"]), "name": str(row["name"])} for row in rows]

    def list_seasons(self, competition_id: int) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT DISTINCT
              s.season_id AS id,
              s.name,
              s.league_id AS competition_id,
              s.starting_at
            FROM {self._table("seasons")} s
            WHERE s.league_id = @competition_id
              AND EXISTS (
                SELECT 1
                FROM {self._table("fixtures")} f
                WHERE f.league_id = s.league_id
                  AND f.season_id = s.season_id
              )
            ORDER BY s.starting_at DESC, s.season_id DESC
            """,
            [bigquery.ScalarQueryParameter("competition_id", "INT64", competition_id)],
        )
        return [
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "competition_id": int(row["competition_id"]),
            }
            for row in rows
        ]

    def list_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        rows = self._query(
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
              WHERE fp.league_id = @competition_id
                AND fp.season_id = @season_id
              GROUP BY fp.fixture_id
            )
            SELECT
              f.fixture_id AS id,
              CAST(f.starting_at AS STRING) AS date,
              COALESCE(p.home_team, SPLIT(f.name, ' vs ')[SAFE_OFFSET(0)], 'Home') AS home_team,
              COALESCE(p.away_team, SPLIT(f.name, ' vs ')[SAFE_OFFSET(1)], 'Away') AS away_team
            FROM {self._table("fixtures")} f
            LEFT JOIN participants p USING (fixture_id)
            WHERE f.league_id = @competition_id
              AND f.season_id = @season_id
            ORDER BY f.starting_at DESC, f.fixture_id DESC
            """,
            [
                bigquery.ScalarQueryParameter("competition_id", "INT64", competition_id),
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
            ],
        )
        return [dict(row.items()) for row in rows]

    def list_teams(self, season_id: int, competition_id: int | None = None) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT DISTINCT team_id AS id, name, short_code, image_path
            FROM {self._table("teams")}
            WHERE season_id = @season_id
              AND (@competition_id IS NULL OR league_id = @competition_id)
            ORDER BY name
            """,
            [
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
                bigquery.ScalarQueryParameter("competition_id", "INT64", competition_id),
            ],
        )
        return [dict(row.items()) for row in rows]

    def list_players(self, season_id: int, competition_id: int | None = None) -> list[dict[str, Any]]:
        rows = self._query(
            f"""
            SELECT DISTINCT
              player_id AS id,
              COALESCE(display_name, name, common_name) AS name,
              position_id,
              image_path
            FROM {self._table("players")}
            WHERE season_id = @season_id
              AND (@competition_id IS NULL OR league_id = @competition_id)
            ORDER BY name
            """,
            [
                bigquery.ScalarQueryParameter("season_id", "INT64", season_id),
                bigquery.ScalarQueryParameter("competition_id", "INT64", competition_id),
            ],
        )
        return [dict(row.items()) for row in rows]

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
            fixture_facts AS (
              SELECT *
              FROM ${self._table("fixture_facts")}
              WHERE fixture_id = @fixture_id
              LIMIT 1
            ),
            season_standings AS (
              SELECT
                s.team_id,
                t.name AS team_name,
                t.image_path AS team_logo,
                s.position,
                s.points,
                s.details
              FROM ${self._table("standings")} s
              CROSS JOIN fixture f
              LEFT JOIN ${self._table("teams")} t
                ON t.team_id = s.team_id
               AND t.league_id = s.league_id
               AND t.season_id = s.season_id
              WHERE s.league_id = f.league_id
                AND s.season_id = f.season_id
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
                s.period_id,
                s.team_id,
                s.player_id,
                s.entity_type,
                s.entity_id,
                s.period_id,
                s.type_id,
                s.value,
                ty.name,
                ty.code,
                ty.developer_name,
                ty.stat_group
              FROM {self._table("statistics")} s
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE s.fixture_id = @fixture_id
                AND (
                  (s.player_id IS NOT NULL AND s.entity_type = 'player')
                  OR (s.player_id IS NULL AND s.team_id IS NOT NULL AND s.entity_type = 'fixture')
                  OR (s.player_id IS NULL AND s.team_id IS NULL AND s.entity_type = 'fixture')
                )
            ),
            goals AS (
              SELECT e.team_id, COUNT(*) AS goals
              FROM {self._table("fixture_events")} e
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE e.fixture_id = @fixture_id
                AND LOWER(COALESCE(ty.name, ty.developer_name, '')) LIKE '%goal%'
              GROUP BY e.team_id
            ),
            events AS (
              SELECT
                e.event_id,
                e.minute,
                e.extra_minute,
                e.type_id,
                e.team_id,
                e.player_id,
                e.player_name,
                e.related_player_name,
                e.info,
                e.addition,
                e.result,
                e.raw_event,
                ty.name AS type_name,
                ty.developer_name AS type_developer_name
              FROM {self._table("fixture_events")} e
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE e.fixture_id = @fixture_id
            ),
            normalized_timeline AS (
              SELECT
                t.timeline_id,
                t.minute,
                t.extra_minute,
                t.type_id,
                t.team_id,
                t.player_id,
                t.related_player_id,
                t.info,
                t.addition,
                t.result,
                t.sort_order,
                t.raw_timeline,
                ty.name AS type_name,
                ty.developer_name AS type_developer_name
              FROM {self._table("fixture_timeline")} t
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE t.fixture_id = @fixture_id
            ),
            raw_timeline AS (
              SELECT
                SAFE_CAST(JSON_VALUE(item, '$.id') AS INT64) AS timeline_id,
                SAFE_CAST(JSON_VALUE(item, '$.minute') AS INT64) AS minute,
                SAFE_CAST(JSON_VALUE(item, '$.extra_minute') AS INT64) AS extra_minute,
                SAFE_CAST(JSON_VALUE(item, '$.type_id') AS INT64) AS type_id,
                SAFE_CAST(JSON_VALUE(item, '$.participant_id') AS INT64) AS team_id,
                SAFE_CAST(JSON_VALUE(item, '$.player_id') AS INT64) AS player_id,
                SAFE_CAST(JSON_VALUE(item, '$.related_player_id') AS INT64) AS related_player_id,
                JSON_VALUE(item, '$.info') AS info,
                JSON_VALUE(item, '$.addition') AS addition,
                JSON_VALUE(item, '$.result') AS result,
                SAFE_CAST(JSON_VALUE(item, '$.sort_order') AS INT64) AS sort_order,
                item AS raw_timeline,
                CAST(NULL AS STRING) AS type_name,
                CAST(NULL AS STRING) AS type_developer_name
              FROM (
                SELECT payload
                FROM {self._raw_table("api_responses")}
                WHERE provider = 'sportmonks'
                  AND entity_type = 'fixture'
                  AND SAFE_CAST(JSON_VALUE(payload, '$.id') AS INT64) = @fixture_id
                ORDER BY fetched_at DESC
                LIMIT 1
              ) raw,
              UNNEST(IFNULL(JSON_QUERY_ARRAY(raw.payload, '$.timeline'), [])) AS item
            ),
            timeline AS (
              SELECT * FROM normalized_timeline
              UNION ALL
              SELECT * FROM raw_timeline
              WHERE NOT EXISTS (SELECT 1 FROM normalized_timeline)
            ),
            scores AS (
              SELECT score_id, type_id, team_id, goals, participant, description
              FROM {self._table("fixture_scores")}
              WHERE fixture_id = @fixture_id
            ),
            venue AS (
              SELECT v.*
              FROM fixture f
              JOIN {self._table("venues")} v ON v.venue_id = f.venue_id
              LIMIT 1
            ),
            weather AS (
              SELECT *
              FROM {self._table("fixture_weather")}
              WHERE fixture_id = @fixture_id
              LIMIT 1
            ),
            sidelined AS (
              SELECT
                s.sideline_id,
                s.player_id,
                s.type_id,
                s.start_date,
                s.end_date,
                s.games_missed,
                p.display_name AS player_name,
                ty.name AS type_name
              FROM {self._table("fixture_sidelined")} s
              LEFT JOIN {self._table("players")} p
                ON p.player_id = s.player_id
               AND p.league_id = s.league_id
               AND p.season_id = s.season_id
              LEFT JOIN {self._table("types")} ty USING (type_id)
              WHERE s.fixture_id = @fixture_id
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
                f.stage_id,
                f.round_id,
                f.venue_id,
                f.leg,
                f.length,
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

            UNION ALL

            SELECT
              'event' AS row_kind,
              TO_JSON_STRING(STRUCT(
                e.event_id AS id,
                e.minute,
                e.extra_minute,
                COALESCE(e.type_name, e.type_developer_name, e.info, 'event') AS type,
                e.team_id,
                e.player_id,
                e.player_name AS player,
                e.related_player_name,
                COALESCE(e.info, e.addition, e.type_name, e.type_developer_name, 'Event') AS text,
                e.result AS class,
                e.raw_event
              )) AS payload
            FROM events e

            UNION ALL

            SELECT
              'timeline' AS row_kind,
              TO_JSON_STRING(STRUCT(
                t.timeline_id AS id,
                t.minute,
                t.extra_minute,
                COALESCE(t.type_name, t.type_developer_name, t.addition, 'timeline') AS type,
                t.team_id,
                t.player_id,
                t.related_player_id,
                COALESCE(t.addition, t.info, t.type_name, t.type_developer_name, 'Timeline event') AS text,
                t.result AS class,
                t.sort_order,
                t.raw_timeline
              )) AS payload
            FROM timeline t

            UNION ALL

            SELECT
              'score' AS row_kind,
              TO_JSON_STRING(STRUCT(
                s.score_id AS id,
                s.type_id,
                s.team_id,
                s.goals,
                s.participant,
                s.description
              )) AS payload
            FROM scores s

            UNION ALL

            SELECT
              'venue' AS row_kind,
              TO_JSON_STRING(STRUCT(
                v.venue_id AS id,
                v.name,
                v.address,
                v.city_name,
                v.latitude,
                v.longitude,
                v.capacity,
                v.image_path,
                v.surface
              )) AS payload
            FROM venue v

            UNION ALL

            SELECT
              'weather' AS row_kind,
              TO_JSON_STRING(STRUCT(
                w.temperature_day,
                w.temperature_current,
                w.feels_like_day,
                w.feels_like_current,
                w.wind_speed,
                w.wind_direction,
                w.humidity,
                w.pressure,
                w.clouds,
                w.description,
                w.icon,
                w.metric
              )) AS payload
            FROM weather w

            UNION ALL

            SELECT
              'sidelined' AS row_kind,
              TO_JSON_STRING(STRUCT(
                s.sideline_id AS id,
                s.player_id,
                s.player_name,
                s.type_id,
                s.type_name,
                CAST(s.start_date AS STRING) AS start_date,
                CAST(s.end_date AS STRING) AS end_date,
                s.games_missed
              )) AS payload
            FROM sidelined s

            UNION ALL

            SELECT
              'raw_fact' AS row_kind,
              TO_JSON_STRING(STRUCT(
                rf.state_name,
                rf.stage_name,
                rf.round_name,
                rf.league_name,
                rf.match_length,
                rf.leg,
                rf.attendance,
                rf.referee_id,
                rf.referee_name,
                rf.referee_image,
                rf.referee_country
              )) AS payload
            FROM fixture_facts rf

            UNION ALL

            SELECT
              'standing' AS row_kind,
              TO_JSON_STRING(STRUCT(
                s.team_id,
                s.team_name,
                s.team_logo,
                s.position,
                s.points,
                s.details
              )) AS payload
            FROM season_standings s
            """,
            [bigquery.ScalarQueryParameter("fixture_id", "INT64", fixture_id)],
        )

        fixture: dict[str, Any] | None = None
        teams_by_location: dict[str, dict[str, Any]] = {}
        players_by_id: dict[int, dict[str, Any]] = {}
        team_stats: dict[int, list[dict[str, Any]]] = {}
        player_stats: dict[int, list[dict[str, Any]]] = {}
        game_stats: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        scores: list[dict[str, Any]] = []
        venue: dict[str, Any] | None = None
        weather: dict[str, Any] | None = None
        sidelined: list[dict[str, Any]] = []
        raw_fact: dict[str, Any] = {}
        standings: list[dict[str, Any]] = []

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
            elif kind == "event":
                team_id = data.get("team_id")
                data["is_home"] = (
                    int(team_id) == int(teams_by_location["home"]["id"])
                    if team_id is not None and "home" in teams_by_location
                    else None
                )
                normalized = str(data.get("type") or "event").casefold()
                if "goal" in normalized:
                    data["type"] = "goal"
                elif "substitution" in normalized:
                    data["type"] = "substitution"
                    data["player_in"] = data.get("related_player_name")
                    data["player_out"] = data.get("player")
                elif "card" in normalized:
                    data["type"] = "card"
                elif "shot" in normalized:
                    data["type"] = "shot"
                raw_event = data.pop("raw_event", None)
                data["ball_path"] = _event_ball_path(
                    raw_event,
                    is_home=data.get("is_home"),
                    event_type=str(data.get("type") or "event"),
                )
                data["player_positions"] = _event_player_positions(raw_event)
                data["detail"] = _event_detail(raw_event)
                events.append(data)
            elif kind == "timeline":
                team_id = data.get("team_id")
                data["is_home"] = (
                    int(team_id) == int(teams_by_location["home"]["id"])
                    if team_id is not None and "home" in teams_by_location
                    else None
                )
                raw_timeline = data.pop("raw_timeline", None)
                data["ball_path"] = _event_ball_path(
                    raw_timeline,
                    is_home=data.get("is_home"),
                    event_type=str(data.get("type") or data.get("text") or "timeline"),
                )
                timeline.append(data)
            elif kind == "score":
                scores.append(data)
            elif kind == "venue":
                venue = data
            elif kind == "weather":
                weather = data
            elif kind == "sidelined":
                sidelined.append(data)
            elif kind == "raw_fact":
                raw_fact = data
            elif kind == "standing":
                standings.append(data)

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
                30,
            )

        players = []
        for player in players_by_id.values():
            player["match_stats"] = _rank_stats(
                player_stats.get(int(player["player_id"]), []),
                player_keywords,
                40,
            )
            players.append(player)

        players.sort(
            key=lambda player: (
                0 if player.get("team_location") == "home" else 1,
                player.get("formation_position") or 999,
                player.get("jersey_number") or 999,
            )
        )

        default_game_stats = _comparison_stats(
            team_stats.get(int(home["id"]), []),
            team_stats.get(int(away["id"]), []),
            (
                "possession",
                "expected goal",
                "xg",
                "shots on target",
                "shot",
                "pass",
                "corner",
                "foul",
                "offside",
                "save",
            ),
            10,
        )
        extra_game_stats = _rank_stats(
            game_stats,
            ("attendance", "duration", "weather"),
            3,
        )

        events.sort(
            key=lambda event: (
                event.get("minute") if event.get("minute") is not None else 999,
                event.get("extra_minute") if event.get("extra_minute") is not None else 0,
                event.get("id") if event.get("id") is not None else 0,
            )
        )

        timeline.sort(
            key=lambda item: (
                item.get("minute") if item.get("minute") is not None else 999,
                item.get("extra_minute") if item.get("extra_minute") is not None else 0,
                item.get("sort_order") if item.get("sort_order") is not None else 999,
                item.get("id") if item.get("id") is not None else 0,
            )
        )

        return {
            "fixture": fixture,
            "home_team": home,
            "away_team": away,
            "game_stats": default_game_stats + extra_game_stats,
            "players": players,
            "events": events,
            "timeline": timeline,
            "scores": scores,
            "venue": venue,
            "weather": weather,
            "sidelined": sidelined,
            "raw_fact": raw_fact,
            "standings": standings,
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
                s.fixture_id,
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
            team_results AS (
              SELECT
                COUNT(DISTINCT f.fixture_id) AS matches_played,
                COUNT(DISTINCT IF(me.winner IS TRUE, f.fixture_id, NULL)) AS wins,
                COUNT(DISTINCT IF(
                  NOT EXISTS (
                    SELECT 1
                    FROM {self._table("fixture_participants")} allp
                    WHERE allp.fixture_id = f.fixture_id
                      AND allp.winner IS TRUE
                  ),
                  f.fixture_id,
                  NULL
                )) AS draws
              FROM {self._table("fixtures")} f
              JOIN {self._table("fixture_participants")} me
                ON me.fixture_id = f.fixture_id
               AND me.team_id = @team_id
              WHERE f.season_id = @season_id
                AND (@league_id IS NULL OR f.league_id = @league_id)
                AND f.starting_at <= CURRENT_TIMESTAMP()
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
                fixture_id,
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
              'summary' AS row_kind,
              TO_JSON_STRING(STRUCT(
                matches_played,
                wins,
                draws,
                GREATEST(matches_played - wins - draws, 0) AS losses,
                (wins * 3 + draws) AS points
              )) AS payload
            FROM team_results

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
        summary: dict[str, Any] = {}

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
            elif kind == "summary":
                summary = data

        if team is None:
            raise LookupError(f"Team {team_id} not found for season {season_id}")

        season_stats = _rank_stats(
            _profile_stat_rows(
                stats,
                matches_played=int(summary.get("matches_played") or 0),
            ),
            (
                "goal",
                "expected goal",
                "xg",
                "possession",
                "shot",
                "pass",
                "clean sheet",
                "corner",
                "foul",
                "offside",
            ),
            30,
        )

        # Results-derived values are authoritative for season result cards.
        derived_stats = [
            {"name": "Points", "developer_name": "points", "value": summary.get("points")},
            {"name": "Matches", "developer_name": "matches_played", "value": summary.get("matches_played")},
            {"name": "Wins", "developer_name": "wins", "value": summary.get("wins")},
            {"name": "Draws", "developer_name": "draws", "value": summary.get("draws")},
            {"name": "Losses", "developer_name": "losses", "value": summary.get("losses")},
        ]

        return {
            "team": team,
            "summary": summary,
            "stats": derived_stats + season_stats,
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
                s.fixture_id,
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
            player_summary AS (
              SELECT
                COUNT(DISTINCT l.fixture_id) AS appearances,
                COUNT(DISTINCT IF(l.lineup_type_id = 11, l.fixture_id, NULL)) AS starts
              FROM {self._table("fixture_lineups")} l
              JOIN {self._table("fixtures")} f USING (fixture_id)
              WHERE l.player_id = @player_id
                AND l.season_id = @season_id
                AND (@league_id IS NULL OR l.league_id = @league_id)
                AND f.starting_at <= CURRENT_TIMESTAMP()
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
                fixture_id,
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
              'summary' AS row_kind,
              TO_JSON_STRING(STRUCT(
                appearances,
                starts
              )) AS payload
            FROM player_summary

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
        summary: dict[str, Any] = {}

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
            elif kind == "summary":
                summary = data

        if player is None:
            raise LookupError(f"Player {player_id} not found for season {season_id}")

        season_stats = _rank_stats(
            _profile_stat_rows(
                stats,
                matches_played=int(summary.get("appearances") or 0),
            ),
            (
                "rating",
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
            40,
        )

        derived_stats = [
            {"name": "Appearances", "developer_name": "appearances", "value": summary.get("appearances")},
            {"name": "Starts", "developer_name": "starts", "value": summary.get("starts")},
        ]

        return {
            "player": player,
            "summary": summary,
            "stats": derived_stats + season_stats,
            "teams": teams,
            "recent_fixtures": fixtures,
            "source": "bigquery",
        }
