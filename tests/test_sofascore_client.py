import unittest
from unittest.mock import Mock

import requests

from goodgame.ingestion.sofascore.client import SofaScoreClient, SofaScoreError


class SofaScoreClientTests(unittest.TestCase):
    def test_get_json_uses_base_url_timeout_and_params(self):
        session = Mock(spec=requests.Session)
        response = Mock()
        response.json.return_value = {"events": []}
        session.get.return_value = response
        client = SofaScoreClient(base_url="https://example.test/api/v1/", timeout=8, session=session)

        result = client.get_json("/events", params={"page": 2})

        self.assertEqual(result, {"events": []})
        session.get.assert_called_once_with(
            "https://example.test/api/v1/events", params={"page": 2}, timeout=8
        )

    def test_get_json_wraps_http_errors(self):
        session = Mock(spec=requests.Session)
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        session.get.return_value = response
        client = SofaScoreClient(session=session)

        with self.assertRaisesRegex(SofaScoreError, "403 Forbidden"):
            client.get_json("event/1")


if __name__ == "__main__":
    unittest.main()