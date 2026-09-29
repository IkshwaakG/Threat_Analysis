"""Export a small packaged demo snapshot from GCP.

Example:
  python scripts/export_demo_snapshot.py \
    --competition-id 8 \
    --season-id 23614 \
    --fixture-id 19134409 \
    --team-id 14 \
    --player-id 1878
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goodgame.serving.bigquery_repository import BigQueryServingRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", type=int, required=True)
    parser.add_argument("--season-id", type=int, required=True)
    parser.add_argument("--fixture-id", type=int, action="append", default=[])
    parser.add_argument("--team-id", type=int, action="append", default=[])
    parser.add_argument("--player-id", type=int, action="append", default=[])
    parser.add_argument("--output", default="demo_data/snapshot.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = BigQueryServingRepository()

    competitions = repo.list_competitions()
    seasons = repo.list_seasons(args.competition_id)
    matches = repo.list_matches(args.competition_id, args.season_id)
    teams = repo.list_teams(args.season_id, args.competition_id)
    players = repo.list_players(args.season_id, args.competition_id)

    fixture_ids = set(args.fixture_id)
    team_ids = set(args.team_id)
    player_ids = set(args.player_id)

    if not fixture_ids:
        fixture_ids = {int(row["id"]) for row in matches[:3]}

    selected_matches = [row for row in matches if int(row["id"]) in fixture_ids]
    game_views = {
        str(fixture_id): repo.get_game_view(fixture_id)
        for fixture_id in sorted(fixture_ids)
    }

    if not team_ids:
        for view in game_views.values():
            team_ids.add(int(view["home_team"]["id"]))
            team_ids.add(int(view["away_team"]["id"]))

    if not player_ids:
        for view in game_views.values():
            player_ids.update(
                int(player["player_id"])
                for player in view.get("players", [])[:10]
            )

    selected_teams = [row for row in teams if int(row["id"]) in team_ids]
    selected_players = [row for row in players if int(row["id"]) in player_ids]

    team_views = {
        f"{team_id}:{args.season_id}:{args.competition_id}":
            repo.get_team_view(team_id, args.season_id, args.competition_id)
        for team_id in sorted(team_ids)
    }
    player_views = {
        f"{player_id}:{args.season_id}:{args.competition_id}":
            repo.get_player_view(player_id, args.season_id, args.competition_id)
        for player_id in sorted(player_ids)
    }

    snapshot = {
        "competitions": [
            row for row in competitions
            if int(row["id"]) == args.competition_id
        ],
        "seasons": [
            row for row in seasons
            if int(row["id"]) == args.season_id
        ],
        "matches": [
            {
                **row,
                "competition_id": args.competition_id,
                "season_id": args.season_id,
            }
            for row in selected_matches
        ],
        "teams": [
            {
                **row,
                "competition_id": args.competition_id,
                "season_id": args.season_id,
            }
            for row in selected_teams
        ],
        "players": [
            {
                **row,
                "competition_id": args.competition_id,
                "season_id": args.season_id,
            }
            for row in selected_players
        ],
        "game_views": game_views,
        "team_views": team_views,
        "player_views": player_views,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, default=str) + "\n")
    print(f"Wrote demo snapshot: {output}")


if __name__ == "__main__":
    main()
