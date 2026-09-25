"""Competition, season, and team lookup endpoints."""

from typing import Any

from goodgame.config import DEFAULT_SEASON_ID, DEFAULT_TOURNAMENT_ID
from goodgame.ingestion.sofascore.client import SofaScoreClient


def fetch_teams(
    client: SofaScoreClient, tournament_id: int, season_id: int
) -> list[dict[str, Any]]:
    payload = client.get_json(
        f"unique-tournament/{tournament_id}/season/{season_id}/standings/total"
    )
    rows = [
        row
        for standing in payload.get("standings", [])
        for row in standing.get("rows", [])
        if isinstance(row.get("team"), dict)
    ]
    return [row["team"] for row in rows]


def find_team_id(
    client: SofaScoreClient, team_name: str, tournament_id: int, season_id: int
) -> int:
    normalized_name = team_name.strip().casefold()
    for team in fetch_teams(client, tournament_id, season_id):
        if str(team.get("name", "")).casefold() == normalized_name:
            return int(team["id"])
    raise LookupError(f"Team not found in this competition and season: {team_name}")


def team_profile_url(team: dict[str, Any]) -> str:
    return f"https://www.sofascore.com/team/football/{team['slug']}/{team['id']}"


def fetch_team_links(
    client: SofaScoreClient,
    tournament_id: int = DEFAULT_TOURNAMENT_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, str]:
    return {
        team["name"]: team_profile_url(team)
        for team in fetch_teams(client, tournament_id, season_id)
    }


def fetch_team_link(
    client: SofaScoreClient,
    team_name: str,
    tournament_id: int = DEFAULT_TOURNAMENT_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> str:
    normalized_name = team_name.strip().casefold()
    for team in fetch_teams(client, tournament_id, season_id):
        if str(team.get("name", "")).casefold() == normalized_name:
            return team_profile_url(team)
    raise LookupError(f"Team not found in this competition and season: {team_name}")


def fetch_team_statistics(
    client: SofaScoreClient,
    team: int | str,
    tournament_id: int = DEFAULT_TOURNAMENT_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, Any]:
    team_id = int(team) if isinstance(team, int) or str(team).isdecimal() else find_team_id(
        client, str(team), tournament_id, season_id
    )
    payload = client.get_json(
        f"team/{team_id}/unique-tournament/{tournament_id}/season/{season_id}/statistics/overall"
    )
    return payload.get("statistics", {})