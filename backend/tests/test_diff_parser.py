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
