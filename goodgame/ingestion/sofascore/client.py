"""Small, reusable HTTP client for SofaScore's public API."""

from typing import Any, Mapping

import requests


class SofaScoreError(RuntimeError):
    """Raised when SofaScore returns an unsuccessful or invalid response."""


class SofaScoreClient:
    def __init__(
        self,
        base_url: str = "https://www.sofascore.com/api/v1",
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 GoodGame/0.1"})

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise SofaScoreError(f"SofaScore request failed for {url}: {error}") from error

        if not isinstance(payload, dict):
            raise SofaScoreError(f"SofaScore returned a non-object response for {url}")
        return payload