import io
import os
import unittest
from unittest.mock import Mock, patch

from goodgame.ingestion.factory import create_provider
from goodgame.ingestion.sportmonks.client import SportmonksClient
from goodgame.ingestion.sportmonks.provider import SportmonksProvider
from goodgame.ingestion.sportmonks.requests import (
    FIXTURE_INCLUDES,
    PLAYER_INCLUDES,
    STANDINGS_INCLUDES,
)
from goodgame.cli import run_cli


class FakeSportmonksClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))

        if path == "standings/seasons/318":
            self.assert_include(params, STANDINGS_INCLUDES)
            return {
                "data": [
                    {
                        "participant_id": 14,
                        "participant": {"name": "Manchester United"},
                        "position": 12,
                        "points": 42,
                        "details": [
                            {
                                "type": {"name": "Overall Games Played"},
                                "value": {"total": 24},
                            },
                            {
                                "type": {"name": "Goal Difference"},
                                "value": {"total": 7},
                            },
                        ],
                    },
                    {
                        "participant_id": 1,
                        "participant": {"name": "Arsenal"},
                        "position": 1,
                        "points": 60,
                        "details": [],
                    },
                ]
            }

        if path == "fixtures/9001":
            self.assert_include(params, FIXTURE_INCLUDES)
            return {"data": self.fixture(include_detail=True)}

        if path == "players/search/Bruno%20Fernandes":
            self.assert_include(params, PLAYER_INCLUDES)
            return {"data": [{"id": 100, "name": "Bruno Fernandes"}]}

        if path in {"players/100", "players/1878"}:
            self.assert_include(params, PLAYER_INCLUDES)
            player_id = int(path.split("/")[-1])
            return {
                "data": {
                    "id": player_id,
                    "name": "Bruno Fernandes",
                    "statistics": [
                        {
                            "team_id": 14,
                            "season_id": 318,
                            "team": {"id": 14, "name": "Manchester United"},
                            "season": {
                                "id": 318,
                                "name": "2024/2025",
                                "league": {"id": 8, "name": "Premier League"},
                            },
                            "details": [
                                {"type": {"name": "Appearances"}, "value": {"total": 22}},
                                {"type": {"name": "Goals"}, "value": {"total": 7}},
                            ],
                        },
                        {
                            "team_id": 14,
                            "season_id": 317,
                            "team": {"id": 14, "name": "Manchester United"},
                            "season": {
                                "id": 317,
                                "name": "2023/2024",
                                "league": {"id": 8, "name": "Premier League"},
                            },
                            "details": [
                                {"type": {"name": "Goals"}, "value": {"total": 10}}
                            ],
                        },
                    ],
                }
            }

        raise AssertionError(f"Unexpected Sportmonks path: {path}")

    def get_all(self, path, params=None):
        self.calls.append((path, params))

        if path == "seasons":
            return [
                {
                    "id": 318,
                    "name": "2024/2025",
                    "league_id": 8,
                    "league": {"id": 8, "name": "Premier League"},
                }
            ]

        if path == "fixtures/seasons/318":
            self.assert_include(params, FIXTURE_INCLUDES)
            return [self.fixture(include_detail=False)]

        if path == "statistics/seasons/teams/14":
            self.assert_include(params, "season;details;details.type")
            return [
                {
                    "team_id": 14,
                    "season_id": 318,
                    "details": [
                        {"type": {"name": "Shots"}, "value": {"total": 100}},
                        {"type": {"name": "Expected Goals"}, "value": {"total": 22.3}},
                    ],
                }
            ]

        return []

    @staticmethod
    def assert_include(params, expected):
        if not params or params.get("include") != expected:
            raise AssertionError(
                f"Expected include={expected!r}, got {None if not params else params.get('include')!r}"
            )

    @staticmethod
    def fixture(include_detail):
        fixture = {
            "id": 9001,
            "league_id": 8,
            "season_id": 318,
            "starting_at": "2025-01-15 20:00:00",
            "starting_at_timestamp": 1736971200,
            "state": {"name": "FT"},
            "participants": [
                {"id": 14, "name": "Manchester United", "meta": {"location": "home"}},
                {"id": 1, "name": "Arsenal", "meta": {"location": "away"}},
            ],
            "scores": [
                {"participant_id": 14, "score": {"goals": 1}},
                {"participant_id": 1, "score": {"goals": 2}},
            ],
        }
        if include_detail:
            fixture.update(
                events=[
                    {
                        "id": 77,
                        "type": {"name": "Goal"},
                        "minute": 42,
                        "participant_id": 14,
                        "player": {"name": "Bruno Fernandes"},
                    }
                ],
                lineups=[
                    {
                        "team_id": 14,
                        "player_id": 100,
                        "player": {"name": "Bruno Fernandes"},
                    }
                ],
                statistics=[{"type_id": 86, "value": 6}],
                expected=[
                    {
                        "participant_id": 14,
                        "data": {"value": 1.7},
                        "location": "home",
                    }
                ],
            )
        return fixture


