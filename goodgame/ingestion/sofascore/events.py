"""Match incident endpoints."""

from goodgame.ingestion.sofascore.client import SofaScoreClient
from goodgame.models.event import Event


def fetch_match_events(client: SofaScoreClient, match_id: int) -> list[Event]:
    payload = client.get_json(f"event/{match_id}/incidents")
    incidents = payload.get("incidents", [])
    return [Event.from_payload(item) for item in incidents if isinstance(item, dict)]