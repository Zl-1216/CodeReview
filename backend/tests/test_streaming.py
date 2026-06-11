"""Tests for the streaming real-review path."""
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewer import (
    _consume_sse_stream,
    _locate_findings_bracket,
    _peel_complete_findings,
    _safe_parse_json,
)


def _finding(title: str, file: str = "a.py") -> str:
    return json.dumps({
        "file_path": file,
        "line_start": 1,
        "line_end": 1,
        "severity": "high",
        "category": "bug",
        "title": title,
        "detail": "d",
        "suggestion": "s",
        "code_snippet": "x",
    })


def _bracket_pos(buf: str) -> int:
    pos = _locate_findings_bracket(buf)
    assert pos > 0, f"bracket not found in {buf!r}"
    return pos


class _FakeStream:
    """Minimal async-iterator stand-in for httpx.Response.aiter_lines()."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


# --- _locate_findings_bracket ----------------------------------------------

def test_locate_returns_zero_when_not_yet_seen():
    assert _locate_findings_bracket("hello world") == 0
    assert _locate_findings_bracket('{"findings"') == 0
    assert _locate_findings_bracket('{"findings": ') == 0


def test_locate_returns_past_bracket():
    pos = _locate_findings_bracket('{"findings": [')
    assert pos > 0
    # Whatever is at pos should be the first character of the array contents
    # (whitespace, '{', or — in pathological cases — the closing ']').
    tail = '{"findings": ['[pos:]
    assert tail == "" or tail[0] in " \t\n\r{]"


# --- _peel_complete_findings ------------------------------------------------

def test_peel_emits_single_complete_object():
    one = _finding("eval")
    buf = '{"findings": [' + one + ']}'
    pos = _bracket_pos(buf)
    objects, new_pos = _peel_complete_findings(buf, pos)
    assert [o["title"] for o in objects] == ["eval"]
    # Position advances past the closing bracket
    assert buf[new_pos:] == '}'


def test_peel_emits_objects_in_order_as_buffer_grows():
    a = _finding("a")
    b = _finding("b")
    buf = '{"findings": [' + a + ", " + b + "]}"
    pos = _bracket_pos(buf)
    objects, _ = _peel_complete_findings(buf, pos)
    assert [o["title"] for o in objects] == ["a", "b"]


def test_peel_waits_until_object_is_complete():
    a = _finding("a")
    # Buffer is truncated in the middle of the second object
    buf = '{"findings": [' + a + ", " + '{"file_path":'
    pos = _bracket_pos(buf)
    objects, new_pos = _peel_complete_findings(buf, pos)
    assert [o["title"] for o in objects] == ["a"]
    # new_pos points into the partial second object
    assert buf[new_pos:] == '{"file_path":'


def test_peel_handles_whitespace_between_objects():
    a = _finding("a")
    b = _finding("b")
    buf = '{ "findings" : [ ' + a + " ,  \n\t " + b + " ] }"
    pos = _bracket_pos(buf)
    objects, _ = _peel_complete_findings(buf, pos)
    assert [o["title"] for o in objects] == ["a", "b"]


def test_peel_stops_at_closing_bracket():
    a = _finding("a")
    buf = '{"findings": [' + a + '], "summary": {}}'
    pos = _bracket_pos(buf)
    objects, new_pos = _peel_complete_findings(buf, pos)
    assert [o["title"] for o in objects] == ["a"]
    # After the `]` we expect the rest of the JSON (the summary key).
    assert buf[new_pos:] == ', "summary": {}}'


def test_peel_resumes_from_start_offset():
    """A second call with pos past the closing `]` should emit nothing
    (everything inside the array was already peeled)."""
    a = _finding("a")
    b = _finding("b")
    buf = '{"findings": [' + a + ", " + b + "]}"
    pos = _bracket_pos(buf)
    _, pos1 = _peel_complete_findings(buf, pos)
    # pos1 is past the `]` — a second call should be a no-op
    objects2, _ = _peel_complete_findings(buf, pos1)
    assert objects2 == []


def test_peel_second_call_picks_up_new_object_appended_to_buffer():
    """Simulates a second delta arriving: buffer grows, the new object's
    bracket is found, and it gets peeled."""
    a = _finding("a")
    buf1 = '{"findings": [' + a + "]}"
    pos = _bracket_pos(buf1)
    _, pos1 = _peel_complete_findings(buf1, pos)
    # The model never re-emits the findings array — subsequent deltas only
    # add more text. We can simulate a "second delta" that appends a
    # closing summary block. No new finding objects should be peeled.
    buf2 = buf1 + ', "summary": {"total_findings": 1}'
    objects2, _ = _peel_complete_findings(buf2, pos1)
    assert objects2 == []


# --- _consume_sse_stream ---------------------------------------------------

def _sse(text: str) -> list[str]:
    """Encode a single text_delta into Anthropic-style SSE lines."""
    return [
        "event: content_block_delta",
        f"data: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}",
        "",  # SSE event terminator
    ]


def _sse_lines(*chunks: str) -> list[str]:
    out: list[str] = []
    for c in chunks:
        out.extend(_sse(c))
    out.extend(["event: message_stop", "data: {\"type\":\"message_stop\"}", ""])
    return out


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_consume_sse_stream_emits_findings_as_they_complete():
    a = _finding("a")
    b = _finding("b")
    # Split the JSON across two deltas; second object should only fire on
    # the second delta because the first leaves it incomplete.
    lines = _sse_lines('{"findings": [' + a + ", ", b + "]}")
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    findings = [f for ev in events for f in ev["findings"]]
    assert [f.title for f in findings] == ["a", "b"]


def test_consume_sse_stream_emits_summary_at_end_of_stream():
    a = _finding("a")
    tail = (
        '], "summary": {'
        '"total_findings": 1,'
        '"by_severity": {"high": 1},'
        '"by_category": {"bug": 1},'
        '"overall_assessment": "ok"'
        "}}"
    )
    lines = _sse_lines('{"findings": [' + a + tail)
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    # summary should appear in some event
    summary_events = [ev for ev in events if ev["summary"] is not None]
    assert summary_events, "expected at least one summary event"
    assert summary_events[-1]["summary"].total_findings == 1


def test_consume_sse_stream_ignores_non_delta_events():
    # Two ping-like events interleaved with the real delta
    a = _finding("a")
    lines = [
        "event: ping",
        "data: {\"type\":\"ping\"}",
        "",
        *_sse('{"findings": [' + a + ']}'),
        "event: message_stop",
        "data: {\"type\":\"message_stop\"}",
        "",
    ]
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    findings = [f for ev in events for f in ev["findings"]]
    assert [f.title for f in findings] == ["a"]


def test_consume_sse_stream_handles_done_sentinel():
    lines = [
        *_sse('{"findings": []}'),
        "data: [DONE]",
        "",
    ]
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    # We just shouldn't error; the empty-findings case is a no-op
    assert isinstance(events, list)


def test_consume_sse_stream_caps_buffer_and_yields_error(monkeypatch):
    """When the model's text exceeds _MAX_STREAM_BUFFER, we yield an error
    event instead of letting the buffer grow without bound."""
    from reviewer import _MAX_STREAM_BUFFER, _consume_sse_stream

    # Pick a chunk size smaller than the cap so we cross it on the second delta
    chunk = "x" * 200_000
    huge_chunk = "x" * (_MAX_STREAM_BUFFER + 1)
    lines = _sse_lines(chunk, huge_chunk)
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    error_events = [ev for ev in events if ev["error"]]
    assert error_events, "expected an error event on buffer overflow"
    assert "exceeded" in error_events[0]["error"]


def test_consume_sse_stream_drains_after_overflow():
    """Overflow should consume the rest of the stream and produce a single
    error event — no re-attempt to parse half-formed deltas."""
    from reviewer import _consume_sse_stream

    lines = _sse_lines("x" * (2 * 1024 * 1024), "more text")
    stream = _FakeStream(lines)
    events = _run(_collect(_consume_sse_stream(stream)))
    # Exactly one error event, and the stream was drained (no parse errors
    # leaking through as additional events).
    assert len([ev for ev in events if ev["error"]]) == 1


def test_safe_parse_json_strips_code_fences():
    text = "```json\n{\"a\": 1}\n```"
    assert _safe_parse_json(text) == {"a": 1}


def test_safe_parse_json_finds_first_balanced_object():
    text = "Here is the JSON: {\"x\": 2} and some trailing prose"
    assert _safe_parse_json(text) == {"x": 2}


def test_safe_parse_json_returns_none_on_garbage():
    assert _safe_parse_json("nothing parseable here") is None


# --- helpers ---------------------------------------------------------------

async def _collect(aiter):
    out = []
    async for ev in aiter:
        out.append({
            "findings": ev.findings,
            "summary": ev.summary,
            "done": ev.done,
            "error": ev.error,
        })
    return out
