"""Authenticated HTTP client for Sportmonks Football API v3."""

import os
from typing import Any, Mapping

import requests


class SportmonksError(RuntimeError):
    """Raised for Sportmonks authentication, HTTP, or response errors."""


class SportmonksClient:
    def __init__(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
        base_url: str = "https://api.sportmonks.com/v3/football",
        timeout: float = 20.0,
    ) -> None:
        self.token = (token or os.environ.get("SPORTMONKS_API_TOKEN", "")).strip()
        if not self.token:
            raise ValueError(
                "Set SPORTMONKS_API_TOKEN in your environment before selecting Sportmonks"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                params=params,
                headers={"Authorization": self.token, "Accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code in {401, 403}:
                message = (
                    f"Sportmonks rejected the request (HTTP {status_code}). "
                    "Check that SPORTMONKS_API_TOKEN is valid and your plan includes this data."
                )
            else:
                message = f"Sportmonks request failed for {url}: {error}"
            raise SportmonksError(message) from error

        if not isinstance(payload, dict):
            raise SportmonksError(f"Sportmonks returned a non-object response for {url}")
        if payload.get("errors"):
            raise SportmonksError(f"Sportmonks API error for {path}: {payload['errors']}")
        return payload

    def get_all(self, path: str, params: Mapping[str, str | int] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        base_params = dict(params or {})
        while page <= 1000:
            page_params = {**base_params, "page": page}
            payload = self.get_json(path, page_params)
            data = payload.get("data", [])
            if isinstance(data, dict):
                rows.append(data)
            elif isinstance(data, list):
                rows.extend(row for row in data if isinstance(row, dict))
            else:
                raise SportmonksError(f"Unexpected data shape from Sportmonks endpoint {path}")

            pagination = payload.get("pagination") or payload.get("meta", {}).get("pagination", {})
            if not isinstance(pagination, dict) or not pagination.get("has_more"):
                break
            page += 1
        else:
            raise SportmonksError(f"Pagination limit reached for Sportmonks endpoint {path}")
        return rows