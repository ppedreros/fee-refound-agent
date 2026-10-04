"""The API's OpenAPI schema, the source of the frontend's types (SPEC-api, "API types").

`npm --prefix frontend run gen:api` runs `python -m backend.api.openapi`, which writes the schema
to `frontend/src/api/openapi.json`; openapi-typescript then turns it into `schema.d.ts`. A unit
test fails when the committed copy no longer matches the code.
"""

import json
from pathlib import Path
from typing import Any

from backend.api.main import create_app
from backend.core.settings import Settings

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"

# The schema doesn't depend on the settings; the app only needs valid ones to be built.
_PLACEHOLDER = Settings(
    _env_file=None,
    app_database_url="postgresql+psycopg://app_writer:unused@127.0.0.1:1/unused",
    agent_database_url="postgresql+psycopg://agent_reader:unused@127.0.0.1:1/unused",
    masking_salt="unused",
)


def openapi_schema() -> dict[str, Any]:
    schema: dict[str, Any] = create_app(_PLACEHOLDER).openapi()
    return schema


def main() -> None:
    text = json.dumps(openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    SCHEMA_FILE.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
