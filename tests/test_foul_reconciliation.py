"""One playable infringement; two provider perspectives retained as evidence."""
import unittest

from goodgame.foul_reconciliation import reconcile_fouls


def foul(identifier, commentary_id, player_id, team_id, minute=27,
         extra_minute=None, sort_order=None):
    return {
        "id": identifier,
        "commentary_id": commentary_id,
        "minute": minute,
        "extra_minute": extra_minute,
        "sort_order": sort_order,
        "player_id": player_id,
        "team_id": team_id,
        "player": {1: "Home Player", 2: "Away Player"}.get(player_id),
        "spatial": {"kind": "foul", "ball_track": []},
        "detail": {"event_sequence": [{"kind": "foul", "label": "Foul"}]},
    }


def data(comments):
    return {
        "players": [
            {"player_id": 1, "name": "Home Player", "team_id": 14},
            {"player_id": 2, "name": "Away Player", "team_id": 3},
        ],
        "commentary": comments,
    }


class FoulIncidentTests(unittest.TestCase):
    def test_same_commentary_foul_committed_and_won_is_one_incident(self):
        game = data([{"id": 101, "minute": 27, "sort_order": 9,
                      "comment": "Away Player fouls Home Player."}])
        result = reconcile_fouls([
            foul(1, 101, 2, 3), foul(2, 101, 1, 14),
        ], game)
        self.assertEqual(len(result), 1)
        incident = result[0]
        self.assertEqual(incident["player_id"], 1)
        self.assertEqual(incident["team_id"], 14)
        self.assertEqual(incident["detail"]["foul_victim_name"], "Home Player")
        self.assertEqual(incident["detail"]["foul_offender_name"], "Away Player")
        self.assertEqual(set(incident["detail"]["foul_event_ids"]), {1, 2})
        self.assertEqual([p["kind"] for p in incident["detail"]["event_sequence"]],
                         ["foul", "free_kick"])

    def test_adjacent_opposing_commit_and_won_comments_are_one_incident(self):
        game = data([
            {"id": 102, "minute": 27, "sort_order": 40,
             "comment": "Away Player commits a foul."},
            {"id": 103, "minute": 27, "sort_order": 41,
             "comment": "Home Player wins a free kick."},
        ])
        rows = reconcile_fouls([
            foul(3, 102, 2, 3), foul(4, 103, 1, 14),
        ], game)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_id"], 1)
        self.assertEqual(set(rows[0]["detail"]["foul_commentary_ids"]), {102, 103})
        self.assertEqual(rows[0]["commentary_id"], 103)

    def test_earned_free_kick_is_recognized_as_foul_won(self):
        game = data([
            {"id": 120, "minute": 27, "sort_order": 40,
             "comment": "Away Player fouls Home Player."},
            {"id": 121, "minute": 27, "sort_order": 41,
             "comment": "Home Player earned a free kick in the defensive half."},
        ])
        merged = reconcile_fouls([
            foul(20, 120, 2, 3), foul(21, 121, 1, 14),
        ], game)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["commentary_id"], 121)
        self.assertEqual(merged[0]["detail"]["foul_victim_id"], 1)
        self.assertEqual(merged[0]["detail"]["foul_offender_id"], 2)

    def test_separate_fouls_in_one_minute_not_merged(self):
        game = data([
            {"id": 104, "minute": 27, "sort_order": 40,
             "comment": "Away Player commits a foul."},
            {"id": 105, "minute": 27, "sort_order": 43,
             "comment": "Home Player wins a free kick."},
        ])
        self.assertEqual(len(reconcile_fouls([
            foul(5, 104, 2, 3), foul(6, 105, 1, 14),
        ], game)), 2)

    def test_distinct_stoppage_clocks_not_merged(self):
        game = data([{"id": 106, "minute": 45, "sort_order": 6,
                      "comment": "Away Player fouls Home Player."}])
        self.assertEqual(len(reconcile_fouls([
            foul(7, 106, 2, 3, minute=45, extra_minute=1),
            foul(8, 106, 1, 14, minute=45, extra_minute=4),
        ], game)), 2)

    def test_same_minute_adjacent_but_same_side_not_merged(self):
        game = data([
            {"id": 107, "minute": 27, "sort_order": 11,
             "comment": "Home Player wins a free kick."},
            {"id": 108, "minute": 27, "sort_order": 12,
             "comment": "Home Player wins a free kick."},
        ])
        self.assertEqual(len(reconcile_fouls([
            foul(9, 107, 1, 14), foul(10, 108, 1, 14),
        ], game)), 2)


if __name__ == "__main__":
    unittest.main()

# CI only: validate committed/won fouls and location confidence.
