"""Git integration: list branches, run `git diff`, parse the result.

The git command is run as a subprocess against a configured repo path
(`REPO_PATH`). Refs are passed positionally to `git diff` so shell
metacharacters in user input cannot be interpreted — we use `shlex.split`
on the diff output but never on the input.
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


# --- Refs ------------------------------------------------------------------

def _validate_ref(label: str, ref: str) -> str:
    ref = (ref or "").strip()
    if not ref:
        raise GitError(f"{label} is required")
    if not _REF_RE.match(ref):
        raise GitError(f"Invalid {label}: {ref!r}")
    if ref.startswith("-"):
        raise GitError(f"{label} must not start with '-'")
    return ref


# --- Command runner --------------------------------------------------------

def _run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout. Raise GitError on non-zero exit.

    When `cwd` is provided, run in that directory (used by the remote-git
    cache). When None, fall back to the configured `config.REPO_PATH` —
    the legacy single-repo mode — and require it to be set.
    """
    if cwd is not None:
        repo = cwd
    else:
        if not config.REPO_PATH:
            raise GitError("Git integration is disabled (REPO_PATH not set)")
        repo = Path(config.REPO_PATH)
    if not repo.exists():
        raise GitError(f"Repo path does not exist: {repo}")
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        raise GitError(f"Not a git repo: {repo}")

    if shutil.which("git") is None:
        raise GitError("git binary not found on PATH")

    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=config.GIT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError("git command timed out") from e
    except OSError as e:
        raise GitError(f"failed to run git: {e}") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # Surface the most common errors in a form that's useful in the UI.
        if "unknown revision" in stderr or "bad revision" in stderr:
            raise GitError(f"Unknown ref: {stderr.splitlines()[0] if stderr else 'ref not found'}")
        if "fatal: ambiguous" in stderr:
            raise GitError(f"Ambiguous ref: {stderr.splitlines()[0] if stderr else 'ambiguous'}")
        raise GitError(stderr or f"git exited with status {proc.returncode}")
    return proc.stdout


# --- Public API ------------------------------------------------------------

def get_repo_info() -> dict:
    """Return metadata about the configured repo. Always succeeds for a valid repo."""
    repo = Path(config.REPO_PATH)
    if not config.REPO_PATH or not repo.exists() or not (repo / ".git").exists():
        return {"configured": False, "path": config.REPO_PATH or ""}

    head = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    head_sha = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo).strip()
    dirty = bool(_run_git(["status", "--porcelain"], cwd=repo).strip())
    # Default branch: prefer HEAD~1 if it has a name (i.e. we are not on the
    # root commit). Otherwise look for a "main" or "master" branch. As a last
    # resort, return HEAD.
    default_branch = "main"
    branches_raw = _run_git(["branch", "--format=%(refname:short)"], cwd=repo)
    branch_names = {b.strip() for b in branches_raw.splitlines() if b.strip()}
    for candidate in ("main", "master", "trunk", "develop"):
        if candidate in branch_names:
            default_branch = candidate
            break
    else:
        if branch_names:
            # fall back to whichever branch is checked out, or first
            default_branch = head or sorted(branch_names)[0]
    return {
        "configured": True,
        "path": str(repo),
        "head": head,
        "head_sha": head_sha,
        "default_branch": default_branch,
        "dirty": dirty,
        "branches": sorted(branch_names),
    }


def list_branches() -> list[dict]:
    """Return local branches with their HEAD commit. Sorted by name."""
    out = _run_git(["for-each-ref", "--format=%(refname:short)|%(objectname:short)|%(subject)", "refs/heads/"])
    branches: list[dict] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        name, sha, subject = parts
        branches.append({"name": name, "sha": sha, "subject": subject.strip()})
    branches.sort(key=lambda b: b["name"])
    return branches


def list_tags() -> list[dict]:
    """Return local tags (capped to 50 most recent)."""
    out = _run_git(["for-each-ref", "--sort=-creatordate", "--format=%(refname:short)|%(objectname:short)", "refs/tags/"])
    tags: list[dict] = []
    for line in out.splitlines()[:50]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        tags.append({"name": parts[0], "sha": parts[1]})
    return tags


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


def diff_refs(base: str, head: str, path: str | None = None, cwd: Path | None = None) -> dict:
    """Run `git diff base...head [-- path]` and return the parsed files.

    Three-dot form (`base...head`) is used so the comparison is against the
    merge base — what would actually land if you merged `head` into `base`.
    The single-line summary (`--stat`) and the full diff (`-M -C --diff-filter=ACMRT`)
    are produced in two passes so the caller can show a stat block alongside
    the parsed files.

    Binary files (which `git diff` renders as `Binary files ... differ`) are
    stripped from the diff and reported via `binary_skipped`.

    `cwd` lets callers point `git` at a non-default working tree — used by
    the remote-git cache (git_remote.RemoteCache) where each clone lives
    under `REVIEW_DATA_DIR/remotes/{hash}/`. When None, falls back to the
    configured `REPO_PATH` (or raises GitError if that's not set).
    """
    base_v = _validate_ref("base", base)
    head_v = _validate_ref("head", head)
    if path is not None and path.strip():
        path_v = path.strip()
        if path_v.startswith("-") or "\x00" in path_v:
            raise GitError("Invalid path filter")
    else:
        path_v = None

    # build the diff args. three-dot form. -M and -C enable rename / copy
    # detection so renamed files show up as one file with a coherent diff.
    diff_args = ["diff", "--no-color", "-M", "-C", "--diff-filter=ACMRT", f"{base_v}...{head_v}"]
    if path_v:
        diff_args += ["--", path_v]

    raw = _run_git(diff_args, cwd=cwd)

    # Quick stat block for the UI to show before the user clicks review.
    stat_args = ["diff", "--stat", f"{base_v}...{head_v}"]
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
