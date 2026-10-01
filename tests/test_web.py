import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from goodgame.web import app


class FakeServingRepository:
    def list_competitions(self):
        return [{"id": 8, "name": "Premier League"}]

    def list_seasons(self, competition_id):
        return [{"id": 318, "name": "2024/2025", "competition_id": competition_id}]

    def list_matches(self, competition_id, season_id):
        return [
            {
                "id": 42,
                "date": "2025-01-15T20:00:00",
                "home_team": "Manchester United",
                "away_team": "Arsenal",
            }
        ]

    def list_teams(self, season_id, competition_id=None):
        return [{"id": 1, "name": "Manchester United"}]

    def list_players(self, season_id, competition_id=None):
        return [{"id": 10, "name": "Bruno Fernandes"}]

    def search_entities(self, query, season_id=None, league_id=None, limit=12):
        return [
            {
                "entity_type": "player",
                "id": 10,
                "name": "Bruno Fernandes",
                "subtitle": "26",
                "image": None,
                "league_id": league_id or 8,
                "season_id": season_id or 318,
            }
        ]

    def get_game_view(self, fixture_id):
        return {
            "fixture": {
                "id": fixture_id,
                "competition_id": 8,
                "season_id": 318,
                "name": "Manchester United vs Arsenal",
                "result_info": "FT",
                "competition_name": "Premier League",
            },
            "home_team": {
                "id": 1,
                "name": "Manchester United",
                "short_code": "MUN",
                "logo": None,
                "goals": 2,
                "profile_url": "/teams/1",
                "stats": [],
            },
            "away_team": {
                "id": 2,
                "name": "Arsenal",
                "short_code": "ARS",
                "logo": None,
                "goals": 1,
                "profile_url": "/teams/2",
                "stats": [],
            },
            "game_stats": [],
            "players": [
                {
                    "player_id": 10,
                    "name": "Bruno Fernandes",
                    "team_id": 1,
                    "team_name": "Manchester United",
                    "team_location": "home",
                    "jersey_number": 8,
                    "position_id": 26,
                    "formation_field": "3:2",
                    "formation_position": 6,
                    "profile_url": "/players/10",
                    "match_stats": [
                        {
                            "type_id": 1,
                            "name": "Rating",
                            "developer_name": "rating",
                            "value": 8.2,
                        }
                    ],
                }
            ],
            "source": "bigquery",
        }

    def get_team_view(self, team_id, season_id, league_id=None):
        return {"team": {"id": team_id}, "stats": [], "players": [], "recent_fixtures": []}

    def get_player_view(self, player_id, season_id, league_id=None):
        return {"player": {"id": player_id}, "stats": [], "teams": [], "recent_fixtures": []}


class GoodGameWebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_search_endpoint_uses_serving_repository(self):
        with patch("goodgame.web._repository", return_value=FakeServingRepository()):
            response = self.client.get(
                "/api/search?q=Bruno&season_id=318&competition_id=8"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["entity_type"], "player")
        self.assertEqual(body[0]["name"], "Bruno Fernandes")

    def test_search_rejects_one_character_queries(self):
        response = self.client.get("/api/search?q=B")
        self.assertEqual(response.status_code, 422)

    def test_game_endpoint_uses_serving_repository(self):
        with patch("goodgame.web._repository", return_value=FakeServingRepository()):
            response = self.client.get("/api/games/42")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["fixture"]["id"], 42)
        self.assertEqual(body["home_team"]["name"], "Manchester United")
        self.assertEqual(body["players"][0]["player_id"], 10)

    def test_visualization_is_derived_from_same_game_view(self):
        with patch("goodgame.web._repository", return_value=FakeServingRepository()):
            response = self.client.get("/api/matches/42/visualization")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["match"]["id"], 42)
        self.assertEqual(body["match"]["home_team"]["name"], "Manchester United")
        self.assertEqual(body["players"][0]["player_id"], 10)
        self.assertEqual(body["players"][0]["stats"]["rating"], 8.2)
        self.assertEqual(body["lineup_source"], "bigquery_game_view")

    def test_legacy_analysis_endpoint_is_retired(self):
        response = self.client.get("/api/matches/42/analysis")
        self.assertEqual(response.status_code, 410)

    def test_rejects_non_positive_ids_without_db_call(self):
        with patch("goodgame.web._repository") as repository:
            response = self.client.get("/api/games/0")
        self.assertEqual(response.status_code, 422)
        repository.assert_not_called()


if __name__ == "__main__":
    unittest.main()
