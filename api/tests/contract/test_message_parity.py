"""Validation wording must be identical in the API and the web forms (AGENTS.md rule 3).

Forward: every UPPERCASE string constant in api/app/schemas/*.py appears verbatim in the web source
(web/components, web/lib) unless it is on API_ONLY with a reason.
Reverse: every exported `*_ERROR|*_MESSAGE|*_DESCRIPTION` string constant in the listed web files
equals the API constant of the same name unless it is on WEB_ONLY with a reason.
"""

import ast
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2]
WEB = API.parent / "web"

# API constants the web never repeats: the API renders them (toast text) or the web shows API text.
API_ONLY = {
    "SELL_PART_REFUSED_MESSAGE": "refused on the sell path; the web renders the API's toast",
    "SELL_PART_REFUSED_DESCRIPTION": "refused on the sell path; the web renders the API's toast",
    "CASH_NAME_LENGTH_ERROR": "cash account name length is checked in the API; the web shows the API text",
    "SIP_INACTIVE_SCHEME_ERROR": "needs the fund master; only the API can know and renders it",
    "SIP_SKIP_NOT_UPCOMING_ERROR": "depends on SIP state; the web only shows the API text",
    "SIP_NO_INSTALMENT_ERROR": "depends on SIP state; the web only shows the API text",
    "SIP_HOLDING_MISMATCH_ERROR": "needs the stored holding; only the API can know and renders it",
}
# Templated / computed API messages (f-strings, concatenations, calls) cannot be compared verbatim.
API_TEMPLATED_ALLOWLIST: dict[str, str] = {}

# Web constants with no API twin of the same name.
WEB_ONLY = {
    "PASSWORD_MIN_ERROR": "API builds it as an f-string from PASSWORD_MIN (services/auth.py), so no literal to compare",
    "PASSWORD_MAX_ERROR": "API builds it as an f-string from PASSWORD_MAX (services/auth.py), so no literal to compare",
}

WEB_FILES = [
    "components/forms/schema.ts",
    "lib/exits.ts",
    "lib/paid-from.ts",
    "lib/sip.ts",
    "lib/profile.ts",
    "lib/edit-guards.ts",
    "lib/cas-import.ts",
    "lib/duplicates.ts",
]


def api_constants() -> tuple[dict[str, str], dict[str, str]]:
    """(plain string constants, templated/computed string constants) from api/app/schemas."""
    plain: dict[str, str] = {}
    templated: dict[str, str] = {}
    for path in sorted((API / "app" / "schemas").glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            else:
                continue
            if not isinstance(target, ast.Name) or not target.id.replace("_", "").isupper():
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                plain[target.id] = value.value
            elif isinstance(value, (ast.JoinedStr, ast.BinOp)) and _is_stringy(value):
                templated[target.id] = path.name
    return plain, templated


def _is_stringy(node) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in ast.walk(node))
    return False


def web_sources() -> dict[str, str]:
    out = {}
    for folder in ("components", "lib"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix in (".ts", ".tsx") and not path.name.endswith((".test.ts", ".test.tsx")):
                out[str(path.relative_to(WEB))] = path.read_text(encoding="utf-8")
    return out


def api_source_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (API / "app").rglob("*.py"))


def _variants(text: str) -> set[str]:
    return {text, text.replace("'", "\\'"), text.replace('"', '\\"'), text.replace("\u2019", "\\u2019")}


CONST = re.compile(
    r"^export const (\w+)(?:\s*:\s*[^=]+?)?\s*=\s*(?:(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`$]*`)|([A-Z][A-Z0-9_]*))\s*;",
    re.M,
)


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n"}.get(m.group(1), m.group(1)), body)


def web_constants() -> dict[str, str]:
    """Exported *_ERROR|*_MESSAGE|*_DESCRIPTION string constants of WEB_FILES (aliases resolved)."""
    found: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for rel in WEB_FILES:
        text = (WEB / rel).read_text(encoding="utf-8")
        for name, quoted, alias in CONST.findall(text):
            if not re.search(r"(_ERROR|_MESSAGE|_DESCRIPTION)$", name):
                continue
            if quoted:
                found[name] = _unquote(quoted)
            else:
                aliases[name] = alias
    for name, alias in aliases.items():
        if alias in found:
            found[name] = found[alias]
    return found


def test_api_constants_appear_in_the_web():
    plain, templated = api_constants()
    sources = "\n".join(web_sources().values())
    missing = []
    for name, value in sorted(plain.items()):
        if name in API_ONLY:
            continue
        if not any(v in sources for v in _variants(value)):
            missing.append(f"{name} = {value!r}")
    assert not missing, (
        "API schema messages not found verbatim in web/components or web/lib (add the same text to the "
        "web, or list the constant in API_ONLY with a reason):\n  " + "\n  ".join(missing)
    )
    unlisted = sorted(set(templated) - set(API_TEMPLATED_ALLOWLIST))
    assert not unlisted, f"templated API messages need an API_TEMPLATED_ALLOWLIST entry: {unlisted}"


def test_allowlists_are_not_stale():
    plain, templated = api_constants()
    web = web_constants()
    api_source = api_source_text()
    sources = "\n".join(web_sources().values())
    for name in API_ONLY:
        assert name in plain, f"API_ONLY lists {name}, which is no longer an API constant"
        assert not any(v in sources for v in _variants(plain[name])), f"{name} is now in the web: drop it from API_ONLY"
    for name in API_TEMPLATED_ALLOWLIST:
        assert name in templated, f"{name} is no longer a templated API constant"
    for name in WEB_ONLY:
        assert name in web, f"WEB_ONLY lists {name}, which the web no longer exports"
        assert name not in plain or web[name] != plain[name], f"{name} now matches the API: drop it from WEB_ONLY"
        assert not any(v in api_source for v in _variants(web[name])), (
            f"{name} text is now in api/app: drop it from WEB_ONLY"
        )


def test_web_constants_equal_the_api():
    plain, _ = api_constants()
    web = web_constants()
    assert len(web) > 40, "the web constant parser found too few constants"
    api_source = api_source_text()
    wrong = []
    for name, value in sorted(web.items()):
        if name in WEB_ONLY:
            continue
        if name not in plain:
            # Many API messages are inline literals or renamed constants: the same text must exist there.
            if not any(v in api_source for v in _variants(value)):
                wrong.append(f"{name} = {value!r}: no API constant of that name and the text is not in api/app")
        elif plain[name] != value:
            wrong.append(f"{name}: web {value!r} != API {plain[name]!r}")
    assert not wrong, "web constants differ from the API:\n  " + "\n  ".join(wrong)


@pytest.mark.parametrize("name", sorted(API_ONLY))
def test_api_only_constants_have_a_reason(name):
    assert API_ONLY[name].strip()
