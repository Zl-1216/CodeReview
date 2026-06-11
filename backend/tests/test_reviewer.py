"""Tests for the review engine (mock path)."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import CodeFile, Review
from reviewer import _severity_rank, _summarize, run_mock_review
from reviewer.rules import RULES as _RULES
from reviewer.rules import rule_matches as _rule_matches


def _review(focuses=("bug", "security", "performance", "style")) -> Review:
    from datetime import datetime
    return Review(
        id="test",
        created_at=datetime.now(),
        title="t",
        file_count=1,
        focuses=list(focuses),
        model="mock",
        status="pending",
    )


def test_mock_review_finds_eval():
    file = CodeFile(
        path="bad.py",
        language="python",
        content="result = eval(user_input)\n",
    )
    review = _review()

    async def run():
        events = []
        async for ev in run_mock_review(review, [file]):
            events.append(ev)
        return events

    events = asyncio.run(run())
    findings = [f for ev in events for f in ev.findings]
    titles = {f.title for f in findings}
    assert "Use of eval()" in titles


def test_mock_review_finds_pickle():
    file = CodeFile(
        path="bad.py",
        language="python",
        content="data = pickle.loads(request.body)\n",
    )

    async def run():
        findings = []
        async for ev in run_mock_review(_review(), [file]):
            findings.extend(ev.findings)
        return findings

    findings = asyncio.run(run())
    assert any(f.title == "pickle deserialization" for f in findings)


def test_mock_review_ignores_unrelated_language():
    """Python-specific rules should not fire on a TypeScript file."""
    file = CodeFile(
        path="ok.ts",
        language="typescript",
        content="const x = 1;\nconsole.log(x);\n",
    )

    async def run():
        findings = []
        async for ev in run_mock_review(_review(), [file]):
            findings.extend(ev.findings)
        return findings

    findings = asyncio.run(run())
    # console.log is info-level; nothing critical/high should be present
    assert all(f.severity in ("info",) for f in findings)


def test_summarize_empty():
    s = _summarize([])
    assert s.total_findings == 0
    assert s.overall_assessment  # non-empty


def test_summarize_counts():
    from models import ReviewFinding
    findings = [
        ReviewFinding(
            file_path="a.py", severity="critical", category="security", title="x", detail="d"
        ),
        ReviewFinding(
            file_path="a.py", severity="high", category="bug", title="y", detail="d"
        ),
        ReviewFinding(
            file_path="a.py", severity="high", category="bug", title="z", detail="d"
        ),
    ]
    s = _summarize(findings)
    assert s.total_findings == 3
    assert s.by_severity["critical"] == 1
    assert s.by_severity["high"] == 2
    assert s.by_category["security"] == 1
    assert s.by_category["bug"] == 2
    # summary should mention the worst severity
    assert "critical" in s.overall_assessment


def test_severity_rank_ordering():
    assert _severity_rank("critical") > _severity_rank("high")
    assert _severity_rank("high") > _severity_rank("medium")
    assert _severity_rank("medium") > _severity_rank("low")
    assert _severity_rank("low") > _severity_rank("info")


def test_rule_matches_python_only():
    """A language-restricted rule should not match other languages."""
    rule = next(r for r in _RULES if r["id"] == "py-eval")
    py = CodeFile(path="a.py", language="python", content="eval(x)")
    ts = CodeFile(path="a.ts", language="typescript", content="eval(x)")
    assert _rule_matches(py, rule)
    assert not _rule_matches(ts, rule)


def test_rule_matches_long_line():
    rule = next(r for r in _RULES if r["id"] == "any-long-line")
    long_line = "x" * 200
    f = CodeFile(path="a.py", language="python", content=long_line)
    assert _rule_matches(f, rule)


def test_mock_review_emits_summary_event():
    file = CodeFile(path="a.py", language="python", content="eval('1')\n")

    async def run():
        events = []
        async for ev in run_mock_review(_review(), [file]):
            events.append(ev)
        return events

    events = asyncio.run(run())
    assert any(ev.summary is not None for ev in events)
    assert events[-1].done is True


# --- Per-rule unit tests ---------------------------------------------------

# Each entry: (rule_id, (content, language)) — picked so the pattern
# fires at least once on the first matching line.
_RULE_POSITIVES = {
    "py-eval": ("eval('1')\n", "python"),
    "py-exec": ("exec(code)\n", "python"),
    "py-shell-true": ("subprocess.run(cmd, shell=True)\n", "python"),
    "py-os-system": ("os.system('ls')\n", "python"),
    "py-pickle": ("data = pickle.loads(b)\n", "python"),
    "py-requests-no-timeout": ("r = requests.get(url)\n", "python"),
    "py-broad-except": ("try:\n    pass\nexcept:\n    pass\n", "python"),
    "py-print": ("print('hi')\n", "python"),
    "py-mutable-default": ("def f(x=[]):\n    pass\n", "python"),
    "py-hash-secret": ("password = 'hunter2'\n", "python"),
    "sql-string-concat": ("q = 'SELECT * FROM t WHERE id=' + id_", "python"),
    "js-eval": ("eval(x);\n", "javascript"),
    "js-innerhtml": ("el.innerHTML = '<b>x</b>';\n", "javascript"),
    "js-dangerously-set": ("<div dangerouslySetInnerHTML={{__html: x}} />\n", "tsx"),
    "js-console-log": ("console.log(x);\n", "javascript"),
    "any-todo": ("# TODO: fix this\n", "python"),
    "any-long-line": ("x" * 200 + "\n", "python"),
    "any-fmt-string": ("x = 'msg' % (name) % 'tail'\n", "python"),
    "any-pdb": ("pdb.set_trace()\n", "python"),
    "js-fetch-no-error-handling": ("data = await fetch(url)\n", "typescript"),
}


@pytest.mark.parametrize(
    "rule_id,content,lang",
    [(rid, content, lang) for rid, (content, lang) in _RULE_POSITIVES.items()],
)
def test_rule_positive(rule_id, content, lang):
    rule = next(r for r in _RULES if r["id"] == rule_id)
    f = CodeFile(path="a.py", language=lang, content=content)
    matches = _rule_matches(f, rule)
    assert matches, f"{rule_id} should match {content!r}"


def test_all_rules_have_positive():
    """Sanity check: every rule in RULES has a positive test case above.
    Adding a rule without a positive case will fail this test."""
    assert set(_RULE_POSITIVES.keys()) == {r["id"] for r in _RULES}


def test_rule_language_restriction():
    """Language-restricted rules must not fire on a non-matching language."""
    rule = next(r for r in _RULES if r["id"] == "py-eval")
    py = CodeFile(path="a.py", language="python", content="eval(x)\n")
    js = CodeFile(path="a.js", language="javascript", content="eval(x)\n")
    # Python file: matches
    assert _rule_matches(py, rule)
    # JS file: not applicable (rule restricted to python)
    assert not _rule_matches(js, rule)


def test_any_language_rule_fires_on_every_language():
    rule = next(r for r in _RULES if r["id"] == "any-long-line")
    for lang in ("python", "javascript", "go", "rust"):
        f = CodeFile(path="a.x", language=lang, content="x" * 200)
        assert _rule_matches(f, rule), f"long-line should fire on {lang}"


def test_mock_review_caps_low_info_per_file():
    """any-long-line fires on every long line; per-file cap is 5."""
    long_line = "x" * 200
    content = "\n".join([long_line] * 20)
    f = CodeFile(path="big.py", language="python", content=content)

    async def run():
        findings = []
        async for ev in run_mock_review(_review(), [f]):
            findings.extend(ev.findings)
        return findings

    findings = asyncio.run(run())
    long_line_findings = [x for x in findings if "160" in x.title]
    assert len(long_line_findings) == 5


def test_mock_review_no_cap_for_security_rules():
    """eval fires once per line and is never capped (severity != low/info)."""
    content = "\n".join(f"x{i} = eval('1')\n" for i in range(20))
    f = CodeFile(path="big.py", language="python", content=content)

    async def run():
        findings = []
        async for ev in run_mock_review(_review(), [f]):
            findings.extend(ev.findings)
        return findings

    findings = asyncio.run(run())
    eval_findings = [x for x in findings if x.title == "Use of eval()"]
    assert len(eval_findings) == 20


def test_mock_review_does_not_duplicate_across_files():
    """Regression: emitting the accumulated list per file caused N²
    dupe. The engine must yield only the new-this-file slice."""

    async def run():
        all_findings = []
        files = [
            CodeFile(path="a.py", language="python", content="result = eval('1')\n"),
            CodeFile(path="b.py", language="python", content="x = eval('2')\n"),
        ]
        async for ev in run_mock_review(_review(), files):
            all_findings.extend(ev.findings)
        return all_findings

    findings = asyncio.run(run())
    eval_findings = [f for f in findings if f.title == "Use of eval()"]
    # 1 finding per file, 2 files → exactly 2
    assert len(eval_findings) == 2
    paths = sorted(f.file_path for f in eval_findings)
    assert paths == ["a.py", "b.py"]


def test_rules_have_precompiled_patterns():
    """Regression for P1-#12: every rule must carry an `_compiled` pattern
    set at module load so `rule_matches` doesn't re.compile per line per
    rule per file."""
    from reviewer.rules import RULES

    for r in RULES:
        assert "_compiled" in r, f"rule {r['id']} has no precompiled pattern"
        # Compiled pattern must be a `re.Pattern`, not the raw string.
        import re
        assert isinstance(r["_compiled"], re.Pattern)
        # And it must behave the same as a fresh compile of the same string.
        assert r["_compiled"].pattern == r["pattern"]


def test_rule_matches_uses_compiled_pattern():
    """`rule_matches` should use the precompiled pattern (or compile a
    fresh one if none is set), not call `re.search` with a string each
    line. We confirm by giving it a rule without `_compiled` and making
    sure it still works."""

    from reviewer.rules import rule_matches

    raw = {"pattern": r"\beval\s*\(", "languages": {"python"}}
    file = CodeFile(path="x.py", language="python", content="eval('1')\n")
    matches = rule_matches(file, raw)
    assert len(matches) == 1
    assert matches[0][0] == 1
