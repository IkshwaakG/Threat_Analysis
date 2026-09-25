"""Shot map endpoint."""

from typing import Any

from goodgame.ingestion.sofascore.client import SofaScoreClient


def fetch_shot_map(client: SofaScoreClient, match_id: int) -> list[dict[str, Any]]:
    payload = client.get_json(f"event/{match_id}/shotmap")
    return [shot for shot in payload.get("shotmap", []) if isinstance(shot, dict)]