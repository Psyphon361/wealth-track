#!/usr/bin/env python3
"""PreToolUse hook (one process per tool call).

Main agent (no `agent_id` in the input): may not change project files. Edit,
Write, MultiEdit and NotebookEdit inside the project are denied, and so is
file-changing Bash, except an allow-list of `git add ... && git commit -F ...`.

Subagents (input has `agent_id`, e.g. the Sonnet `builder`): Edit/Write pass.
Their Bash is checked leniently so hand edits go through Edit/Write instead of
the shell: denied are in-place edits (sed -i, perl -pi, awk -i inplace),
redirects/tee into project paths, inline Python/Node that writes project files,
and git commands that clobber the shared tree (stash, checkout, restore, reset,
clean, switch). Everything else passes. Any parse error or uncertainty allows
(fail open). Writes outside the project (memory, scratchpad, /tmp) are always fine.
"""
import json
import os
import re
import sys

data = json.load(sys.stdin)

project = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
tool = data.get("tool_name", "")
inp = data.get("tool_input") or {}

REASON = (
    "Orchestrator mode: the main agent does not write code or change project files. "
    "Delegate this change to the `builder` subagent (Sonnet) with the Agent tool."
)
SUB_FILE_REASON = (
    "Edit project files with the Edit/Write tools, not shell commands. "
    "Writing to /tmp or the scratchpad is fine."
)
SUB_GIT_REASON = (
    "Other agents may have uncommitted work in this tree; don't stash, reset, restore "
    "or switch. Ask the orchestrator."
)


def deny(reason=REASON):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def in_project(path):
    if not path:
        return True
    full = os.path.realpath(os.path.join(project, os.path.expanduser(path)))
    return full == project or full.startswith(project + os.sep)


# ---------------------------------------------------------------- subagents

# Gitignored build/cache dirs inside the project: writing there is fine.
IGNORED_DIRS = {
    ".next", "node_modules", ".pytest_cache", "__pycache__", ".venv", ".mypy_cache",
    ".ruff_cache", ".turbo", ".vercel", ".cache",
}


class Seg:
    def __init__(self):
        self.words = []
        self.redirs = []   # (op, target)
        self.heredoc = None


