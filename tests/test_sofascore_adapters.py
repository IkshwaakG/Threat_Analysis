import unittest

from goodgame.ingestion.sofascore.matches import fetch_season_matches
from goodgame.ingestion.sofascore.players import fetch_player_statistics, fetch_team_players
from goodgame.ingestion.sofascore.teams import fetch_teams, find_team_id


class FakeClient:
    def __init__(self):
        self.paths = []

    def get_json(self, path, params=None):
        self.paths.append(path)
        if path.endswith("standings/total"):
            return {
                "standings": [
                    {"rows": [{"team": {"id": 123, "name": "Arsenal", "slug": "arsenal"}}]}
                ]
            }
        if path.endswith("events/last/0"):
            return {"events": [self.match_payload()]}
        if path == "team/123/players":
            return {"players": [{"player": {"id": 456, "name": "Sample Player"}}]}
        if path.endswith("statistics/overall"):
            return {"statistics": {"goals": 20}}
        raise AssertionError(f"Unexpected endpoint: {path}")

    @staticmethod
    def match_payload():
        return {
            "id": 789,
            "homeTeam": {"id": 123, "name": "Arsenal"},
            "awayTeam": {"id": 321, "name": "Manchester United"},
            "homeScore": {"current": 2},
            "awayScore": {"current": 1},
            "status": {"description": "Ended"},
        }


class SofaScoreAdapterTests(unittest.TestCase):
    def test_fetches_competition_matches_and_team_players(self):
        client = FakeClient()

        teams = fetch_teams(client, tournament_id=42, season_id=99)
        team_id = find_team_id(client, "Arsenal", tournament_id=42, season_id=99)
        matches = fetch_season_matches(client, tournament_id=42, season_id=99)
        players = fetch_team_players(client, team_id)
        statistics = fetch_player_statistics(client, 456, tournament_id=42, season_id=99)

        self.assertEqual(teams[0]["id"], 123)
        self.assertEqual(team_id, 123)
        self.assertEqual(matches[0].id, 789)
        self.assertEqual(players[0]["name"], "Sample Player")
        self.assertEqual(statistics, {"goals": 20})
        self.assertIn(
            "unique-tournament/42/season/99/events/last/0", client.paths
        )
        self.assertIn("team/123/players", client.paths)


if __name__ == "__main__":
    unittest.main()