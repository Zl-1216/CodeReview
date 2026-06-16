"""Git diff helper used by the remote-repo review flow.

`diff_refs()` runs `git diff base...head` (or `base..head` for the
shallow remote cache) against a working tree at `cwd` and returns the
parsed files. This is the only function left from the old
local-git module after the local-git UI was removed; the
`/api/git/remote/{id}/diff` endpoint in `main.py` is its sole
caller.

Refs are passed positionally to `git diff` so shell metacharacters in
user input cannot be interpreted — we never shell-parse the input.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

import config
from diff_parser import parse_unified_diff

logger = logging.getLogger(__name__)


# Refs can be branch / tag / commit-ish. Disallow whitespace, `..`, `--`, and
# leading `-` to keep the argument list unambiguous.
_REF_RE = re.compile(r"^[A-Za-z0-9_./@^~{}\-]+$")


class GitError(Exception):
    """Raised when a git operation fails in a way the UI should surface."""


def _validate_ref(label: str, ref: str) -> str:
    ref = (ref or "").strip()
    if not ref:
        raise GitError(f"{label} is required")
    if not _REF_RE.match(ref):
        raise GitError(f"Invalid {label}: {ref!r}")
    if ref.startswith("-"):
        raise GitError(f"{label} must not start with '-'")
    return ref


def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git command in `cwd` and capture stdout."""
    if shutil.which("git") is None:
        raise GitError("git binary not found on PATH")
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=config.REMOTE_GIT_CLONE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError("git command timed out") from e
    except OSError as e:
        raise GitError(f"failed to run git: {e}") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if "unknown revision" in stderr or "bad revision" in stderr:
            raise GitError(f"Unknown ref: {stderr.splitlines()[0] if stderr else 'ref not found'}")
        if "fatal: ambiguous" in stderr:
            raise GitError(f"Ambiguous ref: {stderr.splitlines()[0] if stderr else 'ambiguous'}")
        raise GitError(stderr or f"git exited with status {proc.returncode}")
    return proc.stdout


def _strip_binary_blocks(raw: str) -> tuple[str, int]:
    """Remove `diff --git` blocks that contain only a "Binary files" line.

    git's default diff output for a binary file is::

        diff --git a/foo.png b/foo.png
        new file mode 100644
        index 0000..abc
        Binary files /dev/null and b/foo.png differ

    The block has no `--- / +++ / @@` lines, so the parser would otherwise
    produce a CodeFile with an empty content. Stripping the whole block keeps
    the file out of the parsed result while leaving text-based files intact.

    Returns the cleaned raw plus a count of blocks removed.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in raw.splitlines():
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    binary_count = 0
    kept: list[str] = []
    for block in blocks:
        if any(line.startswith("Binary files ") for line in block):
            binary_count += 1
            continue
        kept.extend(block)
    return ("\n".join(kept), binary_count)


def diff_refs(base: str, head: str, path: str | None = None, cwd: Path | None = None,
              refs_prefix: str = "", use_three_dot: bool = True) -> dict:
    """Run `git diff base...head [-- path]` (or `base..head` for shallow
    caches) and return the parsed files.

    Two-dot vs three-dot form:
      * Three-dot (`base...head`) is the "merge preview" form — it
        diffs against the merge base, which is what would actually
        land if you merged `head` into `base`. This is the right
        answer for a "what's in this PR?" review when you have a
        full local history, so we use it by default.
      * Two-dot (`base..head`) compares the two tips directly with no
        merge-base lookup. The remote-git cache is a `--depth 1`
        shallow clone, so the merge-base commit is typically NOT
        in the local history and the three-dot form fails with
        "no merge base". The remote endpoint passes
        `use_three_dot=False` for exactly this reason.

    `cwd` points `git` at the remote cache's working tree. The
    remote endpoint always passes this (no REPO_PATH fallback in
    this version of the service — the local-git UI was removed).

    `refs_prefix` is prepended to both `base` and `head` in the diff
    command. The remote-git cache path passes `"origin/"` because
    the cache only has remote-tracking refs under
    `refs/remotes/origin/*` — the UI's RefPicker sends short names
    like `main` (the part after `origin/`), and we have to re-prefix
    them so `git diff main...feature` resolves to
    `origin/main...origin/feature`. Without this, the user sees
    'ambiguous argument "main...feature": unknown revision or path
    not in the working tree' even though the branch names ARE
    present in the repo (just under `origin/`, not at the top level).
    """
    base_v = _validate_ref("base", base)
    head_v = _validate_ref("head", head)
    if path is not None and path.strip():
        path_v = path.strip()
        if path_v.startswith("-") or "\x00" in path_v:
            raise GitError("Invalid path filter")
    else:
        path_v = None

    if cwd is None:
        raise GitError("diff_refs requires an explicit cwd (the remote cache path)")

    # Build the diff args. Three-dot or two-dot per `use_three_dot`.
    # -M and -C enable rename / copy detection so renamed files show
    # up as one file with a coherent diff.
    sep = "..." if use_three_dot else ".."
    diff_args = [
        "diff", "--no-color", "-M", "-C", "--diff-filter=ACMRT",
        f"{refs_prefix}{base_v}{sep}{refs_prefix}{head_v}",
    ]
    if path_v:
        diff_args += ["--", path_v]

    raw = _run_git(diff_args, cwd=cwd)

    # Quick stat block for the UI to show before the user clicks review.
    # Same refs_prefix and separator as the main diff call above.
    stat_args = ["diff", "--stat", f"{refs_prefix}{base_v}{sep}{refs_prefix}{head_v}"]
    if path_v:
        stat_args += ["--", path_v]
    stat = _run_git(stat_args, cwd=cwd).rstrip()

    if not raw.strip():
        return {
            "base": base_v,
            "head": head_v,
            "path": path_v,
            "stat": stat,
            "files": [],
            "raw": raw,
            "binary_skipped": 0,
        }

    # Detect binary files. git's default output uses "Binary files ... differ"
    # for modified binaries and the same phrase (with /dev/null) for new ones.
    # We strip the whole `diff --git ...` block so the parser doesn't pick
    # up an empty record for the binary file.
    raw, binary_count = _strip_binary_blocks(raw)

    files = parse_unified_diff(raw)

    # Cap the response size to keep review payloads manageable. We keep
    # the first files (in the order the diff produced them) until adding
    # the next one would push us over the budget, then drop the rest and
    # set `truncated` so the caller can surface a warning.
    truncated = False
    if files:
        kept: list = []
        running = 0
        for f in files:
            size = len(f.content.encode("utf-8"))
            if kept and running + size > config.MAX_GIT_DIFF_BYTES:
                truncated = True
                break
            kept.append(f)
            running += size
        if len(kept) != len(files):
            files = kept
            truncated = True

    return {
        "base": base_v,
        "head": head_v,
        "path": path_v,
        "stat": stat,
        "files": files,
        "raw": raw,
        "binary_skipped": binary_count,
        "truncated": truncated,
    }