class SportmonksProviderTests(unittest.TestCase):
    def test_sportmonks_maps_catalog_fixtures_and_match_events(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())

        competitions = provider.list_competitions()
        matches = provider.list_matches(8, 318)
        match = provider.get_match(9001)
        events = provider.get_events(9001)
        lineups = provider.get_lineups(9001)

        self.assertEqual(competitions[0]["competition_name"], "Premier League")
        self.assertEqual(competitions[0]["season_name"], "2024/2025")
        self.assertEqual(matches[0]["match_id"], 9001)
        self.assertEqual((match.home_score, match.away_score), (1, 2))
        self.assertEqual(match.home_team.name, "Manchester United")
        self.assertEqual(events[0].incident_type, "goal")
        self.assertEqual(events[0].player, "Bruno Fernandes")
        self.assertTrue(events[0].is_home)
        self.assertEqual(len(lineups["Manchester United"]), 1)

    def test_fixture_request_uses_full_detailed_include_chain(self):
        client = FakeSportmonksClient()
        provider = SportmonksProvider(client=client)

        provider.get_fixture(9001)

        detail_call = next(call for call in client.calls if call[0] == "fixtures/9001")
        self.assertEqual(detail_call[1]["include"], FIXTURE_INCLUDES)
        self.assertIn("lineups.details.type", FIXTURE_INCLUDES)
        self.assertIn("lineups.xGLineup", FIXTURE_INCLUDES)
        self.assertIn("xGFixture", FIXTURE_INCLUDES)
        self.assertIn("ballCoordinates", FIXTURE_INCLUDES)
        self.assertIn("pressure", FIXTURE_INCLUDES)

    def test_fixture_exposes_match_statistics_and_xg_separately(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())

        self.assertEqual(provider.get_fixture_statistics(9001)[0]["type_id"], 86)
        self.assertEqual(
            provider.get_fixture_xg(9001)[0]["data"]["value"],
            1.7,
        )

    def test_token_is_sent_in_header_not_query_string(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": []}
        session = Mock()
        session.get.return_value = response
        client = SportmonksClient(token="fake-local-token", session=session)

        client.get_json("livescores/inplay", {"include": "participants"})

        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "fake-local-token")
        self.assertNotIn("api_token", kwargs["params"])
        self.assertNotIn("fake-local-token", session.get.call_args.args[0])

    def test_team_stats_use_sportmonks_standings_and_season_totals(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())
        provider.competition_id = 8
        provider.season_id = 318

        stats = provider.get_team_statistics("Manchester United")

        self.assertEqual(stats["position"], 12)
        self.assertEqual(stats["standing_teams"], 2)
        self.assertEqual(stats["points"], 42)
        self.assertEqual(stats["overall_games_played"], 24)
        self.assertEqual(stats["goal_difference"], 7)
        self.assertEqual(stats["shots"], 100)
        self.assertEqual(stats["expected_goals"], 22.3)

    def test_player_stats_search_and_filter_to_selected_season(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())

        stats = provider.get_player_statistics(
            "Bruno Fernandes",
            team="Manchester United",
            competition_id=8,
            season_id=318,
        )

        self.assertEqual(stats["player_id"], 100)
        self.assertEqual(stats["player_name"], "Bruno Fernandes")
        self.assertEqual(stats["competition_name"], "Premier League")
        self.assertEqual(stats["season_name"], "2024/2025")
        self.assertEqual(stats["appearances"], 22)
        self.assertEqual(stats["goals"], 7)

    def test_player_id_uses_full_documented_detail_include(self):
        client = FakeSportmonksClient()
        provider = SportmonksProvider(client=client)

        stats = provider.get_player_statistics(
            1878,
            team="Manchester United",
            competition_id=8,
            season_id=318,
        )

        self.assertEqual(stats["player_id"], 1878)
        detail_call = next(call for call in client.calls if call[0] == "players/1878")
        self.assertEqual(detail_call[1]["include"], PLAYER_INCLUDES)
        self.assertIn("statistics.details.type", PLAYER_INCLUDES)

    def test_player_stats_can_aggregate_available_leagues_in_season(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())

        stats = provider.get_player_statistics_all_leagues(
            "2024/25",
            "Bruno Fernandes",
            team="Manchester United",
        )

        self.assertEqual(stats["competition_count"], 1)
        self.assertEqual(stats["competitions"], ["Premier League"])
        self.assertEqual(stats["appearances"], 22)
        self.assertEqual(stats["goals"], 7)

    def test_cli_routes_team_stats_to_sportmonks(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())
        output = io.StringIO()

        exit_code = run_cli(
            [
                "--provider",
                "sportmonks",
                "--competition-id",
                "8",
                "--season-id",
                "318",
                "--team-stats",
                "Manchester United",
            ],
            provider=provider,
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Current standing: 12th of 2 (42 points", output.getvalue())
        self.assertIn("Overall Games Played: 24", output.getvalue())

    def test_cli_routes_player_stats_to_sportmonks(self):
        provider = SportmonksProvider(client=FakeSportmonksClient())
        output = io.StringIO()

        exit_code = run_cli(
            [
                "--provider",
                "sportmonks",
                "--all-leagues",
                "--season",
                "2024/25",
                "--player-stats",
                "Bruno Fernandes",
                "--player-team",
                "Manchester United",
            ],
            provider=provider,
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("PLAYER SEASON STATS: Bruno Fernandes", output.getvalue())
        self.assertIn("Competitions: Premier League", output.getvalue())
        self.assertIn("Goals: 7", output.getvalue())

    def test_default_provider_is_switchable_via_environment(self):
        with patch.dict(os.environ, {"GOODGAME_PROVIDER": "statsbomb"}, clear=True):
            self.assertEqual(type(create_provider()).__name__, "StatsBombProvider")
        with patch.dict(
            os.environ,
            {
                "GOODGAME_PROVIDER": "sportmonks",
                "SPORTMONKS_API_TOKEN": "test-token",
            },
            clear=True,
        ):
            self.assertEqual(type(create_provider()).__name__, "SportmonksProvider")

    def test_sportmonks_requires_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "SPORTMONKS_API_TOKEN"):
                create_provider("sportmonks")


if __name__ == "__main__":
    unittest.main()
