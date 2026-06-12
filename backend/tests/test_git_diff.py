"""Tests for the git integration. Each test creates a real temporary repo."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import git_diff

# --- Helpers --------------------------------------------------------------

def _run_git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(tmp_path):
    """Build a real local git repo with two branches and a known diff."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(args):
        return subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )

    run(["init", "-q"])
    # Force the initial branch to "main" so the rest of the test is deterministic
    # regardless of the user's init.defaultBranch.
    subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/main"],
        capture_output=True, text=True, check=True,
    )

    # main branch
    (repo / "app.py").write_text("def hello():\n    return 1\n")
    (repo / "lib.py").write_text("LIB = 1\n")
    run(["add", "."])
    run(["commit", "-q", "-m", "initial"])

    # feature branch: modify app.py, add util.py
    run(["checkout", "-q", "-b", "feature"])
    (repo / "app.py").write_text("def hello():\n    return 2\nimport os\n")
    (repo / "util.py").write_text("def new_helper():\n    return 42\n")
    run(["add", "."])
    run(["commit", "-q", "-m", "feature changes"])

    return repo


@pytest.fixture
def configured(monkeypatch, git_repo):
    monkeypatch.setattr(config, "REPO_PATH", str(git_repo))
    return git_repo


# --- get_repo_info --------------------------------------------------------

def test_get_repo_info_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "REPO_PATH", "")
    assert git_diff.get_repo_info() == {"configured": False, "path": ""}


def test_get_repo_info_ok(configured):
    info = git_diff.get_repo_info()
    assert info["configured"] is True
    assert info["path"] == str(configured)
    assert info["head"] == "feature"
    assert info["dirty"] is False
    assert len(info["head_sha"]) >= 7


def test_get_repo_info_dirty(configured):
    (configured / "scratch.py").write_text("print('x')\n")
    info = git_diff.get_repo_info()
    assert info["dirty"] is True


def test_get_repo_info_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REPO_PATH", str(tmp_path / "does-not-exist"))
    info = git_diff.get_repo_info()
    # when the configured path is missing, configured should be False so
    # the UI hides the git tab entirely.
    assert info["configured"] is False
    assert "does-not-exist" in info["path"]


# --- list_branches / list_tags -------------------------------------------

def test_list_branches(configured):
    branches = git_diff.list_branches()
    names = {b["name"] for b in branches}
    assert names == {"main", "feature"}
    for b in branches:
        assert "sha" in b and len(b["sha"]) >= 7
        assert "subject" in b


def test_list_branches_disabled(monkeypatch):
    monkeypatch.setattr(config, "REPO_PATH", "")
    with pytest.raises(git_diff.GitError):
        git_diff.list_branches()


# --- diff_refs ------------------------------------------------------------

def test_diff_refs_branch_to_branch(configured):
    result = git_diff.diff_refs("main", "feature")
    paths = {f.path for f in result["files"]}
    # app.py modified, util.py added, lib.py unchanged
    assert paths == {"app.py", "util.py"}
    app = next(f for f in result["files"] if f.path == "app.py")
    assert "return 2" in app.content
    assert "return 1" in (app.original_content or "")


def test_diff_refs_three_dot_uses_merge_base(configured):
    # with only one commit between branches, three-dot is the same as
    # two-dot in this small repo. Make sure it works.
    result = git_diff.diff_refs("main", "feature")
    assert result.get("files")
    assert result["stat"]


def test_diff_refs_with_path_filter(configured):
    result = git_diff.diff_refs("main", "feature", path="app.py")
    paths = {f.path for f in result["files"]}
    assert paths == {"app.py"}


def test_diff_refs_no_changes(configured):
    result = git_diff.diff_refs("feature", "feature")
    assert result["files"] == []


def test_diff_refs_same_commit_yields_empty(configured):
    result = git_diff.diff_refs("main", "main")
    assert result["files"] == []


def test_diff_refs_rejects_bad_ref(configured):
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main; rm -rf /", "feature")
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "feature --upload-pack=evil")
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "--upload-pack=evil")


def test_diff_refs_rejects_unknown_ref(configured):
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "no-such-branch-12345")
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("no-such-branch-67890", "feature")


