from collections.abc import AsyncIterator

import pytest

from lumina.plugins import PluginPipeline, PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.plugins.errors import PluginNotFoundError
from lumina.providers.base import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    Provider,
    TextPart,
)


class MockPipelineProvider(Provider):
    name = "mock_pipeline"

    def __init__(self, *, response_text: str = "ok") -> None:
        self.response_text = response_text
        self.last_request: LLMRequest | None = None
        self.stream_events: list[LLMStreamEvent] = [
            LLMStreamEvent(type="text_delta", delta="a"),
            LLMStreamEvent(type="text_delta", delta="b"),
            LLMStreamEvent(type="text_delta", delta="c"),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.last_request = req
        return LLMResponse(text=self.response_text, model="gpt-4o")

    async def invoke_stream(self, req: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        self.last_request = req
        for event in self.stream_events:
            yield event

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def registry() -> PluginRegistry:
    return PluginRegistry.load_all(get_plugins_root())


@pytest.fixture
def provider() -> MockPipelineProvider:
    return MockPipelineProvider()


@pytest.fixture
def pipeline(registry: PluginRegistry, provider: MockPipelineProvider) -> PluginPipeline:
    return PluginPipeline(
        registry=registry,
        provider=provider,
        settings_thinking_enabled=True,
    )


def _ctx(**kwargs: object) -> PluginContext:
    return PluginContext(**kwargs)  # type: ignore[arg-type]


def test_pl01_single_translate_system(pipeline: PluginPipeline, provider: MockPipelineProvider) -> None:
    req = pipeline.build_request(["translate"], _ctx(selection_text="hello"))
    assert req.messages[0].role == "system"
    system_text = req.messages[0].content[0].text
    assert "translate system prompt placeholder" in system_text


def test_pl02_multi_plugin_system_join(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request(
        ["translate", "explain"],
        _ctx(selection_text="hello"),
    )
    system_text = req.messages[0].content[0].text
    assert "translate system prompt placeholder" in system_text
    assert "explain system prompt placeholder" in system_text
    assert "\n\n" in system_text


def test_pl03_free_chat_user_input(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request([], _ctx(user_input="x"))
    system_text = req.messages[0].content[0].text
    user_text = req.messages[-1].content[0].text
    assert "AI reading assistant" in system_text
    assert user_text == "x"


def test_pl04_free_chat_with_selection(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request([], _ctx(user_input="x", selection_text="y"))
    user_text = req.messages[-1].content[0].text
    assert "x" in user_text
    assert "[Selected content for context]" in user_text
    assert "y" in user_text


def test_pl05_thinking_translate_false(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request(["translate"], _ctx())
    assert req.thinking is False


def test_pl06_thinking_explain_true(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request(["explain"], _ctx())
    assert req.thinking is True


def test_pl07_thinking_or_multi_plugin(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request(["translate", "explain"], _ctx())
    assert req.thinking is True


def test_pl08_thinking_settings_false(registry: PluginRegistry, provider: MockPipelineProvider) -> None:
    pipeline = PluginPipeline(registry, provider, settings_thinking_enabled=False)
    req = pipeline.build_request(["explain"], _ctx())
    assert req.thinking is False


def test_pl09_thinking_free_chat_default_true(pipeline: PluginPipeline) -> None:
    req = pipeline.build_request([], _ctx(user_input="hi"))
    assert req.thinking is True


@pytest.mark.asyncio
async def test_pl10_run_passthrough(pipeline: PluginPipeline, provider: MockPipelineProvider) -> None:
    resp = await pipeline.run(["translate"], _ctx(selection_text="t"))
    assert resp.text == "ok"


@pytest.mark.asyncio
async def test_pl11_run_stream_passthrough(
    pipeline: PluginPipeline,
    provider: MockPipelineProvider,
) -> None:
    events = [event async for event in pipeline.run_stream(["translate"], _ctx())]
    assert len(events) == 4
    assert [e.type for e in events] == ["text_delta", "text_delta", "text_delta", "done"]


def test_pl12_history_in_messages(pipeline: PluginPipeline) -> None:
    history = [LLMMessage(role="user", content=[TextPart(text="prev")])]
    req = pipeline.build_request(["translate"], _ctx(history=history))
    assert req.messages[0].role == "system"
    assert req.messages[1].role == "user"
    assert req.messages[1].content[0].text == "prev"
    assert req.messages[2].role == "user"


def test_pl13_unknown_plugin_raises(pipeline: PluginPipeline) -> None:
    with pytest.raises(PluginNotFoundError):
        pipeline.build_request(["nonexistent"], _ctx())
