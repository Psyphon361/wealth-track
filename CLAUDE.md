# CLAUDE.md

@AGENTS.md

Then read `docs/STATUS.md` and `docs/SPEC.md` before planning anything.

## Claude Code working mode in this repo

- **Orchestrator + builders.** The main session plans, reviews and commits; it does not edit project files. A PreToolUse hook (`.claude/hooks/block-orchestrator-writes.py`, registered in `.claude/settings.json`) blocks Edit/Write and file-changing shell commands from the main agent inside the project. Delegate code/file changes to the `builder` subagent (`.claude/agents/builder.md`, Sonnet); read-only lookups to `scout` (Haiku).
- The main agent may commit reviewed work itself, but the hook only allows exactly these shapes (no `cd`, no parentheses, no extra `&&` steps):
  - `git add <paths> && git commit -F <message-file>` (message file written outside the project, e.g. the session scratchpad)
  - Paths containing `(` `)` (e.g. `web/app/(app)/layout.tsx`) must be passed as globs: `web/app/?app?/layout.tsx`.
- Briefs to builders must be self-contained: exact files they may touch, the rules in AGENTS.md that apply (no native controls, API-sourced messages, identical validation in API+forms, real data in the dev DB, don't touch ports 3000/8000), acceptance commands, "no tests, no debug code, edit only with Write/Edit, don't commit".
- Run independent builders in parallel only when they touch different files (max 3).
- Verify UI changes yourself in the browser before committing; builders have no browser.
- Commit messages end with the co-author line the harness provides. One commit per reviewed change.
- Never push without the user's explicit OK for that push.

## Memory of user preferences (also in AGENTS.md "Non-negotiable rules")

- User wants concise answers, plans shown before non-trivial builds, and approval before validation/behaviour changes.
- Plans: numbered tasks with goal, files, acceptance, dependencies.
