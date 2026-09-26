import unittest

from goodgame.models.event import Event
from goodgame.models.match import Match
from goodgame.pipeline import GoodGamePipeline


class FakeProvider:
    def get_match(self, match_id):
        return Match.from_statsbomb_payload(
            {
                "match_id": match_id,
                "home_team_id": 1,
                "home_team": "Manchester United",
                "away_team_id": 2,
                "away_team": "Arsenal",
                "home_score": 2,
                "away_score": 1,
            }
        )

    def get_events(self, match_id):
        return [
            Event(
                id="goal-id",
                minute=84,
                incident_type="goal",
                text="Goal",
                is_home=True,
                player="Bruno Fernandes",
                home_score=2,
                away_score=1,
            )
        ]

    def get_lineups(self, match_id):
        return {"home": {"formation": "4-2-3-1"}, "away": {"formation": "4-3-3"}}

    def get_shot_map(self, match_id):
        return [{"player": "Bruno Fernandes", "time": 84}]


class GoodGamePipelineTests(unittest.TestCase):
    def test_fetches_match_resources_and_builds_story(self):
        provider = FakeProvider()

        analysis = GoodGamePipeline(provider=provider).analyze_match(42)

        self.assertEqual(analysis.match.home_team.name, "Manchester United")
        self.assertEqual(analysis.insights[0].title, "Goal sequence")
        self.assertEqual(analysis.lineups["home"]["formation"], "4-2-3-1")
        self.assertEqual(len(analysis.shots), 1)


if __name__ == "__main__":
    unittest.main()