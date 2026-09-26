"""Interactive local runner for configured football data provider."""

import argparse
import re
import sys
from typing import Any, Callable, Sequence, TextIO

from goodgame.ingestion.factory import create_provider
from goodgame.ingestion.provider import MatchDataProvider
from goodgame.ingestion.sportmonks.client import SportmonksError
from goodgame.ingestion.statsbomb.provider import StatsBombProvider
from goodgame.models.match import Match
from goodgame.pipeline import GoodGamePipeline


def _year_key(value: object) -> str:
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze football matches using Sportmonks or StatsBomb."
    )
    parser.add_argument(
        "--provider", choices=("sportmonks", "statsbomb"),
        help="Data provider (default: GOODGAME_PROVIDER or sportmonks)",
    )
    parser.add_argument("--competition-id", type=int, help="Competition/league ID for the selected provider")
    season_group = parser.add_mutually_exclusive_group()
    season_group.add_argument("--season-id", type=int, help="Season ID for the selected provider")
    season_group.add_argument(
        "--season", "--season-year", "--season-name", dest="season_name",
        help="Season label, for example 2023/24 (matched against provider catalog)",
    )
    match_group = parser.add_mutually_exclusive_group()
    match_group.add_argument("--match-id", type=int, help="Analyze this match ID directly")
    match_group.add_argument(
        "--teams", nargs=2, metavar=("TEAM_A", "TEAM_B"),
        help="Find a match between two teams in a selected competition and season",
    )
    stats_group = parser.add_mutually_exclusive_group()
    stats_group.add_argument(
        "--team-stats", metavar="TEAM",
        help="Show season team statistics from the selected provider",
    )
    stats_group.add_argument(
        "--player-stats", metavar="PLAYER",
        help="Show season player statistics from the selected provider",
    )
    parser.add_argument("--player-team", help="Disambiguate a player name by team")
    parser.add_argument(
        "--all-leagues", action="store_true",
        help="Aggregate player stats across competitions sharing the selected season",
    )
    return parser


def _choose(
    labels: list[str], input_fn: Callable[[str], str], output: TextIO, prompt: str
) -> int | None:
    for index, label in enumerate(labels, start=1):
        output.write(f"{index}. {label}\n")
    try:
        choice = int(input_fn(prompt))
    except ValueError:
        output.write("Please enter a listed number.\n")
        return None
    if not 1 <= choice <= len(labels):
        output.write("That number is not in the list.\n")
        return None
    return choice - 1


def _choose_competition_season(
    provider: Any,
    competition_id: int | None,
    season_id: int | None,
    season_name: str | None,
    input_fn: Callable[[str], str],
    output: TextIO,
    team_name: str | None = None,
) -> tuple[int, int] | None:
    if competition_id is not None and season_id is not None:
        return competition_id, season_id

    rows = [
        ((int(row["competition_id"]), int(row["season_id"])), row)
        for row in provider.list_competitions()
        if row.get("competition_id") is not None and row.get("season_id") is not None
    ]
    filtered = []
    team_competitions_checked: list[str] = []
    for key, row in rows:
        if competition_id is not None and key[0] != competition_id:
            continue
        if season_id is not None and key[1] != season_id:
            continue
        if season_name is not None and _year_key(row.get("season_name", "")) != _year_key(season_name):
            continue
        if team_name is not None and (season_id is not None or season_name is not None):
            team_competitions_checked.append(
                str(row.get("competition_name", key[0]))
            )
            matches = provider.list_matches(*key)
            normalized_team = " ".join(team_name.casefold().split())
            team_in_season = any(
                normalized_team
                in {
                    " ".join(str(match.get(field, "")).casefold().split())
                    for field in ("home_team", "away_team")
                }
                for match in matches
            )
            if not team_in_season:
                continue
        filtered.append((key, row))

    if not filtered:
        if team_name is not None:
            checked_competitions = ", ".join(sorted(set(team_competitions_checked)))
            coverage_hint = (
                f" Competitions checked: {checked_competitions}."
                if checked_competitions
                else " No competitions matched the season filters."
            )
            output.write(
                f"Team {team_name!r} was not found in any accessible competition/season "
                f"matching those filters.{coverage_hint}\n"
            )
        else:
            output.write("No matching competition/season was found.\n")
        return None

    competition_options = {
        key[0]: str(row.get("competition_name", key[0]))
        for key, row in filtered
    }
    if competition_id is None and len(competition_options) > 1:
        sorted_competitions = sorted(
            competition_options.items(), key=lambda item: item[1].casefold()
        )
        selection = _choose(
            [f"{name} (competition {current_id})" for current_id, name in sorted_competitions],
            input_fn,
            output,
            "Select a competition: ",
        )
        if selection is None:
            return None
        competition_id = sorted_competitions[selection][0]
    elif competition_id is None:
        competition_id = next(iter(competition_options))

    season_options = [item for item in filtered if item[0][0] == competition_id]
    season_options.sort(
        key=lambda item: (
            -int(_year_key(item[1].get("season_name", "0")).split("/")[0]),
            item[0][1],
        )
    )
    if not season_options:
        output.write("No matching seasons were found for that competition.\n")
        return None
    if len(season_options) == 1:
        return season_options[0][0]

    selection = _choose(
        [
            f"{row.get('season_name', 'Season')} (season {key[1]})"
            for key, row in season_options
        ],
        input_fn,
        output,
        "Select a season: ",
    )
    return season_options[selection][0] if selection is not None else None


