"""Team squad and season-level player statistics endpoints."""

from typing import Any
from urllib.parse import urlparse

from goodgame.config import DEFAULT_SEASON_ID, DEFAULT_TOURNAMENT_ID
from goodgame.ingestion.sofascore.client import SofaScoreClient
from goodgame.ingestion.sofascore.teams import find_team_id


def fetch_team_players(client: SofaScoreClient, team_id: int) -> list[dict[str, Any]]:
    payload = client.get_json(f"team/{team_id}/players")
    players = []
    for entry in payload.get("players", []):
        player = entry.get("player", entry)
        if isinstance(player, dict) and player.get("id") is not None:
            players.append(player)
    return players


def fetch_player_statistics(
    client: SofaScoreClient,
    player_id: int | str,
    tournament_id: int = DEFAULT_TOURNAMENT_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, Any]:
    if isinstance(player_id, str) and not player_id.isdecimal():
        player_id = urlparse(player_id).path.rstrip("/").split("/")[-1]
    try:
        normalized_player_id = int(player_id)
    except (TypeError, ValueError) as error:
        raise ValueError("player_id must be an integer or a SofaScore player URL") from error

    payload = client.get_json(
        f"player/{normalized_player_id}/unique-tournament/{tournament_id}/season/{season_id}/statistics/overall"
    )
    return payload.get("statistics", {})


def fetch_player_links(
    client: SofaScoreClient,
    team_name: str,
    tournament_id: int = DEFAULT_TOURNAMENT_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, str]:
    team_id = find_team_id(client, team_name, tournament_id, season_id)
    players = fetch_team_players(client, team_id)
    return {
        player["name"]: (
            f"https://www.sofascore.com/player/"
            f"{player.get('slug', player['id'])}/{player['id']}"
        )
        for player in players
        if player.get("name")
    }