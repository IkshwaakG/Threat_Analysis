import unittest

from goodgame.analytics.match_analyzer import MatchAnalyzer
from goodgame.models.event import Event
from goodgame.models.match import Match


class MatchAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.match = Match.from_payload(
            {
                "id": 42,
                "homeTeam": {"id": 1, "name": "Manchester United"},
                "awayTeam": {"id": 2, "name": "Arsenal"},
                "homeScore": {"current": 2},
                "awayScore": {"current": 1},
                "status": {"description": "Ended"},
            }
        )

    def test_normalizes_incidents_into_evidence_backed_insights(self):
        events = [
            Event.from_payload(
                {
                    "id": 100,
                    "incidentType": "goal",
                    "time": 84,
                    "isHome": True,
                    "player": {"name": "Bruno Fernandes"},
                    "homeScore": 2,
                    "awayScore": 1,
                    "text": "Goal",
                }
            ),
            Event.from_payload(
                {
                    "incidentType": "substitution",
                    "time": 74,
                    "isHome": False,
                    "playerIn": {"name": "Player In"},
                    "playerOut": {"name": "Player Out"},
                }
            ),
        ]

        insights = MatchAnalyzer().analyze(self.match, events)

        self.assertEqual([insight.kind for insight in insights], ["substitution", "goal"])
        self.assertIn("Player In replaced Player Out", insights[0].summary)
        self.assertIn("Bruno Fernandes", insights[1].summary)
        self.assertIn("2-1", insights[1].summary)
        self.assertEqual(insights[1].start_minute, 84)
        self.assertEqual(insights[1].evidence, ("Goal",))

    def test_ignores_incidents_without_supported_story_rules(self):
        events = [Event.from_payload({"incidentType": "period", "time": 45})]

        self.assertEqual(MatchAnalyzer().analyze(self.match, events), ())


if __name__ == "__main__":
    unittest.main()