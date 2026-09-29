import unittest
from pathlib import Path

from goodgame.serving.demo_repository import DemoServingRepository


class DemoRepositoryTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "demo_data" / "snapshot.example.json"
        self.repo = DemoServingRepository(path)

    def test_example_snapshot_supports_main_views(self):
        competitions = self.repo.list_competitions()
        self.assertEqual(competitions[0]["id"], 999001)

        seasons = self.repo.list_seasons(999001)
        self.assertEqual(seasons[0]["id"], 999101)

        matches = self.repo.list_matches(999001, 999101)
        self.assertEqual(matches[0]["id"], 999201)

        game = self.repo.get_game_view(999201)
        self.assertEqual(game["home_team"]["name"], "Demo United")

        team = self.repo.get_team_view(999301, 999101, 999001)
        self.assertEqual(team["team"]["name"], "Demo United")

        player = self.repo.get_player_view(999401, 999101, 999001)
        self.assertEqual(player["player"]["name"], "Alex Demo")

    def test_example_snapshot_supports_search(self):
        results = self.repo.search_entities("Demo", season_id=999101, league_id=999001)
        self.assertTrue(any(row["entity_type"] == "team" for row in results))
        self.assertTrue(any(row["entity_type"] == "player" for row in results))


if __name__ == "__main__":
    unittest.main()
