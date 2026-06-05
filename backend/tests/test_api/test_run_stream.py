import asyncio
import json
import logging
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport

from lumina.api import _run_core
from lumina.config import Settings, get_settings
from lumina.plugins import PluginPipeline, PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.db.engine import close_all, get_connection
from lumina.db.models import list_messages
from lumina.main import create_app
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    Provider,
)
from lumina.sessions import reset_session_store
from lumina import settings_store

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
PDF_BYTES = b"%PDF-1.4 run stream"


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        event_name = "message"
        data_line = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_line = line.split(":", 1)[1].strip()
        if data_line:
            frames.append((event_name, json.loads(data_line)))
    return frames


def valid_run_payload(pdf_id: str, **overrides: object) -> dict:
    payload = {
        "task_type": "translate",
        "pdf_id": pdf_id,
        "selection": {
            "pdf_id": None,
            "page": 1,
            "x": 0.0,
            "y": 0.0,
            "w": 10.0,
            "h": 10.0,
            "dpi": 144.0,
        },
        "image": {
            "mime": "image/png",
            "data": MINIMAL_PNG_B64,
            "width": 1,
            "height": 1,
        },
        "options": {"target_lang": "zh-CN", "stream": True},
    }
    payload.update(overrides)
    return payload


class MockStreamRunProvider(Provider):
    name = "mock_stream_run"

    def __init__(self, events: list[LLMStreamEvent] | None = None) -> None:
        self.events = events or []
        self.invoke_count = 0
        self.stream_closed = False

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.invoke_count += 1
        return LLMResponse(text="extracted", model="gpt-4o")

    async def invoke_stream(self, req: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        for event in self.events:
            if getattr(event, "_sleep_before", False):
                await asyncio.sleep(event._sleep_before)  # type: ignore[attr-defined]
            yield event
        self.stream_closed = True

    async def health_check(self) -> bool:
        return True


def _manual_prepared(
    *,
    provider: MockStreamRunProvider,
    conversation_id: str,
    meta_payload: dict,
) -> _run_core.PreparedStreamRun:
    registry = PluginRegistry.load_all(get_plugins_root())
    pipeline = PluginPipeline(registry, provider, settings_thinking_enabled=False)
    return _run_core.PreparedStreamRun(
        request_id=meta_payload.get("request_id", "req"),
        start=__import__("time").perf_counter(),
        task_type="translate",
        page=1,
        image_bytes=0,
        project_id=None,
        pdf_id=None,
        conversation_id=conversation_id,
        turn_index=0,
        is_first_turn=True,
        is_screenshot_qa=False,
        extracted_text_chars=1,
        plugin_ids=["translate"],
        plugin_ctx=PluginContext(selection_text="x", target_lang="zh-CN"),
        pipeline=pipeline,
        registry=registry,
        follow_up_user_input=None,
        meta_payload=meta_payload,
    )


def _event_with_sleep(delta: str, seconds: float) -> LLMStreamEvent:
    ev = LLMStreamEvent(type="text_delta", delta=delta)
    ev._sleep_before = seconds  # type: ignore[attr-defined]
    return ev


@pytest.fixture
def stream_pdf_id(data_root):
    return auto_create_project(PDF_BYTES, "streamtest.pdf").pdf_id


@pytest.fixture
def stream_client(data_root, stream_pdf_id) -> TestClient:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    settings_store._reset_state()
    settings_store.bootstrap()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: MockStreamRunProvider()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.stream_pdf_id = stream_pdf_id
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    settings_store._reset_state()
    close_all()
    reset_provider()
    reset_session_store()


def test_stream_response_content_type(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(type="text_delta", delta="hi"),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST",
        "/api/v1/run",
        json=valid_run_payload(stream_client.stream_pdf_id),
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    frames = _parse_sse(body)
    assert frames[0][0] == "meta"
    assert frames[-1][0] == "done"


def test_stream_frame_sequence(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(type="text_delta", delta="<ocr>a</ocr><answer>b"),
            LLMStreamEvent(type="text_delta", delta="c</answer>"),
            LLMStreamEvent(type="usage", usage=LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST", "/api/v1/run", json=valid_run_payload(stream_client.stream_pdf_id)
    ) as response:
        body = "".join(response.iter_text())
    names = [name for name, _ in _parse_sse(body)]
    assert names[0] == "meta"
    assert names.count("text_delta") >= 2
    assert "extracted_text" in names
    assert "usage" in names
    assert names[-1] == "done"


def test_stream_meta_fields_first_turn(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider([LLMStreamEvent(type="done", model="gpt-4o")])
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST", "/api/v1/run", json=valid_run_payload(stream_client.stream_pdf_id)
    ) as response:
        body = "".join(response.iter_text())
    meta = _parse_sse(body)[0][1]
    assert meta["request_id"].startswith("req_")
    assert meta["session_id"].startswith("conv_")
    assert meta["conversation_id"] == meta["session_id"]
    assert meta["task_type"] == "screenshot-qa"
    assert meta["turn_index"] == 0
    assert "model" in meta
    assert "thinking_enabled" in meta
    assert set(meta.keys()) <= {
        "request_id",
        "session_id",
        "conversation_id",
        "task_type",
        "turn_index",
        "model",
        "thinking_enabled",
        "plugins",
    }


def test_v112_first_turn_screenshot_qa_stream(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(type="text_delta", delta="<ocr>OCR</ocr><answer>Ans</answer>"),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST",
        "/api/v1/run",
        json=valid_run_payload(stream_client.stream_pdf_id),
    ) as response:
        body = "".join(response.iter_text())
    events = _parse_sse(body)
    assert events[0][0] == "meta"
    assert events[0][1]["task_type"] == "screenshot-qa"
    ocr_deltas = [
        e for e in events
        if e[0] == "text_delta" and e[1].get("section") == "ocr"
    ]
    answer_deltas = [
        e for e in events
        if e[0] == "text_delta" and e[1].get("section") == "answer"
    ]
    extracted_event = next((e for e in events if e[0] == "extracted_text"), None)
    assert len(ocr_deltas) >= 1
    assert len(answer_deltas) >= 1
    assert extracted_event is not None
    assert extracted_event[1]["text"] == "OCR"
    for _, data in ocr_deltas + answer_deltas:
        for tag in ("<ocr>", "</ocr>", "<answer>", "</answer>"):
            assert tag not in data["delta"]


def test_stream_meta_follow_up_omits_parse_failure(stream_client: TestClient) -> None:
    stream_client.app.dependency_overrides[get_provider] = lambda: MockStreamRunProvider(
        [
            LLMStreamEvent(
                type="text_delta",
                delta="<ocr>first</ocr><answer>ans</answer>",
            ),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    with stream_client.stream(
        "POST", "/api/v1/run", json=valid_run_payload(stream_client.stream_pdf_id)
    ) as response:
        meta_session = _parse_sse("".join(response.iter_text()))[0][1]["session_id"]

    stream_client.app.dependency_overrides[get_provider] = lambda: MockStreamRunProvider(
        [LLMStreamEvent(type="done", model="gpt-4o")]
    )
    with stream_client.stream(
        "POST",
        "/api/v1/run",
        json={
            "task_type": "translate",
            "session_id": meta_session,
            "options": {"target_lang": "zh-CN", "user_question": "more?", "stream": True},
        },
    ) as response:
        meta = _parse_sse("".join(response.iter_text()))[0][1]
    assert "plugins" in meta


@pytest.mark.asyncio
async def test_sse_generator_emits_keep_alive(
    monkeypatch: pytest.MonkeyPatch, data_root
) -> None:
    monkeypatch.setattr(_run_core, "STREAM_HEARTBEAT_SECONDS", 0.05)
    from lumina.sessions import init_session_store

    init_session_store(max_entries=50, ttl_seconds=3600.0)

    async def _slow_stream(req: LLMRequest):
        yield LLMStreamEvent(type="text_delta", delta="one")
        await asyncio.sleep(0.2)
        yield LLMStreamEvent(type="done", model="gpt-4o")

    provider = MockStreamRunProvider()
    provider.invoke_stream = _slow_stream  # type: ignore[method-assign, assignment]
    prepared = _manual_prepared(
        provider=provider,
        conversation_id="conv_hb",
        meta_payload={
            "request_id": "req_hb",
            "session_id": "conv_hb",
            "conversation_id": "conv_hb",
            "task_type": "translate",
            "turn_index": 0,
            "model": "gpt-4o",
            "thinking_enabled": False,
            "plugins": ["translate"],
        },
    )
    prepared.meta_ready.set()
    raw = b"".join(
        [
            chunk
            async for chunk in _run_core.iter_run_sse_bytes(
                prepared=prepared, provider=provider, heartbeat_seconds=0.05
            )
        ]
    )
    assert b":keep-alive" in raw


def test_stream_error_partial_text_kept(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(
                type="text_delta",
                delta="<ocr>part</ocr><answer>ans",
            ),
            LLMStreamEvent(type="error", code="PROVIDER_ERROR", message="fail", retriable=True),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST", "/api/v1/run", json=valid_run_payload(stream_client.stream_pdf_id)
    ) as response:
        frames = _parse_sse("".join(response.iter_text()))
    assert frames[-1][0] == "error"
    assert frames[-1][1]["partial_text_kept"] is True
    assert "done" not in [name for name, _ in frames]


def test_stream_error_no_partial_text(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(type="error", code="PROVIDER_ERROR", message="fail", retriable=False),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST", "/api/v1/run", json=valid_run_payload(stream_client.stream_pdf_id)
    ) as response:
        err = _parse_sse("".join(response.iter_text()))[-1][1]
    assert err["partial_text_kept"] is False


def test_stream_non_stream_json_unchanged(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider()
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    payload = valid_run_payload(stream_client.stream_pdf_id)
    payload["options"]["stream"] = False
    response = stream_client.post("/api/v1/run", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["ok"] is True


def test_stream_meta_includes_plugins(stream_client: TestClient) -> None:
    provider = MockStreamRunProvider(
        [
            LLMStreamEvent(type="text_delta", delta="hi"),
            LLMStreamEvent(type="done", model="gpt-4o"),
        ]
    )
    stream_client.app.dependency_overrides[get_provider] = lambda: provider
    with stream_client.stream(
        "POST",
        "/api/v1/run",
        json=valid_run_payload(stream_client.stream_pdf_id),
    ) as response:
        frames = _parse_sse("".join(response.iter_text()))
    meta = next(data for name, data in frames if name == "meta")
    assert meta["plugins"] == ["screenshot-qa"]


@pytest.mark.asyncio
async def test_sse_generator_marks_stream_aborted_on_cancel(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from lumina.sessions import init_session_store

    caplog.set_level(logging.INFO, logger="lumina.run")
    init_session_store(max_entries=50, ttl_seconds=3600.0)

    async def _slow_stream(req: LLMRequest):
        yield LLMStreamEvent(type="text_delta", delta="partial")
        await asyncio.sleep(60)

    provider = MockStreamRunProvider()
    provider.invoke_stream = _slow_stream  # type: ignore[method-assign, assignment]
    prepared = _manual_prepared(
        provider=provider,
        conversation_id="conv_abort",
        meta_payload={
            "request_id": "req_abort",
            "session_id": "conv_abort",
            "conversation_id": "conv_abort",
            "task_type": "translate",
            "turn_index": 0,
            "model": "gpt-4o",
            "thinking_enabled": False,
            "plugins": ["translate"],
        },
    )
    prepared.meta_ready.set()

    gen = _run_core.iter_run_sse_bytes(prepared=prepared, provider=provider)
    await gen.__anext__()
    await gen.__anext__()
    await gen.aclose()

    stream_logs = [
        getattr(r, "extra_fields", {})
        for r in caplog.records
        if r.message == "run stream completed"
    ]
    assert stream_logs
    assert stream_logs[-1].get("stream_aborted") is True
