"""FastAPI surface for the GoodGame web/AR/VR frontends."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from goodgame.ingestion.bigquery.provider import BigQueryProvider
from goodgame.serving.bigquery_repository import BigQueryServingRepository
from goodgame.serving.repository_factory import create_serving_repository
from goodgame.pipeline import GoodGamePipeline


app = FastAPI(title="GoodGame API", version="0.3.0")

_allowed_origins = [
    item.strip()
    for item in os.environ.get(
        "GOODGAME_WEB_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if item.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _provider() -> BigQueryProvider:
    # Compatibility path for older endpoints.
    return BigQueryProvider()


def _serving_repository():
    # Primary frontend read path. DATA_MODE=gcp uses BigQuery; DATA_MODE=demo
    # reads the packaged snapshot. The API contract stays identical.
    return create_serving_repository()


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _nested_name(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("name", "developer_name", "code", "display_name"):
            current = value.get(key)
            if current:
                return str(current)
    if isinstance(value, str):
        return value
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "captain"}
    if isinstance(value, dict):
        for key in ("value", "total", "count"):
            if key in value:
                return _truthy(value[key])
    return False


def _scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "total", "count"):
            if key in value:
                return _scalar(value[key])
    return value


def _lineup_details(lineup: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    captain = bool(lineup.get("captain"))
    statistics: dict[str, Any] = {}

    for detail in lineup.get("details", []) or []:
        if not isinstance(detail, dict):
            continue
        type_payload = detail.get("type") if isinstance(detail.get("type"), dict) else {}
        type_id = _integer(detail.get("type_id", type_payload.get("id")))
        label = (
            _nested_name(type_payload)
            or detail.get("developer_name")
            or detail.get("code")
            or f"type_{type_id}" if type_id is not None else "stat"
        )
        label = str(label).strip().casefold().replace(" ", "_").replace("-", "_")
        value = _scalar(detail.get("value"))

        if type_id == 40 or label in {"captain", "captain_status"}:
            captain = captain or _truthy(value)
            continue

        if value is not None:
            statistics[label] = value

    return captain, statistics


def _role(lineup: dict[str, Any]) -> str:
    for key in ("detailedPosition", "detailed_position", "position"):
        value = lineup.get(key)
        role = _nested_name(value)
        if role:
            return role

    position_id = _integer(lineup.get("position_id"))
    return {
        24: "Goalkeeper",
        25: "Defender",
        26: "Midfielder",
        27: "Attacker",
    }.get(position_id, "Player")


def _formation_cell(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    parts = re.findall(r"\d+", str(value))
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    return None


def _position_team(rows: list[dict[str, Any]], *, home: bool) -> list[dict[str, Any]]:
    starters = [row for row in rows if _integer(row.get("type_id")) == 11]
    if not starters:
        starters = [row for row in rows if row.get("formation_field") is not None][:11]
    starters = starters[:11]

    parsed = [(row, _formation_cell(row.get("formation_field"))) for row in starters]
    valid_cells = [cell for _, cell in parsed if cell is not None]

    line_numbers = sorted({cell[0] for cell in valid_cells})
    line_index = {line: index for index, line in enumerate(line_numbers)}
    per_line: dict[int, list[tuple[dict[str, Any], tuple[int, int]]]] = {}
    for row, cell in parsed:
        if cell is not None:
            per_line.setdefault(cell[0], []).append((row, cell))

    result: list[dict[str, Any]] = []

    for index, (row, cell) in enumerate(parsed):
        if cell is not None and line_numbers:
            line, slot = cell
            current_line = per_line.get(line, [])
            max_slot = max((current_cell[1] for _, current_cell in current_line), default=len(current_line))
            if max_slot <= 0:
                max_slot = max(1, len(current_line))

            if len(line_numbers) == 1:
                x = 50.0
            else:
                x = 7.5 + (line_index[line] / (len(line_numbers) - 1)) * 65.0
            y = (slot / (max_slot + 1)) * 100.0
        else:
            role = _role(row).casefold()
            if "goal" in role:
                x = 7.5
            elif "def" in role or "back" in role:
                x = 24.0
            elif "mid" in role:
                x = 45.0
            else:
                x = 68.0
            same_role = [item for item in starters if _role(item).casefold() == role]
            role_index = same_role.index(row) if row in same_role else index
            y = ((role_index + 1) / (len(same_role) + 1)) * 100.0

        if not home:
            x = 100.0 - x

        captain, statistics = _lineup_details(row)
        player = row.get("player") if isinstance(row.get("player"), dict) else {}
        player_name = (
            row.get("player_name")
            or player.get("display_name")
            or player.get("common_name")
            or player.get("name")
            or f"Player {row.get('player_id', '')}"
        )

        result.append(
            {
                "player_id": _integer(row.get("player_id", player.get("id"))),
                "name": str(player_name),
                "number": _integer(row.get("jersey_number")) or 0,
                "captain": captain,
                "role": _role(row),
                "formation_field": row.get("formation_field"),
                "formation_position": _integer(row.get("formation_position")),
                "x": round(max(2.0, min(98.0, x)), 2),
                "y": round(max(2.0, min(98.0, y)), 2),
                "stats": statistics,
            }
        )

    return result


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def _hex_values(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return _hex_values(json.loads(stripped))
            except (TypeError, ValueError):
                pass
        results.extend(_HEX_RE.findall(value))
    elif isinstance(value, dict):
        for current in value.values():
            results.extend(_hex_values(current))
    elif isinstance(value, list):
        for current in value:
            results.extend(_hex_values(current))
    return list(dict.fromkeys(results))


def _side_color(payload: Any, aliases: tuple[str, ...]) -> tuple[str | None, list[str]]:
    if not isinstance(payload, dict):
        return None, []

    lowered = {str(key).casefold(): value for key, value in payload.items()}
    for alias in aliases:
        value = lowered.get(alias.casefold())
        colors = _hex_values(value)
        if colors:
            return colors[0], colors

    return None, []


def _team_colors(fixture: dict[str, Any]) -> dict[str, Any]:
    home_color: str | None = None
    away_color: str | None = None
    home_kits: list[str] = []
    away_kits: list[str] = []
    source = "fallback"

    candidates: list[Any] = []
    if fixture.get("colors"):
        candidates.append(fixture.get("colors"))

    for metadata in fixture.get("metadata", []) or []:
        if not isinstance(metadata, dict):
            continue
        type_payload = metadata.get("type") if isinstance(metadata.get("type"), dict) else {}
        label = (
            _nested_name(type_payload)
            or metadata.get("key")
            or metadata.get("name")
            or metadata.get("developer_name")
            or ""
        )
        searchable = " ".join(str(key) for key in metadata.keys()).casefold()
        if "color" in str(label).casefold() or "colour" in str(label).casefold() or "color" in searchable or "colour" in searchable:
            candidates.append(metadata.get("values", metadata.get("value", metadata)))

    for candidate in candidates:
        if home_color is None:
            home_color, home_kits = _side_color(
                candidate,
                ("home", "localteam", "local_team", "home_team", "homecolor", "home_color"),
            )
        if away_color is None:
            away_color, away_kits = _side_color(
                candidate,
                ("away", "visitorteam", "visitor_team", "away_team", "awaycolor", "away_color"),
            )

        if (home_color is None or away_color is None) and isinstance(candidate, dict):
            all_colors = _hex_values(candidate)
            if len(all_colors) >= 2:
                home_color = home_color or all_colors[0]
                away_color = away_color or all_colors[1]
                home_kits = home_kits or [all_colors[0]]
                away_kits = away_kits or [all_colors[1]]

        if home_color and away_color:
            source = "sportmonks_metadata"
            break

    return {
        "home": {
            "primary": home_color or "#32e58c",
            "kit_colors": home_kits or [home_color or "#32e58c"],
        },
        "away": {
            "primary": away_color or "#edf3f0",
            "kit_colors": away_kits or [away_color or "#edf3f0"],
        },
        "source": source,
    }


def _participant(fixture: dict[str, Any], team_id: int) -> dict[str, Any]:
    for participant in fixture.get("participants", []) or []:
        if isinstance(participant, dict) and _integer(participant.get("id")) == team_id:
            return participant
    return {}


def _ball_coordinates(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        fixture.get("ballcoordinates")
        or fixture.get("ballCoordinates")
        or fixture.get("ball_coordinates")
        or []
    )
    rows = [row for row in rows if isinstance(row, dict)]

    if len(rows) > 240:
        step = max(1, len(rows) // 240)
        rows = rows[::step][:240]

    normalized: list[dict[str, Any]] = []
    for row in rows:
        raw_x = _number(row.get("x"))
        raw_y = _number(row.get("y"))
        if raw_x is None or raw_y is None:
            continue

        x = ((raw_x - 0.01) / 1.0) * 100.0
        y = ((raw_y + 0.02) / 1.04) * 100.0
        normalized.append(
            {
                "x": round(max(0.0, min(100.0, x)), 3),
                "y": round(max(0.0, min(100.0, y)), 3),
                "timer": row.get("timer"),
                "period_id": _integer(row.get("period_id")),
            }
        )
    return normalized


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/competitions")
def competitions() -> list[dict[str, Any]]:
    try:
        rows = _serving_repository().list_competitions()
    except (ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    unique: dict[int, dict[str, Any]] = {}
    for row in rows:
        competition_id = _integer(row.get("competition_id"))
        competition_name = row.get("competition_name")
        if competition_id is not None and competition_name:
            unique[competition_id] = {
                "id": competition_id,
                "name": str(competition_name),
            }

    return sorted(unique.values(), key=lambda item: item["name"].casefold())



@app.get("/api/competitions/{competition_id}/seasons")
def seasons(competition_id: int) -> list[dict[str, Any]]:
    try:
        rows = _provider().list_competitions()
    except (ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return rows


@app.get("/api/competitions/{competition_id}/seasons/{season_id}/matches")
def matches(competition_id: int, season_id: int) -> list[dict[str, Any]]:
    try:
        rows = _serving_repository().list_matches(competition_id, season_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return rows


@app.get("/api/matches/{match_id}/visualization")
def match_visualization(match_id: int) -> dict[str, Any]:
    provider = _provider()

    try:
        fixture = provider.get_fixture(match_id)
        match = provider.get_match(match_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    colors = _team_colors(fixture)
    home_rows = [
        row
        for row in fixture.get("lineups", []) or []
        if isinstance(row, dict) and _integer(row.get("team_id")) == match.home_team.id
    ]
    away_rows = [
        row
        for row in fixture.get("lineups", []) or []
        if isinstance(row, dict) and _integer(row.get("team_id")) == match.away_team.id
    ]

    players: list[dict[str, Any]] = []
    for item in _position_team(home_rows, home=True):
        players.append({**item, "team": "home", "color": colors["home"]["primary"]})
    for item in _position_team(away_rows, home=False):
        players.append({**item, "team": "away", "color": colors["away"]["primary"]})

    home_participant = _participant(fixture, match.home_team.id)
    away_participant = _participant(fixture, match.away_team.id)
    league = fixture.get("league") if isinstance(fixture.get("league"), dict) else {}

    return {
        "match": {
            "id": match.id,
            "home_team": {
                "id": match.home_team.id,
                "name": match.home_team.name,
                "short_code": home_participant.get("short_code"),
                "logo": home_participant.get("image_path"),
                "color": colors["home"]["primary"],
                "kit_colors": colors["home"]["kit_colors"],
            },
            "away_team": {
                "id": match.away_team.id,
                "name": match.away_team.name,
                "short_code": away_participant.get("short_code"),
                "logo": away_participant.get("image_path"),
                "color": colors["away"]["primary"],
                "kit_colors": colors["away"]["kit_colors"],
            },
            "home_score": match.home_score,
            "away_score": match.away_score,
            "status": match.status,
            "competition_name": league.get("name"),
        },
        "players": players,
        "ball_coordinates": _ball_coordinates(fixture),
        "color_source": colors["source"],
        "lineup_source": "bigquery_football_core_fixture_lineups",
    }



def _team_payload(team: Any) -> dict[str, Any]:
    return {
        "id": team.id,
        "name": team.name,
        "slug": team.slug,
    }


def _match_payload(match: Any) -> dict[str, Any]:
    return {
        "id": match.id,
        "home_team": _team_payload(match.home_team),
        "away_team": _team_payload(match.away_team),
        "home_score": match.home_score,
        "away_score": match.away_score,
        "status": match.status,
        "start_timestamp": match.start_timestamp,
        "competition_id": match.tournament_id,
        "season_id": match.season_id,
    }


def _event_payload(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "minute": event.minute,
        "type": event.incident_type,
        "text": event.text,
        "is_home": event.is_home,
        "player": event.player,
        "player_in": event.player_in,
        "player_out": event.player_out,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "class": event.incident_class,
    }


def _insight_payload(insight: Any) -> dict[str, Any]:
    return {
        "id": insight.id,
        "kind": insight.kind,
        "title": insight.title,
        "impact": insight.impact,
        "summary": insight.summary,
        "start_minute": insight.start_minute,
        "end_minute": insight.end_minute,
        "evidence": list(insight.evidence),
    }


@app.get("/api/matches/{match_id}/analysis")
def match_analysis(match_id: int) -> dict[str, Any]:
    """Run the GoodGame analysis pipeline for one match.

    This is the stable frontend-facing analysis endpoint. Provider-specific
    payloads stay behind the ingestion layer while normalized match/events and
    GoodGame insights are returned here.
    """
    provider = _provider()

    try:
        analysis = GoodGamePipeline(provider=provider).analyze_match(match_id)
        fixture_statistics = (
            provider.get_fixture_statistics(match_id)
            if callable(getattr(provider, "get_fixture_statistics", None))
            else []
        )
        fixture_xg = (
            provider.get_fixture_xg(match_id)
            if callable(getattr(provider, "get_fixture_xg", None))
            else []
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "schema_version": "1",
        "provider": "bigquery",
        "match": _match_payload(analysis.match),
        "events": [_event_payload(event) for event in analysis.events],
        "insights": [_insight_payload(insight) for insight in analysis.insights],
        "lineups": analysis.lineups,
        "shots": list(analysis.shots),
        "statistics": fixture_statistics,
        "xg": fixture_xg,
    }



@app.get("/api/games/{fixture_id}/dashboard")
def game_dashboard(fixture_id: int) -> dict[str, Any]:
    try:
        provider = _provider()
        if not callable(getattr(provider, "get_game_dashboard", None)):
            raise ValueError("Configured provider does not support game dashboards")
        return provider.get_game_dashboard(fixture_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/games/{fixture_id}/players/{player_id}")
def game_player_dashboard(fixture_id: int, player_id: int) -> dict[str, Any]:
    try:
        provider = _provider()
        if not callable(getattr(provider, "get_game_player_dashboard", None)):
            raise ValueError("Configured provider does not support game-player dashboards")
        return provider.get_game_player_dashboard(fixture_id, player_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/teams/{team_id}/dashboard")
def team_dashboard(
    team_id: int,
    season_id: int,
    competition_id: int | None = None,
) -> dict[str, Any]:
    try:
        provider = _provider()
        if not callable(getattr(provider, "get_team_dashboard", None)):
            raise ValueError("Configured provider does not support team dashboards")
        return provider.get_team_dashboard(
            team_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/players/{player_id}/dashboard")
def player_dashboard(
    player_id: int,
    season_id: int,
    competition_id: int | None = None,
) -> dict[str, Any]:
    try:
        provider = _provider()
        if not callable(getattr(provider, "get_player_dashboard", None)):
            raise ValueError("Configured provider does not support player dashboards")
        return provider.get_player_dashboard(
            player_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error



@app.get("/api/seasons/{season_id}/teams")
def season_teams(
    season_id: int,
    competition_id: int | None = None,
) -> list[dict[str, Any]]:
    try:
        return _serving_repository().list_teams(
            season_id=season_id,
            competition_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/seasons/{season_id}/players")
def season_players(
    season_id: int,
    competition_id: int | None = None,
) -> list[dict[str, Any]]:
    try:
        return _serving_repository().list_players(
            season_id=season_id,
            competition_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error



@app.get("/api/games/{fixture_id}")
def game_view(fixture_id: int) -> dict[str, Any]:
    try:
        return _serving_repository().get_game_view(fixture_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/teams/{team_id}")
def team_view(
    team_id: int,
    season_id: int,
    competition_id: int | None = None,
) -> dict[str, Any]:
    try:
        return _serving_repository().get_team_view(
            team_id=team_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/players/{player_id}")
def player_view(
    player_id: int,
    season_id: int,
    competition_id: int | None = None,
) -> dict[str, Any]:
    try:
        return _serving_repository().get_player_view(
            player_id=player_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error



STATIC_DIR = os.environ.get("GOODGAME_STATIC_DIR", "static")

if os.path.isdir(STATIC_DIR):
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_spa(full_path: str):
        candidate = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
