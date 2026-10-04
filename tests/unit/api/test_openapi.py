"""The frontend's API types come from the backend's OpenAPI schema (SPEC-api, "API types"). The
committed copy must match the code, or the UI is typed against an API that no longer exists."""

import json
from pathlib import Path
from typing import get_args

from backend.api.openapi import SCHEMA_FILE, openapi_schema
from backend.api.schemas import CaseStatus, Topic
from backend.db.models import CASE_STATUSES, TOPICS


def test_the_committed_schema_matches_the_api() -> None:
    committed = json.loads(Path(SCHEMA_FILE).read_text(encoding="utf-8"))

    assert committed == openapi_schema(), "Run `npm --prefix frontend run gen:api`."


def test_the_case_view_is_in_the_schema() -> None:
    schemas = openapi_schema()["components"]["schemas"]

    assert {"CaseView", "QueuePage", "DecisionRequest", "DecisionResult"} <= schemas.keys()


def test_the_closed_sets_match_the_database() -> None:
    assert get_args(CaseStatus.__value__) == CASE_STATUSES
    assert get_args(Topic.__value__) == TOPICS
