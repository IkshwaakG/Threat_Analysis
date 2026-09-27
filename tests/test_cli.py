import io
import unittest

from goodgame.cli import run_cli
from goodgame.models.event import Event
from goodgame.models.match import Match


class FakeProvider:
    def __init__(self):
        self.listed_contexts = []
        self.listed_matches = []
        self.match_ids = []

    def list_competitions(self):
        return [
            {"competition_id": 9, "season_id": 281, "competition_name": "1. Bundesliga", "season_name": "2023/2024"},
            {"competition_id": 9, "season_id": 27, "competition_name": "1. Bundesliga", "season_name": "2015/2016"},
        ]

    def list_matches(self, competition_id, season_id):
        self.listed_contexts.append((competition_id, season_id))
        self.listed_matches.append((competition_id, season_id))
        return [
            {
                "match_id": 3895232,
                "match_date": "2024-02-10",
                "home_team": "Bayer Leverkusen",
                "away_team": "Bayern Munich",
                "home_score": 3,
                "away_score": 0,
            }
        ]

    def get_match(self, match_id):
        self.match_ids.append(match_id)
        return Match.from_statsbomb_payload(
            {
                "match_id": match_id,
                "home_team_id": 904,
                "home_team": "Bayer Leverkusen",
                "away_team_id": 169,
                "away_team": "Bayern Munich",
                "home_score": 3,
                "away_score": 0,
                "match_status": "available",
                "competition_id": 9,
                "season_id": 281,
            }
        )

    def get_events(self, match_id):
        return [
            Event(
                id="goal-1",
                minute=18,
                incident_type="goal",
                text="Goal by Josip Stanisic",
                is_home=True,
                player="Josip Stanisic",
            )
        ]

    def get_lineups(self, match_id):
        return {}

    def get_shot_map(self, match_id):
        return [{"shot_statsbomb_xg": 0.42}]

    def get_team_statistics(self, team):
        return {
            "competition_id": 9,
            "season_id": 281,
            "team_name": team,
            "matches_played": 1,
            "goals_for": 2,
            "position": 1,
            "standing_teams": 18,
            "points": 3,
            "goal_difference": 2,
        }

    def get_player_statistics(self, player, team=None):
        return {"player_name": player, "team_name": team or "Bayer Leverkusen", "goals": 1}

    def get_player_statistics_all_leagues(self, season_name, player, team=None):
        return {
            "player_id": 100,
            "player_name": player,
            "team_name": team or "Bayer Leverkusen",
            "season_name": season_name,
            "competitions": ["1. Bundesliga", "Champions League"],
            "competition_count": 2,
            "appearances": 32,
            "goals": 11,
        }


class CliTests(unittest.TestCase):
    def test_default_flow_selects_competition_season_then_match(self):
        provider = FakeProvider()
        output = io.StringIO()
        choices = iter(["1", "1"])

        exit_code = run_cli([], provider=provider, input_fn=lambda _: next(choices), output=output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.listed_contexts, [(9, 281)])
        self.assertEqual(provider.match_ids, [3895232])
        self.assertIn("Bayer Leverkusen 3-0 Bayern Munich", output.getvalue())

    def test_season_name_and_team_filter_find_match(self):
        provider = FakeProvider()
        output = io.StringIO()
        exit_code = run_cli(
            ["--competition-id", "9", "--season", "2023/24", "--teams", "Bayern Munich", "Bayer Leverkusen"],
            provider=provider,
            input_fn=lambda _: "1",
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.listed_contexts, [(9, 281)])
        self.assertIn("ID 3895232", output.getvalue())

    def test_direct_match_id_skips_catalog_selection(self):
        provider = FakeProvider()
        output = io.StringIO()

        exit_code = run_cli(
            ["--match-id", "3895232"], provider=provider, output=output
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.listed_contexts, [])
        self.assertEqual(provider.match_ids, [3895232])

    def test_team_and_player_stats_are_cli_actions(self):
        provider = FakeProvider()
        team_output = io.StringIO()
        player_output = io.StringIO()

        team_code = run_cli(
            ["--competition-id", "9", "--season-id", "281", "--team-stats", "Bayer Leverkusen"],
            provider=provider,
            output=team_output,
        )
        player_code = run_cli(
            ["--competition-id", "9", "--season-id", "281", "--player-stats", "Florian Wirtz", "--player-team", "Bayer Leverkusen"],
            provider=provider,
            output=player_output,
        )

        self.assertEqual(team_code, 0)
        self.assertIn("Goals For: 2", team_output.getvalue())
        self.assertEqual(player_code, 0)
        self.assertIn("Goals: 1", player_output.getvalue())

    def test_team_stats_prompt_for_competition_and_show_standing(self):
        provider = FakeProvider()
        output = io.StringIO()

        exit_code = run_cli(
            ["--team-stats", "Bayer Leverkusen"],
            provider=provider,
            input_fn=lambda _: "1",
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Competition: 1. Bundesliga (2023/2024)", output.getvalue())
        self.assertIn("Current standing: 1st of 18", output.getvalue())

    def test_team_stats_filter_out_competitions_where_team_does_not_play(self):
        provider = FakeProvider()
        output = io.StringIO()

        exit_code = run_cli(
            ["--team-stats", "Manchester United", "--season", "2023/24"],
            provider=provider,
            input_fn=lambda _: self.fail("There should be no unrelated competition prompt"),
            output=output,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Manchester United", output.getvalue())
        self.assertIn("not found in any accessible competition/season", output.getvalue())
        self.assertIn("Competitions checked: 1. Bundesliga", output.getvalue())

    def test_player_stats_default_to_all_leagues_without_scope_prompt(self):
        provider = FakeProvider()
        output = io.StringIO()

        exit_code = run_cli(
            ["--player-stats", "Florian Wirtz"],
            provider=provider,
            input_fn=lambda _: "1",
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertNotIn("Select player stats scope", output.getvalue())
        self.assertIn("Season: 2023/2024 across 2 competitions", output.getvalue())
        self.assertIn("Competitions: 1. Bundesliga, Champions League", output.getvalue())
        self.assertIn("Goals: 11", output.getvalue())

    def test_all_leagues_can_be_selected_without_prompting(self):
        provider = FakeProvider()
        output = io.StringIO()

        exit_code = run_cli(
            [
                "--all-leagues",
                "--player-stats",
                "Florian Wirtz",
                "--season",
                "2023/24",
            ],
            provider=provider,
            output=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Season: 2023/2024 across 2 competitions", output.getvalue())
        self.assertIn("Goals: 11", output.getvalue())


if __name__ == "__main__":
    unittest.main()