def parse(cmd):
    """Split a shell command into segments (&&, ||, ;, |, &, newline) of words,
    redirects and heredoc bodies. Quote-aware: text in quotes is plain words."""
    segs = [Seg()]
    st = {"buf": [], "have": False, "expect": None}
    pending = []  # (seg, delimiter, strip_tabs)

    def flush():
        if not st["have"]:
            return
        w = "".join(st["buf"])
        st["buf"], st["have"] = [], False
        ex = st["expect"]
        st["expect"] = None
        if ex is None:
            segs[-1].words.append(w)
        elif ex[0] == "redir":
            segs[-1].redirs.append((ex[1], w))
        elif ex[0] == "heredoc":
            pending.append((segs[-1], w, ex[1]))

    def newseg():
        flush()
        st["expect"] = None
        segs.append(Seg())

    def drop_fd():
        if st["have"] and "".join(st["buf"]).isdigit():
            st["buf"], st["have"] = [], False
        else:
            flush()

    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 < n and cmd[i + 1] == "\n":
                flush()
            elif i + 1 < n:
                st["buf"].append(cmd[i + 1])
                st["have"] = True
            i += 2
        elif c == "'":
            j = cmd.index("'", i + 1)
            st["buf"].append(cmd[i + 1:j])
            st["have"] = True
            i = j + 1
        elif c == '"':
            j = i + 1
            out = []
            while True:
                if j >= n:
                    raise ValueError("unterminated quote")
                if cmd[j] == "\\" and j + 1 < n:
                    out.append(cmd[j + 1] if cmd[j + 1] in '"\\$`' else "\\" + cmd[j + 1])
                    j += 2
                elif cmd[j] == '"':
                    break
                else:
                    out.append(cmd[j])
                    j += 1
            st["buf"].append("".join(out))
            st["have"] = True
            i = j + 1
        elif c in " \t":
            flush()
            i += 1
        elif c == "\n":
            newseg()
            i += 1
            for seg, delim, strip in pending:
                body = []
                while i < n:
                    eol = cmd.find("\n", i)
                    line = cmd[i:] if eol < 0 else cmd[i:eol]
                    i = n if eol < 0 else eol + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
                    body.append(line)
                seg.heredoc = "\n".join(body)
            pending.clear()
        elif c == ";":
            newseg()
            i += 1
        elif c == "|":
            newseg()
            i += 2 if cmd[i + 1:i + 2] in ("|", "&") else 1
        elif c == "&":
            nxt = cmd[i + 1:i + 2]
            if nxt == "&":
                newseg()
                i += 2
            elif nxt == ">":
                flush()
                i += 3 if cmd[i + 2:i + 3] == ">" else 2
                st["expect"] = ("redir", ">")
            else:
                newseg()
                i += 1
        elif c == ">":
            drop_fd()
            j = i + 1
            nxt = cmd[j:j + 1]
            if nxt in (">", "|"):
                st["expect"] = ("redir", ">")
                i = j + 1
            elif nxt == "&":
                m = re.match(r"[0-9-]*", cmd[j + 1:])
                if m.group(0) and (j + 1 + len(m.group(0)) >= n or cmd[j + 1 + len(m.group(0))] in " \t\n;&|)"):
                    i = j + 1 + len(m.group(0))   # fd duplication: 2>&1, >&2
                else:
                    st["expect"] = ("redir", ">")
                    i = j + 1
            else:
                st["expect"] = ("redir", ">")
                i = j
        elif c == "<":
            drop_fd()
            if cmd.startswith("<<<", i):
                st["expect"] = ("ignore",)
                i += 3
            elif cmd.startswith("<<", i):
                j = i + 2
                strip = cmd[j:j + 1] == "-"
                st["expect"] = ("heredoc", strip)
                i = j + (1 if strip else 0)
            else:
                st["expect"] = ("ignore",)
                i += 1
        else:
            st["buf"].append(c)
            st["have"] = True
            i += 1
    flush()
    return segs


def resolves_in_project(path, cwd):
    """True if path (relative to cwd) is inside the project and not in an ignored
    build/cache dir. Unknown cwd or variable-bearing paths count as outside."""
    if not path or "$" in path or "`" in path or path[0] in "()":
        return False
    if path.startswith("/dev/"):
        return False
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        if cwd is None:
            return False
        path = os.path.join(cwd, path)
    full = os.path.realpath(path)
    if not (full == project or full.startswith(project + os.sep)):
        return False
    rel = os.path.relpath(full, project)
    return not (set(rel.split(os.sep)) & IGNORED_DIRS)


WRITE_RE = re.compile(
    r"""open\([^)]*,\s*(?:mode\s*=\s*)?['"][rwxabt+]*[wxa+][rwxabt+]*['"]"""
    r"|\.write_text\(|\.write_bytes\(|shutil\.(?:copy|copy2|copyfile|copytree|move)\b"
    r"|os\.(?:replace|rename)\(|\bwriteFile(?:Sync)?\b|\bappendFile(?:Sync)?\b"
)
LITERAL_RE = re.compile(r"""['"]([^'"\n]{1,300})['"]""")


def code_writes_project(code, cwd):
    if not WRITE_RE.search(code):
        return False
    if project in code:
        return True
    for lit in LITERAL_RE.findall(code):
        lit = lit.strip()
        if not re.fullmatch(r"[\w@.\-/~()\[\]+]+", lit) or re.fullmatch(r"[rwxabt+]{1,3}", lit):
            continue
        if "/" not in lit and not re.search(r"\.\w{1,6}$", lit):
            continue
        if resolves_in_project(lit, cwd):
            return True
    return False


WRAPPERS = {"env", "time", "nohup", "command", "exec", "sudo", "nice", "builtin"}


def strip_wrappers(words):
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"[A-Za-z_]\w*=", w) or w in WRAPPERS or (w.startswith("-") and i > 0 and words[i - 1] == "env"):
            i += 1
        else:
            break
    return words[i:]


def nondash(words):
    return [w for w in words if w and not w.startswith("-")]


