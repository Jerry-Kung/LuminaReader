import importlib.util

import pytest

from lumina.plugins import get_plugins_root
from lumina.providers.base import LLMStreamEvent


def _load_parser_module():
    parser_path = get_plugins_root() / "screenshot-qa" / "parser.py"
    spec = importlib.util.spec_from_file_location(
        "lumina_screenshot_qa_parser_test",
        parser_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_parser = _load_parser_module()
StreamingTagParser = _parser.StreamingTagParser
parse_full_response = _parser.parse_full_response


async def _iter_events(events: list[LLMStreamEvent]):
    for ev in events:
        yield ev


async def _run_stream(chunks: list[str], *, model: str = "m") -> list:
    events = [LLMStreamEvent(type="text_delta", delta=c) for c in chunks]
    events.append(LLMStreamEvent(type="done", model=model))
    parser = StreamingTagParser()
    return [ev async for ev in parser.feed_stream(_iter_events(events))], parser


def _delta_text(events: list, section: str) -> str:
    return "".join(
        e.delta or ""
        for e in events
        if e.type == "text_delta" and e.section == section
    )


def _assert_no_tag_fragments(events: list) -> None:
    combined = "".join(e.delta or "" for e in events if e.type == "text_delta")
    for tag in ("<ocr>", "</ocr>", "<answer>", "</answer>"):
        assert tag not in combined


@pytest.mark.asyncio
async def test_s01_single_delta_complete_tags() -> None:
    out, parser = await _run_stream(["<ocr>X</ocr><answer>Y</answer>"])
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert any(e.type == "extracted_text" and e.text == "X" for e in out)
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s02_multi_delta_complete_tags() -> None:
    out, parser = await _run_stream(
        ["<ocr>X", "</ocr><answer>Y", "</answer>"]
    )
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert any(e.type == "extracted_text" and e.text == "X" for e in out)
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s03_ocr_open_split_across_chunks() -> None:
    out, parser = await _run_stream(
        ["<o", "cr>X</ocr><answer>Y</answer>"]
    )
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s04_ocr_close_split_across_chunks() -> None:
    out, parser = await _run_stream(
        ["<ocr>X</o", "cr><answer>Y</answer>"]
    )
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s05_answer_open_split_across_chunks() -> None:
    out, parser = await _run_stream(
        ["<ocr>X</ocr><answ", "er>Y</answer>"]
    )
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s06_answer_close_split_across_chunks() -> None:
    out, parser = await _run_stream(
        ["<ocr>X</ocr><answer>Y</answ", "er>"]
    )
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s07_ocr_contains_html_like_chars() -> None:
    text = "<ocr><div>line</div> value < 3</ocr><answer>ok</answer>"
    out, parser = await _run_stream([text])
    assert _delta_text(out, "ocr") == "<div>line</div> value < 3"
    assert _delta_text(out, "answer") == "ok"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s08_tokens_before_ocr_open_discarded() -> None:
    out, parser = await _run_stream(
        ["  \nnoise  <ocr>Real</ocr><answer>Ans</answer>"]
    )
    assert _delta_text(out, "ocr") == "Real"
    assert _delta_text(out, "answer") == "Ans"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s09_exceed_256_without_ocr_open() -> None:
    long_prefix = "a" * 257
    out, parser = await _run_stream([long_prefix, " more text"])
    assert parser.failure_reason == "ocr_open_not_found"
    assert _delta_text(out, "ocr") == ""
    assert "a" * 257 in _delta_text(out, "answer")
    assert " more text" in _delta_text(out, "answer")
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s10_ocr_unclosed_on_done() -> None:
    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>X"),
        LLMStreamEvent(type="done", model="m"),
    ]
    parser = StreamingTagParser()
    out = [ev async for ev in parser.feed_stream(_iter_events(events))]
    assert parser.failure_reason == "ocr_close_not_found"
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == ""
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s11_missing_answer_open_on_done() -> None:
    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>X</ocr>"),
        LLMStreamEvent(type="done", model="m"),
    ]
    parser = StreamingTagParser()
    out = [ev async for ev in parser.feed_stream(_iter_events(events))]
    assert parser.failure_reason == "answer_open_not_found"
    assert _delta_text(out, "ocr") == "X"
    assert any(e.type == "extracted_text" and e.text == "X" for e in out)
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s12_unclosed_answer_on_done() -> None:
    out, parser = await _run_stream(["<ocr>X</ocr><answer>Y"])
    assert parser.failure_reason is None
    assert _delta_text(out, "ocr") == "X"
    assert _delta_text(out, "answer") == "Y"
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s13_empty_ocr_and_answer_sections() -> None:
    out, parser = await _run_stream(["<ocr></ocr><answer></answer>"])
    assert any(
        e.type == "text_delta" and e.section == "ocr" and e.delta == ""
        for e in out
    )
    assert any(
        e.type == "text_delta" and e.section == "answer" and e.delta == ""
        for e in out
    )
    assert any(e.type == "extracted_text" and e.text == "" for e in out)
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s14_markdown_math_in_ocr() -> None:
    out, parser = await _run_stream(
        ["<ocr>$\\alpha$</ocr><answer>done</answer>"]
    )
    assert _delta_text(out, "ocr") == "$\\alpha$"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s15_chinese_and_emoji_in_ocr() -> None:
    out, parser = await _run_stream(
        ["<ocr>中文😀</ocr><answer>答</answer>"]
    )
    assert _delta_text(out, "ocr") == "中文😀"
    assert _delta_text(out, "answer") == "答"
    assert parser.failure_reason is None
    _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s16_no_tag_fragments_in_any_case() -> None:
    cases = [
        ["<ocr>A</ocr><answer>B</answer>"],
        ["plain", " text"],
        ["<ocr>X</ocr><answer>Y"],
    ]
    for chunks in cases:
        out, _ = await _run_stream(chunks)
        _assert_no_tag_fragments(out)


