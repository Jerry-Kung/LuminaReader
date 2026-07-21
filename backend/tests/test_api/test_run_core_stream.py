import asyncio
from collections.abc import AsyncIterator

import pytest

from lumina.api._run_core import PreparedStreamRun, _stream_driver_events, prepare_stream_run
from lumina.config import Settings
from lumina.plugins import PluginPipeline, PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.projects.manager import auto_create_project
from lumina.providers.base import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    Provider,
    TextPart,
)
from lumina.providers.openai_compat import _is_qwen_base_url
from lumina.schemas.selection import ImagePayload, Selection
from lumina.sessions import SessionStore, get_session_store, init_session_store, reset_session_store
from lumina import settings_store

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
PDF_BYTES = b"%PDF-1.4 stream core"


class MockStreamProvider(Provider):
    name = "mock_stream_core"

    def __init__(self, events: list[LLMStreamEvent]) -> None:
        self.events = events
        self.invoke_count = 0
        self.stream_invoke_count = 0
        self.last_stream_request: LLMRequest | None = None
        self.last_invoke_request: LLMRequest | None = None

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.invoke_count += 1
        self.last_invoke_request = req
        return LLMResponse(text="extracted markdown", model="gpt-4o")

    async def invoke_stream(self, req: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        self.stream_invoke_count += 1
        self.last_stream_request = req
        for event in self.events:
            yield event

    async def health_check(self) -> bool:
        return True


def _selection() -> Selection:
    return Selection(
        pdf_id=None,
        page=1,
        x=0.0,
        y=0.0,
        w=10.0,
        h=10.0,
        dpi=144.0,
    )


def _image() -> ImagePayload:
    return ImagePayload(mime="image/png", data=MINIMAL_PNG_B64, width=1, height=1)


def _stream_prepared(
    *,
    provider: MockStreamProvider,
    conversation_id: str,
    project_id: str | None = None,
    pdf_id: str | None = None,
    plugin_ids: list[str] | None = None,
    settings_thinking_enabled: bool = False,
    **kwargs: object,
) -> PreparedStreamRun:
    registry = PluginRegistry.load_all(get_plugins_root())
    pipeline = PluginPipeline(
        registry=registry,
        provider=provider,
        settings_thinking_enabled=settings_thinking_enabled,
    )
    ids = plugin_ids if plugin_ids is not None else ["translate"]
    plugin_ctx = PluginContext(selection_text="source", target_lang="zh-CN")
    defaults: dict[str, object] = {
        "request_id": "req_test",
        "start": __import__("time").perf_counter(),
        "task_type": ids[0] if ids else "chat",
        "page": 1,
        "image_bytes": 0,
        "project_id": project_id,
        "pdf_id": pdf_id,
        "conversation_id": conversation_id,
        "turn_index": 0,
        "is_first_turn": True,
        "is_screenshot_qa": False,
        "extracted_text_chars": None,
        "plugin_ids": ids,
        "plugin_ctx": plugin_ctx,
        "pipeline": pipeline,
        "registry": registry,
        "follow_up_user_input": None,
        "meta_payload": {},
    }
    defaults.update(kwargs)
    return PreparedStreamRun(**defaults)  # type: ignore[arg-type]


async def _collect_events(gen):
    return [event async for event in gen]


@pytest.fixture(autouse=True)
def _session_env(data_root, monkeypatch):
    settings_store._reset_state()
    settings_store.bootstrap()
    reset_session_store()
    init_session_store(max_entries=50, ttl_seconds=3600)
    yield
    reset_session_store()
    settings_store._reset_state()


@pytest.mark.asyncio
async def test_stream_success_persists_without_interrupted_marker(data_root) -> None:
    created = auto_create_project(PDF_BYTES, "stream.pdf")
    store = SessionStore()
    session = await store.create(
        conversation_id="conv_stream1",
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id="sel_1",
        task_type="translate",
        extracted_text="source",
        selection_row=__import__("lumina.db.models", fromlist=["SelectionRow"]).SelectionRow(
            id="sel_1",
            pdf_id=created.pdf_id,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=1,
        ),
        first_user_question=None,
        first_user_content="source",
        first_assistant_text="",
        first_assistant_meta={},
    )
    events = [
        LLMStreamEvent(type="text_delta", delta="hello "),
        LLMStreamEvent(type="text_delta", delta="world"),
        LLMStreamEvent(type="usage", usage=LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)),
        LLMStreamEvent(type="done", model="gpt-4o", thinking_enabled=False),
    ]
    provider = MockStreamProvider(events)
    prepared = _stream_prepared(
        provider=provider,
        conversation_id=session.session_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        request_id="req_test",
        extracted_text_chars=6,
    )
    collected = await _collect_events(
        _stream_driver_events(prepared=prepared, provider=provider)
    )
    assert [e.type for e in collected] == ["text_delta", "text_delta", "usage", "done"]

    from lumina.db.engine import get_connection
    from lumina.db.models import list_messages

    conn = get_connection(created.project_id)
    rows = list_messages(conn, session.session_id)
    assistant = [r for r in rows if r.role == "assistant" and r.turn_index == 0][0]
    assert assistant.content == "hello world"
    assert "[interrupted]" not in assistant.content
    assert assistant.completion_tokens == 2


