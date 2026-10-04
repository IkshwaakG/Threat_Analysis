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

    # 105 x 68 m reference pitch. IFAB goal opening is 7.32 m wide.
    GOAL_HALF_WIDTH_PERCENT = (7.32 / 68.0) * 50.0
    PENALTY_SPOT_FROM_GOAL_PERCENT = (11.0 / 105.0) * 100.0
    PENALTY_SPOT_RIGHT_X = 100.0 - PENALTY_SPOT_FROM_GOAL_PERCENT
    PENALTY_SPOT_LEFT_X = PENALTY_SPOT_FROM_GOAL_PERCENT

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

    def player_name_for_id(value: Any) -> str | None:
        if value is None:
            return None
        try:
            player = players_by_id.get(int(value))
        except (TypeError, ValueError):
            player = None
        return str(player.get("name")) if player and player.get("name") else None

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

    def event_half(item: dict[str, Any]) -> int:
        """Return regulation half from event match minute.

        Provider period ids are opaque identifiers, while event minute is
        directly usable for first/second-half attacking direction. Extra time
        continues alternating ends every period.
        """
        try:
            minute = int(item.get("minute") or 0)
        except (TypeError, ValueError):
            minute = 0
        # 45' and 90' are regulation stoppage-time anchors, not the next
        # period. Provider carries added time separately in extra_minute.
        if minute <= 45:
            return 1
        if minute <= 90:
            return 2
        if minute <= 105:
            return 3
        return 4

    def attacking_x(
        item: dict[str, Any],
        team_side: str | None,
        home_x: float,
        away_x: float,
    ) -> float:
        """Resolve attacking end, reversing sides after each regulation half."""
        half = event_half(item)
        reversed_ends = half in {2, 4}

        if team_side == "home":
            return away_x if reversed_ends else home_x
        if team_side == "away":
            return home_x if reversed_ends else away_x

        # Unknown ownership stays central instead of inventing direction.
        return 50.0

    ball_coordinates = [
        point
        for point in game.get("ball_coordinates", []) or []
        if isinstance(point, dict)
        and point.get("x") is not None
        and point.get("y") is not None
    ]

    def timer_seconds(value: Any) -> int | None:
        """Provider timer is match time in MM:SS."""
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

    coordinate_stream = [
        (point, timer_seconds(point.get("timer")))
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

    commentary_rows = [
        item
        for item in game.get("commentary", []) or []
        if isinstance(item, dict)
    ]

    trends_value = game.get("trends") or []
    if isinstance(trends_value, str):
        try:
            import json
            trends_value = json.loads(trends_value)
        except (TypeError, ValueError):
            trends_value = []
    trend_rows = [item for item in trends_value if isinstance(item, dict)] if isinstance(trends_value, list) else []

    def commentary_for_event(item: dict[str, Any], kind: str) -> dict[str, Any] | None:
        try:
            minute = int(item.get("minute"))
        except (TypeError, ValueError):
            return None

        scorer = str(item.get("player") or "").strip().casefold()
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for comment in commentary_rows:
            try:
                comment_minute = int(comment.get("minute"))
            except (TypeError, ValueError):
                continue
            if comment_minute != minute:
                continue
            if kind == "goal" and comment.get("is_goal") is not True:
                continue
            text = str(comment.get("comment") or "")
            score = 0
            if scorer and scorer in text.casefold():
                score -= 5
            if kind == "goal" and "goal" in text.casefold():
                score -= 3
            if item.get("related_player_name") and str(item.get("related_player_name")).casefold() in text.casefold():
                score -= 2
            candidates.append((score, int(comment.get("sort_order") or 999999), comment))

        return min(candidates, key=lambda row: (row[0], row[1]))[2] if candidates else None

    def shot_context_from_comment(text: str) -> dict[str, Any]:
        normalized = " ".join(str(text or "").split())
        lower = normalized.casefold()
        if not lower:
            return {}

        context: dict[str, Any] = {"commentary": normalized}

        if "left-footed" in lower or "left footed" in lower or "left foot shot" in lower:
            context["body_part"] = "Left foot"
        elif "right-footed" in lower or "right footed" in lower or "right foot shot" in lower:
            context["body_part"] = "Right foot"
        elif "header" in lower or "headed" in lower:
            context["body_part"] = "Header"

        origin_phrases = (
            "left side of the six-yard box",
            "right side of the six-yard box",
            "center of the six-yard box",
            "centre of the six-yard box",
            "left side of the box",
            "right side of the box",
            "center of the box",
            "centre of the box",
            "outside the box",
            "very close range",
            "over 35 yards",
        )
        for phrase in origin_phrases:
            if phrase in lower:
                context["shot_origin"] = phrase.replace("centre", "center")
                break

        goal_targets = (
            "top left corner",
            "top right corner",
            "bottom left corner",
            "bottom right corner",
            "high center of the goal",
            "high centre of the goal",
            "center of the goal",
            "centre of the goal",
            "left side of the goal",
            "right side of the goal",
        )
        for phrase in goal_targets:
            if phrase in lower:
                normalized_target = phrase.replace("centre", "center")
                context["goal_target"] = normalized_target
                if "top" in normalized_target or "high" in normalized_target:
                    context["goal_height"] = "high"
                    context["goal_height_ratio"] = 0.82
                elif "bottom" in normalized_target:
                    context["goal_height"] = "low"
                    context["goal_height_ratio"] = 0.18
                else:
                    context["goal_height"] = "middle"
                    context["goal_height_ratio"] = 0.48
                if "left" in normalized_target:
                    context["goal_side"] = "left"
                elif "right" in normalized_target:
                    context["goal_side"] = "right"
                else:
                    context["goal_side"] = "center"
                break

        for phrase in ("through ball", "cross", "cutback", "long ball"):
            if phrase in lower:
                context["assist_type"] = phrase
                break

        if "fast break" in lower:
            context["situation"] = "Fast break"
        elif "after a corner" in lower or "from a corner" in lower:
            context["situation"] = "Corner"
        elif "direct free kick" in lower:
            context["situation"] = "Direct free kick"
        elif "penalty" in lower:
            context["situation"] = "Penalty"

        return context

    def trend_context_for_event(item: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            minute = int(item.get("minute"))
        except (TypeError, ValueError):
            return []
        period_id = item.get("period_id")
        result: list[dict[str, Any]] = []
        for trend in trend_rows:
            try:
                trend_minute = int(trend.get("minute"))
            except (TypeError, ValueError):
                continue
            if trend_minute != minute:
                continue
            if period_id is not None and trend.get("period_id") not in (None, period_id):
                continue
            participant = trend.get("participant") if isinstance(trend.get("participant"), dict) else {}
            result.append({
                "id": trend.get("id"),
                "type_id": trend.get("type_id"),
                "minute": trend_minute,
                "period_id": trend.get("period_id"),
                "participant_id": trend.get("participant_id"),
                "participant_name": participant.get("name"),
                "participant_code": participant.get("short_code"),
                "value": trend.get("value"),
            })
        return result[:20]

    def semantic_shot_start(
        item: dict[str, Any],
        team_side: str | None,
        context: dict[str, Any],
    ) -> dict[str, float] | None:
        origin = str(context.get("shot_origin") or "").casefold()
        if not origin:
            return None
        target_x = attacking_x(item, team_side, 100.0, 0.0)
        attacks_right = target_x > 50.0

        if "six-yard" in origin:
            distance_from_goal = 6.0
        elif "center of the box" in origin or "side of the box" in origin:
            distance_from_goal = 14.0
        elif "outside the box" in origin:
            distance_from_goal = 24.0
        elif "35 yards" in origin:
            distance_from_goal = 34.0
        elif "close range" in origin:
            distance_from_goal = 5.0
        else:
            distance_from_goal = 18.0

        x = 100.0 - distance_from_goal if attacks_right else distance_from_goal
        if "left side" in origin:
            y = 34.0 if attacks_right else 66.0
        elif "right side" in origin:
            y = 66.0 if attacks_right else 34.0
        else:
            y = 50.0
        return {"x": x, "y": y}

    def semantic_goal_end(
        item: dict[str, Any],
        team_side: str | None,
        context: dict[str, Any],
    ) -> dict[str, float]:
        target_x = attacking_x(item, team_side, 100.0, 0.0)
        attacks_right = target_x > 50.0
        side_label = str(context.get("goal_side") or "center").casefold()
        if side_label == "left":
            y = 46.0 if attacks_right else 54.0
        elif side_label == "right":
            y = 54.0 if attacks_right else 46.0
        else:
            y = 50.0
        return {"x": target_x, "y": y}

    def event_coordinate_track(
        item: dict[str, Any],
        spatial_data: dict[str, Any],
        kind: str,
    ) -> list[dict[str, Any]]:
        """Match an event to the most plausible stored Provider ball segment.

        ballCoordinates are a frequent time series rather than event-attached
        paths. Match by period/time, then score short contiguous segments
        against the *correct attacking goal* for the event team and half.
        Provider x/y values are rendered directly; they are never mirrored.
        """
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

        # Provider event labels and ball-coordinate timers can differ by
        # one displayed minute in real fixtures. Evaluate both plausible timer
        # windows and let event geometry decide which one belongs to the action.
        display_minute = minute + extra
        candidate_minutes = sorted({
            max(0, display_minute - 1),
            display_minute,
        })
        candidate_windows = [
            (candidate * 60, candidate * 60 + 59)
            for candidate in candidate_minutes
        ]
        event_period_id = item.get("period_id")
        team_side = side(item)
        target_goal_x = attacking_x(item, team_side, 100.0, 0.0)
        detail_context = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        semantic_launch = semantic_shot_start(item, team_side, detail_context)

        def provider_point(point: dict[str, Any]) -> dict[str, Any]:
            return {
                "x": round(float(point["x"]), 3),
                "y": round(float(point["y"]), 3),
                "timer": point.get("timer"),
                "period_id": point.get("period_id"),
            }

        def distance_to_target_goal(point: dict[str, Any]) -> float:
            return abs(float(point["x"]) - target_goal_x)

        def nearest_goal_line_distance(point: dict[str, Any]) -> float:
            x = float(point["x"])
            return min(abs(x), abs(100.0 - x))

        def goal_center_distance(point: dict[str, Any]) -> float:
            return abs(float(point["y"]) - 50.0)

        def touchline_distance(point: dict[str, Any]) -> float:
            y = float(point["y"])
            return min(abs(y), abs(100.0 - y))

        same_period = [
            (point, seconds)
            for point, seconds in coordinate_stream
            if event_period_id is None or point.get("period_id") == event_period_id
        ]
        if not same_period:
            same_period = coordinate_stream

        # Search both plausible timer windows, with a small boundary pad.
        time_candidates = [
            (point, seconds)
            for point, seconds in same_period
            if any(start - 12 <= seconds <= end + 12 for start, end in candidate_windows)
        ]
        if not time_candidates:
            return []

        # Collapse repeated stationary samples but preserve provider order.
        compact_rows: list[tuple[dict[str, Any], int]] = []
        for point, seconds in time_candidates:
            if compact_rows:
                previous = compact_rows[-1][0]
                if (
                    abs(float(point["x"]) - float(previous["x"])) < 0.01
                    and abs(float(point["y"]) - float(previous["y"])) < 0.01
                ):
                    continue
            compact_rows.append((point, seconds))

        if not compact_rows:
            return []

        def time_score(seconds: int) -> float:
            best = float("inf")
            for start, end in candidate_windows:
                if start <= seconds <= end:
                    return 0.0
                best = min(best, abs(seconds - start), abs(seconds - end))
            return best

        def build_approach_segment(
            *,
            on_target: bool,
            max_goal_distance: float,
        ) -> list[tuple[dict[str, Any], int]]:
            """Return the shot flight, starting at the shot-taking point.

            The selected event represents the shot action itself. The stored
            traversal must therefore begin at the launch coordinate and move
            forward in provider time until the terminal save/miss/goal point.
            Do not render the possession/build-up before the shot.
            """
            if len(compact_rows) < 2:
                return []

            # Build candidate forward runs. A shot launch is the point directly
            # before a meaningful goalward movement. From there, keep following
            # provider samples while the ball continues toward the correct goal
            # and stop at the local closest approach (save/miss/goal).
            candidates: list[tuple[float, int, int]] = []

            for launch_index in range(0, len(compact_rows) - 1):
                launch_point, launch_second = compact_rows[launch_index]
                next_point, next_second = compact_rows[launch_index + 1]

                if next_second - launch_second > 16:
                    continue

                launch_distance = distance_to_target_goal(launch_point)
                next_distance = distance_to_target_goal(next_point)
                first_progress = launch_distance - next_distance

                # Require a decisive initial movement toward goal. This keeps
                # the pre-shot possession phase out of the rendered path.
                if first_progress < 3.0:
                    continue

                end_index = launch_index + 1
                previous_distance = next_distance

                for current_index in range(launch_index + 2, len(compact_rows)):
                    point, seconds = compact_rows[current_index]
                    previous_seconds = compact_rows[current_index - 1][1]
                    if seconds - previous_seconds > 16:
                        break

                    current_distance = distance_to_target_goal(point)

                    # Once the ball clearly moves away from goal, the save /
                    # rebound / clearance phase has begun. Stop before it.
                    if current_distance > previous_distance + 3.0:
                        break

                    end_index = current_index
                    previous_distance = current_distance

                end_point, end_second = compact_rows[end_index]
                end_distance = distance_to_target_goal(end_point)

                # Endpoint must plausibly reach the goal zone for the event.
                if end_distance > max_goal_distance:
                    continue

                if on_target:
                    center_distance = goal_center_distance(end_point)
                    if center_distance > GOAL_HALF_WIDTH_PERCENT + 8.0:
                        continue
                else:
                    center_distance = 0.0

                total_progress = launch_distance - end_distance
                if total_progress < 6.0:
                    continue

                # Favor a strong, compact shot movement whose terminal sample
                # is near the correct goal and temporally close to the event.
                duration = max(1, end_second - launch_second)
                launch_semantic_distance = 0.0
                if semantic_launch is not None:
                    launch_semantic_distance = (
                        (float(launch_point["x"]) - float(semantic_launch["x"])) ** 2
                        + (float(launch_point["y"]) - float(semantic_launch["y"])) ** 2
                    ) ** 0.5
                score = (
                    end_distance * 4.0
                    + center_distance * (1.7 if on_target else 0.0)
                    + time_score(launch_second) * 0.2
                    + duration * 0.08
                    + launch_semantic_distance * (1.15 if semantic_launch is not None else 0.0)
                    - total_progress * 0.45
                )
                candidates.append((score, launch_index, end_index))

            if candidates:
                _, launch_index, end_index = min(candidates, key=lambda row: row[0])
                return compact_rows[launch_index : end_index + 1]

            # Sparse provider fallback: choose the closest forward pair that
            # still clearly moves toward the correct goal. The first point is
            # always the shot-taking point; never return a pre-shot run.
            if kind in {"shot", "shot_on_target", "shot_off_target", "goal", "penalty"}:
                sparse: list[tuple[float, int, int]] = []
                for launch_index in range(0, len(compact_rows) - 1):
                    launch_point, launch_second = compact_rows[launch_index]
                    for end_index in range(launch_index + 1, min(len(compact_rows), launch_index + 4)):
                        end_point, end_second = compact_rows[end_index]
                        if end_second - launch_second > 24:
                            break
                        end_distance = distance_to_target_goal(end_point)
                        progress = distance_to_target_goal(launch_point) - end_distance
                        if progress < 8.0 or end_distance > max_goal_distance:
                            continue
                        if on_target and goal_center_distance(end_point) > GOAL_HALF_WIDTH_PERCENT + 8.0:
                            continue
                        launch_semantic_distance = 0.0
                        if semantic_launch is not None:
                            launch_semantic_distance = (
                                (float(launch_point["x"]) - float(semantic_launch["x"])) ** 2
                                + (float(launch_point["y"]) - float(semantic_launch["y"])) ** 2
                            ) ** 0.5
                        sparse.append((
                            end_distance * 4.0
                            + time_score(launch_second) * 0.2
                            + launch_semantic_distance * (1.15 if semantic_launch is not None else 0.0)
                            - progress * 0.4,
                            launch_index,
                            end_index,
                        ))
                if sparse:
                    _, launch_index, end_index = min(sparse, key=lambda row: row[0])
                    return compact_rows[launch_index : end_index + 1]

            return []

        if kind == "corner":
            # A corner origin is both near a goal line and touchline. Prefer the
            # corner at this team's attacking end, then keep the path in that end.
            corner_candidates = [
                (index, point, seconds)
                for index, (point, seconds) in enumerate(compact_rows)
                if distance_to_target_goal(point) <= 10.0
                and touchline_distance(point) <= 12.0
            ]
            if not corner_candidates:
                return []

            start_index, _, _ = min(
                corner_candidates,
                key=lambda row: (
                    distance_to_target_goal(row[1]) * 3.0
                    + touchline_distance(row[1]) * 3.0
                    + time_score(row[2]) * 0.3
                ),
            )
            selected = compact_rows[start_index : start_index + 5]
            if not selected:
                return []

            first_point, first_second = selected[0]
            target_is_left = target_goal_x < 50.0
            same_end: list[tuple[dict[str, Any], int]] = [selected[0]]
            previous_point = first_point
            previous_second = first_second

            for point, seconds in selected[1:]:
                # A corner flight is short and continuous. Stop as soon as the
                # provider stream jumps to a later possession phase.
                if seconds - previous_second > 12 or seconds - first_second > 18:
                    break

                point_x = float(point["x"])
                point_y = float(point["y"])
                previous_x = float(previous_point["x"])
                previous_y = float(previous_point["y"])

                if target_is_left and point_x > 30.0:
                    break
                if not target_is_left and point_x < 70.0:
                    break

                step_distance = ((point_x - previous_x) ** 2 + (point_y - previous_y) ** 2) ** 0.5
                if step_distance > 34.0:
                    break

                # The ball should leave the corner/touchline and enter the
                # penalty-area side of the pitch, not hop between unrelated
                # touchline samples.
                if touchline_distance(point) + 2.0 < touchline_distance(previous_point):
                    break

                same_end.append((point, seconds))
                previous_point = point
                previous_second = seconds

            selected = same_end if len(same_end) >= 2 else []

        elif kind in {"goal", "shot_on_target", "penalty"}:
            selected = build_approach_segment(
                on_target=True,
                max_goal_distance=28.0,
            )

        elif kind in {"shot", "shot_off_target"}:
            # Off-target can miss wide or over the bar. With no Z coordinate,
            # only require a meaningful approach toward the correct goal.
            selected = build_approach_segment(
                on_target=False,
                max_goal_distance=32.0,
            )

        else:  # offside
            selected = [
                min(
                    compact_rows,
                    key=lambda row: (
                        time_score(row[1]),
                        min(
                            abs(row[1] - (start + 30))
                            for start, _ in candidate_windows
                        ),
                    ),
                )
            ]

        result = [provider_point(point) for point, _ in selected]
        if kind != "offside" and len(result) < 2:
            return []
        return result

    def extend_goal_track_with_assist(
        item: dict[str, Any],
        shot_track: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Prepend the most plausible stored assist pass to a goal shot track.

        The goal event minute does not carry an event second. The shot segment is
        first located from provider ball-coordinate timers. If the event has a
        related player/assist, walk backwards from the shot launch through the
        same period and keep only a short, continuous sequence ending at the
        scorer's launch point.
        """
        if len(shot_track) < 2:
            return shot_track, 0
        if not (item.get("related_player_id") or item.get("related_player_name")):
            return shot_track, 0

        shot_start_seconds = timer_seconds(shot_track[0].get("timer"))
        if shot_start_seconds is None:
            return shot_track, 0

        period_id = item.get("period_id")
        shot_start = shot_track[0]
        previous_rows = [
            (point, seconds)
            for point, seconds in coordinate_stream
            if seconds < shot_start_seconds
            and seconds >= shot_start_seconds - 20
            and (period_id is None or point.get("period_id") == period_id)
        ]
        if not previous_rows:
            return shot_track, 0

        compact: list[tuple[dict[str, Any], int]] = []
        for point, seconds in previous_rows:
            if compact:
                prev = compact[-1][0]
                if (
                    abs(float(point["x"]) - float(prev["x"])) < 0.01
                    and abs(float(point["y"]) - float(prev["y"])) < 0.01
                ):
                    continue
            compact.append((point, seconds))

        selected_reversed: list[tuple[dict[str, Any], int]] = []
        next_point = shot_start
        next_seconds = shot_start_seconds

        for point, seconds in reversed(compact):
            gap = next_seconds - seconds
            if gap > 10:
                break
            step = (
                (float(next_point["x"]) - float(point["x"])) ** 2
                + (float(next_point["y"]) - float(point["y"])) ** 2
            ) ** 0.5
            if step > 42.0:
                break
            selected_reversed.append((point, seconds))
            next_point = point
            next_seconds = seconds
            if shot_start_seconds - seconds >= 15 or len(selected_reversed) >= 3:
                break

        if not selected_reversed:
            return shot_track, 0

        prefix = list(reversed(selected_reversed))
        first = prefix[0][0]
        progress = (
            (float(shot_start["x"]) - float(first["x"])) ** 2
            + (float(shot_start["y"]) - float(first["y"])) ** 2
        ) ** 0.5
        if progress < 2.0:
            return shot_track, 0

        normalized_prefix = [
            {
                "x": round(float(point["x"]), 3),
                "y": round(float(point["y"]), 3),
                "timer": point.get("timer"),
                "period_id": point.get("period_id"),
            }
            for point, _ in prefix
        ]
        return normalized_prefix + shot_track, len(normalized_prefix)

    def spatial(item: dict[str, Any], kind: str) -> dict[str, Any]:
        team_side = side(item)
        context = item.get("detail") if isinstance(item.get("detail"), dict) else {}
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
                    end = semantic_goal_end(item, team_side, context)
                elif kind == "corner":
                    start_x = float(start_point.get("x") or 50.0)
                    start_y = float(start_point.get("y") or 50.0)
                    box_y = 43.0 if start_y < 50.0 else 57.0
                    # Corner destination is determined by the corner's actual
                    # goal-line end, not by team/home/half assumptions.
                    end_x = 13.0 if start_x < 50.0 else 87.0
                    end = {"x": end_x, "y": box_y}
                elif kind in {"shot", "shot_on_target", "shot_off_target", "penalty"}:
                    if kind == "shot_off_target":
                        miss_offsets = (
                            -(GOAL_HALF_WIDTH_PERCENT + 3.2),
                            -(GOAL_HALF_WIDTH_PERCENT + 1.8),
                            GOAL_HALF_WIDTH_PERCENT + 1.8,
                            GOAL_HALF_WIDTH_PERCENT + 3.2,
                        )
                        end_y = 50.0 + miss_offsets[seed % len(miss_offsets)]
                    elif kind == "shot_on_target":
                        target_offsets = (-4.0, -2.0, 2.0, 4.0)
                        end_y = 50.0 + target_offsets[seed % len(target_offsets)]
                    else:
                        end_y = 50.0
                    end = {"x": attacking_x(item, team_side, 100.0, 0.0), "y": end_y}

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
            # When no event-attached coordinate exists, use commentary semantics
            # (shot origin/goal side) before falling back to the penalty spot.
            start = semantic_shot_start(item, team_side, context) or {
                "x": attacking_x(item, team_side, PENALTY_SPOT_RIGHT_X, PENALTY_SPOT_LEFT_X),
                "y": 50.0,
            }
            end = semantic_goal_end(item, team_side, context)
            return {
                "kind": kind,
                "source": "commentary_inferred" if context.get("commentary") else "inferred",
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

            # Use the event half to choose the attacking end. Teams exchange
            # ends after half-time, so home/away alone is not enough.
            # Once start_x is chosen, keep the entire corner in that same end.
            start_x = attacking_x(item, team_side, 99.0, 1.0)
            box_y = 43.0 if corner_y < 50.0 else 57.0
            end_x = 13.0 if start_x < 50.0 else 87.0
            start = {"x": start_x, "y": corner_y}
            end = {"x": end_x, "y": box_y}
            return {
                "kind": kind,
                "source": "inferred",
                "anchor": start,
                "ball_path": {"start": start, "end": end},
                "highlight_player_id": None,
            }

        if kind in {"shot", "shot_on_target", "shot_off_target", "penalty"}:
            start_x = PENALTY_SPOT_RIGHT_X if kind == "penalty" else 78.0
            start = {
                "x": attacking_x(item, team_side, start_x, 100.0 - start_x),
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
                miss_offsets = (
                    -(GOAL_HALF_WIDTH_PERCENT + 3.2),
                    -(GOAL_HALF_WIDTH_PERCENT + 1.8),
                    GOAL_HALF_WIDTH_PERCENT + 1.8,
                    GOAL_HALF_WIDTH_PERCENT + 3.2,
                )
                end_y = 50.0 + miss_offsets[seed % len(miss_offsets)]
            elif kind == "shot_on_target":
                seed = int(item.get("id") or item.get("minute") or 0)
                target_offsets = (-4.0, -2.0, 2.0, 4.0)
                end_y = 50.0 + target_offsets[seed % len(target_offsets)]
            else:
                end_y = 50.0
            end = {"x": attacking_x(item, team_side, 100.0, 0.0), "y": end_y}
            return {
                "kind": kind,
                "source": "inferred",
                "anchor": start,
                "ball_path": {"start": start, "end": end},
                "highlight_player_id": None,
            }

        if kind == "offside":
            anchor = {
                "x": attacking_x(item, team_side, 82.0, 18.0),
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

            # Normalize ownership once so every consumer (Spatial, timeline
            # crest, filters, goal/shot/corner rendering) sees the same team.
            team_side = side(item)
            if team_side == "home":
                item["is_home"] = True
            elif team_side == "away":
                item["is_home"] = False

            # Enrich the structured event with the closest play-by-play text.
            # Event/subtype remains authoritative for scorer/assist identity;
            # commentary adds body-part, shot-zone, assist-style and goal-target
            # semantics that are not present in the basic event row.
            matched_commentary = commentary_for_event(item, kind)
            detail = dict(item.get("detail") or {})
            if matched_commentary:
                comment_text = str(matched_commentary.get("comment") or "")
                comment_context = shot_context_from_comment(comment_text)
                for key, value in comment_context.items():
                    if key in {"body_part", "situation"}:
                        detail.setdefault(key, value)
                    else:
                        detail[key] = value
                item["commentary_id"] = matched_commentary.get("id")
                item["commentary_text"] = comment_text
            item["detail"] = detail

            trend_context = trend_context_for_event(item)
            if trend_context:
                item["trend_context"] = trend_context

            spatial_data = spatial(item, kind)
            coordinate_track = event_coordinate_track(item, spatial_data, kind)
            shot_start_index = 0
            if coordinate_track and kind == "goal":
                coordinate_track, shot_start_index = extend_goal_track_with_assist(
                    item,
                    coordinate_track,
                )
            if coordinate_track:
                spatial_data["source"] = (
                    "stored_assist_goal"
                    if kind == "goal" and shot_start_index > 0
                    else "stored"
                )
                spatial_data["ball_track"] = coordinate_track
                spatial_data["anchor"] = coordinate_track[0]
                spatial_data["ball_path"] = {
                    "start": coordinate_track[0],
                    "end": coordinate_track[-1],
                }
                if kind == "goal":
                    spatial_data["shot_start_index"] = shot_start_index
                    spatial_data["phases"] = (
                        [
                            {
                                "kind": "assist",
                                "start_index": 0,
                                "end_index": shot_start_index,
                            },
                            {
                                "kind": "shot",
                                "start_index": shot_start_index,
                                "end_index": len(coordinate_track) - 1,
                            },
                        ]
                        if shot_start_index > 0
                        else [
                            {
                                "kind": "shot",
                                "start_index": 0,
                                "end_index": len(coordinate_track) - 1,
                            }
                        ]
                    )
                item["ball_track"] = coordinate_track
                item["ball_path"] = spatial_data["ball_path"]
            item["spatial"] = spatial_data
            if not item.get("player") and item.get("player_id") is not None:
                current = player_for(item)
                if current is not None:
                    item["player"] = current.get("name")

            if not item.get("related_player_name") and item.get("related_player_id") is not None:
                item["related_player_name"] = player_name_for_id(item.get("related_player_id"))

            if kind == "goal":
                # Normalize the semantic event so UI never presents a scored
                # goal as merely a shot on target.
                item["display_type"] = "Goal"
                item["text"] = "Goal"
                scorer = item.get("player")
                assist = item.get("related_player_name")
                if scorer:
                    item["scorer"] = scorer
                if assist and assist != scorer:
                    item["assist"] = assist
            else:
                item["display_type"] = item.get("text") or item.get("type") or kind

            merged.append(item)

    def _video_name_side(team_name: Any) -> str | None:
        normalized = str(team_name or "").strip().casefold()
        if not normalized:
            return None
        home_name = str(game.get("home_team", {}).get("name") or "").strip().casefold()
        away_name = str(game.get("away_team", {}).get("name") or "").strip().casefold()
        if normalized == home_name or normalized in home_name or home_name in normalized:
            return "home"
        if normalized == away_name or normalized in away_name or away_name in normalized:
            return "away"
        return None

    def _video_team_side(team_id: Any) -> str | None:
        try:
            normalized = int(team_id)
            home_id = int(home_team_id) if home_team_id is not None else None
            away_id = int(away_team_id) if away_team_id is not None else None
        except (TypeError, ValueError):
            return None
        if normalized == home_id:
            return "home"
        if normalized == away_id:
            return "away"
        return None

    def _video_track(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for point in value:
            if not isinstance(point, dict):
                continue
            try:
                x = float(point.get("x"))
                y = float(point.get("y"))
            except (TypeError, ValueError):
                continue
            result.append({
                "x": max(0.0, min(100.0, x)),
                "y": max(0.0, min(100.0, y)),
                "timer": point.get("timer"),
                "period_id": point.get("period_id"),
            })
        return result

    def _video_positions(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for position in value:
            if not isinstance(position, dict):
                continue
            player_id = position.get("player_id")
            try:
                x = float(position.get("x"))
                y = float(position.get("y"))
            except (TypeError, ValueError):
                continue
            current: dict[str, Any] = {
                "x": max(0.0, min(100.0, x)),
                "y": max(0.0, min(100.0, y)),
            }
            if player_id is not None:
                try:
                    current["player_id"] = int(player_id)
                except (TypeError, ValueError):
                    pass
            if position.get("player_name"):
                current["player_name"] = position.get("player_name")
            if position.get("team"):
                current["team"] = position.get("team")
            result.append(current)
        return result

    def _video_event_meta(video: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": video.get("provider"),
            "video_id": video.get("video_id"),
            "video_event_key": (
                video.get("video_event_key")
                or video.get("video_event_id")
                or video.get("id")
            ),
            "start_seconds": video.get("video_start_seconds"),
            "end_seconds": video.get("video_end_seconds"),
            "confidence": video.get("confidence"),
            "analysis": video.get("analysis"),
            "source": video.get("source"),
            "transcript_text": video.get("transcript_text"),
        }

    for video in game.get("video_events", []) or []:
        if not isinstance(video, dict):
            continue

        minute = video.get("match_minute")
        player_id = video.get("player_id")
        player_name = str(video.get("player_name") or player_name_for_id(player_id) or "").strip()
        event_label = video.get("display_label") or video.get("event_label") or video.get("transcript_text")
        kind = category({
            "type": video.get("event_type"),
            "text": event_label,
        })
        video_side = _video_name_side(video.get("team_name")) or _video_team_side(video.get("team_id"))
        video_event_id = video.get("video_event_key") or video.get("video_event_id") or video.get("id")
        track = _video_track(video.get("ball_track"))
        positions = _video_positions(video.get("player_positions"))

        candidates: list[tuple[float, dict[str, Any]]] = []
        for existing in merged:
            existing_kind = (existing.get("spatial") or {}).get("kind") or category(existing)
            if existing_kind != kind:
                continue

            existing_minute = existing.get("minute")
            if minute is not None and existing_minute is not None:
                try:
                    minute_delta = abs(int(existing_minute) - int(minute))
                except (TypeError, ValueError):
                    minute_delta = 99
                if minute_delta > 1:
                    continue
            else:
                minute_delta = 2

            score = float(minute_delta)
            if (
                video.get("match_event_id") is not None
                and str(existing.get("id")) == str(video.get("match_event_id"))
            ):
                score -= 10.0
            existing_side = side(existing)
            if video_side and existing_side and video_side != existing_side:
                score += 6.0

            if player_id is not None and existing.get("player_id") is not None:
                if str(player_id) == str(existing.get("player_id")):
                    score -= 0.5
                else:
                    score += 2.0
            existing_player = str(existing.get("player") or "").strip().casefold()
            if player_name and existing_player:
                if player_name.casefold() == existing_player:
                    score -= 0.5
                else:
                    score += 2.0
            candidates.append((score, existing))

        matched = min(candidates, key=lambda row: row[0])[1] if candidates and min(candidates, key=lambda row: row[0])[0] < 5.0 else None

        if matched is None:
            item: dict[str, Any] = {
                "id": f"video:{video_event_id}",
                "minute": minute,
                "extra_minute": video.get("extra_minute", video.get("match_extra_minute")),
                "type": video.get("event_type") or kind,
                "text": event_label or video.get("event_type") or kind,
                "player": player_name or None,
                "player_id": player_id,
                "related_player_name": video.get("related_player_name"),
                "source_kind": "video",
                "video_analysis": _video_event_meta(video),
                "video_start_seconds": video.get("video_start_seconds"),
                "video_end_seconds": video.get("video_end_seconds"),
                "video_confidence": video.get("confidence"),
                "detail": (
                    video.get("analysis")
                    if isinstance(video.get("analysis"), dict)
                    else {"transcript_text": video.get("transcript_text")}
                    if video.get("transcript_text")
                    else {}
                ),
            }
            if video_side == "home":
                item["is_home"] = True
                item["team_id"] = home_team_id
            elif video_side == "away":
                item["is_home"] = False
                item["team_id"] = away_team_id

            spatial_data = spatial(item, kind)
            if track:
                spatial_data["source"] = "video"
                spatial_data["anchor"] = track[0]
                spatial_data["ball_track"] = track
                spatial_data["ball_path"] = {"start": track[0], "end": track[-1]}
                item["ball_track"] = track
                item["ball_path"] = spatial_data["ball_path"]
            if positions:
                item["player_positions"] = positions
            item["spatial"] = spatial_data
            item["display_type"] = item["text"]
            merged.append(item)
            continue

        matched["video_analysis"] = _video_event_meta(video)
        matched["video_start_seconds"] = video.get("video_start_seconds")
        matched["video_end_seconds"] = video.get("video_end_seconds")
        matched["video_confidence"] = video.get("confidence")
        if player_id is not None and matched.get("player_id") is None:
            matched["player_id"] = player_id
        if player_name and not matched.get("player"):
            matched["player"] = player_name

        if positions and not matched.get("player_positions"):
            matched["player_positions"] = positions

        matched_spatial = matched.get("spatial") or spatial(matched, kind)
        existing_track = list(matched_spatial.get("ball_track") or [])
        if track and not existing_track:
            matched_spatial["source"] = "video"
            matched_spatial["anchor"] = track[0]
            matched_spatial["ball_track"] = track
            matched_spatial["ball_path"] = {"start": track[0], "end": track[-1]}
            matched["ball_track"] = track
            matched["ball_path"] = matched_spatial["ball_path"]
            matched["spatial"] = matched_spatial

    # Provider may expose the scored attempt as both a goal event and a
    # shot-on-target event. Keep the Goal as the canonical selectable event
    # when minute/team/scorer identify the same action.
    goals = [event for event in merged if event.get("spatial", {}).get("kind") == "goal"]
    shots_on_target = [
        event for event in merged
        if event.get("spatial", {}).get("kind") == "shot_on_target"
    ]

    def same_actor(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a.get("player_id") is not None and b.get("player_id") is not None:
            return str(a.get("player_id")) == str(b.get("player_id"))
        a_name = str(a.get("player") or "").strip().casefold()
        b_name = str(b.get("player") or "").strip().casefold()
        return bool(a_name and b_name and a_name == b_name)

    # When Provider exposes a goal plus its scored shot as separate
    # events, the shot-on-target entry may be the one that resolves cleanly to
    # the coordinate stream. Transfer that stored traversal onto the Goal
    # before removing the duplicate shot event.
    for goal in goals:
        goal_spatial = goal.get("spatial") or {}
        if goal_spatial.get("source") == "stored" and goal_spatial.get("ball_track"):
            continue

        candidates = [
            shot for shot in shots_on_target
            if shot.get("minute") == goal.get("minute")
            and shot.get("extra_minute") == goal.get("extra_minute")
            and shot.get("team_id") == goal.get("team_id")
            and (
                same_actor(goal, shot)
                or goal.get("player_id") is None
                or shot.get("player_id") is None
            )
            and (shot.get("spatial") or {}).get("source") == "stored"
            and (shot.get("spatial") or {}).get("ball_track")
        ]
        if not candidates:
            continue

        shot = candidates[0]
        shot_spatial = shot["spatial"]
        track = list(shot_spatial.get("ball_track") or [])
        if not track:
            continue

        goal_spatial["source"] = "stored"
        goal_spatial["anchor"] = track[0]
        goal_spatial["ball_track"] = track
        goal_spatial["ball_path"] = {
            "start": track[0],
            "end": track[-1],
        }
        goal["spatial"] = goal_spatial
        goal["ball_track"] = track
        goal["ball_path"] = goal_spatial["ball_path"]

    cleaned: list[dict[str, Any]] = []
    for event in merged:
        if event.get("spatial", {}).get("kind") == "shot_on_target":
            duplicate_goal = any(
                goal.get("minute") == event.get("minute")
                and goal.get("extra_minute") == event.get("extra_minute")
                and goal.get("team_id") == event.get("team_id")
                and (
                    same_actor(goal, event)
                    or goal.get("player_id") is None
                    or event.get("player_id") is None
                )
                for goal in goals
            )
            if duplicate_goal:
                continue
        cleaned.append(event)
    merged = cleaned

    merged.sort(
        key=lambda item: (
            item.get("minute") if item.get("minute") is not None else 999,
            item.get("extra_minute") if item.get("extra_minute") is not None else 0,
            item.get("sort_order") if item.get("sort_order") is not None else 999,
            0 if item.get("source_kind") == "event" else 1 if item.get("source_kind") == "timeline" else 2,
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
