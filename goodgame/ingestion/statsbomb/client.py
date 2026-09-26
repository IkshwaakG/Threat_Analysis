"""Small cached adapter over the statsbombpy public functions."""

import os
import warnings
from typing import Any, Mapping


def _records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return data.to_dict(orient="records")
    return [dict(row) for row in data]


def _open_data_call(
    function: Any,
    creds: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    try:
        from statsbombpy.api_client import NoAuthWarning
    except ImportError:
        if creds is not None:
            kwargs["creds"] = dict(creds)
        return function(**kwargs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoAuthWarning)
        if creds is not None:
            kwargs["creds"] = dict(creds)
        return function(**kwargs)


class StatsBombClient:
    def __init__(
        self,
        api: Any | None = None,
        creds: Mapping[str, str] | None = None,
    ) -> None:
        if creds is None:
            username = os.environ.get("SB_USERNAME", "").strip()
            password = os.environ.get("SB_PASSWORD", "")
            if bool(username) != bool(password):
                raise ValueError("Set both SB_USERNAME and SB_PASSWORD, or neither")
            self.creds = {"user": username, "passwd": password} if username else None
        else:
            username = creds.get("user", "").strip()
            password = creds.get("passwd", "")
            if not username or not password:
                raise ValueError("StatsBomb credentials require both 'user' and 'passwd'")
            self.creds = {"user": username, "passwd": password}

        if api is None:
            from statsbombpy import sb

            api = sb
        self.api = api
        self._competitions: list[dict[str, Any]] | None = None
        self._matches: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._events: dict[int, list[dict[str, Any]]] = {}
        self._lineups: dict[int, dict[str, list[dict[str, Any]]]] = {}

    def get_competitions(self) -> list[dict[str, Any]]:
        if self._competitions is None:
            self._competitions = _records(
                _open_data_call(self.api.competitions, creds=self.creds)
            )
        return self._competitions

    def get_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        key = (competition_id, season_id)
        if key not in self._matches:
            self._matches[key] = _records(
                _open_data_call(
                    self.api.matches,
                    creds=self.creds,
                    competition_id=competition_id,
                    season_id=season_id,
                )
            )
        return self._matches[key]

    def get_events(self, match_id: int) -> list[dict[str, Any]]:
        if match_id not in self._events:
            self._events[match_id] = _records(
                _open_data_call(self.api.events, creds=self.creds, match_id=match_id)
            )
        return self._events[match_id]

    def get_lineups(self, match_id: int) -> dict[str, list[dict[str, Any]]]:
        if match_id not in self._lineups:
            lineups = _open_data_call(
                self.api.lineups, creds=self.creds, match_id=match_id
            )
            self._lineups[match_id] = {
                str(team_name): _records(players)
                for team_name, players in lineups.items()
            }
        return self._lineups[match_id]