@pytest.mark.asyncio
async def test_stream_error_persists_interrupted_marker(data_root) -> None:
    created = auto_create_project(PDF_BYTES, "stream2.pdf")
    store = SessionStore()
    session = await store.create(
        conversation_id="conv_stream2",
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id="sel_2",
        task_type="translate",
        extracted_text="source",
        selection_row=__import__("lumina.db.models", fromlist=["SelectionRow"]).SelectionRow(
            id="sel_2",
            pdf_id=created.pdf_id,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=1,
        ),
        first_user_question=None,
        first_user_content="source",
        first_assistant_text="",
        first_assistant_meta={},
    )
    provider = MockStreamProvider(
        [
            LLMStreamEvent(type="text_delta", delta="hello"),
            LLMStreamEvent(type="error", code="PROVIDER_ERROR", message="fail", retriable=False),
        ]
    )
    prepared = _stream_prepared(
        provider=provider,
        conversation_id=session.session_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        request_id="req_test2",
    )
    await _collect_events(_stream_driver_events(prepared=prepared, provider=provider))

    from lumina.db.engine import get_connection
    from lumina.db.models import list_messages

    conn = get_connection(created.project_id)
    assistant = [
        r for r in list_messages(conn, session.session_id) if r.role == "assistant"
    ][0]
    assert assistant.content.endswith("[interrupted]")
    assert assistant.completion_tokens is None


@pytest.mark.asyncio
async def test_stream_cancelled_persists_interrupted(data_root) -> None:
    created = auto_create_project(PDF_BYTES, "stream3.pdf")
    store = SessionStore()
    session = await store.create(
        conversation_id="conv_stream3",
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id="sel_3",
        task_type="translate",
        extracted_text="source",
        selection_row=__import__("lumina.db.models", fromlist=["SelectionRow"]).SelectionRow(
            id="sel_3",
            pdf_id=created.pdf_id,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=1,
        ),
        first_user_question=None,
        first_user_content="source",
        first_assistant_text="",
        first_assistant_meta={},
    )

    async def _aborting_stream(req: LLMRequest):
        provider.last_stream_request = req
        yield LLMStreamEvent(type="text_delta", delta="hello")
        await asyncio.sleep(0)
        raise asyncio.CancelledError()

    provider = MockStreamProvider([])
    provider.invoke_stream = _aborting_stream  # type: ignore[method-assign]
    prepared = _stream_prepared(
        provider=provider,
        conversation_id=session.session_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        request_id="req_test3",
    )
    with pytest.raises(asyncio.CancelledError):
        async for _ in _stream_driver_events(prepared=prepared, provider=provider):
            pass

    from lumina.db.engine import get_connection
    from lumina.db.models import list_messages

    conn = get_connection(created.project_id)
    assistant = [
        r for r in list_messages(conn, session.session_id) if r.role == "assistant"
    ][0]
    assert "hello" in assistant.content
    assert assistant.content.endswith("[interrupted]")


