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
            "events": [
                {
                    "id": 9001,
                    "minute": 10,
                    "extra_minute": None,
                    "type": "Shot On Target",
                    "text": "Shot On Target",
                    "team_id": 1,
                    "player_id": 10,
                    "is_home": True,
                    "ball_path": None,
                    "player_positions": [],
                    "detail": {},
                },
                {
                    "id": 9002,
                    "minute": 12,
                    "extra_minute": None,
                    "type": "Corner",
                    "text": "Corner",
                    "team_id": 1,
                    "player_id": 10,
                    "is_home": True,
                    "ball_path": None,
                    "player_positions": [],
                    "detail": {},
                }
,
                {
                    "id": 9003,
                    "minute": 53,
                    "extra_minute": None,
                    "type": "Corner",
                    "text": "Second Half Corner",
                    "team_id": 1,
                    "player_id": 10,
                    "is_home": True,
                    "ball_path": None,
                    "player_positions": [],
                    "detail": {},
                }
            ],
            "timeline": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 100, "timer": "09:55", "x": 61.0, "y": 48.0},
                {"id": 2, "period_id": 100, "timer": "10:00", "x": 44.0, "y": 74.0},
                {"id": 3, "period_id": 100, "timer": "10:05", "x": 43.0, "y": 21.0},
                {"id": 4, "period_id": 100, "timer": "10:10", "x": 10.0, "y": 62.0},
                {"id": 41, "period_id": 100, "timer": "10:20", "x": 72.0, "y": 49.0},
                {"id": 42, "period_id": 100, "timer": "10:25", "x": 86.0, "y": 51.0},
                {"id": 43, "period_id": 100, "timer": "10:30", "x": 97.0, "y": 50.0},
                {"id": 5, "period_id": 100, "timer": "11:56", "x": 99.0, "y": 2.0},
                {"id": 6, "period_id": 100, "timer": "12:00", "x": 96.0, "y": 8.0},
                {"id": 7, "period_id": 100, "timer": "12:04", "x": 91.0, "y": 28.0},
                {"id": 8, "period_id": 100, "timer": "12:08", "x": 86.0, "y": 42.0},
                {"id": 9, "period_id": 100, "timer": "12:12", "x": 63.0, "y": 50.0},
            ],
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
        self.assertTrue(body["selectable_events"])
        shot = body["selectable_events"][0]["spatial"]
        self.assertEqual(shot["source"], "stored")
        self.assertGreaterEqual(len(shot["ball_track"]), 2)
        self.assertGreaterEqual(shot["ball_path"]["end"]["x"], 90.0)
        self.assertLessEqual(abs(shot["ball_path"]["end"]["y"] - 50.0), 9.0)
        self.assertNotEqual(shot["ball_path"]["end"], {"x": 10.0, "y": 62.0})

        corner = next(
            event["spatial"]
            for event in body["selectable_events"]
            if event["spatial"]["kind"] == "corner"
        )
        self.assertEqual(corner["source"], "stored")
        self.assertGreaterEqual(len(corner["ball_track"]), 2)
        self.assertGreaterEqual(corner["ball_path"]["start"]["x"], 95.0)
        self.assertLessEqual(corner["ball_path"]["start"]["y"], 12.0)
        self.assertGreater(corner["ball_path"]["end"]["x"], 70.0)
        # Stored corner starts near the right goal line and must remain in that
        # same attacking end rather than traversing across midfield.
        self.assertGreater(corner["ball_path"]["end"]["x"], 50.0)

        second_half_corner = next(
            event["spatial"]
            for event in body["selectable_events"]
            if event.get("id") == 9003
        )
        self.assertEqual(second_half_corner["source"], "inferred")
        self.assertLess(second_half_corner["ball_path"]["start"]["x"], 50.0)
        self.assertLess(second_half_corner["ball_path"]["end"]["x"], 50.0)

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
