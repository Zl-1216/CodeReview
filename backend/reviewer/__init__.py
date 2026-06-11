"""AI review engine.

Two paths:
  * `run_real_review` — calls the Anthropic API and streams findings.
  * `run_mock_review` — rule-based fallback that returns deterministic but
    realistic findings. Used when no `ANTHROPIC_API_KEY` is configured, so
    the UI is fully functional during development.

Both paths return an async iterator of `ReviewEvent` objects. The first
event carries the `Review` skeleton; subsequent events carry batches of
findings and a final event carries the summary.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import config
import httpx
from models import (
    CodeFile,
    Review,
    ReviewFinding,
    ReviewFocus,
    ReviewSummary,
    Severity,
)

logger = logging.getLogger(__name__)


# --- Event types emitted by the engine -------------------------------------

@dataclass
class ReviewEvent:
    """One progress update from the review engine."""
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: ReviewSummary | None = None
    error: str | None = None
    done: bool = False


# --- Public entry point ----------------------------------------------------

async def run_review(review: Review, files: list[CodeFile]) -> AsyncIterator[ReviewEvent]:
    """Run a review, yielding events as findings stream in."""
    if config.ANTHROPIC_API_KEY:
        async for ev in run_real_review(review, files):
            yield ev
    else:
        async for ev in run_mock_review(review, files):
            yield ev


# --- Real (Anthropic) path -------------------------------------------------

_SYSTEM_PROMPT = """You are a senior staff engineer performing a code review.

Your job is to surface concrete, actionable findings in the supplied code diff. \
For every finding you must answer:
  * What is the issue? (one sentence)
  * Why does it matter? (one short paragraph, in the same language as the file)
  * What should change? (a concrete fix, ideally a code snippet)

Focus areas the user has selected: {focuses}

Output format — strict JSON, no prose, no markdown fences:
{{
  "findings": [
    {{
      "file_path": "<string — exactly the path given in the input>",
      "line_start": <int or null>,
      "line_end": <int or null>,
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "category": "bug" | "security" | "performance" | "style" | "best_practice" | "documentation",
      "title": "<short, specific title>",
      "detail": "<why it matters>",
      "suggestion": "<concrete fix, can include code>",
      "code_snippet": "<the offending line(s), verbatim, or null>"
    }}
  ],
  "summary": {{
    "total_findings": <int>,
    "by_severity": {{"critical": <int>, "high": <int>, "medium": <int>, "low": <int>, "info": <int>}},
    "by_category": {{"<category>": <int>, ...}},
    "overall_assessment": "<one short paragraph>"
  }}
}}

Rules:
  * Cite real line numbers from the supplied `content` (post-change).
  * Prefer fewer, high-quality findings over many noisy ones. If a file is fine, omit it.
  * Skip purely cosmetic nitpicks unless `style` is in the focus list.
  * Never invent files or line numbers that aren't in the input.
  * `overall_assessment` should be a one-paragraph verdict a senior engineer would write.
