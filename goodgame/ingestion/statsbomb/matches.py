"""StatsBomb match metadata lookup."""

from typing import Any

from goodgame.ingestion.statsbomb.client import StatsBombClient


def _same_match(value: Any, match_id: int) -> bool:
    try:
        return int(value) == match_id
    except (TypeError, ValueError):
        return False


def find_match_record(
    client: StatsBombClient,
    match_id: int,
    competition_id: int | None = None,
    season_id: int | None = None,
) -> dict[str, Any]:
    if (competition_id is None) != (season_id is None):
        raise ValueError("competition_id and season_id must be supplied together")

    if competition_id is not None and season_id is not None:
        competitions = [(competition_id, season_id)]
    else:
        competitions = list(
            dict.fromkeys(
                (int(row["competition_id"]), int(row["season_id"]))
                for row in client.get_competitions()
                if row.get("competition_id") is not None and row.get("season_id") is not None
            )
        )

    for current_competition_id, current_season_id in competitions:
        for match in client.get_matches(current_competition_id, current_season_id):
            if _same_match(match.get("match_id"), match_id):
                return match
    raise LookupError(f"StatsBomb match {match_id} was not found in open data")