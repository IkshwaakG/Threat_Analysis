"""Normalized match incidents from a provider."""

from dataclasses import dataclass, field
from typing import Any, Mapping


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _person_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return value.get("name")
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Event:
    minute: int | None
    incident_type: str
    text: str
    is_home: bool | None = None
    player: str | None = None
    player_in: str | None = None
    player_out: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    incident_class: str | None = None
    id: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Event":
        incident_type = str(
            payload.get("incidentType", payload.get("type", payload.get("incidentClass", "event")))
        ).lower()
        player = payload.get("player")
        return cls(
            id=_optional_int(payload.get("id")),
            minute=_optional_int(payload.get("time", payload.get("minute"))),
            incident_type=incident_type,
            text=str(payload.get("text", payload.get("reason", incident_type))),
            is_home=payload.get("isHome"),
            player=_person_name(player),
            player_in=_person_name(payload.get("playerIn")),
            player_out=_person_name(payload.get("playerOut")),
            home_score=_optional_int(payload.get("homeScore")),
            away_score=_optional_int(payload.get("awayScore")),
            incident_class=payload.get("incidentClass"),
            raw=dict(payload),
        )