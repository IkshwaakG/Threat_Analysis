"""Secure FastAPI surface for the GoodGame web/AR/VR frontends."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from goodgame.serving.repository_factory import create_serving_repository


logger = logging.getLogger("goodgame.web")

_PRODUCTION = os.environ.get("GOODGAME_ENV", "development").strip().casefold() == "production"
_DOCS_ENABLED = not _PRODUCTION or os.environ.get("GOODGAME_ENABLE_DOCS", "").strip().casefold() in {
    "1",
    "true",
    "yes",
}

app = FastAPI(
    title="GoodGame API",
    version="0.4.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

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
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)


# Per-instance protection against accidental/hostile query amplification.
# For a public Cloud Run deployment, pair this with Cloud Armor/API Gateway
# limits because this in-memory limiter is intentionally lightweight.
_RATE_LIMIT_PER_MINUTE = max(
    1,
    int(os.environ.get("GOODGAME_RATE_LIMIT_PER_MINUTE", "120")),
)
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = threading.Lock()


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        now = time.monotonic()
        client_key = request.client.host if request.client else "unknown"
        cutoff = now - 60.0

        with _rate_lock:
            window = _rate_windows[client_key]
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= _RATE_LIMIT_PER_MINUTE:
                return JSONResponse(
                    {"detail": "Too many requests. Try again shortly."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            window.append(now)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    if _PRODUCTION:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    return response


def _repository():
    return create_serving_repository()


def _service_error(error: Exception) -> HTTPException:
    # Log the detailed provider/query error server-side, but do not expose
    # project IDs, table names, query text, or credentials to the browser.
    logger.exception("GoodGame data request failed", exc_info=error)
    if isinstance(error, LookupError):
        return HTTPException(
            status_code=404,
            detail="Requested football data was not found.",
        )
    return HTTPException(
        status_code=502,
        detail="Football data service is temporarily unavailable.",
    )


def _positive(value: int, field: str) -> int:
    if value <= 0:
        raise HTTPException(status_code=422, detail=f"{field} must be positive.")
    return value


def _stat_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        for key in ("total", "value", "count", "average"):
            nested = value.get(key)
            if isinstance(nested, (str, int, float, bool)) or nested is None:
                return nested
    return str(value)


def _visual_role(position_id: Any) -> str:
    try:
        current = int(position_id) if position_id is not None else None
    except (TypeError, ValueError):
        current = None
    return {
        24: "Goalkeeper",
        25: "Defender",
        26: "Midfielder",
        27: "Attacker",
    }.get(current, "Player")


_FORMATION_RE = re.compile(r"\d+")


def _formation_cell(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    parts = _FORMATION_RE.findall(str(value))
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    return None


def _visual_players(game: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in game.get("players", [])
        if isinstance(row, dict)
    ]

    result: list[dict[str, Any]] = []
    for side in ("home", "away"):
        side_rows = [row for row in rows if row.get("team_location") == side]
        parsed = [(row, _formation_cell(row.get("formation_field"))) for row in side_rows]
        line_numbers = sorted(
            {
                cell[0]
                for _, cell in parsed
                if cell is not None
            }
        )
        line_index = {line: index for index, line in enumerate(line_numbers)}

        for index, (row, cell) in enumerate(parsed):
            if cell is not None and line_numbers:
                line, slot = cell
                same_line = [
                    current
                    for _, current in parsed
                    if current is not None and current[0] == line
                ]
                max_slot = max(
                    (current[1] for current in same_line),
                    default=max(1, len(same_line)),
                )
                if len(line_numbers) == 1:
                    x = 28.0
                else:
                    # Starting formations must stay inside the team's own half.
                    # Home is rendered on the left, away is mirrored to the right.
                    x = 6.0 + (line_index[line] / (len(line_numbers) - 1)) * 40.0
                y = (slot / (max_slot + 1)) * 100.0
            else:
                role = _visual_role(row.get("position_id")).casefold()
                if "goal" in role:
                    x = 7.0
                elif "def" in role:
                    x = 19.0
                elif "mid" in role:
                    x = 32.0
                else:
                    x = 44.0
                y = ((index + 1) / (len(side_rows) + 1)) * 100.0

            if side == "away":
                x = 100.0 - x

            stats: dict[str, str | int | float | bool | None] = {}
            for stat in row.get("match_stats", []) or []:
                if not isinstance(stat, dict):
                    continue
                key = str(
                    stat.get("developer_name")
                    or stat.get("name")
                    or stat.get("type_id")
                    or "stat"
                ).strip().casefold()
                key = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
                if key:
                    stats[key] = _stat_scalar(stat.get("value"))

            result.append(
                {
                    "player_id": row.get("player_id"),
                    "name": str(row.get("name") or f"Player {row.get('player_id', '')}"),
                    "number": row.get("jersey_number") or 0,
                    "captain": False,
                    "role": _visual_role(row.get("position_id")),
                    "formation_field": row.get("formation_field"),
                    "formation_position": row.get("formation_position"),
                    "x": round(max(2.0, min(98.0, x)), 2),
                    "y": round(max(2.0, min(98.0, y)), 2),
                    "team": side,
                    "color": "#32e58c" if side == "home" else "#edf3f0",
                    "stats": stats,
                }
            )

    return result


def _selectable_events(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge provider events + timeline into one selectable spatial event list."""
    visual_players = _visual_players(game)
    players_by_id = {
        int(player["player_id"]): player
        for player in visual_players
        if player.get("player_id") is not None
    }

    def category(item: dict[str, Any]) -> str:
        value = f"{item.get('type') or ''} {item.get('text') or ''}".casefold()
        if "substitution" in value:
            return "substitution"
        if "goal" in value:
            return "goal"
        if "yellow" in value or "red" in value or "card" in value:
            return "card"
        if "corner" in value:
            return "corner"
        if "shot on target" in value:
            return "shot_on_target"
        if "shot off target" in value:
            return "shot_off_target"
        if "shot" in value:
            return "shot"
        if "offside" in value:
            return "offside"
        if "penalty" in value:
            return "penalty"
        return re.sub(r"[^a-z0-9]+", "_", str(item.get("type") or "event").casefold()).strip("_") or "event"

    def player_for(item: dict[str, Any]) -> dict[str, Any] | None:
        player_id = item.get("player_id")
        if player_id is not None:
            try:
                current = players_by_id.get(int(player_id))
                if current is not None:
                    return current
            except (TypeError, ValueError):
                pass
        player_name = str(item.get("player") or "").strip().casefold()
        if player_name:
            for current in visual_players:
                if str(current.get("name") or "").strip().casefold() == player_name:
                    return current
        return None

    home_team_id = game.get("home_team", {}).get("id")
    away_team_id = game.get("away_team", {}).get("id")

    def side(item: dict[str, Any]) -> str | None:
        # Timeline rows do not always carry is_home. Resolve ownership from the
        # actual participant/team id first so every attacking event is mirrored
        # into the opponent's half correctly.
        team_id = item.get("team_id")
        if team_id is not None:
            try:
                normalized_team_id = int(team_id)
                if home_team_id is not None and normalized_team_id == int(home_team_id):
                    return "home"
                if away_team_id is not None and normalized_team_id == int(away_team_id):
                    return "away"
            except (TypeError, ValueError):
                pass

        if item.get("is_home") is True:
            return "home"
        if item.get("is_home") is False:
            return "away"

        player = player_for(item)
        if player is not None:
            return str(player.get("team") or "") or None
        return None

    def attacking_x(team_side: str | None, home_x: float, away_x: float) -> float:
        # Starting formation: home is left, away is right.
        # Therefore home attacks the right half and away attacks the left half.
        if team_side == "away":
            return away_x
        if team_side == "home":
            return home_x
        # Unknown ownership stays central instead of silently pretending to be home.
        return 50.0

    ball_coordinates = [
        point
        for point in game.get("ball_coordinates", []) or []
        if isinstance(point, dict)
        and point.get("x") is not None
        and point.get("y") is not None
    ]

    period_first_id: dict[Any, int] = {}
    for point in ball_coordinates:
        period_id = point.get("period_id")
        if period_id is None:
            continue
        try:
            coordinate_id = int(point.get("id") or 0)
        except (TypeError, ValueError):
            coordinate_id = 0
        current = period_first_id.get(period_id)
        if current is None or coordinate_id < current:
            period_first_id[period_id] = coordinate_id

    period_order = {
        period_id: index
        for index, (period_id, _) in enumerate(
            sorted(period_first_id.items(), key=lambda item: item[1])
        )
    }

    def timer_seconds(value: Any) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if ":" in text:
                minute, second = text.split(":", 1)
                return int(minute) * 60 + int(float(second))
            return int(float(text) * 60)
        except (TypeError, ValueError):
            return None

    def absolute_coordinate_second(point: dict[str, Any]) -> int | None:
        seconds = timer_seconds(point.get("timer"))
        if seconds is None:
            return None
        order = period_order.get(point.get("period_id"), 0)
        if order == 1 and seconds < 45 * 60:
            seconds += 45 * 60
        elif order == 2 and seconds < 90 * 60:
            seconds += 90 * 60
        elif order >= 3 and seconds < 105 * 60:
            seconds += 105 * 60
        return seconds

    coordinate_stream = [
        (point, absolute_coordinate_second(point))
        for point in ball_coordinates
    ]
    coordinate_stream = [
        (point, seconds)
        for point, seconds in coordinate_stream
        if seconds is not None
    ]
    coordinate_stream.sort(
        key=lambda item: (
            item[1],
            int(item[0].get("id") or 0),
        )
    )

    def event_coordinate_track(
        item: dict[str, Any],
        spatial_data: dict[str, Any],
        kind: str,
    ) -> list[dict[str, Any]]:
        if kind not in {
            "goal",
            "corner",
            "shot",
            "shot_on_target",
            "shot_off_target",
            "penalty",
            "offside",
        }:
            return []

        try:
            minute = int(item.get("minute"))
        except (TypeError, ValueError):
            return []
        try:
            extra = int(item.get("extra_minute") or 0)
        except (TypeError, ValueError):
            extra = 0
        event_second = (minute + extra) * 60

        anchor = spatial_data.get("anchor")
        if not isinstance(anchor, dict):
            path = spatial_data.get("ball_path")
            anchor = path.get("start") if isinstance(path, dict) else None

        candidates: list[tuple[int, dict[str, Any], int, float]] = []
        for index, (point, seconds) in enumerate(coordinate_stream):
            time_delta = abs(seconds - event_second)
            if time_delta > 90:
                continue
            distance = 0.0
            if isinstance(anchor, dict):
                try:
                    dx = float(point["x"]) - float(anchor["x"])
                    dy = float(point["y"]) - float(anchor["y"])
                    distance = (dx * dx + dy * dy) ** 0.5
                except (TypeError, ValueError, KeyError):
                    distance = 0.0
            score = time_delta + distance * 1.8
            candidates.append((index, point, seconds, score))

        if not candidates:
            return []

        center_index, _, center_second, _ = min(
            candidates,
            key=lambda row: row[3],
        )
        center_period = coordinate_stream[center_index][0].get("period_id")

        selected: list[dict[str, Any]] = []
        start_index = max(0, center_index - 6)
        end_index = min(len(coordinate_stream), center_index + 8)
        for point, seconds in coordinate_stream[start_index:end_index]:
            if point.get("period_id") != center_period:
                continue
            if abs(seconds - center_second) > 28:
                continue
            selected.append(
                {
                    "x": round(float(point["x"]), 3),
                    "y": round(float(point["y"]), 3),
                    "timer": point.get("timer"),
                    "period_id": point.get("period_id"),
                }
            )

        return selected

    def spatial(item: dict[str, Any], kind: str) -> dict[str, Any]:
        team_side = side(item)
        player = player_for(item)
        player_anchor = (
            {"x": float(player["x"]), "y": float(player["y"])}
            if player is not None else None
        )
        stored_path = item.get("ball_path") if isinstance(item.get("ball_path"), dict) else None
        source = "stored" if stored_path else "inferred"

        if stored_path:
            start = stored_path.get("start")
            end = stored_path.get("end")
            start_point = start if isinstance(start, dict) else player_anchor

            # A real event coordinate is authoritative. If the provider gives
            # only that point, infer only the missing destination for ball
            # events; do not invent a trajectory for cards/offsides.
            if kind in {"card", "offside"}:
                return {
                    "kind": kind,
                    "source": "stored",
                    "anchor": start_point,
                    "ball_path": None,
                    "highlight_player_id": None,
                }

            if isinstance(start_point, dict) and not isinstance(end, dict):
                seed = (
                    int(item.get("id") or 0)
                    + int(item.get("minute") or 0)
                    + int(item.get("sort_order") or 0)
                )
                if kind == "goal":
                    end = {"x": attacking_x(team_side, 99.2, 0.8), "y": 50.0}
                elif kind == "corner":
                    box_y = 43.0 if float(start_point.get("y") or 50.0) < 50.0 else 57.0
                    end = {"x": attacking_x(team_side, 87.0, 13.0), "y": box_y}
                elif kind in {"shot", "shot_on_target", "shot_off_target", "penalty"}:
                    if kind == "shot_off_target":
                        miss_offsets = (-10.0, -6.0, 6.0, 10.0)
                        end_y = 50.0 + miss_offsets[seed % len(miss_offsets)]
                    elif kind == "shot_on_target":
                        target_offsets = (-5.0, -2.0, 2.0, 5.0)
                        end_y = 50.0 + target_offsets[seed % len(target_offsets)]
                    else:
                        end_y = 50.0
                    end = {"x": attacking_x(team_side, 99.2, 0.8), "y": end_y}

            normalized_path = (
                {"start": start_point, "end": end if isinstance(end, dict) else None}
                if isinstance(start_point, dict)
                else None
            )
            return {
                "kind": kind,
                "source": "stored",
                "anchor": start_point,
                "ball_path": normalized_path,
                "highlight_player_id": item.get("player_id") if kind == "goal" else None,
            }

        if kind == "goal":
            # Until provider ball coordinates are available, keep this deliberately
            # simple and explicit: penalty spot -> attacking goal.
            start = {"x": attacking_x(team_side, 88.0, 12.0), "y": 50.0}
            end = {"x": attacking_x(team_side, 99.2, 0.8), "y": 50.0}
            return {
                "kind": kind,
                "source": "inferred",
                "anchor": player_anchor or start,
                "ball_path": {"start": start, "end": end},
                "highlight_player_id": item.get("player_id"),
            }

        if kind == "corner":
            seed = (
                int(item.get("id") or 0)
                + int(item.get("minute") or 0)
                + int(item.get("sort_order") or 0)
            )
            if player_anchor:
                corner_y = 2.0 if player_anchor["y"] < 50.0 else 98.0
            else:
                corner_y = 2.0 if seed % 2 == 0 else 98.0
            box_y = 43.0 if corner_y < 50.0 else 57.0
            start = {"x": attacking_x(team_side, 99.0, 1.0), "y": corner_y}
            end = {"x": attacking_x(team_side, 87.0, 13.0), "y": box_y}
            return {
                "kind": kind,
                "source": "inferred",
                "anchor": start,
                "ball_path": {"start": start, "end": end},
                "highlight_player_id": None,
            }

        if kind in {"shot", "shot_on_target", "shot_off_target", "penalty"}:
            start_x = 88.0 if kind == "penalty" else 78.0
            start = {
                "x": attacking_x(team_side, start_x, 100.0 - start_x),
                "y": player_anchor["y"] if player_anchor else 50.0,
            }
            if kind == "shot_off_target":
                # Keep misses close to the goal rather than firing them toward
                # a pitch corner. Vary the miss deterministically by event id /
                # minute so multiple shots do not overlap at one point.
                seed = (
                    int(item.get("id") or 0)
                    + int(item.get("minute") or 0)
                    + int(item.get("sort_order") or 0)
                )
                miss_offsets = (-12.0, -8.0, 8.0, 12.0)
                end_y = 50.0 + miss_offsets[seed % len(miss_offsets)]
            elif kind == "shot_on_target":
                seed = int(item.get("id") or item.get("minute") or 0)
                target_offsets = (-5.0, -2.0, 2.0, 5.0)
                end_y = 50.0 + target_offsets[seed % len(target_offsets)]
            else:
                end_y = 50.0
            end = {"x": attacking_x(team_side, 99.2, 0.8), "y": end_y}
            return {
                "kind": kind,
                "source": "inferred",
                "anchor": start,
                "ball_path": {"start": start, "end": end},
                "highlight_player_id": None,
            }

        if kind == "offside":
            anchor = {
                "x": attacking_x(team_side, 82.0, 18.0),
                "y": player_anchor["y"] if player_anchor else 50.0,
            }
        elif player_anchor:
            anchor = player_anchor
        else:
            anchor = {
                "x": 66.0 if team_side == "home" else 34.0 if team_side == "away" else 50.0,
                "y": 50.0,
            }

        return {
            "kind": kind,
            "source": "inferred",
            "anchor": anchor,
            "ball_path": None,
            "highlight_player_id": None,
        }

    # Prefer richer fixture events when timeline contains the same occurrence.
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source_kind in ("events", "timeline"):
        for raw in game.get(source_kind, []) or []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            kind = category(item)
            if kind == "substitution":
                continue

            dedupe_key = (
                item.get("minute"),
                item.get("extra_minute"),
                kind,
                item.get("team_id"),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            item["source_kind"] = "event" if source_kind == "events" else "timeline"
            spatial_data = spatial(item, kind)
            coordinate_track = event_coordinate_track(item, spatial_data, kind)
            if coordinate_track:
                spatial_data["source"] = "stored"
                spatial_data["ball_track"] = coordinate_track
                spatial_data["anchor"] = coordinate_track[0]
                spatial_data["ball_path"] = {
                    "start": coordinate_track[0],
                    "end": coordinate_track[-1],
                }
                item["ball_track"] = coordinate_track
                item["ball_path"] = spatial_data["ball_path"]
            item["spatial"] = spatial_data
            if not item.get("player") and item.get("player_id") is not None:
                current = player_for(item)
                if current is not None:
                    item["player"] = current.get("name")
            merged.append(item)

    merged.sort(
        key=lambda item: (
            item.get("minute") if item.get("minute") is not None else 999,
            item.get("extra_minute") if item.get("extra_minute") is not None else 0,
            item.get("sort_order") if item.get("sort_order") is not None else 999,
            0 if item.get("source_kind") == "event" else 1,
        )
    )
    return merged


def _spatial_flow(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct ball movement from stored events + timeline.

    This is explicitly inferred unless a stored coordinate is present.
    Substitutions and cards do not participate in spatial playback.
    """
    visual_players = _visual_players(game)
    players_by_id = {
        int(player["player_id"]): player
        for player in visual_players
        if player.get("player_id") is not None
    }

    combined: list[dict[str, Any]] = []
    for source_name in ("timeline", "events"):
        for item in game.get(source_name, []) or []:
            if isinstance(item, dict):
                combined.append({**item, "_source_kind": source_name})

    combined.sort(
        key=lambda item: (
            item.get("minute") if item.get("minute") is not None else 999,
            item.get("extra_minute") if item.get("extra_minute") is not None else 0,
            0 if item.get("_source_kind") == "timeline" else 1,
            item.get("sort_order") if item.get("sort_order") is not None else 999,
            item.get("id") if item.get("id") is not None else 0,
        )
    )

    flow: list[dict[str, Any]] = [{
        "event_id": None,
        "minute": 0,
        "x": 50.0,
        "y": 50.0,
        "source": "inferred",
        "reason": "kickoff",
        "label": "Kickoff",
        "team": None,
        "player_id": None,
    }]

    def attacking_goal(is_home: bool | None) -> float:
        return 98.0 if is_home is not False else 2.0

    def attacking_zone(is_home: bool | None) -> float:
        return 74.0 if is_home is not False else 26.0

    for item in combined:
        item_type = str(item.get("type") or "").casefold()
        text = str(item.get("text") or item.get("addition") or item_type or "Event")
        searchable = f"{item_type} {text}".casefold()

        if "substitution" in searchable or "card" in searchable:
            continue

        useful = any(
            token in searchable
            for token in (
                "goal",
                "corner",
                "shot on target",
                "shot off target",
                "shot",
                "offside",
                "penalty",
                "kickoff",
                "kick off",
            )
        )
        if not useful and item.get("_source_kind") == "timeline":
            continue

        is_home = item.get("is_home")
        player_id = item.get("player_id")
        player = None
        if player_id is not None:
            try:
                player = players_by_id.get(int(player_id))
            except (TypeError, ValueError):
                player = None

        stored_path = item.get("ball_path") if isinstance(item.get("ball_path"), dict) else None
        stored_point = None
        if stored_path:
            end = stored_path.get("end")
            start = stored_path.get("start")
            stored_point = end if isinstance(end, dict) else start if isinstance(start, dict) else None

        if stored_point and stored_point.get("x") is not None and stored_point.get("y") is not None:
            x = float(stored_point["x"])
            y = float(stored_point["y"])
            source = "stored"
            reason = "provider_coordinate"
        elif "kickoff" in searchable or "kick off" in searchable:
            x, y = 50.0, 50.0
            source, reason = "inferred", "kickoff"
        elif "corner" in searchable:
            x = attacking_goal(is_home)
            previous_y = float(flow[-1].get("y") or 50.0)
            y = 2.0 if previous_y < 50.0 else 98.0
            source, reason = "inferred", "corner"
        elif "goal" in searchable:
            x, y = attacking_goal(is_home), 50.0
            source, reason = "inferred", "goal"
        elif "penalty" in searchable:
            x, y = ((88.0, 50.0) if is_home is not False else (12.0, 50.0))
            source, reason = "inferred", "penalty"
        elif "shot on target" in searchable:
            x = attacking_goal(is_home)
            y = 44.0 + (len(flow) % 4) * 4.0
            source, reason = "inferred", "shot_on_target"
        elif "shot off target" in searchable:
            x = attacking_goal(is_home)
            y = 8.0 if len(flow) % 2 == 0 else 92.0
            source, reason = "inferred", "shot_off_target"
        elif "shot" in searchable:
            x = attacking_zone(is_home)
            y = float(player.get("y") or 50.0) if player else 50.0
            source, reason = "inferred", "shot"
        elif "offside" in searchable:
            x = 82.0 if is_home is not False else 18.0
            y = float(player.get("y") or 50.0) if player else 50.0
            source, reason = "inferred", "offside"
        elif player is not None:
            x = float(player.get("x") or 50.0)
            y = float(player.get("y") or 50.0)
            source, reason = "inferred", "player_formation_area"
        else:
            continue

        flow.append({
            "event_id": item.get("id"),
            "minute": item.get("minute"),
            "extra_minute": item.get("extra_minute"),
            "x": round(max(0.0, min(100.0, x)), 3),
            "y": round(max(0.0, min(100.0, y)), 3),
            "source": source,
            "reason": reason,
            "label": text,
            "team": "home" if is_home is True else "away" if is_home is False else None,
            "player_id": player_id if reason == "goal" else None,
        })

        if reason == "goal":
            flow.append({
                "event_id": item.get("id"),
                "minute": item.get("minute"),
                "extra_minute": item.get("extra_minute"),
                "x": 50.0,
                "y": 50.0,
                "source": "inferred",
                "reason": "restart",
                "label": "Restart",
                "team": None,
                "player_id": None,
            })

    return flow


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/competitions")
def competitions() -> list[dict[str, Any]]:
    try:
        return _repository().list_competitions()
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/competitions/{competition_id}/seasons")
def seasons(competition_id: int) -> list[dict[str, Any]]:
    _positive(competition_id, "competition_id")
    try:
        return _repository().list_seasons(competition_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/competitions/{competition_id}/seasons/{season_id}/matches")
def matches(competition_id: int, season_id: int) -> list[dict[str, Any]]:
    _positive(competition_id, "competition_id")
    _positive(season_id, "season_id")
    try:
        return _repository().list_matches(competition_id, season_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/seasons/{season_id}/teams")
def season_teams(
    season_id: int,
    competition_id: int | None = Query(default=None, gt=0),
) -> list[dict[str, Any]]:
    _positive(season_id, "season_id")
    try:
        return _repository().list_teams(
            season_id=season_id,
            competition_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/seasons/{season_id}/players")
def season_players(
    season_id: int,
    competition_id: int | None = Query(default=None, gt=0),
) -> list[dict[str, Any]]:
    _positive(season_id, "season_id")
    try:
        return _repository().list_players(
            season_id=season_id,
            competition_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/search")
def global_search(
    q: str = Query(min_length=2, max_length=80),
    season_id: int | None = Query(default=None, gt=0),
    competition_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=12, ge=1, le=20),
) -> list[dict[str, Any]]:
    try:
        return _repository().search_entities(
            query=q,
            season_id=season_id,
            league_id=competition_id,
            limit=limit,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/games/{fixture_id}")
def game_view(fixture_id: int) -> dict[str, Any]:
    _positive(fixture_id, "fixture_id")
    try:
        game = _repository().get_game_view(fixture_id)
        game["selectable_events"] = _selectable_events(game)
        game["spatial_flow"] = _spatial_flow(game)
        return game
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/matches/{fixture_id}/visualization")
def match_visualization(fixture_id: int) -> dict[str, Any]:
    """Compatibility view for the current Figma frontend.

    This now derives from the same DATA_MODE-aware one-query game read model,
    rather than calling the legacy BigQuery provider directly.
    """

    _positive(fixture_id, "fixture_id")
    try:
        game = _repository().get_game_view(fixture_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error

    home = game["home_team"]
    away = game["away_team"]
    fixture = game["fixture"]

    return {
        "match": {
            "id": fixture["id"],
            "home_team": {
                "id": home["id"],
                "name": home["name"],
                "short_code": home.get("short_code"),
                "logo": home.get("logo"),
                "color": "#32e58c",
                "kit_colors": ["#32e58c"],
            },
            "away_team": {
                "id": away["id"],
                "name": away["name"],
                "short_code": away.get("short_code"),
                "logo": away.get("logo"),
                "color": "#edf3f0",
                "kit_colors": ["#edf3f0"],
            },
            "home_score": home.get("goals"),
            "away_score": away.get("goals"),
            "status": str(fixture.get("result_info") or fixture.get("state_id") or "unknown"),
            "competition_name": fixture.get("competition_name"),
        },
        "players": _visual_players(game),
        "ball_coordinates": game.get("ball_coordinates") or [],
        "color_source": "fallback",
        "lineup_source": "bigquery_game_view",
    }


@app.get("/api/teams/{team_id}")
def team_view(
    team_id: int,
    season_id: int = Query(gt=0),
    competition_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any]:
    _positive(team_id, "team_id")
    try:
        return _repository().get_team_view(
            team_id=team_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


@app.get("/api/players/{player_id}")
def player_view(
    player_id: int,
    season_id: int = Query(gt=0),
    competition_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any]:
    _positive(player_id, "player_id")
    try:
        return _repository().get_player_view(
            player_id=player_id,
            season_id=season_id,
            league_id=competition_id,
        )
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error


# Backward-compatible aliases now use the same serving repository instead of
# bypassing DATA_MODE or issuing nested provider queries.
@app.get("/api/games/{fixture_id}/dashboard")
def game_dashboard_alias(fixture_id: int) -> dict[str, Any]:
    return game_view(fixture_id)


@app.get("/api/teams/{team_id}/dashboard")
def team_dashboard_alias(
    team_id: int,
    season_id: int = Query(gt=0),
    competition_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any]:
    return team_view(team_id, season_id, competition_id)


@app.get("/api/players/{player_id}/dashboard")
def player_dashboard_alias(
    player_id: int,
    season_id: int = Query(gt=0),
    competition_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any]:
    return player_view(player_id, season_id, competition_id)


@app.get("/api/games/{fixture_id}/players/{player_id}")
def game_player_alias(fixture_id: int, player_id: int) -> dict[str, Any]:
    _positive(fixture_id, "fixture_id")
    _positive(player_id, "player_id")
    try:
        game = _repository().get_game_view(fixture_id)
    except (LookupError, ValueError, GoogleAPIError, GoogleAuthError) as error:
        raise _service_error(error) from error

    player = next(
        (
            current
            for current in game.get("players", [])
            if current.get("player_id") == player_id
        ),
        None,
    )
    if player is None:
        raise HTTPException(status_code=404, detail="Player was not found in this fixture.")

    team = (
        game["home_team"]
        if player.get("team_location") == "home"
        else game["away_team"]
    )
    return {
        "fixture_id": fixture_id,
        "player": player,
        "team": team,
        "team_profile_url": team.get("profile_url"),
        "player_profile_url": player.get("profile_url"),
    }


@app.get("/api/matches/{match_id}/analysis")
def retired_analysis(match_id: int):
    _positive(match_id, "match_id")
    raise HTTPException(
        status_code=410,
        detail="Legacy analysis endpoint retired. Use /api/games/{fixture_id}.",
    )


_STATIC_DIR = Path(os.environ.get("GOODGAME_STATIC_DIR", "static")).resolve()
_STATIC_INDEX = _STATIC_DIR / "index.html"

if _STATIC_INDEX.is_file():
    assets_dir = _STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend_root():
        return FileResponse(_STATIC_INDEX)

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_spa(full_path: str):
        candidate = (_STATIC_DIR / full_path).resolve()
        try:
            candidate.relative_to(_STATIC_DIR)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found.")

        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_INDEX)
