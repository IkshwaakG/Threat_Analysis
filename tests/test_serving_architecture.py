import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServingArchitectureTests(unittest.TestCase):
    def test_web_serving_does_not_import_provider_clients(self):
        web = (ROOT / "goodgame" / "web.py").read_text()
        self.assertNotIn("sportmonks", web.casefold())
        self.assertNotIn("statsbomb", web.casefold())

    def test_serving_repository_reads_core_only(self):
        serving = (ROOT / "goodgame" / "serving" / "bigquery_repository.py").read_text()
        self.assertNotIn("RAW_DATASET", serving)
        self.assertNotIn("_raw_table(", serving)
        self.assertNotIn("football_raw", serving)
        self.assertIn('self._table("fixture_ball_coordinates")', serving)
        self.assertIn('self._table("fixture_advanced")', serving)
        self.assertIn('self._table("fixture_videos")', serving)
        self.assertIn('"video_reference": video_reference', serving)
        self.assertIn('self._table("fixture_participants")', serving)
        self.assertIn('self._table("fixture_lineups")', serving)
        self.assertIn('"ball_coordinates": ball_coordinates', serving)


if __name__ == "__main__":
    unittest.main()
