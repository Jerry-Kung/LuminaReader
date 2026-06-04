from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from lumina.providers.base import (
    LLMMessage,
    LLMRequest,
    LLMStreamEvent,
    LLMUsage,
    ProviderConfigError,
    TextPart,
)
from lumina.providers.openai_compat import OpenAICompatProvider


def _sample_request(*, stream: bool = True, thinking: bool = False) -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage(role="user", content=[TextPart(text="hi")])],
        stream=stream,
        thinking=thinking,
    )


def _make_chunk(*, content: str | None = None, usage: bool = False):
    chunk = MagicMock()
    if content is not None:
        chunk.choices = [MagicMock(delta=MagicMock(content=content))]
    else:
        chunk.choices = []
    if usage:
        chunk.usage = MagicMock(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )
    else:
        chunk.usage = None
    return chunk


async def _collect_events(provider: OpenAICompatProvider, req: LLMRequest) -> list[LLMStreamEvent]:
    return [ev async for ev in provider.invoke_stream(req)]


def _provider_with_stream(
    *,
    base_url: str = "https://api.openai.com/v1",
    chunks,
    create_error: Exception | None = None,
) -> tuple[OpenAICompatProvider, AsyncMock]:
    create = AsyncMock()
    if create_error is not None:
        create.side_effect = create_error
    else:

        async def _stream():
            for chunk in chunks:
                yield chunk

        async def _create(**kwargs):
            _create.last_kwargs = kwargs
            return _stream()

        create.side_effect = _create

    client = MagicMock()
    client.chat.completions.create = create
    provider = OpenAICompatProvider(
        api_key="sk-test-not-real",
        base_url=base_url,
        model="gpt-4o",
        timeout_seconds=60,
        client=client,
    )
    return provider, create


@pytest.mark.asyncio
async def test_invoke_stream_normal_sequence() -> None:
    chunks = [
        _make_chunk(content="hello"),
        _make_chunk(content=" "),
        _make_chunk(content="world"),
        _make_chunk(usage=True),
    ]
    provider, create = _provider_with_stream(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chunks=chunks,
    )
    req = _sample_request(thinking=True)

    events = await _collect_events(provider, req)

    assert [e.type for e in events] == [
        "text_delta",
        "text_delta",
        "text_delta",
        "usage",
        "done",
    ]
    assert "".join(e.delta for e in events if e.type == "text_delta") == "hello world"
    assert events[-1].model == "gpt-4o"
    assert events[-1].thinking_enabled is True
    assert create.await_args.kwargs["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_invoke_stream_qwen_include_usage() -> None:
    provider, create = _provider_with_stream(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chunks=[_make_chunk(content="x"), _make_chunk(usage=True)],
    )
    await _collect_events(provider, _sample_request())
    assert create.await_args.kwargs["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_invoke_stream_thinking_and_stream_coexist() -> None:
    provider, create = _provider_with_stream(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chunks=[_make_chunk(content="ok"), _make_chunk(usage=True)],
    )
    req = _sample_request(thinking=True)
    events = await _collect_events(provider, req)
    kwargs = create.await_args.kwargs
    assert kwargs["extra_body"] == {"enable_thinking": True}
    assert kwargs["stream_options"] == {"include_usage": True}
    assert events[-1].thinking_enabled is True


@pytest.mark.asyncio
async def test_invoke_stream_thinking_non_qwen_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="lumina.providers.openai_compat")
    provider, create = _provider_with_stream(
        base_url="https://api.openai.com/v1",
        chunks=[_make_chunk(content="ok"), _make_chunk(usage=True)],
    )
    req = _sample_request(thinking=True)
    events = await _collect_events(provider, req)
    assert "extra_body" not in create.await_args.kwargs
    assert events[-1].thinking_enabled is False
    assert any(
        "thinking_not_supported_by_base_url" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_invoke_stream_upstream_5xx_error_event() -> None:
    response = MagicMock(status_code=503)
    err = openai.APIStatusError("upstream", response=response, body=None)
    provider, _ = _provider_with_stream(chunks=[], create_error=err)
    events = await _collect_events(provider, _sample_request())
    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].code == "PROVIDER_ERROR"
    assert events[0].retriable is True


@pytest.mark.asyncio
async def test_invoke_stream_upstream_401_error_event() -> None:
    err = openai.AuthenticationError("auth", response=MagicMock(), body=None)
    provider, _ = _provider_with_stream(chunks=[], create_error=err)
    events = await _collect_events(provider, _sample_request())
    assert events[0].type == "error"
    assert events[0].code == "PROVIDER_ERROR"
    assert events[0].retriable is False


@pytest.mark.asyncio
async def test_invoke_stream_timeout_error_event() -> None:
    provider, _ = _provider_with_stream(
        chunks=[], create_error=openai.APITimeoutError("timeout")
    )
    events = await _collect_events(provider, _sample_request())
    assert events[0].code == "PROVIDER_TIMEOUT"
    assert events[0].retriable is True


@pytest.mark.asyncio
async def test_invoke_stream_connection_error_event() -> None:
    provider, _ = _provider_with_stream(chunks=[], create_error=ConnectionError("lost"))
    events = await _collect_events(provider, _sample_request())
    assert events[0].code == "STREAM_INTERRUPTED"
    assert events[0].retriable is True


@pytest.mark.asyncio
async def test_invoke_stream_requires_stream_true() -> None:
    provider, _ = _provider_with_stream(chunks=[])
    with pytest.raises(ProviderConfigError, match="req.stream=False"):
        await _collect_events(provider, _sample_request(stream=False))


@pytest.mark.asyncio
async def test_invoke_rejects_stream_true() -> None:
    provider, _ = _provider_with_stream(chunks=[])
    with pytest.raises(ProviderConfigError, match="req.stream=True"):
        await provider.invoke(_sample_request(stream=True))
