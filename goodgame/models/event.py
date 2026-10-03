"""Normalized match incidents from a provider."""

from dataclasses import dataclass, field
import math
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


def _event_id(value: Any) -> int | str | None:
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _value(value: Any) -> Any:
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    return value


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
    id: int | str | None = None
    extra_minute: int | None = None
    player_id: int | None = None
    related_player_id: int | None = None
    team_id: int | None = None
    rescinded: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Event":
        incident_type = str(
            payload.get("incidentType", payload.get("type", payload.get("incidentClass", "event")))
        ).lower()
        player = payload.get("player")
        return cls(
            id=_event_id(payload.get("id")),
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

    @classmethod
    def from_statsbomb_payload(
        cls, payload: Mapping[str, Any], home_team_name: str
    ) -> "Event":
        event_type = str(_value(payload.get("type")) or "event")
        shot_outcome = str(_value(payload.get("shot_outcome")) or "")
        card = _value(payload.get("foul_committed_card")) or _value(
            payload.get("bad_behaviour_card")
        )
        normalized_type = event_type.casefold()
        if normalized_type == "shot" and shot_outcome.casefold() == "goal":
            incident_type = "goal"
        elif normalized_type == "substitution":
            incident_type = "substitution"
        elif card is not None:
            incident_type = "card"
        else:
            incident_type = normalized_type.replace(" ", "_")

        player = _person_name(_value(payload.get("player")))
        player_in = _person_name(_value(payload.get("substitution_replacement")))
        player_out = player if incident_type == "substitution" else None
        team_name = _value(payload.get("team"))
        text = str(card) if incident_type == "card" else event_type
        if incident_type == "goal":
            text = f"Goal by {player or 'unknown player'}"
        elif incident_type == "substitution":
            text = f"Substitution: {player_out or 'unknown player'} replaced by {player_in or 'unknown player'}"

        return cls(
            id=_event_id(payload.get("id")),
            minute=_optional_int(_value(payload.get("minute"))),
            incident_type=incident_type,
            text=text,
            is_home=team_name == home_team_name if team_name is not None else None,
            player=player,
            player_in=player_in,
            player_out=player_out,
            incident_class=str(card) if card is not None else None,
            raw=dict(payload),
        )