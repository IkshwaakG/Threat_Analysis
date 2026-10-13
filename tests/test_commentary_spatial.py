"""Narrative-owned spatial actors, corner context, and supporting coordinates."""
import unittest

from goodgame.commentary_replays import commentary_simulations
from goodgame.commentary_spatial import _zone
from goodgame.web import _selectable_events


def game_with(*, commentary=None, events=None, ball_coordinates=None):
    return {
        "home_team": {"id": 14, "name": "Manchester United"},
        "away_team": {"id": 3, "name": "Sunderland"},
        "players": [
            {"player_id": 100, "name": "Bruno Fernandes", "team_id": 14,
             "team_location": "home", "position_id": 26, "formation_field": "3:3"},
            {"player_id": 101, "name": "Mason Mount", "team_id": 14,
             "team_location": "home", "position_id": 27, "formation_field": "4:2"},
            {"player_id": 102, "name": "Amad Diallo", "team_id": 14,
             "team_location": "home", "position_id": 26, "formation_field": "3:1"},
            {"player_id": 200, "name": "Robin Roefs", "team_id": 3,
             "team_location": "away", "position_id": 24, "formation_field": "1:1"},
            {"player_id": 201, "name": "Dan Ballard", "team_id": 3,
             "team_location": "away", "position_id": 25, "formation_field": "2:2"},
            {"player_id": 202, "name": "Granit Xhaka", "team_id": 3,
             "team_location": "away", "position_id": 26, "formation_field": "3:2"},
            {"player_id": 203, "name": "Trai Hume", "team_id": 3,
             "team_location": "away", "position_id": 25, "formation_field": "2:4"},
        ],
        "events": events or [], "timeline": [],
        "commentary": commentary or [], "ball_coordinates": ball_coordinates or [],
    }


def replays(game):
    return commentary_simulations(game, _selectable_events(game), _selectable_events)