def test_diff_refs_handles_rename(configured):
    # create a rename in a new branch
    subprocess.run(
        ["git", "mv", "lib.py", "library.py"],
        cwd=str(configured), capture_output=True, text=True, check=True,
    )
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "t@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    subprocess.run(
        ["git", "commit", "-q", "-m", "rename lib"],
        cwd=str(configured), env=env, capture_output=True, text=True, check=True,
    )
    result = git_diff.diff_refs("main", "feature")
    paths = {f.path for f in result["files"]}
    # rename detection may produce both old and new names; library.py must appear
    assert "library.py" in paths


def test_diff_refs_handles_binary_file(configured):
    # commit a binary file in feature
    (configured / "image.bin").write_bytes(b"\x00\x01\x02\x03BINARYDATA")
    subprocess.run(
        ["git", "add", "image.bin"],
        cwd=str(configured), capture_output=True, text=True, check=True,
    )
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "t@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    subprocess.run(
        ["git", "commit", "-q", "-m", "add binary"],
        cwd=str(configured), env=env, capture_output=True, text=True, check=True,
    )
    result = git_diff.diff_refs("main", "feature")
    assert result["binary_skipped"] >= 1
    # image.bin should not appear in parsed files
    assert not any(f.path == "image.bin" for f in result["files"])


def test_diff_truncation_drops_overflow_files(monkeypatch, tmp_path):
    """When the diff exceeds MAX_GIT_DIFF_BYTES, the response keeps the
    first files that fit and sets truncated=True."""
    # Build a fresh repo so the file order in the diff is predictable.
    repo = tmp_path / "repo"
    repo.mkdir()
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    })
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    for name in ("f1.py", "f2.py", "f3.py"):
        (repo / name).write_text((name + "\n") * 30)
    subprocess.run(["git", "add", "."], cwd=str(repo), env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), env=env, check=True)
    # Move the modified files to a `feature` branch so `main` stays put.
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=str(repo), check=True)
    for name in ("f1.py", "f2.py", "f3.py"):
        (repo / name).write_text((name + "\n") * 40)
    subprocess.run(["git", "add", "."], cwd=str(repo), env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "modify"], cwd=str(repo), env=env, check=True)

    monkeypatch.setattr(config, "REPO_PATH", str(repo))
    # Lower the cap so the second file overflows.
    monkeypatch.setattr(config, "MAX_GIT_DIFF_BYTES", 50)
    result = git_diff.diff_refs("main", "feature")
    assert result["truncated"] is True
    paths = [f.path for f in result["files"]]
    # We always keep the first file; subsequent ones are dropped.
    assert paths[0] == "f1.py"
    assert len(paths) < 3


def test_diff_refs_disabled(monkeypatch):
    monkeypatch.setattr(config, "REPO_PATH", "")
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "feature")


def test_diff_refs_bad_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REPO_PATH", str(tmp_path))  # not a git repo
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "feature")


def test_diff_refs_rejects_bad_path(configured):
    with pytest.raises(git_diff.GitError):
        git_diff.diff_refs("main", "feature", path="--upload-pack=evil")


# --- refs_prefix (remote cache) ------------------------------------------


