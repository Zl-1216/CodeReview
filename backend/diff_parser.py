"""Unified diff parser used to turn `git diff` output into per-file entries.

The parser handles standard `git diff` / `diff -u` output and tries to be
forgiving of the small variations real-world tools produce. It does not aim
to be a full reimplementation of git's diff format — it only needs to recover
the per-file before/after state well enough for a code review.
"""

# TODO: support combined diff format (`--cc`) — currently we only handle
# plain unified diffs, which is what `git diff` emits by default. Once
# merge commits become a common review target we should switch to the
# combined format parser from `unidiff` or implement it ourselves.

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from models import CodeFile, DiffLine

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (.+)$")


@dataclass
class _FileBuilder:
    path: str = ""
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    old_lineno: int = 0
    new_lineno: int = 0


def _strip_diff_headers(raw: str) -> Iterable[tuple[str, str | None, list[str]]]:
    """Yield (path, hunk_lines) tuples from a raw unified diff.

    A single file in a diff has the form:

        diff --git a/foo.py b/foo.py
        index ...
        --- a/foo.py
        +++ b/foo.py
        @@ ... @@
        <hunk body>
        @@ ... @@
        <hunk body>
        ...

    We extract the destination path and the concatenated hunk bodies.
    For renames / copies, `rename to X` / `copy to X` overrides the path
    taken from the `diff --git` header. The `old_path` (when present
    via `rename from X`) is the second tuple element so the caller can
    detect renames and mark the file with `status="renamed"`.
    """
    current_path: str | None = None
    current_old_path: str | None = None
    current_lines: list[str] = []

    def flush() -> tuple[str, str | None, list[str]] | None:
        nonlocal current_path, current_old_path, current_lines
        if current_path is None:
            return None
        result = (current_path, current_old_path, current_lines)
        current_path = None
        current_old_path = None
        current_lines = []
        return result

    for line in raw.splitlines():
        if line.startswith("diff --git "):
            flushed = flush()
            if flushed is not None:
                yield flushed
            # best-effort: take the b/ side of the header
            parts = line.split()
            if len(parts) >= 4:
                # The header's b/ side is "b/<path>"; strip exactly the
                # two-character prefix. (lstrip("b/") would also strip
                # any leading b or / chars from the path itself.)
                current_path = parts[3].removeprefix("b/")
            current_lines = []
        elif line.startswith("rename from "):
            current_old_path = line[len("rename from "):].strip()
        elif line.startswith("copy from "):
            current_old_path = line[len("copy from "):].strip()
        elif line.startswith("rename to "):
            current_path = line[len("rename to "):].strip()
        elif line.startswith("copy from "):
            pass
        elif line.startswith("copy to "):
            current_path = line[len("copy to "):].strip()
        elif line.startswith("+++ "):
            # `+++ /dev/null` means a deletion
            target = line[4:].strip().split("\t", 1)[0]
            if target == "/dev/null":
                # keep the current_path inferred from `---`, but mark deletion later
                pass
            elif target.startswith("b/"):
                current_path = target[2:]
        elif line.startswith("--- "):
            # don't overwrite current_path on the a/ side — b/ takes precedence
            pass
        elif line.startswith("@@") or (line and line[0] in {" ", "+", "-"}):
            current_lines.append(line)
        else:
            # blank line, "index ...", or other metadata — keep hunk parsing simple
            pass

    flushed = flush()
    if flushed is not None:
        yield flushed


