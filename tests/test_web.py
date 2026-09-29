import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from goodgame.models.event import Event
from goodgame.models.match import Match
from goodgame.web import app


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
        return {
            "Manchester United": [{"player_id": 10}],
            "Arsenal": [{"player_id": 11}],
        }

    def get_shot_map(self, match_id):
        return [{"player": "Bruno Fernandes", "minute": 84}]

    def get_fixture_statistics(self, match_id):
        return [{"type_id": 42, "value": 12}]

    def get_fixture_xg(self, match_id):
        return [{"participant_id": 1, "data": {"value": 1.7}}]


class GoodGameWebTests(unittest.TestCase):
    def test_analysis_endpoint_returns_stable_frontend_payload(self):
        client = TestClient(app)

        with patch("goodgame.web._provider", return_value=FakeProvider()):
            response = client.get("/api/matches/42/analysis")

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["schema_version"], "1")
        self.assertEqual(body["provider"], "bigquery")
        self.assertEqual(body["match"]["id"], 42)
        self.assertEqual(body["match"]["home_team"]["name"], "Manchester United")
        self.assertEqual(body["events"][0]["player"], "Bruno Fernandes")
        self.assertEqual(body["insights"][0]["title"], "Goal sequence")
        self.assertEqual(body["shots"][0]["player"], "Bruno Fernandes")
        self.assertEqual(body["statistics"][0]["type_id"], 42)
        self.assertEqual(body["xg"][0]["data"]["value"], 1.7)


if __name__ == "__main__":
    unittest.main()