"""


def _build_user_prompt(files: list[CodeFile], focuses: list[ReviewFocus]) -> str:
    chunks: list[str] = []
    chunks.append(f"Review the following {len(files)} file(s). Focus on: {', '.join(focuses)}.")
    chunks.append("")
    for f in files:
        lang = f.language or "unknown"
        chunks.append(f"=== FILE: {f.path}  (language: {lang}) ===")
        if f.original_content is not None:
            chunks.append("--- before ---")
            chunks.append(_truncate(f.original_content))
        chunks.append("--- after (current) ---")
        chunks.append(_truncate(f.content))
        chunks.append("")
    return "\n".join(chunks)


def _truncate(content: str, max_lines: int = config.MAX_DIFF_LINES) -> str:
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    head = lines[: max_lines // 2]
    tail = lines[-(max_lines // 2) :]
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join([*head, f"# ... {omitted} lines omitted ...", *tail])


async def run_real_review(
    review: Review, files: list[CodeFile]
) -> AsyncIterator[ReviewEvent]:
    """Call Anthropic's API and yield findings as they arrive.

    Uses the streaming endpoint (`stream: true`) so the first finding reaches
    the UI long before the model has finished its full reply. We accumulate
    `text_delta` events into a buffer and, after every delta, scan forward
    for the next complete JSON object inside `"findings": [...]` — any
    completed object is emitted immediately and sliced off the buffer.
    Anything left at end-of-stream is parsed one last time.
    """
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": config.ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": review.model or config.ANTHROPIC_MODEL,
        "max_tokens": 4096,
        "stream": True,
        "system": _SYSTEM_PROMPT.format(focuses=", ".join(review.focuses)),
        "messages": [
            {
                "role": "user",
                "content": _build_user_prompt(files, review.focuses),
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT) as client, client.stream(
            "POST",
            f"{config.ANTHROPIC_BASE_URL}/v1/messages",
            headers=headers,
            json=body,
        ) as resp:
            if resp.status_code >= 400:
                body_text = await resp.aread()
                logger.error(
                    "Anthropic API error: %s %s", resp.status_code, body_text[:500]
                )
                yield ReviewEvent(
                    error=f"AI provider returned {resp.status_code}: {body_text[:200]!s}",
                    done=True,
                )
                return

            async for ev in _consume_sse_stream(resp):
                yield ev
    except asyncio.CancelledError:
        # Task cancelled — let it propagate so the caller's finally
        # block runs cleanly.
        raise
    except httpx.TimeoutException:
        yield ReviewEvent(error="AI provider timed out", done=True)
    except Exception as exc:
        logger.exception("AI review failed")
        yield ReviewEvent(error=f"AI review failed: {exc}", done=True)


async def _consume_sse_stream(resp) -> AsyncIterator[ReviewEvent]:
    """Yield ReviewEvents by parsing an Anthropic SSE response.

    Anthropic's stream emits several event types; we only care about
    `content_block_delta` (carries the `text_delta` we accumulate). The
    full text buffer is kept around; a `pos` cursor tracks the offset of
    the first character after the opening `[` of the `"findings": [...]`
    array (or 0 if we haven't located the array yet). After each peel we
    compact the buffer so its size stays proportional to the largest
    in-progress finding rather than the cumulative response length.
    """
    buffer = ""
    pos = 0
    bracket_found = False
    event_type: str | None = None
    overflowed = False
    async for line in resp.aiter_lines():
        if overflowed:
            # Drain the rest of the stream so the connection closes cleanly.
            continue
        if not line:
            # blank line = end of one SSE event
            event_type = None
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].lstrip()
        if payload == "[DONE]":
            break
        if event_type != "content_block_delta":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        delta = data.get("delta") or {}
        if delta.get("type") != "text_delta":
            continue
        buffer += delta.get("text", "")

        if len(buffer) > _MAX_STREAM_BUFFER:
            overflowed = True
            yield ReviewEvent(
                error=f"AI response exceeded {_MAX_STREAM_BUFFER // 1024} KB before parsing could complete",
                done=True,
            )
            break

        if not bracket_found:
            pos = _locate_findings_bracket(buffer)
            if pos == 0:
                # haven't seen "findings": [ yet — keep accumulating
                continue
            bracket_found = True

        peeled, pos = _peel_complete_findings(buffer, pos)
        for raw in peeled:
            try:
                yield ReviewEvent(findings=[ReviewFinding(**raw)])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Skipping malformed finding from stream: %s", exc)

    if overflowed:
        return

    # End of stream. Findings have already been peeled off during streaming,
    # so the only thing left to extract is the summary. We parse the full
    # buffer (the only valid JSON it represents is the whole document).
    if not buffer.strip():
        return
    parsed = _safe_parse_json(buffer)
    if not parsed:
        return
    summary_data = parsed.get("summary")
    if not summary_data:
        return
    summary = ReviewSummary(**summary_data)
    yield ReviewEvent(findings=[], summary=summary, done=True)


# Hard cap on the size of the in-flight text buffer. 1 MB is comfortably
# larger than any plausible finding list (a single finding object is
# typically < 2 KB) so reaching this is a strong signal the model has
# gone off the rails.
_MAX_STREAM_BUFFER = 1 * 1024 * 1024


def _locate_findings_bracket(buffer: str) -> int:
    """Return the index just past the `[` of `"findings": [` in `buffer`.

    Returns 0 if the bracket hasn't arrived yet (caller should keep
    accumulating deltas).
    """
    arr_idx = buffer.find('"findings"')
    if arr_idx < 0:
        return 0
    bracket = buffer.find("[", arr_idx)
    if bracket < 0:
        return 0
    return bracket + 1


def _peel_complete_findings(buffer: str, pos: int) -> tuple[list[dict], int]:
    """Peel complete finding objects from `buffer` starting at `pos`.

    `pos` is the index of the first character after the opening `[` of the
    findings array. The caller is responsible for advancing `pos` past the
    closing `]` (or stopping at the first partial object) between calls.
    Stops at the first partial object. Returns `(objects, new_pos)`.
    """
    peeled: list[dict] = []
    while pos < len(buffer):
        # skip whitespace and the comma between objects
        while pos < len(buffer) and buffer[pos] in " \t\n\r,":
            pos += 1
        if pos >= len(buffer):
            break
        if buffer[pos] == "]":
            # end of the findings array — anything after is summary
            return peeled, pos + 1
        try:
            obj, end = _JSON_DECODER.raw_decode(buffer, pos)
        except json.JSONDecodeError:
            # not enough bytes yet for the next object
            return peeled, pos
        if isinstance(obj, dict):
            peeled.append(obj)
        pos = end
    return peeled, pos


# Reused across all peel calls. raw_decode holds no per-call state, so a
# single module-level instance is safe and saves an allocation per delta.
_JSON_DECODER = json.JSONDecoder()


def _extract_text(data: dict) -> str:
    """Pull the text out of an Anthropic Messages response."""
    parts = data.get("content") or []
    out: list[str] = []
    for block in parts:
        if block.get("type") == "text":
            out.append(block.get("text", ""))
    return "\n".join(out).strip()


def _safe_parse_json(text: str) -> dict | None:
    """Parse JSON, tolerating ```json fences or leading prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # try to find the first {...} block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# --- Mock (rule-based) path -----------------------------------------------
# The rules themselves live in `reviewer/rules.py` so the engine code here
# stays small. Adding a rule is a one-line entry in that file.

async def run_mock_review(
    review: Review, files: list[CodeFile]
) -> AsyncIterator[ReviewEvent]:
    """Rule-based review used when no API key is configured.

    Findings are emitted file-by-file with a small artificial delay so the
    UI's streaming animation is exercised end to end.

    A per-file finding cap protects the UI from rules that fire on every
    line of a long file (e.g. long-line / TODO markers). Rules that match
    "any" language and produce only low/info findings are subject to the
    cap; security/correctness rules always emit every match.
    """
    from reviewer.rules import RULES, rule_matches
    # Hoisted out of the per-file loop: the cap and the set of rules it
    # applies to never change between files. Cheap to compute, but it
    # used to happen for every file.
    cap = 5
    cap_rules = {r["id"] for r in RULES if r["severity"] in ("low", "info") and r["languages"] is None}
    findings: list[ReviewFinding] = []
    for file in files:
        findings_before_file = list(findings)
        per_file_counts: dict[str, int] = {}
        for rule in RULES:
            if rule["id"] in cap_rules:
                remaining = cap - per_file_counts.get(rule["id"], 0)
                if remaining <= 0:
                    continue
            else:
                remaining = None
            for lineno, snippet in rule_matches(file, rule):
                if remaining is not None:
                    if remaining <= 0:
                        break
                    remaining -= 1
                per_file_counts[rule["id"]] = per_file_counts.get(rule["id"], 0) + 1
                findings.append(
                    ReviewFinding(
                        file_path=file.path,
                        line_start=lineno,
                        line_end=lineno,
                        severity=rule["severity"],
                        category=rule["category"],
                        title=rule["title"],
                        detail=rule["detail"],
                        suggestion=rule["suggestion"],
                        code_snippet=snippet,
                    )
                )
        # Yield the slice of findings this file contributed (not the
        # full accumulated list — the consumer appends, so emitting
        # the whole list each time would duplicate every prior file's
        # findings).
        prev_count = len(findings_before_file)
        new_findings = findings[prev_count:]
        if new_findings:
            yield ReviewEvent(findings=new_findings)
            await asyncio.sleep(0.05)

    summary = _summarize(findings)
    yield ReviewEvent(findings=[], summary=summary, done=True)


def _summarize(findings: list[ReviewFinding]) -> ReviewSummary:
    by_sev: dict[str, int] = {s: 0 for s in config.SEVERITY_LEVELS}
    by_cat: dict[str, int] = {c: 0 for c in config.REVIEW_FOCUSES}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    if not findings:
        verdict = "No issues detected by the rule set. If this is a real review, configure ANTHROPIC_API_KEY for a deeper analysis."
    else:
        worst = max(findings, key=lambda f: _severity_rank(f.severity))
        verdict = (
            f"Found {len(findings)} finding(s). Highest severity is {worst.severity} "
            f"({worst.category}) in {worst.file_path}:{worst.line_start or '?'}. "
            "Address critical and high items before merge; medium and low can follow up."
        )
    return ReviewSummary(
        total_findings=len(findings),
        by_severity=by_sev,
        by_category=by_cat,
        overall_assessment=verdict,
    )


def _severity_rank(s: Severity) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(s, 0)
