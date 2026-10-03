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
                score = (
                    end_distance * 4.0
                    + center_distance * (1.7 if on_target else 0.0)
                    + time_score(launch_second) * 0.2
                    + duration * 0.08
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
                        sparse.append((
                            end_distance * 4.0 + time_score(launch_second) * 0.2 - progress * 0.4,
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

            first_second = selected[0][1]
            target_is_left = target_goal_x < 50.0
            same_end: list[tuple[dict[str, Any], int]] = []
            for row in selected:
                point, seconds = row
                if seconds - first_second > 22:
                    break
                point_x = float(point["x"])
                if same_end:
                    if target_is_left and point_x > 30.0:
                        break
                    if not target_is_left and point_x < 70.0:
                        break
                same_end.append(row)
            selected = same_end

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
                    end = {"x": attacking_x(item, team_side, 100.0, 0.0), "y": 50.0}
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
            # Until provider ball coordinates are available, keep this deliberately
            # simple and explicit: penalty spot -> attacking goal.
            start = {
                "x": attacking_x(item, team_side, PENALTY_SPOT_RIGHT_X, PENALTY_SPOT_LEFT_X),
                "y": 50.0,
            }
            end = {"x": attacking_x(item, team_side, 100.0, 0.0), "y": 50.0}
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
