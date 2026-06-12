"""Tests for the unified diff parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diff_parser import line_numbers_in_original, parse_unified_diff


def test_simple_modification():
    diff = (
        "diff --git a/app.py b/app.py\n"
        "index 1234..5678 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def hello():\n"
        "-    return 1\n"
        "+    return 2\n"
        "\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].path == "app.py"
    assert files[0].original_content == "def hello():\n    return 1"
    assert files[0].content == "def hello():\n    return 2"
    assert files[0].language == "python"


def test_new_file():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "index 0000..1234\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def foo():\n"
        "+    pass\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].path == "new.py"
    assert files[0].content == "def foo():\n    pass"
    # new file has no original
    assert files[0].original_content in (None, "")


def test_deletion():
    diff = (
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "index 1234..0000\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-def gone():\n"
        "-    return 1\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].content == "" or files[0].content.strip() == ""
    # the original_content should still hold the old lines so the user
    # can see what was deleted
    assert files[0].original_content is not None
    assert "def gone" in files[0].original_content


def test_multiple_files():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "index ..1\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/b.ts b/b.ts\n"
        "index ..2\n"
        "--- a/b.ts\n"
        "+++ b/b.ts\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 2
    paths = {f.path for f in files}
    assert paths == {"a.py", "b.ts"}


def test_multiple_hunks():
    diff = (
        "diff --git a/big.py b/big.py\n"
        "--- a/big.py\n"
        "+++ b/big.py\n"
        "@@ -1,2 +1,2 @@\n"
        " a\n"
        "-b\n"
        "+B\n"
        "@@ -10,2 +10,2 @@\n"
        " x\n"
        "-y\n"
        "+Y\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert "B" in files[0].content
    assert "Y" in files[0].content
    assert "b" in (files[0].original_content or "")


def test_empty_input():
    assert parse_unified_diff("") == []


def test_no_headers_falls_back_to_snippet():
    files = parse_unified_diff("print('hi')")
    assert len(files) == 1
    assert files[0].path == "snippet.txt"
    assert "print" in files[0].content


def test_infer_language():
    from diff_parser import _infer_language
    assert _infer_language("foo.py") == "python"
    assert _infer_language("Foo.tsx") == "typescript"
    assert _infer_language("noext") is None
    assert _infer_language("") is None


def test_line_numbers_in_original():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -5,3 +5,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        " keep\n"
    )
    files = parse_unified_diff(diff)
    mapping = line_numbers_in_original(files[0])
    # "new" is line 2 in the new file, "old" was line 6 in the original
    # so we expect mapping[2] == 6
    assert mapping.get(2) == 6


def test_path_starting_with_b_keeps_b_prefix():
    """Regression: parts[3].lstrip("b/") would strip any leading b or /
    characters from the path. A file at b/bar/x.py must come out as
    b/bar/x.py, not ar/x.py."""
    diff = (
        "diff --git a/b/bar/x.py b/b/bar/x.py\n"
        "--- a/b/bar/x.py\n"
        "+++ b/b/bar/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].path == "b/bar/x.py"


# --- I5: status + diff (line-level change list) --------------------------


def test_status_modified_for_changed_file():
    files = parse_unified_diff(
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert len(files) == 1
    f = files[0]
    assert f.status == "modified"
    assert f.added_count == 1
    assert f.removed_count == 1
    assert len(f.diff) == 2
    # Old line first, then new line — that's the order `git diff`
    # produces and the order the frontend's unified-diff viewer
    # wants to render.
    assert f.diff[0].type == "removed"
    assert f.diff[0].old_line == 1
    assert f.diff[0].new_line is None
    assert f.diff[0].text == "old"
    assert f.diff[1].type == "added"
    assert f.diff[1].old_line is None
    assert f.diff[1].new_line == 1
    assert f.diff[1].text == "new"


def test_status_added_for_new_file():
    files = parse_unified_diff(
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n+++ b/new.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+a = 1\n"
        "+b = 2\n"
        "+c = 3\n"
    )
    assert files[0].status == "added"
    assert files[0].added_count == 3
    assert files[0].removed_count == 0
    assert [d.type for d in files[0].diff] == ["added", "added", "added"]
    assert [d.new_line for d in files[0].diff] == [1, 2, 3]
    # Added lines never have an old_line.
    assert all(d.old_line is None for d in files[0].diff)


def test_status_deleted_for_removed_file():
    files = parse_unified_diff(
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "--- a/old.py\n+++ /dev/null\n"
        "@@ -1,3 +0,0 @@\n"
        "-x = 1\n"
        "-y = 2\n"
        "-z = 3\n"
    )
    assert files[0].status == "deleted"
    assert files[0].added_count == 0
    assert files[0].removed_count == 3
    assert [d.type for d in files[0].diff] == ["removed", "removed", "removed"]
    assert [d.old_line for d in files[0].diff] == [1, 2, 3]
    # Removed lines never have a new_line.
    assert all(d.new_line is None for d in files[0].diff)


def test_status_renamed_when_old_path_differs():
    files = parse_unified_diff(
        "diff --git a/old_name.py b/new_name.py\n"
        "similarity index 100%\n"
        "rename from old_name.py\n"
        "rename to new_name.py\n"
    )
    assert files[0].status == "renamed"
    assert files[0].path == "new_name.py"
    # A 100% rename has no content change.
    assert files[0].added_count == 0
    assert files[0].removed_count == 0


def test_diff_context_lines_carry_both_line_numbers():
    files = parse_unified_diff(
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -10,3 +10,4 @@\n"
        " ctx1\n"
        "+inserted\n"
        " ctx2\n"
        " ctx3\n"
    )
    f = files[0]
    # 3 context + 1 added = 4 entries. The parser uses RELATIVE
    # line numbers (1-indexed within the reconstructed snippet), not
    # absolute file lines — that's what the AI reviewer reports and
    # what the frontend's diff viewer keys on.
    assert len(f.diff) == 4
    assert [d.type for d in f.diff] == ["context", "added", "context", "context"]
    # Context lines carry BOTH line numbers (in the relative space).
    ctx = [d for d in f.diff if d.type == "context"]
    assert [(d.old_line, d.new_line) for d in ctx] == [(1, 1), (2, 3), (3, 4)]
    # The added line sits between the first and second context line,
    # taking new-line slot 2 (the one the old line 1 → new line 1
    # context left open).
    add = f.diff[1]
    assert add.type == "added"
    assert add.new_line == 2
    assert add.old_line is None


def test_diff_counts_match_diff_lines():
    """The added_count / removed_count fields are denormalized from the
    diff list and the UI uses them for the +N / -M badges in the
    file list. A mismatch would mean the badge and the actual diff
    render disagree, so we pin them together."""
    raw = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1,5 +1,5 @@\n"
        " keep\n"
        "-old1\n"
        "-old2\n"
        "+new1\n"
        "+new2\n"
        "+new3\n"
        " keep\n"
    )
    f = parse_unified_diff(raw)[0]
    assert f.added_count == 3
    assert f.removed_count == 2
    assert sum(1 for d in f.diff if d.type == "added") == f.added_count
    assert sum(1 for d in f.diff if d.type == "removed") == f.removed_count
