"""Match discovery and detail endpoints."""

from typing import Any

from goodgame.ingestion.sofascore.client import SofaScoreClient
from goodgame.models.match import Match


def fetch_season_matches(
    client: SofaScoreClient,
    tournament_id: int,
    season_id: int,
    direction: str = "last",
    page: int = 0,
) -> list[Match]:
    if direction not in {"last", "next"} or page < 0:
        raise ValueError("direction must be 'last' or 'next' and page must be non-negative")
    payload = client.get_json(
        f"unique-tournament/{tournament_id}/season/{season_id}/events/{direction}/{page}"
    )
    return [Match.from_payload(event) for event in payload.get("events", [])]


def fetch_match(client: SofaScoreClient, match_id: int) -> Match:
    payload: dict[str, Any] = client.get_json(f"event/{match_id}")
    return Match.from_payload(payload.get("event", payload))