@pytest.mark.asyncio
async def test_first_turn_single_screenshot_qa_stream(monkeypatch) -> None:
    from fastapi import Request
    from lumina.schemas.api import TranslateRequest, TranslateOptions

    created = auto_create_project(PDF_BYTES, "stream4.pdf")
    provider = MockStreamProvider(
        [
            LLMStreamEvent(type="text_delta", delta="ok"),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    scope = {"type": "http", "method": "POST", "headers": [], "path": "/"}
    body = TranslateRequest(
        task_type="translate",
        pdf_id=created.pdf_id,
        selection=_selection(),
        image=_image(),
        options=TranslateOptions(stream=True),
    )
    registry = PluginRegistry.load_all(get_plugins_root())
    prep = await prepare_stream_run(
        request=Request(scope),
        body=body,
        provider=provider,
        settings=Settings(openai_api_key="sk-test", openai_model="gpt-4o"),
        registry=registry,
        request_id="req_first",
    )
    assert not isinstance(prep, __import__("fastapi").responses.JSONResponse)
    assert provider.invoke_count == 0
    assert isinstance(prep, PreparedStreamRun)
    assert prep.is_screenshot_qa is True
    await _collect_events(_stream_driver_events(prepared=prep, provider=provider))
    assert provider.stream_invoke_count == 1
    assert provider.last_stream_request is not None
    assert provider.last_stream_request.stream is True


@pytest.mark.asyncio
async def test_stream_double_empty_skips_provider_and_persists(data_root) -> None:
    """V1.2.4：双落空短路不得触碰 Provider，且落库文本/model/sources_json 需符合固定话术契约。"""
    created = auto_create_project(PDF_BYTES, "recall_stream.pdf")
    store = SessionStore()
    session = await store.create(
        conversation_id="conv_recall_empty",
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id="sel_empty",
        task_type="concept-recall",
        extracted_text="完全不存在XYZ",
        selection_row=__import__("lumina.db.models", fromlist=["SelectionRow"]).SelectionRow(
            id="sel_empty",
            pdf_id=created.pdf_id,
            page=1,
            x=None,
            y=None,
            w=None,
            h=None,
            dpi=None,
            thumbnail_png=None,
            created_at=1,
            type="text",
            text="完全不存在XYZ",
        ),
        first_user_question=None,
        first_user_content="完全不存在XYZ",
        first_assistant_text="",
        first_assistant_meta={"model": None},
        selection_type="text",
    )
    provider = MockStreamProvider([])  # 不应被调用
    plugin_ctx = PluginContext(selection_text="完全不存在XYZ", selection_type="text", target_lang="zh-CN")
    prepared = _stream_prepared(
        provider=provider,
        conversation_id=session.session_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        request_id="req_recall_empty",
        plugin_ids=["concept-recall"],
        task_type="concept-recall",
        recall_sources=[],
        recall_is_empty=True,
    )
    prepared.plugin_ctx = plugin_ctx
    collected = await _collect_events(
        _stream_driver_events(prepared=prepared, provider=provider)
    )
    assert [e.type for e in collected] == ["text_delta", "done"]
    assert provider.invoke_count == 0
    assert provider.stream_invoke_count == 0

    from lumina.db.engine import get_connection
    from lumina.db.models import list_messages

    conn = get_connection(created.project_id)
    rows = list_messages(conn, session.session_id)
    assistant = [r for r in rows if r.role == "assistant" and r.turn_index == 0][0]
    assert "完全不存在XYZ" in assistant.content
    assert assistant.model is None
    assert assistant.sources_json == "[]"


@pytest.mark.asyncio
async def test_stream_injects_thinking_when_enabled(data_root, monkeypatch) -> None:
    store = SessionStore()
    created = auto_create_project(PDF_BYTES, "think.pdf")
    session = await store.create(
        conversation_id="conv_think",
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id="sel_t",
        task_type="translate",
        extracted_text="source",
        selection_row=__import__("lumina.db.models", fromlist=["SelectionRow"]).SelectionRow(
            id="sel_t",
            pdf_id=created.pdf_id,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=1,
        ),
        first_user_question=None,
        first_user_content="source",
        first_assistant_text="",
        first_assistant_meta={},
    )
    settings_store.apply_update(
        {
            "provider": {
                "kind": "openai_compat",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-fake12345678",
                "default_model": "qwen-max",
                "timeout_seconds": 60,
            },
            "task_models": {"extract": None, "translate": None, "explain": None},
            "thinking": {"enabled": True},
        }
    )
    provider = MockStreamProvider([LLMStreamEvent(type="done", model="qwen-max")])
    prepared = _stream_prepared(
        provider=provider,
        conversation_id=session.session_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        request_id="req_think",
        plugin_ids=["explain"],
        task_type="explain",
        settings_thinking_enabled=True,
    )
    await _collect_events(_stream_driver_events(prepared=prepared, provider=provider))
    assert provider.last_stream_request is not None
    assert provider.last_stream_request.thinking is True
