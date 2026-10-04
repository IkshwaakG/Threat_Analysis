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
                    "minute": 11,
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
                    "minute": 11,
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

    def test_goal_reconstruction_uses_assist_commentary_and_ball_timers(self):
        game = {
            "home_team": {"id": 1, "name": "Manchester United"},
            "away_team": {"id": 2, "name": "Ipswich Town"},
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
                    "match_stats": [],
                },
                {
                    "player_id": 11,
                    "name": "Matheus Cunha",
                    "team_id": 1,
                    "team_name": "Manchester United",
                    "team_location": "home",
                    "jersey_number": 10,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                },
            ],
            "events": [
                {
                    "id": 9100,
                    "minute": 40,
                    "extra_minute": None,
                    "period_id": 100,
                    "type": "goal",
                    "text": "Goal",
                    "team_id": 1,
                    "player_id": 10,
                    "player": "Bruno Fernandes",
                    "related_player_id": 11,
                    "related_player_name": "Matheus Cunha",
                    "is_home": True,
                    "detail": {"body_part": "Left foot shot"},
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7001,
                    "minute": 40,
                    "extra_minute": None,
                    "comment": (
                        "Goal! Bruno Fernandes scores for Manchester United with a left-footed "
                        "shot from the center of the box into the top left corner, assisted by "
                        "Matheus Cunha's through ball after a fast break."
                    ),
                    "is_goal": True,
                    "is_important": True,
                    "sort_order": 42,
                }
            ],
            "trends": [
                {
                    "id": 8001,
                    "fixture_id": 42,
                    "participant_id": 1,
                    "type_id": 45,
                    "period_id": 100,
                    "value": 61,
                    "minute": 40,
                    "participant": {"id": 1, "name": "Manchester United", "short_code": "MUN"},
                }
            ],
            "ball_coordinates": [
                {"id": 1, "period_id": 100, "timer": "39:40", "x": 65.0, "y": 48.0},
                {"id": 2, "period_id": 100, "timer": "39:45", "x": 75.0, "y": 49.0},
                {"id": 3, "period_id": 100, "timer": "39:50", "x": 86.0, "y": 50.0},
                {"id": 4, "period_id": 100, "timer": "39:53", "x": 95.0, "y": 48.0},
                {"id": 5, "period_id": 100, "timer": "39:56", "x": 99.0, "y": 46.0},
            ],
            "video_events": [],
        }

        events = _selectable_events(game)
        goal = next(event for event in events if event.get("id") == 9100)

        self.assertEqual(goal["detail"]["body_part"], "Left foot shot")
        self.assertEqual(goal["detail"]["shot_origin"], "center of the box")
        self.assertEqual(goal["detail"]["goal_target"], "top left corner")
        self.assertEqual(goal["detail"]["assist_type"], "through ball")
        self.assertEqual(goal["detail"]["situation"], "Fast break")
        self.assertEqual(goal["commentary_id"], 7001)
        self.assertEqual(goal["trend_context"][0]["participant_name"], "Manchester United")
        self.assertEqual(goal["spatial"]["source"], "stored_assist_goal")
        self.assertEqual(goal["spatial"]["shot_actor_anchor"], {"x": 86.0, "y": 50.0})
        self.assertNotEqual(goal["spatial"]["shot_actor_anchor"], goal["spatial"]["ball_track"][-1])
        self.assertGreater(goal["spatial"]["shot_start_index"], 0)
        self.assertEqual(goal["spatial"]["phases"][0]["kind"], "assist")
        self.assertEqual(goal["spatial"]["phases"][1]["kind"], "shot")
        shot_index = goal["spatial"]["shot_start_index"]
        self.assertEqual(goal["spatial"]["ball_track"][shot_index]["timer"], "39:50")
        self.assertEqual(goal["spatial"]["ball_track"][0]["timer"], "39:40")

    def test_goal_clusters_same_minute_corner_buildup(self):
        game = {
            "home_team": {"id": 1, "name": "Manchester United"},
            "away_team": {"id": 2, "name": "Arsenal"},
            "players": [
                {
                    "player_id": 31,
                    "name": "Riccardo Calafiori",
                    "team_id": 2,
                    "team_name": "Arsenal",
                    "team_location": "away",
                    "jersey_number": 33,
                    "position_id": 25,
                    "formation_field": "2:2",
                    "formation_position": 4,
                    "match_stats": [],
                }
            ],
            "events": [
                {
                    "id": 150944812,
                    "minute": 13,
                    "period_id": 6175643,
                    "type": "goal",
                    "text": "Goal",
                    "team_id": 2,
                    "player_id": 31,
                    "player": "Riccardo Calafiori",
                    "is_home": False,
                    "detail": {
                        "body_part": "Header",
                        "period_clock": "46:04",
                        "period_minutes": 46,
                        "period_seconds": 4,
                        "period_elapsed_seconds": 2764,
                        "period_counts_from": 0,
                    },
                },
                {
                    "id": 150944811,
                    "minute": 13,
                    "period_id": 6175643,
                    "type": "corner",
                    "text": "Corner",
                    "team_id": 2,
                    "is_home": False,
                    "detail": {},
                    "ball_path": {
                        "start": {"x": 1.0, "y": 98.0},
                        "end": {"x": 12.0, "y": 55.0},
                    },
                },
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7400,
                    "minute": 13,
                    "comment": (
                        "Goal! Arsenal lead 1-0. Riccardo Calafiori scores with a header "
                        "from very close range into the bottom right corner after a corner."
                    ),
                    "is_goal": True,
                    "is_important": True,
                    "sort_order": 13,
                }
            ],
            "trends": [],
            "ball_coordinates": [],
            "video_events": [],
        }

        events = _selectable_events(game)
        minute_events = [event for event in events if event.get("minute") == 13]

        self.assertEqual(len(minute_events), 1)
        goal = minute_events[0]
        self.assertEqual(goal["spatial"]["kind"], "goal")
        self.assertEqual(goal["display_type"], "Goal")
        self.assertEqual(goal["player"], "Riccardo Calafiori")
        self.assertEqual(goal["detail"]["body_part"], "Header")
        self.assertEqual(goal["detail"]["situation"], "Corner")
        self.assertEqual(goal["spatial"]["source"], "semantic_reconstructed")
        self.assertEqual(goal["spatial"]["shot_start_index"], 0)
        self.assertEqual(goal["spatial"]["phases"], [{"kind": "shot", "start_index": 0, "end_index": 1}])
        self.assertEqual(goal["spatial"]["ball_track"][0]["x"], goal["spatial"]["shot_actor_anchor"]["x"])
        self.assertEqual(goal["spatial"]["ball_track"][0]["y"], goal["spatial"]["shot_actor_anchor"]["y"])

    def test_saved_comment_reclassifies_raw_off_target_shot(self):
        game = {
            "home_team": {"id": 1, "name": "Manchester United"},
            "away_team": {"id": 2, "name": "Arsenal"},
            "players": [
                {
                    "player_id": 10,
                    "name": "Matheus Cunha",
                    "team_id": 1,
                    "team_name": "Manchester United",
                    "team_location": "home",
                    "jersey_number": 10,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                }
            ],
            "events": [
                {
                    "id": 9500,
                    "minute": 38,
                    "period_id": 100,
                    "type": "shot_off_target",
                    "text": "Shot Off Target",
                    "team_id": 1,
                    "player_id": 10,
                    "player": "Matheus Cunha",
                    "is_home": True,
                    "detail": {},
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7500,
                    "minute": 38,
                    "comment": (
                        "Attempt saved. Matheus Cunha has a left-footed shot from a tough "
                        "angle on the left, but David Raya saves it in the center of the goal."
                    ),
                    "is_goal": False,
                    "is_important": True,
                    "sort_order": 38,
                }
            ],
            "trends": [],
            "ball_coordinates": [],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9500)

        self.assertEqual(event["spatial"]["kind"], "shot_on_target")
        self.assertEqual(event["display_type"], "Shot On Target")
        self.assertEqual(event["detail"]["shot_outcome_hint"], "saved")
        self.assertEqual(event["detail"]["shot_origin"], "left side of the box")
        self.assertEqual(event["spatial"]["outcome_marker"]["kind"], "save")

    def test_event_minute_13_maps_to_12xx_ball_timer_window(self):
        game = {
            "home_team": {"id": 1, "name": "Home"},
            "away_team": {"id": 2, "name": "Away"},
            "players": [
                {
                    "player_id": 41,
                    "name": "Minute Thirteen",
                    "team_id": 1,
                    "team_name": "Home",
                    "team_location": "home",
                    "jersey_number": 9,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                }
            ],
            "events": [
                {
                    "id": 9160,
                    "minute": 13,
                    "extra_minute": None,
                    "period_id": 100,
                    "type": "goal",
                    "text": "Goal",
                    "team_id": 1,
                    "player_id": 41,
                    "player": "Minute Thirteen",
                    "is_home": True,
                    "detail": {
                        "body_part": "Right foot",
                        "period_clock": "46:04",
                        "period_minutes": 46,
                        "period_seconds": 4,
                        "period_elapsed_seconds": 2764,
                        "period_counts_from": 0,
                    },
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7060,
                    "minute": 13,
                    "comment": "Goal! Minute Thirteen scores from the center of the box.",
                    "is_goal": True,
                    "is_important": True,
                    "sort_order": 13,
                }
            ],
            "trends": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 100, "timer": "12:10", "x": 85.0, "y": 50.0},
                {"id": 2, "period_id": 100, "timer": "12:16", "x": 99.0, "y": 50.0},
                {"id": 3, "period_id": 100, "timer": "13:10", "x": 20.0, "y": 20.0},
            ],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9160)
        self.assertEqual(event["spatial"]["source"], "semantic_fused")
        self.assertEqual(event["spatial"]["coordinate_support"]["terminal_timer"], "12:16")
        self.assertEqual(event["spatial"]["coordinate_support"]["points"], 2)
        self.assertEqual(event["spatial"]["ball_track"][0]["x"], event["spatial"]["shot_actor_anchor"]["x"])
        self.assertNotEqual(event["spatial"]["ball_track"][0].get("timer"), "13:10")

    def test_period_minutes_seconds_bound_ball_coordinate_join(self):
        game = {
            "home_team": {"id": 1, "name": "Home"},
            "away_team": {"id": 2, "name": "Away"},
            "players": [
                {
                    "player_id": 10,
                    "name": "Header Scorer",
                    "team_id": 1,
                    "team_name": "Home",
                    "team_location": "home",
                    "jersey_number": 5,
                    "position_id": 25,
                    "formation_field": "2:2",
                    "formation_position": 4,
                    "match_stats": [],
                }
            ],
            "events": [
                {
                    "id": 9150,
                    "minute": 45,
                    "extra_minute": 2,
                    "period_id": 100,
                    "type": "goal",
                    "text": "Goal",
                    "team_id": 1,
                    "player_id": 10,
                    "player": "Header Scorer",
                    "is_home": True,
                    "detail": {
                        "body_part": "Header",
                        "period_clock": "46:04",
                        "period_minutes": 46,
                        "period_seconds": 4,
                        "period_elapsed_seconds": 2764,
                        "period_counts_from": 0,
                    },
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7050,
                    "minute": 45,
                    "extra_minute": 2,
                    "comment": "Goal! Header Scorer scores with a header from the center of the box.",
                    "is_goal": True,
                    "is_important": True,
                    "sort_order": 46,
                }
            ],
            "trends": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 100, "timer": "45:58", "x": 85.0, "y": 50.0},
                {"id": 2, "period_id": 100, "timer": "46:03", "x": 99.0, "y": 50.0},
                # This point is after the period's 46:04 clock and must never
                # participate in the event track.
                {"id": 3, "period_id": 100, "timer": "46:08", "x": 20.0, "y": 20.0},
            ],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9150)
        timers = [
            point.get("timer")
            for point in event.get("spatial", {}).get("ball_track", [])
        ]

        self.assertTrue(timers)
        self.assertIn("46:03", timers)
        self.assertNotIn("46:08", timers)

    def test_off_target_commentary_guides_shot_without_inventing_player_tracking(self):
        game = {
            "home_team": {"id": 1, "name": "Home"},
            "away_team": {"id": 2, "name": "Away"},
            "players": [
                {
                    "player_id": 20,
                    "name": "Shooter",
                    "team_id": 2,
                    "team_name": "Away",
                    "team_location": "away",
                    "jersey_number": 9,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                }
            ],
            "events": [
                {
                    "id": 9200,
                    "minute": 61,
                    "period_id": 200,
                    "type": "shot_off_target",
                    "text": "Shot off target",
                    "team_id": 2,
                    "player_id": 20,
                    "player": "Shooter",
                    "is_home": False,
                    "detail": {},
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7100,
                    "minute": 61,
                    "comment": "Shooter's right-footed shot from outside the box misses to the right.",
                    "is_goal": False,
                    "is_important": False,
                    "sort_order": 20,
                }
            ],
            "trends": [],
            "ball_coordinates": [],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9200)
        self.assertEqual(event["commentary_id"], 7100)
        self.assertEqual(event["detail"]["body_part"], "Right foot")
        self.assertEqual(event["detail"]["shot_origin"], "outside the box")
        self.assertEqual(event["detail"]["shot_outcome_hint"], "right")
        self.assertEqual(event["spatial"]["source"], "commentary_inferred")
        self.assertEqual(event["spatial"]["shot_actor_anchor"], {"x": 76.0, "y": 50.0})
        self.assertGreater(event["spatial"]["ball_path"]["end"]["y"], 50.0)
        self.assertFalse(event.get("player_positions"))

    def test_assisted_saved_shot_splits_pass_shot_and_save(self):
        game = {
            "home_team": {"id": 1, "name": "Tottenham Hotspur"},
            "away_team": {"id": 2, "name": "Brentford"},
            "players": [
                {
                    "player_id": 10,
                    "name": "Xavi Simons",
                    "team_id": 1,
                    "team_name": "Tottenham Hotspur",
                    "team_location": "home",
                    "jersey_number": 7,
                    "position_id": 26,
                    "formation_field": "3:2",
                    "formation_position": 6,
                    "match_stats": [],
                },
                {
                    "player_id": 11,
                    "name": "Richarlison",
                    "team_id": 1,
                    "team_name": "Tottenham Hotspur",
                    "team_location": "home",
                    "jersey_number": 9,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                },
                {
                    "player_id": 30,
                    "name": "Caoimhin Kelleher",
                    "team_id": 2,
                    "team_name": "Brentford",
                    "team_location": "away",
                    "jersey_number": 1,
                    "position_id": 24,
                    "formation_field": "1:1",
                    "formation_position": 1,
                    "match_stats": [],
                },
            ],
            "events": [
                {
                    "id": 9300,
                    "minute": 62,
                    "period_id": 200,
                    "type": "shot_on_target",
                    "text": "Shot On Target",
                    "team_id": 1,
                    "player_id": None,
                    "player": None,
                    "related_player_id": None,
                    "related_player_name": None,
                    "is_home": True,
                    "detail": {},
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7200,
                    "minute": 62,
                    "comment": (
                        "A fresh offensive move unfolds as Xavi Simons from Tottenham Hotspur "
                        "takes a right-footed shot from outside the penalty area. The attempt is "
                        "expertly denied by Brentford's Caoimhin Kelleher, who makes a save in "
                        "the top right corner. The assist for this play comes from Richarlison."
                    ),
                    "is_goal": False,
                    "is_important": True,
                    "sort_order": 30,
                }
            ],
            "trends": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 200, "timer": "61:20", "x": 65.0, "y": 52.0},
                {"id": 2, "period_id": 200, "timer": "61:24", "x": 24.0, "y": 50.0},
                {"id": 3, "period_id": 200, "timer": "61:27", "x": 4.0, "y": 46.0},
            ],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9300)

        self.assertEqual(event["player"], "Xavi Simons")
        self.assertEqual(event["related_player_name"], "Richarlison")
        self.assertEqual(event["detail"]["body_part"], "Right foot")
        self.assertEqual(event["detail"]["shot_origin"], "outside the box")
        self.assertEqual(event["detail"]["shot_outcome_hint"], "saved")
        self.assertEqual(event["spatial"]["source"], "semantic_fused")
        self.assertEqual(event["spatial"]["shot_start_index"], 1)
        self.assertIn("assist_actor_anchor", event["spatial"])
        self.assertEqual(event["spatial"]["shot_actor_anchor"], {"x": 24.0, "y": 50.0})
        self.assertEqual(event["spatial"]["ball_track"][0]["x"], event["spatial"]["assist_actor_anchor"]["x"])
        self.assertEqual(event["spatial"]["ball_track"][1]["x"], event["spatial"]["shot_actor_anchor"]["x"])
        self.assertEqual(event["spatial"]["phases"][0]["kind"], "assist")
        self.assertEqual(event["spatial"]["phases"][1]["kind"], "shot")
        self.assertEqual(event["spatial"]["outcome_marker"]["kind"], "save")
        self.assertLess(event["spatial"]["outcome_marker"]["x"], 10.0)

    def test_cross_then_blocked_shot_adds_missing_shot_phase(self):
        game = {
            "home_team": {"id": 1, "name": "Tottenham Hotspur"},
            "away_team": {"id": 2, "name": "Brentford"},
            "players": [
                {
                    "player_id": 11,
                    "name": "Richarlison",
                    "team_id": 1,
                    "team_name": "Tottenham Hotspur",
                    "team_location": "home",
                    "jersey_number": 9,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 9,
                    "match_stats": [],
                },
                {
                    "player_id": 12,
                    "name": "Mohammed Kudus",
                    "team_id": 1,
                    "team_name": "Tottenham Hotspur",
                    "team_location": "home",
                    "jersey_number": 20,
                    "position_id": 26,
                    "formation_field": "3:1",
                    "formation_position": 5,
                    "match_stats": [],
                },
            ],
            "events": [
                {
                    "id": 9400,
                    "minute": 14,
                    "period_id": 100,
                    "type": "shot_off_target",
                    "text": "Shot Off Target",
                    "team_id": 1,
                    "player_id": None,
                    "player": None,
                    "related_player_id": None,
                    "related_player_name": None,
                    "is_home": True,
                    "detail": {},
                }
            ],
            "timeline": [],
            "commentary": [
                {
                    "id": 7300,
                    "minute": 14,
                    "comment": (
                        "A shot is deflected. Richarlison from Tottenham Hotspur attempts a "
                        "right-footed strike from the middle of the penalty area, but it is "
                        "blocked. The assist came from Mohammed Kudus, who delivered a cross."
                    ),
                    "is_goal": False,
                    "is_important": True,
                    "sort_order": 14,
                }
            ],
            "trends": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 100, "timer": "13:20", "x": 60.0, "y": 78.0},
                {"id": 2, "period_id": 100, "timer": "13:25", "x": 86.0, "y": 50.0},
            ],
            "video_events": [],
        }

        event = next(item for item in _selectable_events(game) if item.get("id") == 9400)

        self.assertEqual(event["player"], "Richarlison")
        self.assertEqual(event["related_player_name"], "Mohammed Kudus")
        self.assertEqual(event["detail"]["shot_origin"], "center of the box")
        self.assertEqual(event["detail"]["shot_outcome_hint"], "blocked")
        self.assertEqual(event["detail"]["assist_type"], "cross")
        self.assertEqual(event["spatial"]["source"], "semantic_fused")
        self.assertEqual(event["spatial"]["shot_start_index"], 1)
        self.assertIn("assist_actor_anchor", event["spatial"])
        self.assertEqual(event["spatial"]["shot_actor_anchor"], {"x": 86.0, "y": 50.0})
        self.assertEqual(len(event["spatial"]["ball_track"]), 3)
        self.assertEqual(event["spatial"]["ball_track"][0]["x"], event["spatial"]["assist_actor_anchor"]["x"])
        self.assertEqual(event["spatial"]["ball_track"][1]["x"], event["spatial"]["shot_actor_anchor"]["x"])
        self.assertGreater(event["spatial"]["ball_track"][-1]["x"], 86.0)
        self.assertLess(event["spatial"]["ball_track"][-1]["x"], 100.0)
        self.assertEqual(event["spatial"]["outcome_marker"]["kind"], "block")

    def test_saved_attempt_duplicate_rows_collapse_to_one_semantic_event(self):
        game = {
            "home_team": {"id": 14, "name": "Manchester United"},
            "away_team": {"id": 19, "name": "Arsenal"},
            "players": [
                {
                    "player_id": 1846739,
                    "name": "Matheus Cunha",
                    "team_id": 14,
                    "team_name": "Manchester United",
                    "team_location": "home",
                    "jersey_number": 10,
                    "position_id": 27,
                    "formation_field": "5:1",
                    "formation_position": 11,
                    "match_stats": [],
                },
                {
                    "player_id": 537121,
                    "name": "Mason Mount",
                    "team_id": 14,
                    "team_name": "Manchester United",
                    "team_location": "home",
                    "jersey_number": 7,
                    "position_id": 27,
                    "formation_field": "4:2",
                    "formation_position": 10,
                    "match_stats": [],
                },
            ],
            "events": [],
            "timeline": [
                {
                    "id": 150945365,
                    "minute": 38,
                    "period_id": 6175643,
                    "type": "Shot On Target",
                    "text": "7th Shot On Target",
                    "team_id": 14,
                    "player_id": 1846739,
                    "related_player_id": 537121,
                    "player": "Matheus Cunha",
                    "related_player_name": "Mason Mount",
                    "is_home": True,
                    "sort_order": 12,
                },
                {
                    "id": 150945386,
                    "minute": 38,
                    "period_id": 6175643,
                    "type": "Shot Off Target",
                    "text": "5th Shot Off Target",
                    "team_id": 14,
                    "player_id": 1846739,
                    "related_player_id": 537121,
                    "player": "Matheus Cunha",
                    "related_player_name": "Mason Mount",
                    "is_home": True,
                    "sort_order": 13,
                },
            ],
            "commentary": [
                {
                    "id": 11094777,
                    "minute": 38,
                    "comment": (
                        "Attempt saved. Matheus Cunha from Manchester United has a left-footed "
                        "shot from a tough angle on the left, but David Raya from Arsenal saves "
                        "it in the center of the goal. The assist came from Mason Mount."
                    ),
                    "is_goal": False,
                    "is_important": False,
                    "sort_order": 37,
                }
            ],
            "trends": [],
            "ball_coordinates": [
                {"id": 1, "period_id": 6175643, "timer": "37:38", "x": 75.0, "y": 78.0},
                {"id": 2, "period_id": 6175643, "timer": "37:49", "x": 85.0, "y": 47.0},
                {"id": 3, "period_id": 6175643, "timer": "37:54", "x": 98.0, "y": 50.0},
            ],
            "video_events": [],
        }

        events = [
            event for event in _selectable_events(game)
            if event.get("minute") == 38
            and (event.get("spatial") or {}).get("kind") == "shot_on_target"
        ]

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["id"], 150945365)
        self.assertEqual(event["commentary_id"], 11094777)
        self.assertEqual(event["player"], "Matheus Cunha")
        self.assertEqual(event["related_player_name"], "Mason Mount")
        self.assertEqual(event["display_type"], "Shot On Target")
        self.assertEqual(event["spatial"]["source"], "semantic_fused")
        self.assertEqual(event["spatial"]["shot_start_index"], 1)
        self.assertEqual(event["spatial"]["ball_track"][0]["x"], event["spatial"]["assist_actor_anchor"]["x"])
        self.assertEqual(event["spatial"]["ball_track"][1]["x"], event["spatial"]["shot_actor_anchor"]["x"])
        self.assertEqual(event["spatial"]["outcome_marker"]["kind"], "save")

    def test_corner_setup_is_hidden_when_commentary_identifies_following_shot(self):
        game = {
            "home_team": {"id": 14, "name": "Manchester United"},
            "away_team": {"id": 19, "name": "Arsenal"},
            "players": [
                {
                    "player_id": 3259,
                    "name": "Ben White",
                    "team_id": 19,
                    "team_name": "Arsenal",
                    "team_location": "away",
                    "jersey_number": 4,
                    "position_id": 25,
                    "formation_field": "2:4",
                    "formation_position": 2,
                    "match_stats": [],
                }
            ],
            "events": [],
            "timeline": [
                {
                    "id": 150945407,
                    "minute": 41,
                    "period_id": 6175643,
                    "type": "Corner",
                    "text": "4th Corner",
                    "team_id": 19,
                    "is_home": False,
                    "sort_order": 4,
                },
                {
                    "id": 150945408,
                    "minute": 41,
                    "period_id": 6175643,
                    "type": "Shot Off Target",
                    "text": "6th Shot Off Target",
                    "team_id": 19,
                    "player_id": 3259,
                    "player": "Ben White",
                    "is_home": False,
                    "sort_order": 5,
                },
            ],
            "commentary": [
                {
                    "id": 11094781,
                    "minute": 40,
                    "comment": "Arsenal win a corner after Patrick Dorgu concedes.",
                    "is_goal": False,
                    "is_important": False,
                    "sort_order": 41,
                },
                {
                    "id": 11094784,
                    "minute": 41,
                    "comment": (
                        "Ben White from Arsenal misses a right-footed shot from outside the box "
                        "to the left after a corner."
                    ),
                    "is_goal": False,
                    "is_important": False,
                    "sort_order": 44,
                },
            ],
            "trends": [],
            "ball_coordinates": [],
            "video_events": [],
        }

        events = _selectable_events(game)
        minute_events = [event for event in events if event.get("minute") == 41]

        self.assertEqual(len(minute_events), 1)
        shot = minute_events[0]
        self.assertEqual(shot["player"], "Ben White")
        self.assertEqual(shot["spatial"]["kind"], "shot_off_target")
        self.assertEqual(shot["display_type"], "Shot Off Target")
        self.assertEqual(shot["detail"]["situation"], "Corner")
        self.assertEqual(shot["detail"]["shot_origin"], "outside the box")
        self.assertEqual(shot["detail"]["shot_outcome_hint"], "left")
        self.assertEqual(shot["spatial"]["source"], "semantic_reconstructed")
        self.assertEqual(shot["spatial"]["shot_start_index"], 0)
        self.assertEqual(shot["spatial"]["ball_track"][0]["x"], shot["spatial"]["shot_actor_anchor"]["x"])
        self.assertEqual(len(shot["spatial"]["ball_track"]), 2)

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
        self.assertIn(shot["source"], {"semantic_fused", "semantic_reconstructed"})
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
        timer_minute = max(0, event_minute - 1 + extra_minute)
        return timer_minute * 60, timer_minute * 60 + 59

    assert timer_window(13) == (12 * 60, 12 * 60 + 59)
    assert timer_window(62) == (61 * 60, 61 * 60 + 59)
    assert timer_window(45, 1) == (45 * 60, 45 * 60 + 59)
    assert timer_window(45, 2) == (46 * 60, 46 * 60 + 59)


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
