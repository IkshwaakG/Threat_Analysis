import unittest

from goodgame.ingestion.statsbomb.client import StatsBombClient
from goodgame.ingestion.statsbomb.provider import StatsBombProvider
from goodgame.models.insight import Insight
from goodgame.pipeline import GoodGamePipeline


class FakeStatsBombApi:
    def __init__(self):
        self.competitions_calls = 0
        self.match_calls = []

    def competitions(self):
        self.competitions_calls += 1
        return [{"competition_id": 9, "season_id": 281}]

    def matches(self, competition_id, season_id):
        self.match_calls.append((competition_id, season_id))
        return [
            {
                "match_id": 3895232,
                "match_date": "2024-02-10",
                "kick_off": "19:30:00.000",
                "home_team_id": 904,
                "home_team": "Bayer Leverkusen",
                "away_team_id": 169,
                "away_team": "Bayern Munich",
                "home_score": 3,
                "away_score": 0,
                "match_status": "available",
                "competition_id": 9,
                "season_id": 281,
                "season": "2023/2024",
            }
        ]

    def events(self, match_id):
        self.assert_match_id(match_id)
        return [
            {
                "id": "goal-event-id",
                "type": "Shot",
                "minute": 18,
                "player": "Florian Wirtz",
                "player_id": 100,
                "team": "Bayer Leverkusen",
                "team_id": 904,
                "shot_outcome": "Goal",
                "shot_statsbomb_xg": 0.42,
            },
            {
                "id": "pass-event-id",
                "type": "Pass",
                "minute": 10,
                "player": "Florian Wirtz",
                "player_id": 100,
                "team": "Bayer Leverkusen",
                "team_id": 904,
                "pass_outcome": None,
                "pass_shot_assist": True,
                "pass_goal_assist": True,
            },
            {
                "id": "pressure-event-id",
                "type": "Pressure",
                "minute": 11,
                "player": "Florian Wirtz",
                "player_id": 100,
                "team": "Bayer Leverkusen",
                "team_id": 904,
            },
            {
                "id": "sub-event-id",
                "type": "Substitution",
                "minute": 74,
                "player": "Thomas Muller",
                "player_id": 200,
                "team": "Bayern Munich",
                "team_id": 169,
                "substitution_replacement": "Mathys Tel",
            },
        ]

    def lineups(self, match_id):
        self.assert_match_id(match_id)
        return {
            "Bayer Leverkusen": [
                {
                    "player_id": 100,
                    "player_name": "Florian Wirtz",
                    "positions": [
                        {"from": "00:00", "to": "90:00", "start_reason": "Starting XI"}
                    ],
                }
            ],
            "Bayern Munich": [
                {"player_id": 200, "player_name": "Thomas Muller", "positions": []},
                {"player_id": 300, "player_name": "Unused Substitute", "positions": []},
            ],
        }

    @staticmethod
    def assert_match_id(match_id):
        if match_id != 3895232:
            raise AssertionError(f"Unexpected match ID: {match_id}")


class SingleInsightAnalyzer:
    def analyze(self, match, events):
        return [
            Insight(
                id="provider-independent",
                kind="test",
                title=match.home_team.name,
                impact="low",
                summary=f"Received {len(events)} normalized events",
            )
        ]


class TwoCompetitionApi:
    def competitions(self):
        return [
            {"competition_id": 9, "season_id": 281, "competition_name": "Bundesliga", "season_name": "2023/2024"},
            {"competition_id": 16, "season_id": 4, "competition_name": "Champions League", "season_name": "2023/2024"},
            {"competition_id": 77, "season_id": 55, "competition_name": "Other Cup", "season_name": "2023/2024"},
            {"competition_id": 78, "season_id": 56, "competition_name": "Unused Cup", "season_name": "2023/2024"},
        ]

    def matches(self, competition_id, season_id):
        if competition_id == 77:
            return [{
            "match_id": 3,
                "home_team_id": 300,
                "home_team": "Other Club",
                "away_team_id": 301,
                "away_team": "Another Club",
                "home_score": 0,
                "away_score": 0,
            }]
        if competition_id == 78:
            return [{
                "match_id": 4,
                "home_team_id": 904,
                "home_team": "Bayer Leverkusen",
                "away_team_id": 278,
                "away_team": "Unused Cup Opponent",
                "home_score": 0,
                "away_score": 0,
            }]
        match_id = 1 if competition_id == 9 else 2
        return [
            {
                "match_id": match_id,
                "home_team_id": 904,
                "home_team": "Bayer Leverkusen",
                "away_team_id": 200 + competition_id,
                "away_team": f"Opponent {competition_id}",
                "home_score": 1,
                "away_score": 0,
            }
        ]

    def lineups(self, match_id):
        if match_id == 3:
            return {"Other Club": [], "Another Club": []}
        if match_id == 4:
            return {
                "Bayer Leverkusen": [
                    {"player_id": 100, "player_name": "Florian Wirtz", "positions": []}
                ],
                "Unused Cup Opponent": [],
            }
        return {
            "Bayer Leverkusen": [
                {
                    "player_id": 100,
                    "player_name": "Florian Wirtz",
                    "positions": [
                        {"from": "00:00", "to": "90:00", "start_reason": "Starting XI"}
                    ],
                }
            ],
            f"Opponent {9 if match_id == 1 else 16}": [],
        }

    def events(self, match_id):
        if match_id == 4:
            return []
        return [
            {
                "type": "Shot",
                "player_id": 100,
                "player": "Florian Wirtz",
                "team_id": 904,
                "team": "Bayer Leverkusen",
                "shot_outcome": "Goal",
                "shot_statsbomb_xg": 0.4,
            }
        ]


