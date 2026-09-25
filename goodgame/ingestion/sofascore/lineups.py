"""Starting lineups and formation data endpoint."""

from typing import Any

from goodgame.ingestion.sofascore.client import SofaScoreClient


def fetch_lineups(client: SofaScoreClient, match_id: int) -> dict[str, Any]:
    return client.get_json(f"event/{match_id}/lineups")