"""Commentary-first replay policy: no uncorroborated timeline milestones."""
import unittest

from goodgame.commentary_replays import commentary_simulations
from goodgame.web import _selectable_events


def fixture(*, events=None, timeline=None, commentary=None):
    return {
        "home_team": {"id": 14, "name": "Manchester United"},
        "away_team": {"id": 3, "name": "Sunderland"},
        "players": [
            {"player_id": 1, "name": "Bruno Fernandes", "team_id": 14,
             "team_location": "home", "position_id": 26},
            {"player_id": 2, "name": "Amad Diallo", "team_id": 14,
             "team_location": "home", "position_id": 26},
            {"player_id": 3, "name": "Trai Hume", "team_id": 3,
             "team_location": "away", "position_id": 25},
            {"player_id": 4, "name": "Dan Ballard", "team_id": 3,
             "team_location": "away", "position_id": 25},
        ],
        "events": events or [],
        "timeline": timeline or [],
        "commentary": commentary or [],
        "ball_coordinates": [],
    }


def replays(game):
    return commentary_simulations(game, _selectable_events(game), _selectable_events)


class CommentaryReplayTests(unittest.TestCase):
    def test_no_commentary_means_no_simulations_but_structured_data_survives(self):
        game = fixture(events=[
            {"id": 10, "minute": 45, "team_id": 14, "type": "Shot On Target",
             "text": "5th Shot On Target", "player_id": 1},
        ])
        self.assertEqual(replays(game), [])
        self.assertEqual(game["events"][0]["id"], 10)

    def test_only_supported_shot_kept_not_unmatched_statistical_rows(self):
        game = fixture(timeline=[
            {"id": 11, "minute": 45, "team_id": 14, "player_id": 1,
             "type": "Shot On Target", "text": "5th Shot On Target"},
            {"id": 12, "minute": 45, "team_id": 3,
             "type": "Corner", "text": "7th Corner"},
            {"id": 13, "minute": 45, "team_id": 3,
             "type": "Shot Off Target", "text": "6th Shot Off Target"},
        ], commentary=[
            {"id": 1001, "minute": 45,
             "comment": "Bruno Fernandes takes a right-footed shot which is blocked.",
             "sort_order": 1},
        ])
        rows = replays(game)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 11)
        self.assertEqual(rows[0]["commentary_id"], 1001)
        self.assertEqual(rows[0]["spatial"]["kind"], "blocked_shot")

    def test_unmatched_commentary_shot_generates_selectable_replay(self):
        game = fixture(commentary=[
            {"id": 1002, "minute": 30, "sort_order": 22,
             "comment": "Bruno Fernandes takes a right-footed shot from outside the box but misses wide."},
        ])
        rows = replays(game)
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["id"], 0)
        self.assertEqual(rows[0]["commentary_id"], 1002)
        self.assertEqual(rows[0]["player_id"], 1)
        self.assertEqual(rows[0]["team_id"], 14)
        self.assertEqual(rows[0]["spatial"]["kind"], "shot_off_target")
        self.assertTrue(rows[0]["spatial"]["ball_path"])

    def test_two_same_minute_comments_do_not_reuse_each_others_clock(self):
        game = fixture(commentary=[
            {"id": 1004, "minute": 45, "extra_minute": 3, "sort_order": 49,
             "comment": "Amad Diallo takes a shot but misses wide."},
            {"id": 1003, "minute": 45, "extra_minute": 1, "sort_order": 45,
             "comment": "Bruno Fernandes takes a shot but misses wide."},
        ])
        rows = replays(game)
        self.assertEqual([x["commentary_id"] for x in rows], [1003, 1004])
        self.assertEqual([x["extra_minute"] for x in rows], [1, 3])
        self.assertEqual([x["player_id"] for x in rows], [1, 2])

    def test_var_with_ordered_commentary_is_one_decision_not_fake_ball(self):
        game = fixture(
            timeline=[{"id": 2001, "minute": 45, "team_id": 3,
                       "player_id": 3, "type": "Penalty Cancelled",
                       "text": "Penalty disallowed"}],
            commentary=[
                {"id": 2002, "minute": 45, "extra_minute": 3,
                 "sort_order": 48,
                 "comment": "Penalty awarded to Sunderland! Trai Hume is brought down inside the box."},
                {"id": 2003, "minute": 45, "extra_minute": 5,
                 "sort_order": 49,
                 "comment": "Bruno Fernandes of Manchester United has given away a penalty."},
                {"id": 2004, "minute": 45, "extra_minute": 7,
                 "sort_order": 50,
                 "comment": "VAR Review: Potential Penalty for Sunderland."},
            ],
        )
        rows = replays(game)
        decision = next(x for x in rows if x["id"] == 2001)
        self.assertEqual(decision["spatial"]["source"], "decision_only")
        self.assertEqual(decision["spatial"]["ball_track"], [])
        self.assertEqual(decision["detail"]["commentary_step_ids"], [2002, 2003, 2004])
        self.assertEqual(
            [p["kind"] for p in decision["detail"]["event_sequence"]],
            ["award", "conceded", "review", "decision"],
        )
        self.assertEqual(len(rows), 1)

    def test_awarded_corner_belongs_to_recipient_not_named_conceding_defender(self):
        game = fixture(commentary=[
            {"id": 1020, "minute": 25, "sort_order": 8,
             "comment": (
                 "Corner awarded to Manchester United after a defensive "
                 "play by Trai Hume of Sunderland."
             )},
        ])
        rows = replays(game)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spatial"]["kind"], "corner")
        self.assertEqual(rows[0]["team_id"], 14)
        self.assertIsNone(rows[0].get("player_id"))
        self.assertEqual(rows[0]["commentary_id"], 1020)

    def test_unknown_team_commentary_does_not_invent_a_replay(self):
        game = fixture(commentary=[
            {"id": 1005, "minute": 37, "sort_order": 1,
             "comment": "A shot is saved."},
        ])
        self.assertEqual(replays(game), [])


if __name__ == "__main__":
    unittest.main()
