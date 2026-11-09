"""Regenerate the committed OpenAPI snapshot.

Run after an intended API change:  cd api && .venv/bin/python -m tests.contract.update_snapshot
"""

import json
import os
from pathlib import Path

# Importing the app never connects (the engine is lazy); this is only a safety net.
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:1/dummy")

SNAPSHOT = Path(__file__).with_name("openapi.snapshot.json")
UPDATE_COMMAND = "cd api && .venv/bin/python -m tests.contract.update_snapshot"


def current_schema() -> dict:
    from app.main import app

    app.openapi_schema = None  # never reuse a cached schema
    return json.loads(json.dumps(app.openapi()))


def dumps(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    SNAPSHOT.write_text(dumps(current_schema()), encoding="utf-8")
    print(f"Wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
