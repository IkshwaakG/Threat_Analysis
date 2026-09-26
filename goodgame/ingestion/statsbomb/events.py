"""StatsBomb event normalization."""

from typing import Any

from goodgame.ingestion.statsbomb.client import StatsBombClient
from goodgame.models.event import Event


def fetch_match_events(
    client: StatsBombClient, match_id: int, home_team_name: str
) -> list[Event]:
    records = client.get_events(match_id)
    return [
        Event.from_statsbomb_payload(record, home_team_name)
        for record in records
    ]


def fetch_shots(client: StatsBombClient, match_id: int) -> list[dict[str, Any]]:
    return [
        event
        for event in client.get_events(match_id)
        if str(event.get("type", "")).casefold() == "shot"
    ]