def _apply_hunks(path: str, hunk_lines: list[str], old_path: str | None = None) -> CodeFile:
    """Apply a concatenated set of hunk bodies to reconstruct old/new content.

    Tracks absolute line numbers in the original file so the frontend can
    map a new-file finding back to the corresponding old-file line.

    The reconstructed `content` / `original_content` use *relative* line
    numbers (1-indexed within the snippet), since that is what the AI
    reviewer reports. The `line_map` translates those relative new-line
    numbers into absolute old-file line numbers, applying these rules:

      * Context line in both sides  -> direct mapping
      * `+X` after a `-Y` line       -> new maps to the position Y occupied
      * `+X` with no preceding `-Y`  -> unmapped (genuinely new line)

    Also builds a structured per-line `diff` list (list of `DiffLine`)
    for the frontend's diff viewer, and classifies the file's
    `status` as `added` / `modified` / `deleted` / `renamed` /
    `unchanged`.
    """
    old: list[str] = []
    new: list[str] = []
    line_map: dict[int, int] = {}
    diff: list[DiffLine] = []
    added_count = 0
    removed_count = 0
    old_lineno = 0  # absolute line in the original file (from hunk header)
    new_lineno = 0  # absolute line in the new file (from hunk header)
    rel_new = 0  # 1-indexed line within the reconstructed new content
    rel_old_for_diff = 0  # 1-indexed within the reconstructed old; used for DiffLine.old_line
    pending_old_line: int | None = None  # last `-` line's old position

    i = 0
    n = len(hunk_lines)
    while i < n:
        line = hunk_lines[i]
        if not line.startswith("@@"):
            i += 1
            continue
        m = _HUNK_RE.match(line)
        if not m:
            i += 1
            continue
        old_lineno = int(m.group(1))
        new_lineno = int(m.group(3))
        pending_old_line = None
        # `rel_old_for_diff` is the relative (1-indexed) old-side
        # cursor for the DiffLine list. It must reset at each hunk
        # header so line numbers in the diff line list restart at
        # 1 (matching `rel_new`'s reset). The hunk header's old-side
        # count is the upper bound, so we know when to stop.
        rel_old_for_diff = 0
        i += 1
        while i < n and not hunk_lines[i].startswith("@@"):
            body = hunk_lines[i]
            if body.startswith("+"):
                text = body[1:]
                new.append(text)
                rel_new += 1
                new_lineno += 1
                added_count += 1
                if pending_old_line is not None:
                    line_map[rel_new] = pending_old_line
                    pending_old_line = None
                diff.append(DiffLine(
                    type="added",
                    old_line=None,
                    new_line=rel_new,
                    text=text,
                ))
            elif body.startswith("-"):
                text = body[1:]
                old.append(text)
                pending_old_line = old_lineno
                old_lineno += 1
                removed_count += 1
                rel_old_for_diff += 1
                diff.append(DiffLine(
                    type="removed",
                    old_line=rel_old_for_diff,
                    new_line=None,
                    text=text,
                ))
            elif body.startswith(" "):
                text = body[1:]
                old.append(text)
                new.append(text)
                rel_new += 1
                new_lineno += 1
                line_map[rel_new] = old_lineno
                old_lineno += 1
                pending_old_line = None
                # Both old_line and new_line are RELATIVE (1-indexed
                # within the reconstructed snippet), not the absolute
                # hunk numbers. The AI reviewer reports relative line
                # numbers in findings, so making the diff line list
                # speak the same dialect keeps the frontend's diff
                # viewer and the finding-line highlighter in sync
                # without a translation layer.
                rel_old_for_diff += 1
                diff.append(DiffLine(
                    type="context",
                    old_line=rel_old_for_diff,
                    new_line=rel_new,
                    text=text,
                ))
            else:
                pass
            i += 1

    # Classify the file's change status. Order matters:
    #   1. renames are detected by `old_path` being set and differing
    #   2. additions: no `original_content` after parsing (no `-` lines)
    #   3. deletions: no `content` after parsing (no `+` lines)
    #   4. modified: both sides populated
    #   5. unchanged: no diff lines at all (rare in real diffs; happens
    #      when git shows a file in the diff because of mode changes
    #      only).
    if old_path and old_path != path:
        status = "renamed"
    elif not old:
        status = "added"
    elif not new:
        status = "deleted"
    elif added_count == 0 and removed_count == 0:
        status = "unchanged"
    else:
        status = "modified"

    return CodeFile(
        path=path,
        content="\n".join(new),
        original_content="\n".join(old) if old else None,
        language=_infer_language(path),
        line_map=line_map,
        status=status,
        added_count=added_count,
        removed_count=removed_count,
        diff=diff,
    )


def parse_unified_diff(raw: str) -> list[CodeFile]:
    """Parse a unified diff string into a list of `CodeFile`s.

    Handles:
      * `diff --git a/foo b/foo` headers (standard `git diff`)
      * `--- /dev/null` (new file) — original_content left as None
      * `+++ /dev/null` (deletion) — content is empty
      * Multiple files in a single diff
      * Multiple hunks per file

    Falls back to a single-file "raw diff" entry if it can't identify any
    file headers, so callers always get a non-empty result for non-empty input.
    """
    if not raw.strip():
        return []

    files: list[CodeFile] = []
    for path, old_path, hunk_lines in _strip_diff_headers(raw):
        # Even with no hunk lines (e.g. a 100% rename) the file should be
        # surfaced so the UI can list it. The content will be empty in that
        # case — the reviewer can still produce a "consider the new name"
        # style finding.
        files.append(_apply_hunks(path, hunk_lines, old_path=old_path))

    if not files:
        # No recognizable file headers — treat the whole input as new content
        # of a synthetic file. Useful for ad-hoc paste.
        return [CodeFile(path="snippet.txt", content=raw, language="text")]

    return files


def _infer_language(path: str) -> str | None:
    """Map a file extension to a language identifier used in prompts."""
    if not path:
        return None
    ext = Path(path).suffix.lower().lstrip(".")
    mapping = {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "vue": "vue",
        "go": "go",
        "rs": "rust",
        "java": "java",
        "kt": "kotlin",
        "rb": "ruby",
        "php": "php",
        "cs": "csharp",
        "cpp": "cpp",
        "cc": "cpp",
        "c": "c",
        "h": "c",
        "hpp": "cpp",
        "swift": "swift",
        "sh": "bash",
        "bash": "bash",
        "zsh": "bash",
        "sql": "sql",
        "html": "html",
        "css": "css",
        "scss": "scss",
        "yaml": "yaml",
        "yml": "yaml",
        "json": "json",
        "md": "markdown",
        "toml": "toml",
    }
    return mapping.get(ext)


def line_numbers_in_original(file: CodeFile) -> dict[int, int]:
    """Return a mapping from new-line-number -> old-line-number for the file.

    The parser records the mapping while applying hunks, so this just returns
    it. For files built without hunk headers (e.g. raw paste), it falls back
    to a simple text-walk.
    """
    if file.line_map:
        return dict(file.line_map)
    if not file.original_content or not file.content:
        return {}
    old_lines = file.original_content.splitlines()
    new_lines = file.content.splitlines()
    mapping: dict[int, int] = {}
    i = j = 0
    while i < len(old_lines) and j < len(new_lines):
        if old_lines[i] == new_lines[j]:
            mapping[j + 1] = i + 1
            i += 1
            j += 1
        else:
            advance = False
            for k in range(j + 1, min(len(new_lines), j + 8) + 1):
                if k < len(new_lines) and old_lines[i] == new_lines[k]:
                    j = k
                    mapping[j + 1] = i + 1
                    i += 1
                    j += 1
                    advance = True
                    break
            if advance:
                continue
            j += 1
    return mapping
