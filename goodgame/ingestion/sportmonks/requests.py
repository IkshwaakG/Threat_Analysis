"""Sportmonks Football API v3 request definitions.

This module owns endpoint paths, full include chains, filters, and pagination.
Response normalization belongs in responses.py.

The include constants intentionally retain the detailed documented include chains
because GoodGame needs the richest response available to the account/plan.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence
from urllib.parse import quote

from goodgame.ingestion.sportmonks.client import SportmonksClient


FIXTURE_INCLUDES = (
    "sport;round;stage;group;aggregate;league;season;coaches;tvStations;venue;"
    "state;weatherReport;lineups;lineups.player;lineups.position;"
    "lineups.detailedPosition;lineups.details.type;lineups.xGLineup;"
    "events;events.player;events.relatedPlayer;events.type;events.period;"
    "timeline;comments;trends;statistics;statistics.type;periods;participants;"
    "odds;premiumOdds;inplayOdds;prematchNews;postmatchNews;metadata;sidelined;"
    "sidelined.sideline.player;sidelined.sideline.type;predictions;referees;"
    "formations;ballCoordinates;scores;xGFixture;pressure;expectedLineups"
)

# Matches the exact include chain confirmed working against the live Free Plan
# account; broader bare includes (sport, country, teams, latest, lineups, ...)
# were dropped because Sportmonks returned them as empty/placeholder on this
# plan while nested includes below still resolve their data.
PLAYER_INCLUDES = (
    "nationality;detailedPosition;statistics.details.type;metadata.type;"
    "trophies.trophy;trophies.team;teams.team;statistics.team;"
    "statistics.season.league;latest.fixture.participants;"
    "latest.fixture.league;latest.fixture.scores;latest.details.type;"
    "trophies.league;trophies.season"
)

TEAM_INCLUDES = (
    "sport;country;venue;coaches;rivals;players;latest;upcoming;seasons;"
    "activeSeasons;sidelined;sidelinedHistory;statistics;"
    "statistics.details.type;trophies;socials;rankings"
)

LEAGUE_INCLUDES = (
    "sport;country;stages;latest;upcoming;inplay;today;currentSeason;seasons"
)

SEASON_INCLUDES = (
    "sport;league;teams;stages;currentStage;fixtures;groups;statistics;"
    "statistics.details.type;topscorers"
)

# Bulk "list all seasons" only needs enough to group by competition; the full
# SEASON_INCLUDES chain (fixtures/statistics/topscorers for every season across
# every league) is heavy enough to be rejected or exhaust the request quota.
SEASON_LIST_INCLUDES = "league"

# Bulk fixture listings only need to build the match picker (teams/score/state).
# Full event/lineup/odds detail is fetched per-fixture in get_fixture instead.
FIXTURE_LIST_INCLUDES = "participants;scores;state"

SQUAD_INCLUDES = (
    "team;player;player.statistics;player.statistics.details.type;"
    "position;detailedPosition;transfer;details.type"
)

STANDINGS_INCLUDES = "participant;details;details.type"
TOPSCORER_INCLUDES = "player;participant;type"
EXPECTED_TEAM_INCLUDES = "type;fixture;participant"
EXPECTED_PLAYER_INCLUDES = "type;fixture;player;team"
STAGE_INCLUDES = (
    "league;season;type;sport;rounds;currentRound;groups;fixtures;"
    "aggregates;topscorers;statistics"
)
ROUND_INCLUDES = "sport;league;season;stage;fixtures;statistics"


class SportmonksRequests:
    """Low-level Sportmonks v3 request facade.

    Every method maps to one resource endpoint. Rich includes are kept here so
    callers do not have to duplicate or accidentally truncate them.
    """

    def __init__(self, client: SportmonksClient) -> None:
        self.client = client

    # ---------- Leagues ----------

    def list_leagues(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "leagues", {"include": LEAGUE_INCLUDES, "per_page": 50}
        )

    def get_league(self, league_id: int) -> dict[str, Any]:
        return self._one(f"leagues/{league_id}", {"include": LEAGUE_INCLUDES})

    def search_leagues(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/search/{quote(name.strip(), safe='')}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_live_leagues(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "leagues/live", {"include": LEAGUE_INCLUDES, "per_page": 50}
        )

    def get_leagues_by_fixture_date(
        self, fixture_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/date/{fixture_date}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_current_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/teams/{team_id}/current",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def get_team_all_leagues(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/teams/{team_id}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    # ---------- Seasons ----------

    def list_seasons(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "seasons", {"include": SEASON_LIST_INCLUDES, "per_page": 50}
        )

    def get_season(self, season_id: int) -> dict[str, Any]:
        return self._one(f"seasons/{season_id}", {"include": SEASON_INCLUDES})

    def search_seasons(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"seasons/search/{quote(name.strip(), safe='')}",
            {"include": SEASON_INCLUDES, "per_page": 50},
        )

    # ---------- Teams ----------

    def list_teams(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "teams", {"include": TEAM_INCLUDES, "per_page": 50}
        )

    def list_teams_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/seasons/{season_id}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def list_teams_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/countries/{country_id}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def get_team(self, team_id: int) -> dict[str, Any]:
        return self._one(f"teams/{team_id}", {"include": TEAM_INCLUDES})

    def search_teams(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"teams/search/{quote(name.strip(), safe='')}",
            {"include": TEAM_INCLUDES, "per_page": 50},
        )

    def get_team_squad(self, season_id: int, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"squads/seasons/{season_id}/teams/{team_id}",
            {"include": SQUAD_INCLUDES, "per_page": 50},
        )

    def get_team_season_statistics(self, team_id: int) -> list[dict[str, Any]]:
        return self.get_participant_season_statistics("teams", team_id)

    # ---------- Players ----------

    def list_players(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "players", {"include": PLAYER_INCLUDES, "per_page": 50}
        )

    def list_players_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"players/countries/{country_id}",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    def get_player(
        self, player_id: int, season_ids: Sequence[int] | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"include": PLAYER_INCLUDES}
        if season_ids:
            # Server-side season narrowing keeps the statistics payload small
            # instead of returning every season the player has ever played.
            # Sportmonks accepts a comma-joined list of IDs for this filter,
            # which covers the "all leagues in this season" case too.
            joined = ",".join(str(value) for value in season_ids)
            params["filters"] = f"playerstatisticSeasons:{joined}"
        return self._one(f"players/{player_id}", params)

    def search_players(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"players/search/{quote(name.strip(), safe='')}",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    def get_latest_players(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "players/latest",
            {"include": PLAYER_INCLUDES, "per_page": 50},
        )

    # ---------- Fixtures / match API ----------

    def list_fixtures(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "fixtures", {"include": FIXTURE_LIST_INCLUDES, "per_page": 50}
        )

    def get_fixture(self, fixture_id: int) -> dict[str, Any]:
        return self._one(
            f"fixtures/{fixture_id}", {"include": FIXTURE_INCLUDES}
        )

    def get_fixtures_by_ids(self, fixture_ids: list[int]) -> list[dict[str, Any]]:
        joined = ",".join(str(value) for value in fixture_ids)
        return self.client.get_all(
            f"fixtures/multi/{joined}",
            {"include": FIXTURE_INCLUDES, "per_page": 50},
        )

    def list_fixtures_by_date(
        self, fixture_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/date/{fixture_date}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def list_fixtures_between(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/between/{start_date}/{end_date}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def list_team_fixtures_between(
        self,
        team_id: int,
        start_date: str | date,
        end_date: str | date,
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/between/{start_date}/{end_date}/{team_id}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def search_fixtures(self, query: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/search/{quote(query.strip(), safe='')}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_head_to_head(
        self, team_a_id: int, team_b_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/head-to-head/{team_a_id}/{team_b_id}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_latest_updated_fixtures(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "fixtures/latest",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    # ---------- Live scores ----------

    def get_inplay_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/inplay",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_all_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_latest_livescores(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "livescores/latest",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    # ---------- Schedules / stages / rounds ----------

    def get_schedule_by_season(self, season_id: int) -> list[dict[str, Any]]:
        # There is no fixtures-by-season endpoint in Sportmonks v3; the
        # schedule nests fixtures under stages -> rounds/groups instead.
        return self.client.get_all(
            f"schedules/seasons/{season_id}",
            {"include": FIXTURE_LIST_INCLUDES},
        )

    def get_schedule_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(f"schedules/teams/{team_id}")

    def get_schedule_by_season_and_team(
        self, season_id: int, team_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"schedules/seasons/{season_id}/teams/{team_id}"
        )

    def get_stages_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"stages/seasons/{season_id}",
            {"include": STAGE_INCLUDES, "per_page": 50},
        )

    def get_rounds_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"rounds/seasons/{season_id}",
            {"include": ROUND_INCLUDES, "per_page": 50},
        )

    # ---------- Expected / xG ----------

    def get_expected_by_team(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "expected/fixtures",
            {"include": EXPECTED_TEAM_INCLUDES, "per_page": 50},
        )

    def get_expected_by_player(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "expected/lineups",
            {"include": EXPECTED_PLAYER_INCLUDES, "per_page": 50},
        )

    def get_expected_lineups_by_team(
        self, team_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"expected-lineups/teams/{team_id}",
            {"include": EXPECTED_PLAYER_INCLUDES, "per_page": 50},
        )

    def get_expected_lineups_by_player(
        self, player_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"expected-lineups/players/{player_id}",
            {"include": EXPECTED_PLAYER_INCLUDES, "per_page": 50},
        )

    # ---------- Standings / leaders ----------

    def get_standings(self, season_id: int) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            f"standings/seasons/{season_id}",
            {"include": STANDINGS_INCLUDES},
        )
        return self._many(payload.get("data"))

    def get_topscorers(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"topscorers/seasons/{season_id}",
            {"include": TOPSCORER_INCLUDES, "per_page": 50},
        )

    def get_topscorers_by_stage(self, stage_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"topscorers/stages/{stage_id}",
            {"include": TOPSCORER_INCLUDES, "per_page": 50},
        )

    def list_standings(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "standings", {"include": STANDINGS_INCLUDES, "per_page": 50}
        )

    def get_standings_by_round(self, round_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"standings/rounds/{round_id}",
            {"include": STANDINGS_INCLUDES, "per_page": 50},
        )

    def get_standing_corrections(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"standings/corrections/seasons/{season_id}", {"per_page": 50}
        )

    def get_live_standings_by_league(self, league_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"standings/live/leagues/{league_id}",
            {"include": STANDINGS_INCLUDES, "per_page": 50},
        )

    # ---------- League/season completeness ----------

    def list_leagues_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"leagues/countries/{country_id}",
            {"include": LEAGUE_INCLUDES, "per_page": 50},
        )

    def list_seasons_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"seasons/teams/{team_id}",
            {"include": SEASON_LIST_INCLUDES, "per_page": 50},
        )

    def get_season_brackets(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"seasons/{season_id}/brackets", {"per_page": 50}
        )

    # ---------- Squad completeness ----------

    def get_team_squad_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"squads/teams/{team_id}",
            {"include": SQUAD_INCLUDES, "per_page": 50},
        )

    def get_extended_team_squad(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"squads/teams/{team_id}/extended",
            {"include": SQUAD_INCLUDES, "per_page": 50},
        )

    # ---------- Statistics by participant ----------

    def get_participant_season_statistics(
        self, participant: str, participant_id: int
    ) -> list[dict[str, Any]]:
        """participant is one of: players, teams, coaches, referees."""
        return self.client.get_all(
            f"statistics/seasons/{participant}/{participant_id}",
            {"include": "season;details;details.type", "per_page": 50},
        )

    def get_stage_statistics(self, stage_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"statistics/stages/{stage_id}",
            {"include": "details;details.type", "per_page": 50},
        )

    def get_round_statistics(self, round_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"statistics/rounds/{round_id}",
            {"include": "details;details.type", "per_page": 50},
        )

    # ---------- Fixtures by market / TV station ----------

    def get_upcoming_fixtures_by_market(self, market_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/upcoming/markets/{market_id}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_upcoming_fixtures_by_tv_station(
        self, tv_station_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/upcoming/tv-stations/{tv_station_id}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    def get_past_fixtures_by_tv_station(
        self, tv_station_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"fixtures/past/tv-stations/{tv_station_id}",
            {"include": FIXTURE_LIST_INCLUDES, "per_page": 50},
        )

    # ---------- Stages / Rounds completeness ----------

    def list_stages(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "stages", {"include": STAGE_INCLUDES, "per_page": 50}
        )

    def get_stage(self, stage_id: int) -> dict[str, Any]:
        return self._one(f"stages/{stage_id}", {"include": STAGE_INCLUDES})

    def search_stages(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"stages/search/{quote(name.strip(), safe='')}",
            {"include": STAGE_INCLUDES, "per_page": 50},
        )

    def list_rounds(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "rounds", {"include": ROUND_INCLUDES, "per_page": 50}
        )

    def get_round(self, round_id: int) -> dict[str, Any]:
        return self._one(f"rounds/{round_id}", {"include": ROUND_INCLUDES})

    def search_rounds(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"rounds/search/{quote(name.strip(), safe='')}",
            {"include": ROUND_INCLUDES, "per_page": 50},
        )

    # ---------- States ----------

    def list_states(self) -> list[dict[str, Any]]:
        return self.client.get_all("states", {"per_page": 50})

    def get_state(self, state_id: int) -> dict[str, Any]:
        return self._one(f"states/{state_id}")

    # ---------- Venues ----------

    def list_venues(self) -> list[dict[str, Any]]:
        return self.client.get_all("venues", {"per_page": 50})

    def get_venue(self, venue_id: int) -> dict[str, Any]:
        return self._one(f"venues/{venue_id}")

    def list_venues_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"venues/seasons/{season_id}", {"per_page": 50}
        )

    def search_venues(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"venues/search/{quote(name.strip(), safe='')}", {"per_page": 50}
        )

    # ---------- TV Stations ----------

    def list_tv_stations(self) -> list[dict[str, Any]]:
        return self.client.get_all("tv-stations", {"per_page": 50})

    def get_tv_station(self, tv_station_id: int) -> dict[str, Any]:
        return self._one(f"tv-stations/{tv_station_id}")

    def get_tv_stations_by_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"tv-stations/fixtures/{fixture_id}", {"per_page": 50}
        )

    # ---------- Coaches ----------

    def list_coaches(self) -> list[dict[str, Any]]:
        return self.client.get_all("coaches", {"per_page": 50})

    def get_coach(self, coach_id: int) -> dict[str, Any]:
        return self._one(f"coaches/{coach_id}")

    def list_coaches_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"coaches/countries/{country_id}", {"per_page": 50}
        )

    def search_coaches(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"coaches/search/{quote(name.strip(), safe='')}", {"per_page": 50}
        )

    def get_latest_coaches(self) -> list[dict[str, Any]]:
        return self.client.get_all("coaches/latest", {"per_page": 50})

    # ---------- Referees ----------

    def list_referees(self) -> list[dict[str, Any]]:
        return self.client.get_all("referees", {"per_page": 50})

    def get_referee(self, referee_id: int) -> dict[str, Any]:
        return self._one(f"referees/{referee_id}")

    def list_referees_by_country(self, country_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"referees/countries/{country_id}", {"per_page": 50}
        )

    def list_referees_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"referees/seasons/{season_id}", {"per_page": 50}
        )

    def search_referees(self, name: str) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"referees/search/{quote(name.strip(), safe='')}", {"per_page": 50}
        )

    # ---------- Transfers ----------

    def list_transfers(self) -> list[dict[str, Any]]:
        return self.client.get_all("transfers", {"per_page": 50})

    def get_transfer(self, transfer_id: int) -> dict[str, Any]:
        return self._one(f"transfers/{transfer_id}")

    def get_latest_transfers(self) -> list[dict[str, Any]]:
        return self.client.get_all("transfers/latest", {"per_page": 50})

    def list_transfers_between(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfers/between/{start_date}/{end_date}", {"per_page": 50}
        )

    def list_transfers_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfers/teams/{team_id}", {"per_page": 50}
        )

    def list_transfers_by_player(self, player_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfers/players/{player_id}", {"per_page": 50}
        )

    # ---------- Transfer Rumours ----------

    def list_transfer_rumours(self) -> list[dict[str, Any]]:
        return self.client.get_all("transfer-rumours", {"per_page": 50})

    def get_transfer_rumour(self, transfer_rumour_id: int) -> dict[str, Any]:
        return self._one(f"transfer-rumours/{transfer_rumour_id}")

    def list_transfer_rumours_between(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfer-rumours/between/{start_date}/{end_date}",
            {"per_page": 50},
        )

    def list_transfer_rumours_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfer-rumours/teams/{team_id}", {"per_page": 50}
        )

    def list_transfer_rumours_by_player(
        self, player_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"transfer-rumours/players/{player_id}", {"per_page": 50}
        )

    # ---------- Rivals ----------

    def list_rivals(self) -> list[dict[str, Any]]:
        return self.client.get_all("rivals", {"per_page": 50})

    def list_rivals_by_team(self, team_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"rivals/teams/{team_id}", {"per_page": 50}
        )

    # ---------- Commentaries ----------

    def list_commentaries(self) -> list[dict[str, Any]]:
        return self.client.get_all("commentaries", {"per_page": 50})

    def list_commentaries_by_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"commentaries/fixtures/{fixture_id}", {"per_page": 50}
        )

    # ---------- Predictions ----------

    def get_prediction_probabilities(self) -> list[dict[str, Any]]:
        return self.client.get_all(
            "predictions/probabilities", {"per_page": 50}
        )

    def get_predictability_by_league(self, league_id: int) -> dict[str, Any]:
        return self._one(f"predictions/predictability/leagues/{league_id}")

    def get_probabilities_by_fixture(self, fixture_id: int) -> dict[str, Any]:
        return self._one(f"predictions/probabilities/fixtures/{fixture_id}")

    def list_value_bets(self) -> list[dict[str, Any]]:
        return self.client.get_all("predictions/value-bets", {"per_page": 50})

    def get_value_bets_by_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"predictions/value-bets/fixtures/{fixture_id}", {"per_page": 50}
        )

    # ---------- News ----------

    def list_prematch_news(self) -> list[dict[str, Any]]:
        return self.client.get_all("news/pre-match", {"per_page": 50})

    def list_prematch_news_by_season(self, season_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"news/pre-match/seasons/{season_id}", {"per_page": 50}
        )

    def list_prematch_news_upcoming(self) -> list[dict[str, Any]]:
        return self.client.get_all("news/pre-match/upcoming", {"per_page": 50})

    def list_postmatch_news(self) -> list[dict[str, Any]]:
        return self.client.get_all("news/post-match", {"per_page": 50})

    def list_postmatch_news_by_season(
        self, season_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"news/post-match/seasons/{season_id}", {"per_page": 50}
        )

    # ---------- Match Facts (beta) ----------

    def list_match_facts(self) -> list[dict[str, Any]]:
        return self.client.get_all("match-facts", {"per_page": 50})

    def get_match_facts_by_fixture(self, fixture_id: int) -> dict[str, Any]:
        return self._one(f"match-facts/{fixture_id}")

    def list_match_facts_between(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"match-facts/fixtures/between/{start_date}/{end_date}",
            {"per_page": 50},
        )

    def list_match_facts_by_league(self, league_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"match-facts/leagues/{league_id}", {"per_page": 50}
        )

    # ---------- Team of the Week (beta) ----------

    def list_team_of_the_week(self) -> list[dict[str, Any]]:
        return self.client.get_all("team-of-the-week", {"per_page": 50})

    def get_team_of_the_week_by_round(self, round_id: int) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"team-of-the-week/rounds/{round_id}", {"per_page": 50}
        )

    def get_latest_team_of_the_week_by_league(
        self, league_id: int
    ) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"team-of-the-week/leagues/{league_id}/latest", {"per_page": 50}
        )

    # ---------- Team Rankings (beta) ----------

    def get_team_rankings_by_date(self, ranking_date: str | date) -> list[dict[str, Any]]:
        return self.client.get_all(
            f"team-rankings/teams/date/{ranking_date}", {"per_page": 50}
        )

    # ---------- Helpers ----------

    @staticmethod
    def _many(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        return []

    @staticmethod
    def _one_payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return next((row for row in value if isinstance(row, dict)), {})
        return {}

    def _one(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self.client.get_json(path, params)
        return self._one_payload(payload.get("data"))
