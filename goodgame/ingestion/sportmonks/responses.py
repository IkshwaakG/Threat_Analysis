"""Sportmonks Football API v3 response normalization.

The request module owns endpoint paths/includes. This module converts raw
Sportmonks payloads into GoodGame models or stable dictionaries.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from goodgame.models.event import Event
from goodgame.models.match import Match, Team


def name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    return value if isinstance(value, str) else None


def integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def slug(value: Any) -> str:
    return "_".join(
        part
        for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in str(value)
        ).split()
        if part
    )


def extract_fixtures_from_schedule(schedule: Any) -> list[dict[str, Any]]:
    """Flatten a schedules-by-season payload into a flat, de-duplicated fixture list.

    Sportmonks v3 has no fixtures-by-season endpoint; schedules-by-season
    nests fixtures under stages -> rounds/groups instead, at varying depth
    depending on competition format, so this walks the whole tree.
    """
    fixtures: dict[int, dict[str, Any]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            raw_fixtures = node.get("fixtures")
            if isinstance(raw_fixtures, list):
                for fixture in raw_fixtures:
                    if isinstance(fixture, dict) and fixture.get("id") is not None:
                        fixtures[fixture["id"]] = fixture
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schedule)
    return list(fixtures.values())


def season_key(value: Any) -> str:
    parts = re.findall(r"\d{2,4}", str(value))
    if not parts:
        return str(value).strip().casefold()
    start = int(parts[0])
    if len(parts[0]) == 2:
        start += 2000 if start < 70 else 1900
    if len(parts) == 1:
        return str(start)
    end = int(parts[1])
    if len(parts[1]) == 2:
        end += start // 100 * 100
        if end < start:
            end += 100
    return f"{start}/{end}"


def detail_statistics(details: Any) -> dict[str, Any]:
    """Flatten Sportmonks detail records while preserving nested values."""
    results: dict[str, Any] = {}
    if not isinstance(details, list):
        return results
    for detail in details:
        if not isinstance(detail, dict):
            continue
        stat_type = detail.get("type")
        stat_name = name(stat_type) or f"stat_{detail.get('type_id', 'unknown')}"
        # Fixture lineup details use `data`; season/player statistics use
        # `value`. Support both shapes so callers can normalize either.
        raw_value = detail.get("data") if "data" in detail else detail.get("value")
        results[slug(stat_name)] = raw_value
    return results


def scalar_statistics(details: Any) -> dict[str, Any]:
    """Flatten common total/value wrappers for convenience."""
    results: dict[str, Any] = {}
    for key, value in detail_statistics(details).items():
        if isinstance(value, dict):
            if "total" in value:
                value = value["total"]
            elif "value" in value:
                value = value["value"]
        results[key] = value
    return results


def fixture_to_match(fixture: dict[str, Any]) -> Match:
    home = away = None
    for participant in fixture.get("participants", []) or []:
        if not isinstance(participant, dict):
            continue
        location = (participant.get("meta") or {}).get("location")
        if location == "home":
            home = participant
        elif location == "away":
            away = participant

    if home is None or away is None:
        raise ValueError(
            f"Sportmonks fixture {fixture.get('id')} is missing participants"
        )

    score_by_team: dict[int, int] = {}
    for item in fixture.get("scores", []) or []:
        if not isinstance(item, dict):
            continue
        participant_id = integer(item.get("participant_id"))
        score = item.get("score") or {}
        value = integer(score.get("goals")) if isinstance(score, dict) else integer(score)
        if participant_id is not None and value is not None:
            score_by_team[participant_id] = value

    state = fixture.get("state") or {}
    league = fixture.get("league") or {}
    season = fixture.get("season") or {}

    stamp = integer(fixture.get("starting_at_timestamp"))
    if stamp is None and fixture.get("starting_at"):
        try:
            stamp = int(datetime.fromisoformat(str(fixture["starting_at"])).timestamp())
        except ValueError:
            stamp = None

    return Match(
        id=int(fixture["id"]),
        home_team=Team(id=int(home["id"]), name=str(home.get("name", "Home"))),
        away_team=Team(id=int(away["id"]), name=str(away.get("name", "Away"))),
        home_score=score_by_team.get(int(home["id"])),
        away_score=score_by_team.get(int(away["id"])),
        status=str(state.get("name", "unknown")),
        start_timestamp=stamp,
        tournament_id=integer(fixture.get("league_id", league.get("id"))),
        season_id=integer(fixture.get("season_id", season.get("id"))),
    )


_EVENT_KINDS = {
    "goal": "goal",
    "owngoal": "own_goal",
    "penalty": "penalty_goal",
    "missed_penalty": "missed_penalty",
    "substitution": "substitution",
    "yellowcard": "card",
    "redcard": "card",
    "yellowredcard": "card",
    "var": "var",
    "var_card": "var",
}


def _event_code(event: dict[str, Any]) -> str:
    type_info = event.get("type")
    if isinstance(type_info, dict):
        code = type_info.get("developer_name") or type_info.get("code")
        if code:
            return str(code).casefold().replace(" ", "_")
    return ""


def fixture_event_to_event(event: dict[str, Any], match: Match) -> Event:
    event_type = (
        name(event.get("type"))
        or str(event.get("type_name") or event.get("info") or "event")
    )
    normalized_type = event_type.casefold()
    code = _event_code(event)

    if code in _EVENT_KINDS:
        kind = _EVENT_KINDS[code]
    elif "goal" in normalized_type:
        kind = "goal"
    elif "substitution" in normalized_type:
        kind = "substitution"
    elif "card" in normalized_type:
        kind = "card"
    elif "shot" in normalized_type:
        kind = "shot"
    else:
        kind = normalized_type.replace(" ", "_")

    participant_id = integer(event.get("participant_id"))
    player = name(event.get("player")) or event.get("player_name")
    related_player = (
        name(event.get("relatedPlayer"))
        or name(event.get("related_player"))
        or event.get("related_player_name")
    )
    result = event.get("result")

    text = str(event.get("info") or event.get("addition") or event_type)
    if kind in {"goal", "penalty_goal"} and player:
        text = f"Goal by {player}"
    elif kind == "own_goal" and player:
        text = f"Own goal by {player}"

    card_class = None
    if kind == "card":
        card_class = str(result) if result is not None else code or None

    return Event(
        id=event.get("id"),
        minute=integer(event.get("minute")),
        incident_type=kind,
        text=text,
        is_home=(
            participant_id == match.home_team.id
            if participant_id is not None
            else None
        ),
        player=player,
        player_in=related_player if kind == "substitution" else None,
        player_out=player if kind == "substitution" else None,
        incident_class=card_class,
        extra_minute=integer(event.get("extra_minute")),
        player_id=integer(event.get("player_id")),
        related_player_id=integer(event.get("related_player_id")),
        team_id=participant_id,
        rescinded=bool(event.get("rescinded")),
        raw=dict(event),
    )


def fixture_ball_coordinates(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Ball traversal points (ballCoordinates include) in time order."""
    rows = [
        {
            "id": item.get("id"),
            "participant_id": integer(item.get("participant_id")),
            "minute": integer(item.get("minute")),
            "second": integer(item.get("second")),
            "x": integer(item.get("x")),
            "y": integer(item.get("y")),
        }
        for item in fixture.get("ballcoordinates", fixture.get("ballCoordinates", []))
        or []
        if isinstance(item, dict)
    ]
    return sorted(
        rows, key=lambda r: (r["minute"] or 0, r["second"] or 0, r["id"] or 0)
    )


