import unittest

from goodgame.pipeline import GoodGamePipeline


class FakeSofaScoreClient:
    def __init__(self):
        self.paths = []

    def get_json(self, path, params=None):
        self.paths.append(path)
        if path == "event/42":
            return {
                "event": {
                    "id": 42,
                    "homeTeam": {"id": 1, "name": "Manchester United"},
                    "awayTeam": {"id": 2, "name": "Arsenal"},
                    "homeScore": {"current": 2},
                    "awayScore": {"current": 1},
                    "status": {"description": "Ended"},
                }
            }
        if path == "event/42/incidents":
            return {
                "incidents": [
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
                ]
            }
        if path == "event/42/lineups":
            return {"home": {"formation": "4-2-3-1"}, "away": {"formation": "4-3-3"}}
        if path == "event/42/shotmap":
            return {"shotmap": [{"player": {"name": "Bruno Fernandes"}, "time": 84}]}
        raise AssertionError(f"Unexpected endpoint: {path}")


class GoodGamePipelineTests(unittest.TestCase):
    def test_fetches_match_resources_and_builds_story(self):
        client = FakeSofaScoreClient()

        analysis = GoodGamePipeline(client=client).analyze_match(42)

        self.assertEqual(
            client.paths,
            [
                "event/42",
                "event/42/incidents",
                "event/42/lineups",
                "event/42/shotmap",
            ],
        )
        self.assertEqual(analysis.match.home_team.name, "Manchester United")
        self.assertEqual(analysis.insights[0].title, "Goal sequence")
        self.assertEqual(analysis.lineups["home"]["formation"], "4-2-3-1")
        self.assertEqual(len(analysis.shots), 1)


if __name__ == "__main__":
    unittest.main()