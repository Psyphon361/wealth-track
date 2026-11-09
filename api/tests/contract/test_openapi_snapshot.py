"""The API's OpenAPI document must equal the committed snapshot.

A change to a route, a request body or a response model shows up here so it is reviewed on purpose
(and the web types checked). After an intended change run:
    cd api && .venv/bin/python -m tests.contract.update_snapshot
"""

import json

from tests.contract.update_snapshot import SNAPSHOT, UPDATE_COMMAND, current_schema, dumps


def _ops(schema: dict) -> dict:
    return {
        f"{method.upper()} {path}": op
        for path, item in schema.get("paths", {}).items()
        for method, op in item.items()
        if isinstance(op, dict)
    }


def _section(title: str, before: dict, after: dict, lines: list[str]) -> None:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    for label, keys in (("added", added), ("removed", removed), ("changed", changed)):
        for key in keys:
            lines.append(f"  {title} {label}: {key}")
    if changed and title == "schema":
        for key in changed:
            old, new = before[key].get("properties", {}), after[key].get("properties", {})
            for name in sorted(set(new) - set(old)):
                lines.append(f"    {key}.{name} added")
            for name in sorted(set(old) - set(new)):
                lines.append(f"    {key}.{name} removed")
            for name in sorted(n for n in set(old) & set(new) if old[n] != new[n]):
                lines.append(f"    {key}.{name} changed")


def compact_diff(old: dict, new: dict) -> str:
    lines: list[str] = []
    _section("operation", _ops(old), _ops(new), lines)
    _section("schema", old.get("components", {}).get("schemas", {}), new.get("components", {}).get("schemas", {}), lines)
    return "\n".join(lines) or "  (only other parts of the document differ, e.g. info or security)"


def test_openapi_matches_snapshot():
    current = current_schema()
    assert SNAPSHOT.exists(), f"No snapshot yet. Create it with: {UPDATE_COMMAND}"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if dumps(current) != SNAPSHOT.read_text(encoding="utf-8"):
        raise AssertionError(
            "The OpenAPI document no longer matches tests/contract/openapi.snapshot.json:\n"
            + compact_diff(committed, current)
            + f"\nIf the change is intended, check the web types, then run: {UPDATE_COMMAND}"
        )


def test_snapshot_is_deterministic():
    assert dumps(current_schema()) == dumps(current_schema())