def fixture_player_positions(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-player formation slot and pitch position from lineups."""
    return [
        {
            "player_id": integer(row.get("player_id")),
            "player_name": row.get("player_name") or name(row.get("player")),
            "team_id": integer(row.get("team_id")),
            "position_id": integer(row.get("position_id")),
            "position": name(row.get("position")),
            "formation_field": row.get("formation_field"),
            "formation_position": integer(row.get("formation_position")),
            "jersey_number": integer(row.get("jersey_number")),
            "starter": integer(row.get("type_id")) == 11,
        }
        for row in fixture.get("lineups", []) or []
        if isinstance(row, dict)
    ]


def fixture_events(fixture: dict[str, Any], match: Match) -> list[Event]:
    return [
        fixture_event_to_event(event, match)
        for event in fixture.get("events", []) or []
        if isinstance(event, dict)
    ]


def fixture_lineups(
    fixture: dict[str, Any], match: Match
) -> dict[str, list[dict[str, Any]]]:
    teams: dict[str, list[dict[str, Any]]] = {
        match.home_team.name: [],
        match.away_team.name: [],
    }
    for lineup in fixture.get("lineups", []) or []:
        if not isinstance(lineup, dict):
            continue
        participant_id = integer(lineup.get("team_id"))
        if participant_id == match.home_team.id:
            teams[match.home_team.name].append(lineup)
        elif participant_id == match.away_team.id:
            teams[match.away_team.name].append(lineup)
    return teams


def fixture_shots(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in fixture.get("events", []) or []
        if isinstance(event, dict)
        and "shot" in str(name(event.get("type")) or "").casefold()
    ]


def normalize_player_statistics(
    player_record: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    team: str | None = None,
    competition_id: int | None = None,
    season_id: int | None = None,
) -> dict[str, Any]:
    filtered: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    requested_team = " ".join(team.casefold().split()) if team else None

    for record in records:
        season = record.get("season") if isinstance(record.get("season"), dict) else {}
        stat_team = record.get("team") if isinstance(record.get("team"), dict) else {}
        league = season.get("league") if isinstance(season.get("league"), dict) else {}

        if season_id is not None and integer(record.get("season_id", season.get("id"))) != season_id:
            continue
        if competition_id is not None and integer(
            league.get("id", season.get("league_id"))
        ) != competition_id:
            continue
        if requested_team and " ".join(
            str(stat_team.get("name", "")).casefold().split()
        ) != requested_team:
            continue
        filtered.append((record, season, stat_team, league))

    if not filtered:
        raise LookupError("No Sportmonks player statistics matched the selected filters")

    result: dict[str, Any] = {
        "player_id": player_record.get("id"),
        "player_name": player_record.get("name") or player_record.get("display_name"),
        "team_id": None,
        "team_name": None,
        "season_id": season_id,
        "competition_id": competition_id,
    }

    for record, season, stat_team, league in filtered:
        result["team_id"] = result["team_id"] or record.get("team_id", stat_team.get("id"))
        result["team_name"] = result["team_name"] or stat_team.get("name")
        result["season_id"] = record.get("season_id", season.get("id"))
        result["season_name"] = season.get("name")
        result["competition_id"] = league.get("id", season.get("league_id"))
        result["competition_name"] = league.get("name")
        result.update(scalar_statistics(record.get("details")))

    return result


def normalize_team_statistics(
    standing: dict[str, Any],
    season_records: list[dict[str, Any]],
    *,
    competition_id: int | None,
    season_id: int,
    standings_count: int,
    team_name: str,
) -> dict[str, Any]:
    participant = standing.get("participant") or {}
    team_id = integer(standing.get("participant_id"))
    if team_id is None:
        raise LookupError(f"Sportmonks standing has no team ID for {team_name}")

    stats: dict[str, Any] = {
        "team_id": team_id,
        "team_name": str(name(participant) or team_name),
        "competition_id": competition_id or standing.get("league_id"),
        "season_id": season_id,
        "position": integer(standing.get("position")) or 0,
        "standing_teams": standings_count,
        "points": integer(standing.get("points")) or 0,
    }
    stats.update(scalar_statistics(standing.get("details")))

    for record in season_records:
        if integer(record.get("season_id")) == season_id:
            stats.update(scalar_statistics(record.get("details")))

    stats.setdefault("goal_difference", 0)
    return stats
