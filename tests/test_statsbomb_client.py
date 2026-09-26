import os
import unittest
from unittest.mock import patch

from goodgame.ingestion.statsbomb.client import StatsBombClient


class AuthenticatedApi:
    def __init__(self):
        self.calls = []

    def competitions(self, creds=None):
        self.calls.append(("competitions", creds))
        return []

    def matches(self, competition_id, season_id, creds=None):
        self.calls.append(("matches", creds))
        return []

    def events(self, match_id, creds=None):
        self.calls.append(("events", creds))
        return []

    def lineups(self, match_id, creds=None):
        self.calls.append(("lineups", creds))
        return {}


class StatsBombClientTests(unittest.TestCase):
    def test_environment_credentials_are_passed_to_each_api_call(self):
        api = AuthenticatedApi()
        with patch.dict(
            os.environ,
            {"SB_USERNAME": "analyst@example.com", "SB_PASSWORD": "secret-value"},
            clear=True,
        ):
            client = StatsBombClient(api=api)
            client.get_competitions()
            client.get_matches(9, 318)
            client.get_events(123)
            client.get_lineups(123)

        expected_credentials = {"user": "analyst@example.com", "passwd": "secret-value"}
        self.assertEqual(
            api.calls,
            [
                ("competitions", expected_credentials),
                ("matches", expected_credentials),
                ("events", expected_credentials),
                ("lineups", expected_credentials),
            ],
        )

    def test_partial_environment_credentials_are_rejected(self):
        with patch.dict(os.environ, {"SB_USERNAME": "analyst@example.com"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Set both SB_USERNAME and SB_PASSWORD"):
                StatsBombClient(api=AuthenticatedApi())

    def test_explicit_credentials_require_username_and_password(self):
        with self.assertRaisesRegex(ValueError, "require both"):
            StatsBombClient(api=AuthenticatedApi(), creds={"user": "analyst@example.com"})


if __name__ == "__main__":
    unittest.main()