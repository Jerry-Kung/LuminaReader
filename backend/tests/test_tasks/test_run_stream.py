from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from lumina.providers.base import LLMRequest, LLMStreamEvent, Provider
from lumina.tasks.base import TaskContext
from lumina.tasks.translate import TranslateTask

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


class MockStreamProvider(Provider):
    name = "mock_stream"

    def __init__(self, events: list[LLMStreamEvent]) -> None:
        self.events = events
        self.last_request: LLMRequest | None = None

    async def invoke(self, req: LLMRequest):
        raise NotImplementedError

    async def invoke_stream(self, req: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        self.last_request = req
        for event in self.events:
            yield event

    async def health_check(self) -> bool:
        return True


def _translate_context() -> TaskContext:
    from lumina.schemas.selection import ImagePayload, Selection

    return TaskContext(
        selection=Selection(
            pdf_id=None,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
        ),
        image=ImagePayload(
            mime="image/png",
            data=MINIMAL_PNG_B64,
            width=1,
            height=1,
        ),
        options={"target_lang": "zh-CN"},
        extracted_text="sample text",
    )


async def _collect_stream(gen: AsyncIterator[LLMStreamEvent]) -> list[LLMStreamEvent]:
    return [event async for event in gen]


@pytest.mark.asyncio
async def test_run_stream_default_passthrough() -> None:
    events = [
        LLMStreamEvent(type="text_delta", delta="a"),
        LLMStreamEvent(type="text_delta", delta="b"),
        LLMStreamEvent(type="done", model="gpt-4o"),
    ]
    provider = MockStreamProvider(events)
    task = TranslateTask()
    ctx = _translate_context()

    collected = await _collect_stream(task.run_stream(ctx, provider))

    assert collected == events
    assert provider.last_request is not None
    assert provider.last_request.stream is True


@pytest.mark.asyncio
async def test_openai_compat_invoke_stream_requires_stream_flag() -> None:
    from lumina.providers.openai_compat import OpenAICompatProvider
    from lumina.providers.base import ProviderConfigError, TextPart, LLMMessage

    provider = OpenAICompatProvider(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        timeout_seconds=60,
        client=MagicMock(),
    )
    req = LLMRequest(
        messages=[LLMMessage(role="user", content=[TextPart(text="hi")])],
        stream=False,
    )
    with pytest.raises(ProviderConfigError, match="req.stream=False"):
        async for _ in provider.invoke_stream(req):
            pass
