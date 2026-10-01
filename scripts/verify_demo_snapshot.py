"""Verify a packaged GoodGame demo snapshot without GCP access."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from goodgame.serving.demo_repository import DemoServingRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot",
        default="demo_data/snapshot.json",
        help="Snapshot JSON to verify.",
    )
    args = parser.parse_args()

    path = Path(args.snapshot)
    repo = DemoServingRepository(path)

    competitions = repo.list_competitions()
    if not competitions:
        raise SystemExit("Demo snapshot has no competitions")

    checked_games = 0
    checked_teams = 0
    checked_players = 0

    for competition in competitions:
        seasons = repo.list_seasons(int(competition["id"]))
        for season in seasons:
            season_id = int(season["id"])
            competition_id = int(competition["id"])

            matches = repo.list_matches(competition_id, season_id)
            for match in matches:
                repo.get_game_view(int(match["id"]))
                checked_games += 1

            teams = repo.list_teams(season_id, competition_id)
            for team in teams:
                repo.get_team_view(int(team["id"]), season_id, competition_id)
                checked_teams += 1

            players = repo.list_players(season_id, competition_id)
            for player in players:
                repo.get_player_view(int(player["id"]), season_id, competition_id)
                checked_players += 1

    if checked_games == 0:
        raise SystemExit("Demo snapshot has no usable game views")
    if checked_teams == 0:
        raise SystemExit("Demo snapshot has no usable team views")
    if checked_players == 0:
        raise SystemExit("Demo snapshot has no usable player views")

    search_probe = repo.search_entities("Demo")
    if not search_probe:
        raise SystemExit("Demo snapshot search returned no results")

    print(
        "Demo snapshot verified: "
        f"games={checked_games}, teams={checked_teams}, players={checked_players}"
    )


if __name__ == "__main__":
    main()