@pytest.mark.asyncio
async def test_s17_upstream_error_passthrough() -> None:
    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>X"),
        LLMStreamEvent(
            type="error",
            code="STREAM_INTERRUPTED",
            message="interrupted",
            retriable=True,
        ),
    ]
    parser = StreamingTagParser()
    out = [ev async for ev in parser.feed_stream(_iter_events(events))]
    assert out[-1].type == "error"
    assert out[-1].code == "STREAM_INTERRUPTED"
    assert out[-1].section is None


@pytest.mark.asyncio
async def test_s18_usage_event_passthrough() -> None:
    from lumina.providers.base import LLMUsage

    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>X</ocr><answer>Y</answer>"),
        LLMStreamEvent(
            type="usage",
            usage=LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        ),
        LLMStreamEvent(type="done", model="m"),
    ]
    parser = StreamingTagParser()
    out = [ev async for ev in parser.feed_stream(_iter_events(events))]
    usage_events = [e for e in out if e.type == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0].section is None


def test_p01_parse_full_response_success() -> None:
    result, reason = parse_full_response(
        "<ocr>OCR</ocr><answer>Ans</answer>"
    )
    assert result.extracted_text == "OCR"
    assert result.answer == "Ans"
    assert reason is None


def test_p02_parse_full_response_ocr_only() -> None:
    result, reason = parse_full_response("<ocr>only ocr</ocr>")
    assert result.extracted_text is None
    assert result.answer == "only ocr"
    assert reason == "non_stream_regex_failed"


def test_p03_parse_full_response_answer_only() -> None:
    result, reason = parse_full_response("<answer>only ans</answer>")
    assert result.extracted_text is None
    assert result.answer == "only ans"
    assert reason == "non_stream_regex_failed"


def test_p04_parse_full_response_no_tags() -> None:
    result, reason = parse_full_response("plain text")
    assert result.extracted_text is None
    assert result.answer == "plain text"
    assert reason == "non_stream_regex_failed"


def test_p05_parse_full_response_strips_residual_tags() -> None:
    result, reason = parse_full_response("before <ocr>frag</answer> after")
    assert result.extracted_text is None
    assert result.answer == "before frag after"
    assert reason == "non_stream_regex_failed"
