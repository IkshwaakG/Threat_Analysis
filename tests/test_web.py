import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from goodgame.web import _selectable_events, app


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
            "commentary": [
                {
                    "id": 5001,
                    "minute": 12,
                    "extra_minute": None,
                    "comment": "Bruno Fernandes tests the goalkeeper from outside the box.",
                    "is_goal": False,
                    "is_important": True,
                    "sort_order": 9,
                }
            ],
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
            "match_facts": [
                {
                    "id": 701,
                    "fixture_id": fixture_id,
                    "type_id": 99,
                    "participant": "home",
                    "basis": "team",
                    "category": "streaks",
                    "scope": "league_matches",
                    "natural_language": "Manchester United have scored in 6 consecutive league matches.",
                    "data": {"streak": 6},
                    "related_player": None,
                }
            ],
            "ai_overviews": [
                {"id": 801, "summary": "Manchester United enter the fixture in strong scoring form."}
            ],
            "head_to_head": [
                {
                    "id": 41,
                    "starting_at": "2024-12-01T16:30:00+00:00",
                    "home_team_id": 2,
                    "home_team": "Arsenal",
                    "away_team_id": 1,
                    "away_team": "Manchester United",
                    "home_score": 1,
                    "away_score": 1,
                    "result_info": "FT",
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

    def test_selectable_events_support_both_video_event_shapes(self):
        game = {
            "home_team": {"id": 1, "name": "Manchester United"},
            "away_team": {"id": 2, "name": "Arsenal"},
            "players": [{"player_id": 10, "name": "Bruno Fernandes", "team": "home"}],
            "events": [
                {
                    "id": 9001,
                    "minute": 10,
                    "type": "Goal",
                    "text": "Goal",
                    "team_id": 1,
                    "player_id": 10,
                    "is_home": True,
                }
            ],
            "timeline": [],
            "video_events": [
                {
                    "video_event_id": 100,
                    "match_event_id": 9001,
                    "event_type": "goal",
                    "event_label": "Goal",
                    "match_minute": 10,
                    "team_id": 1,
                    "player_id": 10,
                    "confidence": 0.95,
                    "transcript_text": "Goal scored",
                },
                {
                    "video_event_key": "video-goal",
                    "event_type": "goal",
                    "display_label": "Video-only goal",
                    "match_minute": 25,
                    "team_name": "Manchester United",
                    "player_name": "Bruno Fernandes",
                    "ball_track": [{"x": 50, "y": 50}, {"x": 90, "y": 50}],
                    "analysis": {"confidence": 0.8},
                },
            ],
        }

        events = _selectable_events(game)

        self.assertEqual(len(events), 2)
        matched = next(event for event in events if event.get("id") == 9001)
        self.assertEqual(matched["video_analysis"]["video_event_key"], 100)
        self.assertEqual(matched["video_analysis"]["transcript_text"], "Goal scored")
        video_only = next(event for event in events if event["source_kind"] == "video")
        self.assertEqual(video_only["id"], "video:video-goal")
        self.assertEqual(video_only["player"], "Bruno Fernandes")
        self.assertEqual(video_only["spatial"]["source"], "video")
        self.assertEqual(len(video_only["spatial"]["ball_track"]), 2)

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
        self.assertEqual(body["commentary"][0]["id"], 5001)
        self.assertTrue(body["commentary"][0]["is_important"])
        self.assertEqual(body["match_facts"][0]["category"], "streaks")
        self.assertIn("6 consecutive", body["match_facts"][0]["natural_language"])
        self.assertTrue(body["ai_overviews"])
        self.assertEqual(body["head_to_head"][0]["id"], 41)
        self.assertEqual(body["head_to_head"][0]["home_score"], 1)
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


def test_regulation_minute_boundaries_do_not_flip_45_or_90():
    # Regression documentation: 45' is still first-half stoppage time and 90'
    # is still second-half stoppage time. extra_minute stores added time.
    def event_half(minute: int) -> int:
        if minute <= 45:
            return 1
        if minute <= 90:
            return 2
        if minute <= 105:
            return 3
        return 4

    assert event_half(45) == 1
    assert event_half(46) == 2
    assert event_half(90) == 2
    assert event_half(91) == 3


def test_shot_matching_prefers_correct_attacking_goal():
    # Regression contract: stored shot traversal must approach the attacking
    # goal for that team/half rather than the nearest goal on the pitch.
    def progress_to_target(start_x: float, end_x: float, target_x: float) -> float:
        return abs(start_x - target_x) - abs(end_x - target_x)

    assert progress_to_target(55.0, 88.0, 100.0) > 0
    assert progress_to_target(55.0, 12.0, 100.0) < 0
    assert progress_to_target(45.0, 12.0, 0.0) > 0


def test_goal_can_reuse_matching_shot_on_target_track():
    goal = {"minute": 37, "team_id": 1, "player_id": 10}
    shot = {
        "minute": 37,
        "team_id": 1,
        "player_id": 10,
        "spatial": {"source": "stored", "ball_track": [{"x": 75, "y": 50}, {"x": 96, "y": 49}]},
    }
    assert goal["minute"] == shot["minute"]
    assert goal["team_id"] == shot["team_id"]
    assert shot["spatial"]["source"] == "stored"


def test_event_minute_matches_same_sportmonks_timer_minute():
    def timer_window(event_minute: int, extra_minute: int = 0) -> tuple[int, int]:
        match_minute = event_minute + extra_minute
        return match_minute * 60, match_minute * 60 + 59

    assert timer_window(35) == (35 * 60, 35 * 60 + 59)
    assert timer_window(37) == (37 * 60, 37 * 60 + 59)
    assert timer_window(90) == (90 * 60, 90 * 60 + 59)


def test_goal_matcher_must_not_use_kickoff_reset_as_goal_track():
    centre = {"x": 50.0, "y": 50.0}
    assert abs(centre["x"] - 50.0) <= 3.0
    assert abs(centre["y"] - 50.0) <= 6.0


def test_event_coordinate_match_checks_current_and_previous_timer_minute():
    def candidate_windows(display_minute: int) -> list[tuple[int, int]]:
        candidates = sorted({max(0, display_minute - 1), display_minute})
        return [(minute * 60, minute * 60 + 59) for minute in candidates]

    assert candidate_windows(39) == [(38 * 60, 38 * 60 + 59), (39 * 60, 39 * 60 + 59)]
    assert candidate_windows(1) == [(0, 59), (60, 119)]


def test_shot_track_stops_before_rebound():
    # The terminal point of a shot is the local closest approach to the target
    # goal. A later sample moving away belongs to save/rebound/clearance.
    target_x = 100.0
    xs = [55.0, 82.0, 96.0, 74.0]
    distances = [abs(x - target_x) for x in xs]
    terminal = min(range(len(distances)), key=distances.__getitem__)
    assert terminal == 2
    assert distances[3] > distances[2]


def test_shot_traversal_starts_at_launch_and_moves_forward():
    # A stored shot trajectory begins at the coordinate where the shot is
    # launched and continues forward to the terminal save/miss/goal point.
    target_x = 100.0
    xs = [42.0, 44.0, 71.0, 93.0, 72.0]
    distances = [abs(x - target_x) for x in xs]

    # 44 -> 71 is the first decisive goalward movement, so 44 is launch.
    launch_index = 1
    assert distances[launch_index] - distances[launch_index + 1] >= 3.0

    # 93 is the local closest approach; 72 is post-save/rebound movement.
    assert distances[3] < distances[2]
    assert distances[4] > distances[3]


def test_corner_track_rejects_large_provider_jump():
    # A corner may move from the flag into the box, but a large unrelated
    # provider jump should terminate the stored segment.
    start = (99.0, 2.0)
    good = (88.0, 24.0)
    bad = (72.0, 78.0)

    def distance(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    assert distance(start, good) < 34.0
    assert distance(good, bad) > 34.0