class StatsBombProviderTests(unittest.TestCase):
    def test_provider_normalizes_data_for_the_common_pipeline(self):
        api = FakeStatsBombApi()
        provider = StatsBombProvider(client=StatsBombClient(api))

        analysis = GoodGamePipeline(provider=provider).analyze_match(3895232)

        self.assertEqual(analysis.match.home_team.name, "Bayer Leverkusen")
        self.assertEqual(analysis.match.away_score, 0)
        self.assertEqual(
            [event.incident_type for event in analysis.events],
            ["goal", "pass", "pressure", "substitution"],
        )
        self.assertEqual(analysis.events[0].id, "goal-event-id")
        self.assertEqual(analysis.events[0].raw["shot_statsbomb_xg"], 0.42)
        self.assertEqual([insight.kind for insight in analysis.insights], ["goal", "substitution"])
        self.assertEqual(len(analysis.shots), 1)
        self.assertEqual(api.competitions_calls, 1)
        self.assertEqual(api.match_calls, [(9, 281)])

    def test_pipeline_accepts_analyzer_collection(self):
        api = FakeStatsBombApi()
        provider = StatsBombProvider(client=StatsBombClient(api), competition_id=9, season_id=281)

        analysis = GoodGamePipeline(
            provider=provider, analyzers=[SingleInsightAnalyzer()]
        ).analyze_match(3895232)

        self.assertEqual(len(analysis.insights), 1)
        self.assertEqual(analysis.insights[0].kind, "test")
        self.assertEqual(api.competitions_calls, 0)

    def test_competition_and_season_must_be_provided_together(self):
        with self.assertRaisesRegex(ValueError, "supplied together"):
            StatsBombProvider(competition_id=9)

    def test_team_and_player_season_statistics(self):
        api = FakeStatsBombApi()
        provider = StatsBombProvider(
            client=StatsBombClient(api), competition_id=9, season_id=281
        )

        teams = provider.list_teams()
        players = provider.list_players(team="Bayer Leverkusen")
        team_stats = provider.get_team_statistics("Bayer Leverkusen")
        player_stats = provider.get_player_statistics("Florian Wirtz")

        self.assertEqual([team["team_name"] for team in teams], ["Bayer Leverkusen", "Bayern Munich"])
        self.assertEqual(players[0]["player_id"], 100)
        self.assertEqual((team_stats["matches_played"], team_stats["wins"]), (1, 1))
        self.assertEqual((team_stats["position"], team_stats["standing_teams"]), (1, 2))
        self.assertEqual((team_stats["goals_for"], team_stats["shots"]), (3, 1))
        self.assertEqual((team_stats["passes_completed"], team_stats["pressures"]), (1, 1))
        self.assertEqual((player_stats["appearances"], player_stats["starts"]), (1, 1))
        self.assertEqual((player_stats["goals"], player_stats["assists"]), (1, 1))
        self.assertEqual(player_stats["minutes_played"], 90)

    def test_unused_substitutes_are_roster_members_not_appearances(self):
        provider = StatsBombProvider(
            client=StatsBombClient(FakeStatsBombApi()), competition_id=9, season_id=281
        )

        statistics = provider.get_player_statistics("Unused Substitute")

        self.assertEqual(statistics["appearances"], 0)
        self.assertEqual(statistics["minutes_played"], 0)

    def test_player_stats_aggregate_across_competitions_in_a_season(self):
        provider = StatsBombProvider(client=StatsBombClient(TwoCompetitionApi()))

        statistics = provider.get_player_statistics_all_leagues(
            "2023/24", "Florian Wirtz", team="Bayer Leverkusen"
        )

        self.assertEqual(statistics["competition_count"], 2)
        self.assertEqual(statistics["competitions"], ["Bundesliga", "Champions League"])
        self.assertEqual(statistics["appearances"], 2)
        self.assertEqual(statistics["goals"], 2)
        self.assertEqual(statistics["expected_goals"], 0.8)
        self.assertNotIn("Other Cup", statistics["competitions"])
        self.assertNotIn("Unused Cup", statistics["competitions"])


if __name__ == "__main__":
    unittest.main()