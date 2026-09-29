"""Select the frontend-serving repository."""

from __future__ import annotations

import os
from typing import Any

from goodgame.serving.bigquery_repository import BigQueryServingRepository
from goodgame.serving.demo_repository import DemoServingRepository


def create_serving_repository() -> Any:
    mode = os.environ.get("DATA_MODE", "gcp").strip().casefold()
    if mode == "gcp":
        return BigQueryServingRepository()
    if mode == "demo":
        return DemoServingRepository()
    raise ValueError("DATA_MODE must be either 'gcp' or 'demo'")
