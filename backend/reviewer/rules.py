"""Mock review rules.

Each rule is a dict with these keys:
  * id            — short stable identifier
  * languages     — set of language identifiers that this rule applies to,
                    or None for "any language"
  * severity      — critical | high | medium | low | info
  * category      — bug | security | performance | style | best_practice | documentation
  * pattern       — a regex applied per line of file content
  * title         — short, user-facing title
  * detail        — why this matters (one paragraph)
  * suggestion    — a concrete fix, may include code

Adding a rule is one entry below; no other code needs to change.
"""
from __future__ import annotations

import re

from models import CodeFile

RULES: list[dict] = [
    {
        "id": "py-eval",
        "languages": {"python"},
        "severity": "high",
        "category": "security",
        "pattern": r"\beval\s*\(",
        "title": "Use of eval()",
        "detail": "`eval()` executes arbitrary Python from a string. If any part of the input is "
                  "user-controlled this is a remote code execution vulnerability. Even for "
                  "internal use it makes the code hard to audit.",
        "suggestion": "Replace with a safe parser (`ast.literal_eval` for literals, `json.loads` "
                      "for JSON) or a domain-specific interpreter.",
    },
    {
        "id": "py-exec",
        "languages": {"python"},
        "severity": "high",
        "category": "security",
        "pattern": r"\bexec\s*\(",
        "title": "Use of exec()",
        "detail": "`exec()` runs arbitrary Python code. Even in trusted contexts it hides "
                  "control flow and complicates testing.",
        "suggestion": "Refactor to call the function or method directly. If you genuinely need "
                      "dynamic dispatch, use `importlib` and a whitelist of allowed names.",
    },
    {
        "id": "py-shell-true",
        "languages": {"python"},
        "severity": "critical",
        "category": "security",
        "pattern": r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True",
        "title": "subprocess with shell=True",
        "detail": "Combining `shell=True` with any user-controlled input is a shell-injection "
                  "vector. The argument is parsed by `/bin/sh`, so characters like `;`, `|` and "
                  "`$()` are interpreted.",
        "suggestion": "Pass the command as a list (no shell) and validate each argument against "
                      "an allowlist, e.g. `subprocess.run(['ls', user_path], check=True)`.",
    },
    {
        "id": "py-os-system",
        "languages": {"python"},
        "severity": "high",
        "category": "security",
        "pattern": r"\bos\.(?:system|popen)\s*\(",
        "title": "os.system / os.popen",
        "detail": "Both functions invoke the shell with a string command. Like "
                  "`subprocess(shell=True)`, this is dangerous if any part of the argument is "
                  "user-controlled.",
        "suggestion": "Use `subprocess.run([...], shell=False)` and a list of arguments.",
    },
    {
        "id": "py-pickle",
        "languages": {"python"},
        "severity": "critical",
        "category": "security",
        "pattern": r"\bpickle\.loads?\s*\(",
        "title": "pickle deserialization",
        "detail": "`pickle.load` will execute arbitrary code embedded in the input. Never "
                  "unpickle data you did not produce yourself.",
        "suggestion": "Use `json` for plain data, or `pydantic` for typed payloads. If you must "
                      "deserialize Python objects, sign them with HMAC and use "
                      "`itsdangerous`.",
    },
    {
        "id": "py-requests-no-timeout",
        "languages": {"python"},
        "severity": "medium",
        "category": "bug",
        "pattern": r"requests\.[a-z_]+\([^)]*\)(?![^.]*timeout)",
        "title": "requests call without timeout",
        "detail": "Without an explicit `timeout=`, a `requests` call can hang forever, blocking "
                  "the event loop or the worker. This is a common cause of stuck production "
                  "workers.",
        "suggestion": "Pass `timeout=` to every `requests` call, e.g. `requests.get(url, timeout=5)`.",
    },
    {
        "id": "py-broad-except",
        "languages": {"python"},
        "severity": "low",
        "category": "style",
        "pattern": r"except\s*:\s*$",
        "title": "Bare `except:` clause",
        "detail": "A bare `except:` catches `KeyboardInterrupt` and `SystemExit` as well, which "
                  "is almost never what you want.",
        "suggestion": "Catch `Exception` (or, better, a specific subclass) and re-raise things "
                      "you cannot handle.",
    },
    {
        "id": "py-print",
        "languages": {"python"},
        "severity": "low",
        "category": "style",
        "pattern": r"^\s*print\s*\(",
        "title": "print() left in code",
        "detail": "A `print()` call usually means leftover debug output. In a server it pollutes "
                  "stdout and leaks values that may include user data.",
        "suggestion": "Remove it, or replace with a structured `logger.debug(...)` call.",
    },
    {
        "id": "py-mutable-default",
        "languages": {"python"},
        "severity": "high",
        "category": "bug",
        "pattern": r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|\set\(\))",
        "title": "Mutable default argument",
        "detail": "Default arguments are evaluated once at function-definition time, so a mutable "
                  "default is *shared* between calls. This is a classic source of cross-call "
                  "leakage and confusing test failures.",
        "suggestion": "Use the sentinel pattern: `def f(x=None): x = [] if x is None else x`.",
    },
    {
        "id": "py-hash-secret",
        "languages": {"python"},
        "severity": "high",
        "category": "security",
        "pattern": r"(password|secret|api[_-]?key|token)\s*=\s*['\"]",
        "title": "Hardcoded secret in source",
        "detail": "A literal secret in source will be committed to version control and will be "
                  "visible to anyone with read access to the repo.",
        "suggestion": "Read the value from an environment variable or a secret manager, and fail "
                      "fast if it is missing.",
    },
    {
        "id": "sql-string-concat",
        "languages": {"python", "javascript", "typescript", "java", "go", "php", "ruby"},
        "severity": "critical",
        "category": "security",
        "pattern": r"(SELECT|INSERT|UPDATE|DELETE)[^;\n]*['\"]?\s*\+\s*\w",
        "title": "Possible SQL string concatenation",
        "detail": "Building SQL by concatenating variables is the canonical SQL-injection pattern. "
                  "If any of the variables are user-controlled the database is compromised.",
        "suggestion": "Use parameterized queries: `cursor.execute('SELECT * FROM t WHERE id = %s', (id,))`.",
    },
    {
        "id": "js-eval",
        "languages": {"javascript", "typescript"},
        "severity": "high",
        "category": "security",
        "pattern": r"\beval\s*\(",
        "title": "Use of eval()",
        "detail": "In JavaScript, `eval` executes any string as code. It is also blocked by CSP "
                  "in most modern apps, so it tends to indicate a deeper design issue.",
        "suggestion": "Use `JSON.parse` for JSON, or restructure to call the function directly.",
    },
    {
        "id": "js-innerhtml",
        "languages": {"javascript", "typescript"},
        "severity": "high",
        "category": "security",
        "pattern": r"\.innerHTML\s*=",
        "title": "innerHTML assignment",
        "detail": "Assigning to `innerHTML` parses the value as HTML. If any part of it is "
                  "user-controlled this is an XSS vector. Even without user input it is fragile.",
        "suggestion": "Use `textContent` for plain text, or a framework templating layer that "
                      "escapes by default.",
    },
    {
        "id": "js-dangerously-set",
        "languages": {"javascript", "typescript", "tsx", "jsx"},
        "severity": "medium",
        "category": "security",
        "pattern": r"dangerouslySetInnerHTML",
        "title": "dangerouslySetInnerHTML usage",
        "detail": "React's `dangerouslySetInnerHTML` bypasses its built-in escaping. Only use it "
                  "for content you have sanitized yourself.",
        "suggestion": "Sanitize with DOMPurify before passing, or render the content as a child "
                      "node so React can escape it.",
    },
    {
        "id": "js-console-log",
        "languages": {"javascript", "typescript"},
        "severity": "info",
        "category": "style",
        "pattern": r"^\s*console\.log\s*\(",
        "title": "console.log left in code",
        "detail": "A `console.log` is usually leftover debug output. It is fine while developing, "
                  "but it should not ship.",
        "suggestion": "Remove it, or use a real logger and gate it behind a debug flag.",
    },
    {
        "id": "any-todo",
        "languages": None,
        "severity": "info",
        "category": "best_practice",
        "pattern": r"\b(TODO|FIXME|XXX|HACK)\b",
        "title": "TODO/FIXME comment",
        "detail": "A marker comment usually means unfinished work. It is fine while a PR is open, "
                  "but stale TODOs rot fast and the next reader has no idea whether they are "
                  "still relevant.",
        "suggestion": "Either fix it now, or convert the comment into a tracked issue and link to "
                      "it.",
    },
    {
        "id": "any-long-line",
        "languages": None,
        "severity": "low",
        "category": "style",
        "pattern": r"^.{161,}$",
        "title": "Line over 160 characters",
        "detail": "Long lines are hard to read in code review and on smaller terminals. Most "
                  "formatters target 80-120.",
        "suggestion": "Reflow the line, or configure a formatter (black, prettier) and run it.",
    },
    {
        "id": "any-fmt-string",
        "languages": {"python"},
        "severity": "medium",
        "category": "security",
        "pattern": r"%\s*\(\s*[\w\., ]+\s*\)\s*%",
        "title": "Old-style format with user data",
        "detail": "Old-style `%`-formatting is fine for static strings but not for log lines that "
                  "include user input — exception objects, file paths, etc. may contain `%s` and "
                  "crash the logger.",
        "suggestion": "Use f-strings or `logger.exception('msg: %s', value)` with a single `%s` "
                      "placeholder.",
    },
    {
        "id": "any-pdb",
        "languages": {"python"},
        "severity": "medium",
        "category": "bug",
        "pattern": r"\b(pdb|breakpoint|ipdb|pudb)\.set_trace\(\)|pdb\.pm\(\)",
        "title": "Debugger breakpoint left in code",
        "detail": "An interactive debugger in a code path will pause the process in production. "
                  "If the code runs inside a request handler it will hang that handler forever.",
        "suggestion": "Remove the breakpoint. If you need to debug later, set one only locally.",
    },
    {
        "id": "js-fetch-no-error-handling",
        "languages": {"javascript", "typescript"},
        "severity": "medium",
        "category": "bug",
        "pattern": r"await\s+fetch\([^)]*\)",
        "title": "fetch() may reject",
        "detail": "`fetch` only rejects on network failure, not on HTTP error statuses. Calling "
                  "`response.json()` on a 4xx/5xx response will throw a parse error, and the "
                  "caller may not handle it.",
        "suggestion": "Check `response.ok` (or `response.status`) and throw a descriptive error, "
                      "or use a wrapper like `ofetch` / `ky` that does this for you.",
    },
]


def rule_matches(file: CodeFile, rule: dict) -> list[tuple[int, str]]:
    """Return [(line_no, matched_text), ...] for a rule on a file's content.

    Public for unit tests; the mock engine uses this internally.
    """
    if rule["languages"] is not None and (file.language or "") not in rule["languages"]:
        return []
    pattern = rule.get("_compiled") or re.compile(rule["pattern"])
    matches: list[tuple[int, str]] = []
    for lineno, line in enumerate(file.content.splitlines(), 1):
        if pattern.search(line):
            matches.append((lineno, line.rstrip()))
    return matches


# Pre-compile the patterns once at import time. Without this, a 200 KB
# file matched against 20 rules re-compiles the regex per line per rule
# — i.e. tens of thousands of compilations per review.
for _r in RULES:
    _r["_compiled"] = re.compile(_r["pattern"])
del _r


def find_rule(rule_id: str) -> dict | None:
    for r in RULES:
        if r["id"] == rule_id:
            return r
    return None
