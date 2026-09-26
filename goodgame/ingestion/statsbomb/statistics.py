"""Season-level team and player statistics derived from StatsBomb Open Data."""

import math
import re
from typing import Any

from goodgame.ingestion.statsbomb.client import StatsBombClient


_ON_TARGET_OUTCOMES = {"goal", "saved", "saved to post"}


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str:
    return "" if _missing(value) else str(value)


def _int(value: Any, default: int = 0) -> int:
    if _missing(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float:
    if _missing(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: Any) -> bool:
    return not _missing(value) and bool(value)


def _identity(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _event_counters() -> dict[str, int | float]:
    return {
        "shots": 0,
        "shots_on_target": 0,
        "expected_goals": 0.0,
        "passes_attempted": 0,
        "passes_completed": 0,
        "key_passes": 0,
        "pressures": 0,
        "tackles": 0,
        "interceptions": 0,
        "clearances": 0,
        "recoveries": 0,
        "fouls": 0,
        "yellow_cards": 0,
        "red_cards": 0,
    }


def _accumulate_event(counters: dict[str, int | float], event: dict[str, Any]) -> None:
    event_type = _text(event.get("type")).casefold()
    if event_type == "shot":
        counters["shots"] += 1
        outcome = _text(event.get("shot_outcome")).casefold()
        if outcome in _ON_TARGET_OUTCOMES:
            counters["shots_on_target"] += 1
        counters["expected_goals"] += _float(event.get("shot_statsbomb_xg"))
    elif event_type == "pass":
        counters["passes_attempted"] += 1
        if _missing(event.get("pass_outcome")):
            counters["passes_completed"] += 1
        if _truthy(event.get("pass_shot_assist")):
            counters["key_passes"] += 1
    elif event_type == "pressure":
        counters["pressures"] += 1
    elif event_type == "duel" and _text(event.get("duel_type")).casefold() == "tackle":
        counters["tackles"] += 1
    elif event_type == "interception":
        counters["interceptions"] += 1
    elif event_type == "clearance":
        counters["clearances"] += 1
    elif event_type == "ball recovery":
        counters["recoveries"] += 1
    elif event_type == "foul committed":
        counters["fouls"] += 1

    card = _text(event.get("foul_committed_card")) or _text(
        event.get("bad_behaviour_card")
    )
    if "yellow" in card.casefold():
        counters["yellow_cards"] += 1
    elif "red" in card.casefold():
        counters["red_cards"] += 1


def list_teams(
    client: StatsBombClient, competition_id: int, season_id: int
) -> list[dict[str, Any]]:
    teams: dict[int, str] = {}
    for match in client.get_matches(competition_id, season_id):
        for side in ("home", "away"):
            team_id = _int(match.get(f"{side}_team_id"), -1)
            team_name = _text(match.get(f"{side}_team"))
            if team_id >= 0 and team_name:
                teams[team_id] = team_name
    return [
        {"team_id": team_id, "team_name": name}
        for team_id, name in sorted(teams.items(), key=lambda item: item[1].casefold())
    ]


def get_team_standings(
    client: StatsBombClient, competition_id: int, season_id: int
) -> list[dict[str, Any]]:
    table = {
        team["team_id"]: {
            **team,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        }
        for team in list_teams(client, competition_id, season_id)
    }
    for match in client.get_matches(competition_id, season_id):
        home_goals = _int(match.get("home_score"), -1)
        away_goals = _int(match.get("away_score"), -1)
        if home_goals < 0 or away_goals < 0:
            continue
        home_id = _int(match.get("home_team_id"), -1)
        away_id = _int(match.get("away_team_id"), -1)
        if home_id not in table or away_id not in table:
            continue

        home, away = table[home_id], table[away_id]
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_goals
        home["goals_against"] += away_goals
        away["goals_for"] += away_goals
        away["goals_against"] += home_goals
        if home_goals > away_goals:
            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1
        elif home_goals < away_goals:
            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1

    rows = list(table.values())
    for row in rows:
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    rows.sort(
        key=lambda row: (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            row["team_name"].casefold(),
        )
    )
    for position, row in enumerate(rows, start=1):
        row["position"] = position
    return rows


def list_players(
    client: StatsBombClient,
    competition_id: int,
    season_id: int,
    team: str | int | None = None,
) -> list[dict[str, Any]]:
    teams_by_name = {
        _identity(match.get(f"{side}_team")): _int(match.get(f"{side}_team_id"), -1)
        for match in client.get_matches(competition_id, season_id)
        for side in ("home", "away")
    }
    requested_team_id = None
    if team is not None:
        if isinstance(team, int) or _text(team).isdecimal():
            requested_team_id = int(team)
        else:
            requested_team_id = teams_by_name.get(_identity(team))
            if requested_team_id is None:
                raise LookupError(f"Team not found in this StatsBomb season: {team}")

    players: dict[tuple[int, int], dict[str, Any]] = {}
    for match in client.get_matches(competition_id, season_id):
        for team_name, team_players in client.get_lineups(_int(match.get("match_id"))).items():
            team_id = teams_by_name.get(_identity(team_name), -1)
            if requested_team_id is not None and team_id != requested_team_id:
                continue
            for player in team_players:
                player_id = _int(player.get("player_id"), -1)
                player_name = _text(player.get("player_name"))
                if player_id >= 0 and player_name:
                    players[(team_id, player_id)] = {
                        "player_id": player_id,
                        "player_name": player_name,
                        "team_id": team_id,
                        "team_name": team_name,
                    }
    return sorted(
        players.values(), key=lambda player: (player["team_name"].casefold(), player["player_name"].casefold())
    )


def get_team_statistics(
    client: StatsBombClient,
    competition_id: int,
    season_id: int,
    team: str | int,
) -> dict[str, Any]:
    matches = client.get_matches(competition_id, season_id)
    teams = list_teams(client, competition_id, season_id)
    if isinstance(team, int) or _text(team).isdecimal():
        selected = next((item for item in teams if item["team_id"] == int(team)), None)
    else:
        selected = next((item for item in teams if _identity(item["team_name"]) == _identity(team)), None)
    if selected is None:
        raise LookupError(f"Team not found in this StatsBomb season: {team}")

    team_id = selected["team_id"]
    standings = get_team_standings(client, competition_id, season_id)
    standing = next(
        row
        for row in standings
        if row["team_id"] == team_id
    )
    stats = _event_counters()
    stats.update(
        team_id=team_id,
        team_name=selected["team_name"],
        competition_id=competition_id,
        season_id=season_id,
        matches_played=0,
        wins=0,
        draws=0,
        losses=0,
        goals_for=0,
        goals_against=0,
        position=standing["position"],
        standing_teams=len(standings),
        points=standing["points"],
        goal_difference=standing["goal_difference"],
    )
    for match in matches:
        if _int(match.get("home_team_id"), -1) == team_id:
            side = "home"
        elif _int(match.get("away_team_id"), -1) == team_id:
            side = "away"
        else:
            continue

        stats["matches_played"] += 1
        goals_for = _int(match.get(f"{side}_score"))
        goals_against = _int(match.get("away_score" if side == "home" else "home_score"))
        stats["goals_for"] += goals_for
        stats["goals_against"] += goals_against
        if goals_for > goals_against:
            stats["wins"] += 1
        elif goals_for == goals_against:
            stats["draws"] += 1
        else:
            stats["losses"] += 1

        for event in client.get_events(_int(match.get("match_id"))):
            event_team_id = _int(event.get("team_id"), -1)
            event_team_name = _identity(event.get("team"))
            if event_team_id == team_id or (
                event_team_id < 0 and event_team_name == _identity(selected["team_name"])
            ):
                _accumulate_event(stats, event)

    attempts = stats["passes_attempted"]
    stats["pass_completion_pct"] = (
        round(stats["passes_completed"] / attempts * 100, 1) if attempts else None
    )
    stats["expected_goals"] = round(stats["expected_goals"], 3)
    return stats


def _season_key(value: Any) -> str:
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


def get_player_statistics_all_leagues(
    client: StatsBombClient,
    season_name: str,
    player: str | int,
    team: str | None = None,
) -> dict[str, Any]:
    season_key = _season_key(season_name)
    season_rows = [
        row
        for row in client.get_competitions()
        if _season_key(row.get("season_name", "")) == season_key
        and row.get("competition_id") is not None
        and row.get("season_id") is not None
    ]
    contexts = list(
        dict.fromkeys((int(row["competition_id"]), int(row["season_id"])) for row in season_rows)
    )
    if not contexts:
        raise LookupError(f"No StatsBomb competitions contain season {season_name}")

    total_keys = (
        "appearances", "starts", "substitute_appearances", "goals", "assists",
        "shots", "shots_on_target", "passes_attempted", "passes_completed",
        "key_passes", "pressures", "tackles", "interceptions", "clearances",
        "recoveries", "fouls", "yellow_cards", "red_cards", "minutes_played",
        "expected_goals",
    )
    totals: dict[str, Any] | None = None
    used_competitions: list[str] = []
    team_names: set[str] = set()
    for competition_id, current_season_id in contexts:
        try:
            stats = get_player_statistics(
                client, competition_id, current_season_id, player, team
            )
        except LookupError as error:
            if str(error).startswith((
                "Player not found in this StatsBomb season:",
                "Team not found in this StatsBomb season:",
            )):
                continue
            raise
        if stats["appearances"] == 0:
            continue
        if totals is None:
            totals = {key: 0 for key in total_keys}
            totals.update(
                player_id=stats["player_id"],
                player_name=stats["player_name"],
                season_name=season_name,
            )
        for key in total_keys:
            totals[key] += stats.get(key, 0)
        team_names.add(stats["team_name"])
        competition = next(
            (
                str(row.get("competition_name", competition_id))
                for row in season_rows
                if int(row["competition_id"]) == competition_id
                and int(row["season_id"]) == current_season_id
            ),
            str(competition_id),
        )
        used_competitions.append(competition)

    if totals is None:
        raise LookupError(f"Player not found in StatsBomb season {season_name}: {player}")

    totals["team_name"] = ", ".join(sorted(team_names))
    totals["competitions"] = sorted(set(used_competitions))
    totals["competition_count"] = len(totals["competitions"])
    attempts = totals["passes_attempted"]
    totals["pass_completion_pct"] = (
        round(totals["passes_completed"] / attempts * 100, 1) if attempts else None
    )
    totals["expected_goals"] = round(totals["expected_goals"], 3)
    totals["minutes_played"] = round(totals["minutes_played"], 1)
    return totals


def _clock_seconds(value: Any) -> float | None:
    if _missing(value):
        return None
    parts = str(value).split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return None


def get_player_statistics(
    client: StatsBombClient,
    competition_id: int,
    season_id: int,
    player: str | int,
    team: str | None = None,
) -> dict[str, Any]:
    roster = list_players(client, competition_id, season_id, team)
    if isinstance(player, int) or _text(player).isdecimal():
        candidates = [item for item in roster if item["player_id"] == int(player)]
    else:
        candidates = [item for item in roster if _identity(item["player_name"]) == _identity(player)]
    if not candidates:
        raise LookupError(f"Player not found in this StatsBomb season: {player}")
    if len(candidates) > 1:
        team_names = ", ".join(item["team_name"] for item in candidates)
        raise LookupError(f"Player name is ambiguous ({team_names}); pass a player ID or team")
    selected = candidates[0]

    stats = _event_counters()
    stats.update(
        player_id=selected["player_id"],
        player_name=selected["player_name"],
        team_id=selected["team_id"],
        team_name=selected["team_name"],
        competition_id=competition_id,
        season_id=season_id,
        appearances=0,
        starts=0,
        substitute_appearances=0,
        goals=0,
        assists=0,
        minutes_played=0.0,
    )
    for match in client.get_matches(competition_id, season_id):
        match_id = _int(match.get("match_id"))
        lineup_rows = client.get_lineups(match_id).get(selected["team_name"], [])
        lineup = next(
            (row for row in lineup_rows if _int(row.get("player_id"), -1) == selected["player_id"]),
            None,
        )
        if lineup is None:
            continue
        events = client.get_events(match_id)
        player_events = [
            event
            for event in events
            if _int(event.get("player_id"), -1) == selected["player_id"]
        ]
        was_subbed_on = any(
            _int(event.get("substitution_replacement_id"), -1) == selected["player_id"]
            for event in events
        )

        positions = lineup.get("positions", []) or []
        if not positions and not player_events and not was_subbed_on:
            continue
        started = any(position.get("start_reason") == "Starting XI" for position in positions)
        end_seconds = max(
            (_int(event.get("minute")) * 60 + _float(event.get("second")) for event in events),
            default=0,
        )
        minutes = 0.0
        for position in positions:
            start = _clock_seconds(position.get("from"))
            end = _clock_seconds(position.get("to"))
            if start is not None:
                minutes += max(0.0, ((end if end is not None else end_seconds) - start) / 60)

        stats["appearances"] += 1
        stats["starts"] += int(started)
        stats["minutes_played"] += minutes
        for event in player_events:
            _accumulate_event(stats, event)
            event_type = _text(event.get("type")).casefold()
            if event_type == "shot" and _text(event.get("shot_outcome")).casefold() == "goal":
                stats["goals"] += 1
            if event_type == "pass" and _truthy(event.get("pass_goal_assist")):
                stats["assists"] += 1

    stats["substitute_appearances"] = stats["appearances"] - stats["starts"]
    stats["minutes_played"] = round(stats["minutes_played"], 1)
    attempts = stats["passes_attempted"]
    stats["pass_completion_pct"] = (
        round(stats["passes_completed"] / attempts * 100, 1) if attempts else None
    )
    stats["expected_goals"] = round(stats["expected_goals"], 3)
    return stats