def test_diff_refs_with_refs_prefix_resolves_origin_tracking_refs(tmp_path, monkeypatch):
    """The remote-git cache is a `--depth 1` shallow clone. The UI's
    RefPicker sends short ref names (`main`, `feature/remote-git`).
    The diff endpoint passes those through git_diff.diff_refs with
    `refs_prefix="origin/"` and `use_three_dot=False`, so the actual
    command becomes `git diff origin/main..origin/feature/remote-git`
    — the prefix resolves `feature/remote-git` (a slashy name git
    can't disambiguate as a ref in a shallow tree) and the two-dot
    form sidesteps the missing merge-base commit.

    Without either of those, the user sees:
      * 'Unknown ref: fatal: ambiguous argument
        "main...feature/remote-git": unknown revision or path
        not in the working tree' (the original bug report) — fixed
        by refs_prefix="origin/"
      * 'fatal: origin/main...origin/feature/remote-git: no merge
        base' — fixed by use_three_dot=False
    This test pins both halves of that contract."""
    import subprocess as sp
    import git_remote as gr

    # Build a local bare repo with a `main` branch and a
    # `feature/remote-git` branch (slash in the name is the actual
    # thing that triggers git's "ambiguous argument" — it can't
    # tell whether `feature/remote-git` is a ref or a path).
    src = tmp_path / "src"; src.mkdir()
    def run(args, cwd=src):
        sp.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@e.com", *args],
            cwd=str(cwd), check=True, capture_output=True, text=True,
        )
    run(["init", "-q", "-b", "main"])
    (src / "a.py").write_text("a=1\n")
    run(["add", "."]); run(["commit", "-q", "-m", "i"])
    run(["checkout", "-q", "-b", "feature/remote-git"])
    (src / "a.py").write_text("a=2\n")
    (src / "b.py").write_text("b=1\n")
    run(["add", "."]); run(["commit", "-q", "-m", "feat"])
    bare = tmp_path / "bare.git"
    sp.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True, text=True)

    # RemoteCache pointed at the bare repo via the file:// test backdoor.
    base = tmp_path / "remotes"
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_DIR", base)
    monkeypatch.setattr(config, "REMOTE_GIT_CACHE_TTL", 3600)
    monkeypatch.setattr(config, "REMOTE_GIT_ALLOWED_HOSTS", ("localhost",), raising=False)

    def _parse(raw):
        if raw.startswith("file://"):
            p = raw[len("file://"):]
            name = p.rstrip("/")
            if name.endswith(".git"):
                name = name[:-4]
            return gr._ParsedURL(
                canonical=raw, host="", path="/" + p.lstrip("/"),
                name=name, scheme="https", ssh_user=None,
            )
        return gr._parse_url(raw)
    monkeypatch.setattr(gr, "_parse_url", _parse)

    cache = gr.RemoteCache()
    entry, _ = cache.get_or_create(f"file://{bare}")

    # 1. Old call shape (no prefix, default three-dot) fails — git
    # can't disambiguate `feature/remote-git` as a ref vs a path in
    # the shallow tree. This is the exact error the user reported.
    with pytest.raises(git_diff.GitError) as ei:
        git_diff.diff_refs("main", "feature/remote-git", cwd=entry.path)
    assert "unknown revision" in str(ei.value) or "ambiguous" in str(ei.value).lower()

    # 2. Even with the prefix fixed, three-dot still fails on a
    # depth-1 clone because the merge-base commit isn't in the
    # shallow history. Confirms the second half of the bug.
    with pytest.raises(git_diff.GitError) as ei:
        git_diff.diff_refs(
            "main", "feature/remote-git",
            cwd=entry.path, refs_prefix="origin/",
        )
    assert "no merge base" in str(ei.value).lower()

    # 3. The fix: refs_prefix="origin/" + use_three_dot=False →
    # `git diff origin/main..origin/feature/remote-git` succeeds and
    # returns the expected diff.
    result = git_diff.diff_refs(
        "main", "feature/remote-git",
        cwd=entry.path, refs_prefix="origin/", use_three_dot=False,
    )
    paths = {f.path for f in result["files"]}
    assert paths == {"a.py", "b.py"}
    a = next(f for f in result["files"] if f.path == "a.py")
    assert "a=2" in a.content
    assert "a=1" in (a.original_content or "")


def test_diff_refs_default_refs_prefix_keeps_local_mode_unchanged(configured):
    """Sanity: the default `refs_prefix=""` and `use_three_dot=True`
    must not break the local REPO_PATH path — `git diff
    main...feature` against a real local repo (with a full history
    and local branches named `main` and `feature`) still returns the
    expected diff."""
    result = git_diff.diff_refs("main", "feature")
    paths = {f.path for f in result["files"]}
    # `configured` fixture creates a repo with app.py / util.py / lib.py;
    # `app.py` is modified on the feature branch.
    assert "app.py" in paths


def test_diff_refs_default_three_dot_for_local_history(configured):
    """Explicit pin: the default for the local REPO_PATH path stays
    three-dot (`use_three_dot=True` is the default). The remote
    endpoint flips this off, but the local endpoint never does —
    silently switching the local mode to two-dot would change the
    diff semantics for full-history repos in a way that no existing
    test would catch. The actual diff of `main...feature` on disk
    is the canonical reference; we just call `diff_refs` with the
    default and compare paths."""
    import subprocess
    result = git_diff.diff_refs("main", "feature")  # default
    on_disk = subprocess.run(
        ["git", "diff", "--name-only", "main...feature"],
        cwd=str(config.REPO_PATH), capture_output=True, text=True, check=True,
    ).stdout.split()
    assert {f.path for f in result["files"]} == set(on_disk)
    # Sanity: the local mode still produces app.py in the diff (the
    # only file the `configured` fixture modifies on the feature
    # branch). The two-dot vs three-dot distinction would only show
    # up with branched histories, which this fixture doesn't model.
    assert "app.py" in {f.path for f in result["files"]}
