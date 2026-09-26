"""Sportmonks implementation of GoodGame's normalized match provider."""

from datetime import datetime
import re
from typing import Any
from urllib.parse import quote

from goodgame.ingestion.provider import MatchDataProvider
from goodgame.ingestion.sportmonks.client import SportmonksClient
from goodgame.models.event import Event
from goodgame.models.match import Match, Team


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    return value if isinstance(value, str) else None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _slug(value: Any) -> str:
    return "_".join(
        part for part in "".join(
            character.lower() if character.isalnum() else " " for character in str(value)
        ).split()
        if part
    )


def _details_statistics(details: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    if not isinstance(details, list):
        return results
    for detail in details:
        if not isinstance(detail, dict):
            continue
        stat_name = _name(detail.get("type")) or f"stat_{detail.get('type_id', 'unknown')}"
        value = detail.get("value")
        if isinstance(value, dict):
            if "total" in value:
                value = value["total"]
            elif "value" in value:
                value = value["value"]
        results[_slug(stat_name)] = value
    return results


def _season_key(value: Any) -> str:
    parts = re.findall(r"\d{2,4}", str(value))
    if not parts:
        return str(value).strip().casefold()
    start = int(parts[0])
    if len(parts[0]) == 2:
        start += 2000 if start < 70 else 1900
    if len(parts) == 1:
        return str(start)
    end = int(parts[1])
    if len(parts[1]) == 2:
        end += start // 100 * 100
        if end < start:
            end += 100
    return f"{start}/{end}"


_PLAYER_INCLUDES = (
    "nationality;detailedPosition;statistics.details.type;metadata.type;"
    "trophies.trophy;trophies.team;teams.team;statistics.team;statistics.season.league;"
    "latest.fixture.participants;statistics.details.type;latest.fixture.league;"
    "latest.fixture.scores;latest.details.type;trophies.league;trophies.season"
)

_FIXTURE_INCLUDES = (
    "state;participants;venue;scores;weatherReport;league;events.player;"
    "statistics.type;events.type;events.period;sidelined.sideline.player;"
    "sidelined.sideline.type"
)


def _timestamp(fixture: dict[str, Any]) -> int | None:
    stamp = _integer(fixture.get("starting_at_timestamp"))
    if stamp is not None:
        return stamp
    value = fixture.get("starting_at")
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp())
    except ValueError:
        return None


