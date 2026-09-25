import unittest

from goodgame.ingestion.sofascore.players import fetch_player_links, fetch_player_statistics
from goodgame.ingestion.sofascore.teams import (
    fetch_team_link,
    fetch_team_links,
    fetch_team_statistics,
)


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
        if path == "team/123/players":
            return {
                "players": [
                    {"player": {"id": 456, "name": "Sample Player", "slug": "sample-player"}}
                ]
            }
        if path.startswith("team/123/"):
            return {"statistics": {"wins": 28}}
        if path.startswith("player/456/"):
            return {"statistics": {"goals": 20}}
        raise AssertionError(f"Unexpected endpoint: {path}")


class EntityHelperTests(unittest.TestCase):
    def test_team_helpers_support_names_and_full_numeric_ids(self):
        client = FakeClient()

        link = fetch_team_link(client, "Arsenal", tournament_id=42, season_id=99)
        statistics = fetch_team_statistics(
            client, "Arsenal", tournament_id=42, season_id=99
        )
        statistics_by_id = fetch_team_statistics(
            client, 123, tournament_id=42, season_id=99
        )

        self.assertEqual(link, "https://www.sofascore.com/team/football/arsenal/123")
        self.assertEqual(statistics, {"wins": 28})
        self.assertEqual(statistics_by_id, {"wins": 28})
        self.assertIn("team/123/unique-tournament/42/season/99/statistics/overall", client.paths)

    def test_team_links_include_all_standing_teams(self):
        client = FakeClient()

        links = fetch_team_links(client, tournament_id=42, season_id=99)

        self.assertEqual(links["Arsenal"], "https://www.sofascore.com/team/football/arsenal/123")

    def test_player_helpers_accept_profile_urls_and_resolve_team_names(self):
        client = FakeClient()

        statistics = fetch_player_statistics(
            client,
            "https://www.sofascore.com/player/sample-player/456",
            tournament_id=42,
            season_id=99,
        )
        links = fetch_player_links(client, "Arsenal", tournament_id=42, season_id=99)

        self.assertEqual(statistics, {"goals": 20})
        self.assertEqual(
            links["Sample Player"],
            "https://www.sofascore.com/player/sample-player/456",
        )
        self.assertIn("player/456/unique-tournament/42/season/99/statistics/overall", client.paths)


if __name__ == "__main__":
    unittest.main()