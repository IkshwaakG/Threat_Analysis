"""Validate all-league player stats only report competitions with appearances.

Run from the repository root:
    python tests/validate_player_competitions.py --player "Florian Wirtz" --season 2023/24
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goodgame.ingestion.statsbomb.provider import StatsBombProvider


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


def validate_player_competitions(
    provider: StatsBombProvider,
    player: str,
    season: str,
    team: str | None = None,
) -> dict[str, Any]:
    requested_season = _season_key(season)
    season_rows = [
        row
        for row in provider.list_competitions()
        if _season_key(row.get("season_name", "")) == requested_season
    ]
    appeared_in: set[str] = set()
    for row in season_rows:
        try:
            stats = provider.get_player_statistics(
                player,
                team=team,
                competition_id=int(row["competition_id"]),
                season_id=int(row["season_id"]),
            )
        except LookupError as error:
            if str(error).startswith((
                "Player not found in this StatsBomb season:",
                "Team not found in this StatsBomb season:",
            )):
                continue
            raise
        if stats["appearances"] > 0:
            appeared_in.add(str(row.get("competition_name", row["competition_id"])))

    aggregate = provider.get_player_statistics_all_leagues(season, player, team)
    reported_in = set(aggregate["competitions"])
    if reported_in != appeared_in:
        raise AssertionError(
            "All-leagues result does not match competitions with appearances: "
            f"reported={sorted(reported_in)}, expected={sorted(appeared_in)}"
        )
    if not reported_in:
        raise AssertionError(f"No appearances found for {player!r} in season {season!r}")
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", required=True, help="Player name or StatsBomb player ID")
    parser.add_argument("--season", required=True, help="StatsBomb season label, e.g. 2023/24")
    parser.add_argument("--team", help="Team name to disambiguate the player")
    args = parser.parse_args()

    try:
        result = validate_player_competitions(
            StatsBombProvider(), args.player, args.season, args.team
        )
    except (LookupError, AssertionError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1

    print(f"Validated {result['player_name']} in season {result['season_name']}.")
    print(f"Competitions with appearances ({result['competition_count']}):")
    for competition in result["competitions"]:
        print(f"- {competition}")
    print(f"Appearances: {result['appearances']}; goals: {result['goals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