def _choose_player_scope(
    input_fn: Callable[[str], str], output: TextIO
) -> bool | None:
    selection = _choose(
        [
            "All competitions available in a season",
            "One competition and season",
        ],
        input_fn,
        output,
        "Select player stats scope: ",
    )
    return None if selection is None else selection == 0


def _choose_all_league_season(
    provider: Any,
    season_id: int | None,
    season_name: str | None,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> str | None:
    rows = provider.list_competitions()
    if season_id is not None:
        matching_ids = [row for row in rows if row.get("season_id") == season_id]
        if season_name is not None:
            matching_ids = [
                row for row in matching_ids
                if _year_key(row.get("season_name", "")) == _year_key(season_name)
            ]
        if not matching_ids:
            output.write("No StatsBomb season matches that season ID.\n")
            return None
        return str(matching_ids[0].get("season_name", season_id))

    options: dict[str, str] = {}
    for row in rows:
        label = str(row.get("season_name", "")).strip()
        if not label:
            continue
        key = _year_key(label)
        if season_name is not None and key != _year_key(season_name):
            continue
        options.setdefault(key, label)
    seasons = sorted(
        options.values(),
        key=lambda name: -int(_year_key(name).split("/")[0]),
    )
    if not seasons:
        output.write("No StatsBomb competitions contain that season.\n")
        return None
    if len(seasons) == 1:
        return seasons[0]
    selection = _choose(seasons, input_fn, output, "Select a season across competitions: ")
    return seasons[selection] if selection is not None else None


def _competition_season_label(
    provider: Any, competition_id: int, season_id: int
) -> tuple[str, str]:
    for row in provider.list_competitions():
        if row.get("competition_id") == competition_id and row.get("season_id") == season_id:
            return str(row.get("competition_name", competition_id)), str(
                row.get("season_name", season_id)
            )
    return str(competition_id), str(season_id)


def _write_statistics(output: TextIO, statistics: dict[str, object], excluded: set[str]) -> None:
    for name, value in statistics.items():
        if name not in excluded:
            output.write(f"{name.replace('_', ' ').title()}: {value}\n")


def _ordinal(position: int) -> str:
    if 10 <= position % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    return f"{position}{suffix}"


def _format_match(index: int, record: dict[str, object]) -> str:
    home_score = record.get("home_score")
    away_score = record.get("away_score")
    score = f"{home_score}-{away_score}" if home_score is not None and away_score is not None else "vs"
    date = record.get("match_date", "date unknown")
    return (
        f"{index}. {date}: {record.get('home_team', 'Home')} {score} "
        f"{record.get('away_team', 'Away')} (ID {record.get('match_id')})"
    )


def _find_match_id(
    provider: Any,
    competition_id: int,
    season_id: int,
    teams: tuple[str, str] | None,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> int | None:
    matches = provider.list_matches(competition_id, season_id)
    if teams is not None:
        requested = {" ".join(team.casefold().split()) for team in teams}
        matches = [
            row
            for row in matches
            if {
                " ".join(str(row.get(key, "")).casefold().split())
                for key in ("home_team", "away_team")
            }
            == requested
        ]
    matches.sort(key=lambda row: str(row.get("match_date", "")))
    if not matches:
        output.write("No matching StatsBomb matches were found.\n")
        return None

    labels = [_format_match(index, row) for index, row in enumerate(matches, start=1)]
    selection = _choose(labels, input_fn, output, "Select a match: ")
    if selection is None:
        return None
    return int(matches[selection]["match_id"])


def run_cli(
    argv: Sequence[str] | None = None,
    provider: MatchDataProvider | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> int:
    args = _build_parser().parse_args(argv)
    try:
        provider = provider or create_provider(args.provider)
    except ValueError as error:
        output.write(f"GoodGame could not create the provider: {error}\n")
        return 1
    if args.player_team and not args.player_stats:
        _build_parser().error("--player-team requires --player-stats")
    if args.all_leagues and not args.player_stats:
        _build_parser().error("--all-leagues requires --player-stats")
    if args.all_leagues and args.competition_id is not None:
        _build_parser().error("--all-leagues cannot be combined with --competition-id")
    if (args.team_stats or args.player_stats) and (args.match_id or args.teams):
        _build_parser().error("Season statistics cannot be combined with match selection")

    try:
        match_id = args.match_id
        if args.team_stats:
            if not callable(getattr(provider, "get_team_statistics", None)):
                output.write(
                    "Season team statistics are currently available through "
                    "--provider statsbomb or sportmonks only.\n"
                )
                return 1
            selection = _choose_competition_season(
                provider,
                args.competition_id,
                args.season_id,
                args.season_name,
                input_fn,
                output,
                team_name=args.team_stats,
            )
            if selection is None:
                return 1
            competition_id, season_id = selection
            provider.competition_id = competition_id
            provider.season_id = season_id
            competition_name, season_label = _competition_season_label(
                provider, competition_id, season_id
            )
            statistics = provider.get_team_statistics(args.team_stats)
            output.write(f"\nTEAM SEASON STATS: {statistics['team_name']}\n")
            output.write(f"Competition: {competition_name} ({season_label})\n")
            output.write(
                f"Current standing: {_ordinal(statistics['position'])} of "
                f"{statistics['standing_teams']} ({statistics['points']} points, "
                f"goal difference {statistics['goal_difference']:+})\n"
            )
            _write_statistics(
                output,
                statistics,
                {
                    "team_id", "team_name", "competition_id", "season_id",
                    "position", "standing_teams", "points", "goal_difference",
                },
            )
            return 0

        if args.player_stats:
            if not callable(getattr(provider, "get_player_statistics", None)):
                output.write(
                    "Season player statistics are currently available through "
                    "--provider statsbomb or sportmonks only.\n"
                )
                return 1
            all_leagues = args.all_leagues
            if not all_leagues and args.competition_id is None:
                all_leagues = _choose_player_scope(input_fn, output)
                if all_leagues is None:
                    return 1

            if all_leagues:
                if not callable(getattr(provider, "get_player_statistics_all_leagues", None)):
                    output.write(
                        "All-leagues player stats are not supported by the selected provider.\n"
                    )
                    return 1
                season_label = _choose_all_league_season(
                    provider,
                    args.season_id,
                    args.season_name,
                    input_fn,
                    output,
                )
                if season_label is None:
                    return 1
                statistics = provider.get_player_statistics_all_leagues(
                    season_label, args.player_stats, team=args.player_team
                )
                output.write(
                    f"\nPLAYER SEASON STATS: {statistics['player_name']} "
                    f"({statistics['team_name']})\n"
                )
                output.write(
                    f"Season: {season_label} across {statistics['competition_count']} competitions\n"
                )
                output.write(f"Competitions: {', '.join(statistics['competitions'])}\n")
                _write_statistics(
                    output,
                    statistics,
                    {
                        "player_id", "player_name", "team_id", "team_name",
                        "season_name", "competitions", "competition_count",
                    },
                )
                return 0

            selection = _choose_competition_season(
                provider,
                args.competition_id,
                args.season_id,
                args.season_name,
                input_fn,
                output,
            )
            if selection is None:
                return 1
            competition_id, season_id = selection
            provider.competition_id = competition_id
            provider.season_id = season_id
            competition_name, season_label = _competition_season_label(
                provider, competition_id, season_id
            )
            statistics = provider.get_player_statistics(
                args.player_stats,
                team=args.player_team,
            )
            output.write(
                f"\nPLAYER SEASON STATS: {statistics['player_name']} "
                f"({statistics['team_name']})\n"
            )
            output.write(f"Competition: {competition_name} ({season_label})\n")
            _write_statistics(
                output,
                statistics,
                {"player_id", "player_name", "team_id", "team_name", "competition_id", "season_id"},
            )
            return 0

        context_requested = (
            args.competition_id is not None
            or args.season_id is not None
            or args.season_name is not None
            or args.teams is not None
        )
        competition_id = None
        season_id = None
        if context_requested or match_id is None:
            selection = _choose_competition_season(
                provider,
                args.competition_id,
                args.season_id,
                args.season_name,
                input_fn,
                output,
            )
            if selection is None:
                return 1
            competition_id, season_id = selection
            provider.competition_id = competition_id
            provider.season_id = season_id
            output.write(f"Competition {competition_id}, season {season_id}\n")

        if match_id is None:
            match_id = _find_match_id(
                provider,
                competition_id,
                season_id,
                tuple(args.teams) if args.teams else None,
                input_fn,
                output,
            )
            if match_id is None:
                return 1

        analysis = GoodGamePipeline(provider=provider).analyze_match(match_id)
    except (LookupError, ValueError, SportmonksError) as error:
        output.write(f"GoodGame could not complete the run: {error}\n")
        return 1

    match: Match = analysis.match
    score = (
        f"{match.home_score}-{match.away_score}"
        if match.home_score is not None and match.away_score is not None
        else "vs"
    )
    output.write(f"\n{match.home_team.name} {score} {match.away_team.name}\n")
    output.write(f"{len(analysis.events)} events, {len(analysis.shots)} shots\n")
    if not analysis.insights:
        output.write("No supported story events were found.\n")
        return 0
    output.write("\nMATCH STORY\n")
    for index, insight in enumerate(analysis.insights, start=1):
        minute = f"{insight.start_minute}'" if insight.start_minute is not None else ""
        output.write(f"{index:02d}  {insight.title} {minute}\n")
        output.write(f"    {insight.summary}\n")
    return 0


def main() -> None:
    raise SystemExit(run_cli())