def _participants(fixture: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    home = away = None
    for participant in fixture.get("participants", []):
        if not isinstance(participant, dict):
            continue
        location = (participant.get("meta") or {}).get("location")
        if location == "home":
            home = participant
        elif location == "away":
            away = participant
    return home, away


def _current_scores(
    fixture: dict[str, Any], home: dict[str, Any], away: dict[str, Any]
) -> tuple[int | None, int | None]:
    scores: dict[int, int] = {}
    for item in fixture.get("scores", []):
        if not isinstance(item, dict):
            continue
        participant_id = _integer(item.get("participant_id"))
        score = item.get("score") or {}
        value = _integer(score.get("goals")) if isinstance(score, dict) else _integer(score)
        if participant_id is not None and value is not None:
            scores[participant_id] = value
    return scores.get(int(home["id"])), scores.get(int(away["id"]))


def _match_from_fixture(fixture: dict[str, Any]) -> Match:
    home, away = _participants(fixture)
    if home is None or away is None:
        raise ValueError(f"Sportmonks fixture {fixture.get('id')} is missing participants")
    home_score, away_score = _current_scores(fixture, home, away)
    state = fixture.get("state") or {}
    league = fixture.get("league") or {}
    season = fixture.get("season") or {}
    return Match(
        id=int(fixture["id"]),
        home_team=Team(id=int(home["id"]), name=str(home.get("name", "Home"))),
        away_team=Team(id=int(away["id"]), name=str(away.get("name", "Away"))),
        home_score=home_score,
        away_score=away_score,
        status=str(state.get("name", "unknown")),
        start_timestamp=_timestamp(fixture),
        tournament_id=_integer(fixture.get("league_id", league.get("id"))),
        season_id=_integer(fixture.get("season_id", season.get("id"))),
    )


def _event_from_fixture(event: dict[str, Any], match: Match) -> Event:
    event_type = _name(event.get("type")) or str(event.get("type_name") or event.get("info") or "event")
    normalized_type = event_type.casefold()
    if "goal" in normalized_type:
        kind = "goal"
    elif "substitution" in normalized_type:
        kind = "substitution"
    elif "card" in normalized_type:
        kind = "card"
    elif "shot" in normalized_type:
        kind = "shot"
    else:
        kind = normalized_type.replace(" ", "_")

    participant_id = _integer(event.get("participant_id"))
    player = _name(event.get("player")) or event.get("player_name")
    player_in = _name(event.get("relatedPlayer")) or _name(event.get("related_player"))
    result = event.get("result")
    text = str(event.get("info") or event.get("addition") or event_type)
    if kind == "goal" and player:
        text = f"Goal by {player}"

    return Event(
        id=event.get("id"),
        minute=_integer(event.get("minute")),
        incident_type=kind,
        text=text,
        is_home=(participant_id == match.home_team.id) if participant_id is not None else None,
        player=player,
        player_in=player_in,
        player_out=player if kind == "substitution" else None,
        incident_class=str(result) if kind == "card" and result is not None else None,
        raw=dict(event),
    )


class SportmonksProvider(MatchDataProvider):
    def __init__(self, client: SportmonksClient | None = None) -> None:
        self.client = client or SportmonksClient()
        self._seasons: list[dict[str, Any]] | None = None
        self._season_fixtures: dict[int, list[dict[str, Any]]] = {}
        self._fixtures: dict[int, dict[str, Any]] = {}
        self._matches: dict[int, Match] = {}

    def list_competitions(self) -> list[dict[str, Any]]:
        if self._seasons is None:
            rows = self.client.get_all("seasons", {"include": "league", "per_page": 50})
            self._seasons = [
                {
                    "competition_id": row.get("league_id"),
                    "season_id": row.get("id"),
                    "competition_name": _name(row.get("league")) or row.get("league_name"),
                    "season_name": row.get("name"),
                }
                for row in rows
                if row.get("league_id") is not None and row.get("id") is not None
            ]
        return self._seasons

    def _get_player_records(self, player: str | int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if isinstance(player, int) or str(player).strip().isdigit():
            player_id = int(player)
        else:
            payload = self.client.get_json(
                f"players/search/{quote(str(player).strip(), safe='')}"
            )
            data = payload.get("data")
            candidates = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            requested = " ".join(str(player).casefold().split())
            exact = [
                item for item in candidates
                if isinstance(item, dict)
                and any(
                    " ".join(str(item.get(field, "")).casefold().split()) == requested
                    for field in ("name", "display_name", "common_name")
                )
            ]
            candidates = exact or [item for item in candidates if isinstance(item, dict)]
            if not candidates:
                raise LookupError(f"Player not found in Sportmonks account coverage: {player}")
            if len(candidates) > 1:
                names = ", ".join(str(item.get("name", item.get("id"))) for item in candidates[:5])
                raise LookupError(f"Player search is ambiguous; select a player ID: {names}")
            player_id = _integer(candidates[0].get("id"))
            if player_id is None:
                raise LookupError(f"Sportmonks player search returned no player ID for {player}")

        payload = self.client.get_json(
            f"players/{player_id}", {"include": _PLAYER_INCLUDES}
        )
        data = payload.get("data")
        candidates = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        selected = next(
            (
                item for item in candidates
                if isinstance(item, dict) and _integer(item.get("id")) == player_id
            ),
            None,
        )
        if selected is None:
            raise LookupError(f"Player ID {player_id} was not found in Sportmonks response")
        statistics = selected.get("statistics", []) or []
        return selected, [row for row in statistics if isinstance(row, dict)]

    @staticmethod
    def _stat_team(record: dict[str, Any]) -> dict[str, Any]:
        return record.get("team") if isinstance(record.get("team"), dict) else {}

    @staticmethod
    def _stat_season(record: dict[str, Any]) -> dict[str, Any]:
        return record.get("season") if isinstance(record.get("season"), dict) else {}

    def get_player_statistics(
        self,
        player: str | int,
        team: str | None = None,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        player_record, records = self._get_player_records(player)
        filtered = []
        for record in records:
            season = self._stat_season(record)
            stat_team = self._stat_team(record)
            league = season.get("league") if isinstance(season.get("league"), dict) else {}
            if season_id is not None and _integer(record.get("season_id", season.get("id"))) != season_id:
                continue
            if competition_id is not None and _integer(league.get("id", season.get("league_id"))) != competition_id:
                continue
            if team is not None and " ".join(str(stat_team.get("name", "")).casefold().split()) != " ".join(team.casefold().split()):
                continue
            filtered.append((record, season, stat_team, league))
        if not filtered:
            raise LookupError(
                f"No Sportmonks season statistics found for player {player} "
                "with the selected team/competition/season filters"
            )

        result: dict[str, Any] = {
            "player_id": player_record.get("id"),
            "player_name": player_record.get("name") or player_record.get("display_name"),
            "team_id": None,
            "team_name": None,
            "season_id": season_id,
            "competition_id": competition_id,
        }
        for record, season, stat_team, league in filtered:
            if result["team_id"] is None:
                result["team_id"] = record.get("team_id", stat_team.get("id"))
                result["team_name"] = stat_team.get("name")
            result["season_id"] = record.get("season_id", season.get("id"))
            result["season_name"] = season.get("name")
            result["competition_id"] = league.get("id", season.get("league_id"))
            result["competition_name"] = league.get("name")
            result.update(_details_statistics(record.get("details")))
        return result

    def get_player_statistics_all_leagues(
        self,
        season_name: str,
        player: str | int,
        team: str | None = None,
    ) -> dict[str, Any]:
        player_record, records = self._get_player_records(player)
        season_key = _season_key(season_name)
        selected = []
        for record in records:
            season = self._stat_season(record)
            stat_team = self._stat_team(record)
            league = season.get("league") if isinstance(season.get("league"), dict) else {}
            if _season_key(season.get("name", "")) != season_key:
                continue
            if team is not None and " ".join(str(stat_team.get("name", "")).casefold().split()) != " ".join(team.casefold().split()):
                continue
            selected.append((record, season, stat_team, league))
        if not selected:
            raise LookupError(f"No Sportmonks statistics found for {player} in {season_name}")

        stats: dict[str, Any] = {}
        competitions: set[str] = set()
        teams: set[str] = set()
        for record, season, stat_team, league in selected:
            competitions.add(str(league.get("name", league.get("id", "Unknown competition"))))
            if stat_team.get("name"):
                teams.add(str(stat_team["name"]))
            for key, value in _details_statistics(record.get("details")).items():
                if isinstance(value, (int, float)):
                    stats[key] = stats.get(key, 0) + value
                else:
                    stats[key] = value
        stats.update(
            player_id=player_record.get("id"),
            player_name=player_record.get("name") or player_record.get("display_name"),
            team_name=", ".join(sorted(teams)),
            season_name=season_name,
            competitions=sorted(competitions),
            competition_count=len(competitions),
        )
        return stats

    def list_matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        if season_id not in self._season_fixtures:
            payload = self.client.get_json(
                f"seasons/{season_id}",
                {
                    "include": "league;fixtures;fixtures.participants;fixtures.scores;fixtures.state",
                    "per_page": 50,
                },
            )
            season = payload.get("data", {})
            fixtures = season.get("fixtures", []) if isinstance(season, dict) else []
            self._season_fixtures[season_id] = [
                fixture for fixture in fixtures if isinstance(fixture, dict)
            ]
        rows = []
        for fixture in self._season_fixtures[season_id]:
            if _integer(fixture.get("league_id", competition_id)) != competition_id:
                continue
            try:
                match = _match_from_fixture(fixture)
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "match_id": match.id,
                "match_date": fixture.get("starting_at", ""),
                "home_team": match.home_team.name,
                "away_team": match.away_team.name,
                "home_score": match.home_score,
                "away_score": match.away_score,
            })
            self._matches[match.id] = match
        return rows

    def get_team_statistics(
        self,
        team: str | int,
        competition_id: int | None = None,
        season_id: int | None = None,
    ) -> dict[str, Any]:
        if season_id is None:
            season_id = self.season_id
        if competition_id is None:
            competition_id = self.competition_id
        if season_id is None:
            raise ValueError("Choose a season before requesting team stats")

        standings_payload = self.client.get_json(
            f"standings/seasons/{season_id}",
            {"include": "participant;details;details.type"},
        )
        standings = standings_payload.get("data", [])
        if not isinstance(standings, list):
            standings = []
        requested_team = str(team).strip().casefold()
        selected = next(
            (
                row
                for row in standings
                if isinstance(row, dict)
                and (
                    _integer(team) == _integer(row.get("participant_id"))
                    if str(team).strip().isdigit()
                    else str(_name(row.get("participant")) or "").strip().casefold() == requested_team
                )
            ),
            None,
        )
        if selected is None:
            raise LookupError(f"Team not found in Sportmonks season {season_id}: {team}")

        participant = selected.get("participant") or {}
        team_id = _integer(selected.get("participant_id"))
        if team_id is None:
            raise LookupError(f"Sportmonks standing has no team ID for {team}")
        stats: dict[str, Any] = {
            "team_id": team_id,
            "team_name": str(_name(participant) or team),
            "competition_id": competition_id or selected.get("league_id"),
            "season_id": season_id,
            "position": _integer(selected.get("position")) or 0,
            "standing_teams": len(standings),
            "points": _integer(selected.get("points")) or 0,
        }
        stats.update(_details_statistics(selected.get("details")))
        stats.setdefault("goal_difference", 0)

        season_statistics = self.client.get_all(
            f"statistics/seasons/teams/{team_id}",
            {"include": "season;details;details.type", "per_page": 50},
        )
        for record in season_statistics:
            if _integer(record.get("season_id")) == season_id:
                stats.update(_details_statistics(record.get("details")))
        return stats

    def _get_fixture(self, match_id: int) -> dict[str, Any]:
        if match_id not in self._fixtures:
            payload = self.client.get_json(
                f"fixtures/{match_id}",
                {"include": _FIXTURE_INCLUDES},
            )
            fixture = payload.get("data")
            if not isinstance(fixture, dict):
                raise LookupError(f"Sportmonks fixture {match_id} was not found")
            self._fixtures[match_id] = fixture
        return self._fixtures[match_id]

    def get_match(self, match_id: int) -> Match:
        if match_id not in self._matches:
            self._matches[match_id] = _match_from_fixture(self._get_fixture(match_id))
        return self._matches[match_id]

    def get_events(self, match_id: int) -> list[Event]:
        fixture = self._get_fixture(match_id)
        match = self.get_match(match_id)
        events = fixture.get("events", []) or []
        return [
            _event_from_fixture(event, match)
            for event in events
            if isinstance(event, dict)
        ]

    def get_lineups(self, match_id: int) -> dict[str, Any]:
        fixture = self._get_fixture(match_id)
        match = self.get_match(match_id)
        teams: dict[str, list[dict[str, Any]]] = {
            match.home_team.name: [],
            match.away_team.name: [],
        }
        for lineup in fixture.get("lineups", []) or []:
            participant_id = _integer(lineup.get("team_id"))
            team_name = (
                match.home_team.name if participant_id == match.home_team.id
                else match.away_team.name if participant_id == match.away_team.id
                else None
            )
            if team_name is not None:
                teams[team_name].append(lineup)
        return teams

    def get_shot_map(self, match_id: int) -> list[dict[str, Any]]:
        fixture = self._get_fixture(match_id)
        return [
            event
            for event in (fixture.get("events", []) or [])
            if isinstance(event, dict)
            and "shot" in str(_name(event.get("type")) or "").casefold()
        ]