#!/usr/bin/env python3
"""PreToolUse hook: the main (orchestrator) agent may not change project files.

Subagent tool calls carry an `agent_id` in the hook input; the main agent's
calls don't. Edits from subagents (e.g. the Sonnet `builder`) pass through.
Writes outside the project (memory, scratchpad) are allowed for everyone.
"""
import json
import os
import re
import sys

data = json.load(sys.stdin)
if data.get("agent_id"):
    sys.exit(0)

project = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
tool = data.get("tool_name", "")
inp = data.get("tool_input") or {}

REASON = (
    "Orchestrator mode: the main agent does not write code or change project files. "
    "Delegate this change to the `builder` subagent (Sonnet) with the Agent tool."
)


def deny():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }))
    sys.exit(0)


def in_project(path):
    if not path:
        return True
    full = os.path.realpath(os.path.join(project, os.path.expanduser(path)))
    return full == project or full.startswith(project + os.sep)


if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    if in_project(inp.get("file_path") or inp.get("notebook_path")):
        deny()

elif tool == "Bash":
    cmd = inp.get("command", "").strip()
    # Allow-list (user-approved 2026-10-21): the main agent may stage reviewed
    # paths and commit with a message file (-F). The -F file keeps `>` in
    # commit trailers from looking like a redirect.
    allowed = [
        r"^git add (?:-- )?[^;&|<>`$()\n]+$",
        r"^git commit -F [^;&|<>`$()\s]+$",
        r"^git add (?:-- )?[^;&|<>`$()\n]+ && git commit -F [^;&|<>`$()\s]+$",
    ]
    if any(re.fullmatch(p, cmd) for p in allowed):
        sys.exit(0)
    # Common ways to modify files from a shell. Redirects to /dev/* are fine.
    patterns = [
        r"(^|[^0-9&<>])>>?\s*(?!/dev/|&)\S",   # > file, >> file
        r"\bsed\b[^|;&]*\s-i",                   # sed -i
        r"\bperl\b[^|;&]*\s-[a-z]*i",            # perl -i / -pi
        r"\btee\b",
        r"\b(rm|mv|cp|touch|mkdir|rmdir|ln|chmod|truncate|dd|patch)\b",
        r"\bgit\s+(apply|checkout|restore|reset|stash|commit|merge|rebase|mv|rm|add)\b",
        r"\b(npm|pnpm|yarn|bun|pip3?|uv|poetry|cargo)\s+(i|install|add|remove|uninstall|init|create)\b",
        r"\b(python3?|node|ruby)\s+-[ce]\b",     # inline scripts can write files
    ]
    if any(re.search(p, cmd) for p in patterns):
        deny()

sys.exit(0)