def analyze(cmd, cwd, depth=0):
    """Return a deny reason for a subagent Bash command, or None."""
    cur = cwd
    for seg in parse(cmd):
        for op, target in seg.redirs:
            if resolves_in_project(target, cur):
                return SUB_FILE_REASON
        words = strip_wrappers(seg.words)
        if not words:
            continue
        base = os.path.basename(words[0])
        args = words[1:]

        if base == "cd":
            if len(args) == 1 and "$" not in args[0] and args[0] != "-" and cur is not None:
                cur = os.path.realpath(os.path.join(cur, os.path.expanduser(args[0])))
            else:
                cur = None
            continue

        if base == "tee":
            if any(resolves_in_project(a, cur) for a in nondash(args)):
                return SUB_FILE_REASON

        elif base == "sed":
            inplace = any(a == "--in-place" or a.startswith("--in-place=")
                          or (re.match(r"-[A-Za-z]*i", a) and not a.startswith("--")) for a in args)
            if inplace:
                files = nondash(args)
                if not any(a in ("-e", "-f", "--expression", "--file") for a in args):
                    files = files[1:]
                if any(resolves_in_project(f, cur) for f in files):
                    return SUB_FILE_REASON

        elif base == "perl":
            if any(re.match(r"-[A-Za-z]*i", a) and not a.startswith("--") for a in args):
                code_idx = {k + 1 for k, a in enumerate(args) if a in ("-e", "-E")}
                files = [a for k, a in enumerate(args) if k not in code_idx and a and not a.startswith("-")]
                if any(resolves_in_project(f, cur) for f in files):
                    return SUB_FILE_REASON

        elif base in ("awk", "gawk"):
            if any(a == "-i" and k + 1 < len(args) and args[k + 1] == "inplace" for k, a in enumerate(args)) \
                    or "-iinplace" in args:
                files = [a for a in nondash(args) if a != "inplace"]
                if "-f" not in args:
                    files = files[1:]
                if any(resolves_in_project(f, cur) for f in files):
                    return SUB_FILE_REASON

        elif base == "git":
            i = 0
            while i < len(args) and args[i].startswith("-"):
                i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
            sub = args[i] if i < len(args) else ""
            if sub in ("checkout", "restore", "reset", "clean", "switch"):
                return SUB_GIT_REASON
            if sub == "stash" and (args[i + 1] if i + 1 < len(args) else "") not in ("list", "show"):
                return SUB_GIT_REASON

        elif base in ("bash", "sh", "zsh") and depth < 2:
            for k, a in enumerate(args):
                if re.fullmatch(r"-[a-z]*c[a-z]*", a) and k + 1 < len(args):
                    reason = analyze(args[k + 1], cur, depth + 1)
                    if reason:
                        return reason
                    break

        # Inline Python / Node (also `uv run python`, `.venv/bin/python`).
        idx = next((k for k, w in enumerate(words[:4])
                    if re.fullmatch(r"python[\d.]*|node", os.path.basename(w))), None)
        if idx is not None and (idx == 0 or base in ("uv", "poetry", "pipenv", "npx", "env")):
            is_py = os.path.basename(words[idx]).startswith("python")
            rest = words[idx + 1:]
            code = None
            for k, a in enumerate(rest):
                if is_py and a == "-m":
                    break
                if a in ("-c", "-e", "-p", "--eval", "--print") and k + 1 < len(rest):
                    code = rest[k + 1]
                    break
                if is_py and re.fullmatch(r"-c.+", a):
                    code = a[2:]
                    break
            if code is None and seg.heredoc is not None and ("-" in rest or not nondash(rest)):
                code = seg.heredoc
            if code is not None and code_writes_project(code, cur):
                return SUB_FILE_REASON
    return None


def subagent_check():
    if tool != "Bash":
        return
    cmd = inp.get("command") or ""
    cwd = os.path.realpath(data.get("cwd") or project)
    try:
        reason = analyze(cmd, cwd)
    except Exception:
        return  # fail open
    if reason:
        deny(reason)


if data.get("agent_id"):
    subagent_check()
    sys.exit(0)

# ------------------------------------------------------------- main agent

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