class CommentarySpatialTests(unittest.TestCase):
    def test_outer_penalty_area_is_distinct_from_small_six_yard_area(self):
        # Standard 105m pitch: large box depth 16.5m (~15.7%),
        # goal area depth 5.5m (~5.2%). Coordinates must preserve this.
        large = _zone("from inside the penalty area", 100)
        small = _zone("from the right side of the six-yard box", 100)
        close = _zone("close-range header", 0)
        self.assertIsNotNone(large)
        self.assertIsNotNone(small)
        self.assertIsNotNone(close)
        self.assertGreater(large["x"], 84.0)
        self.assertLess(large["x"], 95.0)
        self.assertGreater(small["x"], 94.0)
        self.assertLess(small["x"], 100.0)
        self.assertGreater(small["y"], 50.0)
        self.assertLess(small["y"], 63.5)
        self.assertGreater(close["x"], 5.0)
        self.assertLess(close["x"], 15.7)

    def test_shooter_zone_is_distinct_from_assisters_right_wing(self):
        game = game_with(commentary=[
            {"id": 111, "minute": 25, "sort_order": 11,
             "comment": (
                 "Bruno Fernandes of Manchester United takes a left-footed "
                 "shot from the center of the box; assisted by Mason Mount "
                 "with a cross from the right wing. The shot is saved by Robin Roefs."
             )},
        ])
        attempts = replays(game)
        self.assertEqual(len(attempts), 1)
        attempt = attempts[0]
        actors = {p["role"]: p for p in attempt["spatial"]["actor_positions"]}
        self.assertEqual(actors["shooter"]["player_id"], 100)
        self.assertEqual(actors["assister"]["player_id"], 101)
        self.assertEqual(actors["goalkeeper"]["player_id"], 200)
        self.assertAlmostEqual(actors["shooter"]["x"], 85, delta=4)
        self.assertAlmostEqual(actors["shooter"]["y"], 50, delta=4)
        self.assertGreater(actors["assister"]["y"], actors["shooter"]["y"])
        self.assertNotEqual(actors["goalkeeper"]["x"], actors["shooter"]["x"])
        self.assertEqual(attempt["spatial"]["actor_placement_policy"], "commentary_first")
        self.assertEqual(attempt["spatial"]["ball_track"][attempt["spatial"]["shot_start_index"]]["y"], actors["shooter"]["y"])

    def test_corner_commentary_links_cross_and_header_on_attacking_end(self):
        game = game_with(commentary=[
            {"id": 300, "minute": 45, "extra_minute": 7, "sort_order": 60,
             "comment": "Corner awarded to Sunderland after a defensive play by Amad Diallo."},
            {"id": 301, "minute": 45, "extra_minute": 7, "sort_order": 61,
             "comment": (
                 "Dan Ballard of Sunderland misses a header from the center "
                 "of the box to the left after a corner, assisted by Granit Xhaka "
                 "with a cross."
             )},
        ])
        rows = replays(game)
        corner = next(p for p in rows if p["spatial"]["kind"] == "corner")
        actors = {p["role"]: p for p in corner["spatial"]["actor_positions"]}
        self.assertEqual(corner["team_id"], 3)
        self.assertEqual(corner["detail"]["follow_up_commentary_id"], 301)
        self.assertEqual(actors["crosser"]["player_id"], 202)
        self.assertNotIn("corner_taker", actors)
        self.assertEqual(actors["receiver"]["player_id"], 201)
        self.assertNotIn(102, [p["player_id"] for p in corner["spatial"]["actor_positions"]])
        track = corner["spatial"]["ball_track"]
        self.assertEqual(len(track), 3)
        self.assertLess(track[0]["x"], 5)
        self.assertAlmostEqual(track[1]["x"], 15, delta=4)
        self.assertEqual(corner["spatial"]["shot_start_index"], 1)
        self.assertEqual([p["kind"] for p in corner["detail"]["event_sequence"]],
                         ["corner", "delivery", "attempt"])
        self.assertEqual(actors["receiver"]["position_source"], "commentary_zone")

    def test_timed_ball_coordinate_support_chooses_corner_side_only(self):
        game = game_with(commentary=[
            {"id": 302, "minute": 25, "sort_order": 15,
             "comment": "Corner awarded to Sunderland."},
        ], ball_coordinates=[
            {"id": 1, "timer": "24:20", "x": .02, "y": .91},
            {"id": 2, "timer": "24:25", "x": .02, "y": .91},
            {"id": 3, "timer": "24:30", "x": .04, "y": .88},
            {"id": 4, "timer": "24:35", "x": .05, "y": .82},
        ])
        result = replays(game)[0]
        self.assertEqual(result["spatial"]["kind"], "corner")
        self.assertEqual(result["spatial"]["corner_side_source"], "time_matched_ball_coordinates")
        self.assertGreater(result["spatial"]["ball_track"][0]["y"], 95)
        self.assertEqual(result["spatial"]["actor_positions"] if "actor_positions" in result["spatial"] else [], [])

    def test_shooter_zone_may_be_refined_but_not_assigned_ball_endpoint(self):
        game = game_with(commentary=[
            {"id": 350, "minute": 22, "sort_order": 3,
             "comment": "Bruno Fernandes shoots from the right side of the box and misses wide."},
        ], ball_coordinates=[
            {"id": 1, "timer": "21:05", "x": .82, "y": .66},
            {"id": 2, "timer": "21:10", "x": .82, "y": .66},
            {"id": 3, "timer": "21:20", "x": .99, "y": .51},
        ])
        attempt = replays(game)[0]
        shooter = next(p for p in attempt["spatial"]["actor_positions"] if p["role"] == "shooter")
        self.assertLess(shooter["x"], 92)
        self.assertGreater(shooter["y"], 62)
        self.assertEqual(shooter["position_source"], "commentary_zone_coordinate_refined")
        self.assertNotEqual(shooter["x"], 99)

    def test_foul_without_ball_samples_has_no_traversal_or_player(self):
        game = game_with(commentary=[
            {"id": 402, "minute": 76, "sort_order": 2,
             "comment": "Matheus Cunha earned a free kick in an offensive position."},
        ])
        # Add a named participant but NO tracking. Formation fallback is forbidden.
        game["players"].append({
            "player_id": 105, "name": "Matheus Cunha", "team_id": 14,
            "team_location": "home", "position_id": 27,
        })
        rows = replays(game)
        foul = next(p for p in rows if p["spatial"]["kind"] == "foul")
        self.assertEqual(foul["spatial"]["source"], "foul_position_only")
        self.assertEqual(foul["spatial"]["ball_track"], [])
        self.assertIsNone(foul["spatial"]["ball_path"])
        self.assertIsNone(foul["spatial"]["anchor"])
        self.assertEqual(foul["spatial"]["actor_positions"], [])
        self.assertIsNone(foul["ball_path"])

    def test_foul_shows_only_fouled_player_at_first_ball_sample_of_minute(self):
        game = game_with(commentary=[
            {"id": 402, "minute": 34, "sort_order": 2,
             "comment": "Trai Hume fouls Mason Mount on the right wing; free kick to Manchester United."},
        ], ball_coordinates=[
            # 34' displayed -> 33:00–33:59. Previous-minute point must not
            # determine the fouled player's position.
            {"id": 1, "timer": "32:55", "x": .8, "y": .7},
            {"id": 2, "timer": "33:08", "x": .72, "y": .35},
            {"id": 3, "timer": "33:13", "x": .73, "y": .4},
            {"id": 4, "timer": "33:18", "x": .71, "y": .45},
        ])
        foul = replays(game)[0]
        self.assertEqual(foul["spatial"]["ball_track"], [])
        self.assertIsNone(foul["spatial"]["ball_path"])
        positions = foul["spatial"]["actor_positions"]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["player_id"], 101)  # fouled player
        self.assertEqual((positions[0]["x"], positions[0]["y"]), (72, 35))
        self.assertEqual(
            positions[0]["position_source"],
            "minute_ball_sample_context_not_player_tracking",
        )

    def test_outer_penalty_box_and_close_range_header_away_from_midfield(self):
        game = game_with(commentary=[
            {"id": 501, "minute": 85, "sort_order": 18,
             "comment": (
                 "Missed opportunity! Bruno Fernandes of Manchester United "
                 "has a close-range header that went off target."
             )},
        ])
        row = replays(game)[0]
        scorer = next(a for a in row["spatial"]["actor_positions"]
                      if a["role"] == "shooter")
        self.assertLess(scorer["x"], 12)  # United attacks left in 2H
        self.assertAlmostEqual(scorer["y"], 50, delta=4)
        self.assertGreater(scorer["x"], 5)

    def test_header_following_corner_places_crosser_near_wing_not_midfield(self):
        game = game_with(commentary=[
            {"id": 600, "minute": 84, "sort_order": 1,
             "comment": "Corner awarded to Manchester United after Lutsharel Geertruida cleared the ball."},
            {"id": 601, "minute": 85, "sort_order": 2,
             "comment": (
                 "Missed opportunity! Matheus Cunha of Manchester United had "
                 "a close-range header that went off target. The assist came from "
                 "Bruno Fernandes, who delivered a cross following a corner kick."
             )},
        ])
        game["players"].append({
            "player_id": 106, "name": "Matheus Cunha", "team_id": 14,
            "team_location": "home", "position_id": 27,
        })
        rows = replays(game)
        header = next(r for r in rows if r["spatial"]["kind"] == "shot_off_target")
        header_actors = {a["role"]: a for a in header["spatial"]["actor_positions"]}
        self.assertLess(header_actors["shooter"]["x"], 12)
        self.assertLess(header_actors["assister"]["x"], 20)
        self.assertGreater(abs(header_actors["assister"]["y"] - 50), 25)
        self.assertEqual(header["spatial"]["actor_placement_policy"], "commentary_first")

    def test_offside_still_places_mentioned_player_from_zone(self):
        game = game_with(commentary=[
            {"id": 401, "minute": 33, "sort_order": 1,
             "comment": "Offside against Manchester United, Bruno Fernandes is caught offside outside the penalty area."},
        ])
        offside = replays(game)[0]
        self.assertIn(100, [a["player_id"] for a in offside["spatial"]["actor_positions"]])


if __name__ == "__main__":
    unittest.main()

# CI verify final physical penalty-box and foul geometry.
