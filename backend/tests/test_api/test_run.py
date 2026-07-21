import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.main import create_app
from lumina.projects.manager import auto_create_project
from lumina import settings_store
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import (
    ImagePart,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderTimeout,
)
from lumina.providers.errors import StreamUnsupportedError
from lumina.providers.openai_compat import _is_qwen_base_url
from lumina.sessions import get_session_store, reset_session_store

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
MOCK_SCREENSHOT_QA_RESPONSE = "<ocr>mock</ocr><answer>mock</answer>"


def valid_run_payload(task_type: str = "translate", pdf_id: str | None = None, **overrides: object) -> dict:
    payload = {
        "task_type": task_type,
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
        "options": {"target_lang": "zh-CN"},
    }
    payload.update(overrides)
    return payload


class MockRunProvider(Provider):
    name = "mock_run"

    def __init__(
        self,
        *,
        response_text: str = MOCK_SCREENSHOT_QA_RESPONSE,
        invoke_error: Exception | None = None,
        invoke_errors: list[Exception | None] | None = None,
    ) -> None:
        self.response_text = response_text
        self.invoke_error = invoke_error
        self.invoke_errors = invoke_errors
        self.last_request: LLMRequest | None = None
        self.all_requests: list[LLMRequest] = []
        self.invoke_count = 0

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.invoke_count += 1
        self.last_request = req
        self.all_requests.append(req)
        if self.invoke_errors is not None:
            index = self.invoke_count - 1
            if index < len(self.invoke_errors) and self.invoke_errors[index] is not None:
                raise self.invoke_errors[index]
        if self.invoke_error is not None:
            raise self.invoke_error
        model = "gpt-4o"
        if req.extras and req.extras.get("model_override"):
            model = str(req.extras["model_override"])
        thinking_active = False
        if req.thinking:
            try:
                base_url = settings_store.get_current().base_url
                thinking_active = _is_qwen_base_url(base_url)
            except RuntimeError:
                thinking_active = False
        return LLMResponse(
            text=self.response_text,
            model=model,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            thinking_enabled=thinking_active,
        )

    async def invoke_stream(self, req: LLMRequest):
        raise StreamUnsupportedError("streaming not supported in mock run provider")
        yield LLMStreamEvent(type="done")  # pragma: no cover

    async def health_check(self) -> bool:
        return True


PDF_BYTES = b"%PDF-1.4 run test"


@pytest.fixture
def default_pdf_id(data_root):
    return auto_create_project(PDF_BYTES, "runtest.pdf").pdf_id


@pytest.fixture
def run_client(data_root, default_pdf_id) -> TestClient:
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
    app.dependency_overrides[get_provider] = lambda: MockRunProvider()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.default_pdf_id = default_pdf_id
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    settings_store._reset_state()
    close_all()
    reset_provider()
    reset_session_store()


def run_payload(client: TestClient, **overrides: object) -> dict:
    return valid_run_payload(pdf_id=client.default_pdf_id, **overrides)


def follow_up_payload(session_id: str, **overrides: object) -> dict:
    payload = {
        "task_type": "translate",
        "session_id": session_id,
        "selection": None,
        "image": None,
        "options": {"target_lang": "zh-CN", "user_question": "next q"},
    }
    payload.update(overrides)
    return payload


def text_selection_payload(
    pdf_id: str,
    *,
    text: str = "Hello, world.",
    page: int = 5,
    page_end: int | None = None,
    plugins: list[str] | None = None,
    **overrides: object,
) -> dict:
    page_end = page_end if page_end is not None else page
    payload = {
        "task_type": "translate",
        "pdf_id": pdf_id,
        "selection": {
            "type": "text",
            "pdf_id": None,
            "page": page,
            "page_end": page_end,
            "text": text,
            "segments": [
                {
                    "page": page,
                    "text": text,
                    "offset_start": 0,
                    "offset_end": len(text),
                }
            ],
        },
        "image": None,
        "plugins": plugins if plugins is not None else ["translate"],
        "options": {"target_lang": "zh-CN"},
    }
    payload.update(overrides)
    return payload


def _request_has_image_part(req: LLMRequest) -> bool:
    for msg in req.messages:
        for part in msg.content:
            if isinstance(part, ImagePart):
                return True
    return False


def test_run_translate_success(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["text"] == "mock"
    assert body["data"]["extracted_text"] == "mock"
    assert body["data"]["meta"]["request_id"].startswith("req_")
    assert body["data"]["meta"]["task_type"] == "screenshot-qa"
    assert body["data"]["meta"]["plugins"] == ["screenshot-qa"]
    assert body["data"]["session_id"]
    assert body["data"]["meta"]["turn_index"] == 0


def test_run_explain_success(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="explain"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["meta"]["task_type"] == "screenshot-qa"
    assert body["data"]["session_id"]
    assert body["data"]["meta"]["turn_index"] == 0
    assert provider.last_request is not None
    system_text = provider.last_request.messages[0].content[0].text
    assert "LuminaReader" in system_text


def test_run_unsupported_task_coerced_on_first_turn_image(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="qa"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["meta"]["task_type"] == "screenshot-qa"


def test_run_invalid_mime(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["image"] = {**payload["image"], "mime": "image/jpeg"}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_invalid_base64(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["image"] = {**payload["image"], "data": "not-valid-base64!!!"}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_missing_selection(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["selection"] = None
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_payload_too_large(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["image"] = {**payload["image"], "data": "A" * (8 * 1024 * 1024)}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_run_provider_timeout(run_client: TestClient) -> None:
    run_client.app.dependency_overrides[get_provider] = lambda: MockRunProvider(
        invoke_error=ProviderTimeout("timed out")
    )
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_TIMEOUT"
    assert "sk-" not in response.text


def test_run_provider_auth_error(run_client: TestClient) -> None:
    run_client.app.dependency_overrides[get_provider] = lambda: MockRunProvider(
        invoke_error=ProviderAuthError("auth failed")
    )
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "auth failed" not in response.text


def test_run_health(run_client: TestClient) -> None:
    response = run_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["service"] == "lumina-backend"
    assert isinstance(body["data"]["provider_ready"], bool)


def test_run_first_turn_single_screenshot_qa_invoke(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    assert len(provider.all_requests) == 1
    system_text = provider.all_requests[0].messages[0].content[0].text.lower()
    assert "<ocr>" in system_text or "ocr" in system_text
    user_content = provider.all_requests[0].messages[-1].content
    assert any(part.type == "image" for part in user_content)


def test_run_first_turn_response_contains_session_id_and_turn_index_zero(
    run_client: TestClient,
) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    body = response.json()
    assert body["data"]["session_id"]
    assert body["data"]["meta"]["turn_index"] == 0


def test_run_first_turn_with_user_question(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    payload = run_payload(run_client,
        options={"target_lang": "zh-CN", "user_question": "为什么 V=8?"},
    )
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 200
    user_content = provider.all_requests[0].messages[-1].content
    combined = "".join(part.text for part in user_content if part.type == "text")
    assert "为什么 V=8?" in combined


def test_run_first_turn_missing_image(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["image"] = None
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_first_turn_pipeline_failure_does_not_create_session(
    run_client: TestClient,
) -> None:
    provider = MockRunProvider(invoke_errors=[ProviderTimeout("timed out")])
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "PROVIDER_TIMEOUT"
    assert len(get_session_store()) == 0


def test_run_follow_up_success(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    provider.all_requests.clear()
    provider.invoke_count = 0

    second = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert second.status_code == 200
    body = second.json()
    assert body["data"]["session_id"] == session_id
    assert body["data"]["meta"]["turn_index"] == 1
    assert len(provider.all_requests) == 1
    assert len(provider.all_requests[0].messages) >= 4
    assert all(
        part.type != "image"
        for message in provider.all_requests[0].messages
        for part in message.content
    )


def test_run_follow_up_session_not_found(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=follow_up_payload("conv_does_not_exist"),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_run_follow_up_cross_plugin_allowed(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    session_id = first.json()["data"]["session_id"]
    response = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, task_type="explain"),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["explain"]


def test_run_follow_up_rejects_image(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    payload = follow_up_payload(session_id)
    payload["image"] = run_payload(run_client)["image"]
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_follow_up_requires_user_question(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    payload = follow_up_payload(session_id)
    payload["task_type"] = "chat"
    payload["plugins"] = []
    payload["user_input"] = None
    payload["options"] = {"target_lang": "zh-CN"}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_follow_up_turn_index_increments(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    assert first.json()["data"]["meta"]["turn_index"] == 0

    for expected_turn in (1, 2, 3):
        response = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
        assert response.status_code == 200
        assert response.json()["data"]["meta"]["turn_index"] == expected_turn


def test_run_follow_up_appends_to_session_messages(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    store = get_session_store()
    session = asyncio.run(store.get(session_id))
    assert session is not None
    assert len(session.messages) == 4


def test_run_follow_up_session_survives_driving_task_failure(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    run_client.app.dependency_overrides[get_provider] = lambda: MockRunProvider(
        invoke_error=ProviderTimeout("timed out")
    )
    response = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert response.status_code == 504
    store = get_session_store()
    session = asyncio.run(store.get(session_id))
    assert session is not None


def test_run_first_turn_log_includes_session_and_extract_fields(
    run_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="lumina.run")
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    run_logs = [
        getattr(record, "extra_fields", {})
        for record in caplog.records
        if record.message == "run call completed"
    ]
    assert run_logs
    fields = run_logs[-1]
    assert fields["session_id"].startswith("conv_")
    assert fields["turn_index"] == 0
    assert fields["parse_failure_reason"] == ""
    assert isinstance(fields["extracted_text_chars"], int)


def test_run_follow_up_log_omits_extract_fields(
    run_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    caplog.clear()
    caplog.set_level(logging.INFO, logger="lumina.run")
    response = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert response.status_code == 200
    run_logs = [
        getattr(record, "extra_fields", {})
        for record in caplog.records
        if record.message == "run call completed"
    ]
    follow_up_log = next(item for item in run_logs if item.get("turn_index") == 1)
    assert follow_up_log["session_id"] == session_id
    assert follow_up_log["parse_failure_reason"] == ""
    assert follow_up_log["extracted_text_chars"] == ""


def test_first_turn_thumbnail_written(run_client: TestClient) -> None:
    from lumina.db.engine import get_connection
    from lumina.projects.manager import lookup_project_by_pdf_id

    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    pdf_id = run_client.default_pdf_id
    entry = lookup_project_by_pdf_id(pdf_id)
    conn = get_connection(entry.id)
    row = conn.execute(
        "SELECT thumbnail_png FROM selections ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row[0] is not None
    assert len(row[0]) <= 200 * 1024


def test_first_turn_thumbnail_none_on_failure_does_not_block(
    run_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lumina.db.engine import get_connection
    from lumina.projects.manager import lookup_project_by_pdf_id

    def boom(_: str):
        raise RuntimeError("thumbnail failed")

    monkeypatch.setattr("lumina.api._run_core.render_thumbnail", boom)
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    pdf_id = run_client.default_pdf_id
    entry = lookup_project_by_pdf_id(pdf_id)
    conn = get_connection(entry.id)
    row = conn.execute(
        "SELECT thumbnail_png FROM selections ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row[0] is None


def _put_settings(
    run_client: TestClient,
    *,
    base_url: str = "https://api.openai.com/v1",
    thinking_enabled: bool | None = None,
    **task_overrides: str | None,
) -> None:
    payload = {
        "provider": {
            "kind": "openai_compat",
            "base_url": base_url,
            "api_key": "sk-fake-test1234",
            "default_model": "gpt-4o",
            "timeout_seconds": 60,
        },
        "task_models": {
            "extract": None,
            "translate": None,
            "explain": None,
            **task_overrides,
        },
    }
    if thinking_enabled is not None:
        payload["thinking"] = {"enabled": thinking_enabled}
    response = run_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 200


def test_run_thinking_disabled_meta_false(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["thinking_enabled"] is False


def test_run_thinking_enabled_qwen_meta_true(run_client: TestClient) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    response = run_client.post(
        "/api/v1/run", json=run_payload(run_client, task_type="explain")
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["thinking_enabled"] is True


def test_run_thinking_enabled_non_qwen_meta_false(run_client: TestClient) -> None:
    _put_settings(run_client, thinking_enabled=True)
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["thinking_enabled"] is False


def test_run_screenshot_qa_thinking_enabled_on_qwen(run_client: TestClient) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    assert provider.all_requests[0].thinking is True


def test_run_follow_up_injects_thinking(run_client: TestClient) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post(
        "/api/v1/run", json=run_payload(run_client, task_type="explain")
    )
    session_id = first.json()["data"]["session_id"]
    provider.all_requests.clear()
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, task_type="explain"),
    )
    assert second.status_code == 200
    assert len(provider.all_requests) == 1
    assert provider.all_requests[0].thinking is True


def test_run_log_includes_thinking_enabled(
    run_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    caplog.set_level(logging.INFO, logger="lumina.run")
    response = run_client.post(
        "/api/v1/run", json=run_payload(run_client, task_type="explain")
    )
    assert response.status_code == 200
    run_logs = [
        getattr(record, "extra_fields", {})
        for record in caplog.records
        if record.message == "run call completed"
    ]
    assert run_logs[-1]["thinking_enabled"] is True


def test_run_first_turn_screenshot_qa_ignores_task_model_override(run_client: TestClient) -> None:
    _put_settings(run_client, translate="gpt-4o-mini")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    assert provider.all_requests[0].extras.get("model_override") is None
    assert response.json()["data"]["meta"]["model"] == "gpt-4o"


def test_run_first_turn_no_model_override(run_client: TestClient) -> None:
    _put_settings(run_client, translate="gpt-4o-mini")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="explain"))
    assert response.status_code == 200
    assert provider.all_requests[0].extras.get("model_override") is None
    assert response.json()["data"]["meta"]["model"] == "gpt-4o"


def test_run_follow_up_uses_translate_override(run_client: TestClient) -> None:
    _put_settings(run_client, translate="gpt-4o-mini")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    session_id = first.json()["data"]["session_id"]
    for _ in range(2):
        response = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
        assert response.status_code == 200
        assert response.json()["data"]["meta"]["model"] == "gpt-4o-mini"
    follow_up_requests = provider.all_requests[1:]
    assert all(req.extras.get("model_override") == "gpt-4o-mini" for req in follow_up_requests)


def test_r02_01_plugins_translate_coerced_to_screenshot_qa(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, plugins=["translate"]),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_02_unknown_plugin_id_coerced_on_first_turn(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, plugins=["nonexistent"]),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_03_first_turn_image_coerced_to_screenshot_qa(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            task_type="chat",
            plugins=[],
            user_input="hi",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_04_empty_plugins_and_input_defaults_screenshot_qa(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            task_type="chat",
            plugins=[],
            user_input=None,
            options={"target_lang": "zh-CN", "user_question": None},
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_05_legacy_task_type_user_question(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            task_type="translate",
            options={"target_lang": "zh-CN", "user_question": "why?"},
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_06_task_type_chat_coerced(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            task_type="chat",
            user_input="what is this?",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_07_dictionary_coerced_to_screenshot_qa(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="<ocr>one two three four five</ocr><answer>x</answer>")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, plugins=["dictionary"]),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r02_09_cross_plugin_translate_then_explain(run_client: TestClient) -> None:
    first = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, plugins=["translate"]),
    )
    session_id = first.json()["data"]["session_id"]
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(
            session_id,
            task_type="explain",
            options={"target_lang": "zh-CN", "user_question": "explain more"},
        ),
    )
    assert second.status_code == 200
    assert second.json()["data"]["meta"]["plugins"] == ["explain"]


def test_r03_03_multi_plugin_coerced_to_screenshot_qa(run_client: TestClient) -> None:
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            plugins=["translate", "explain"],
            user_input="why?",
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["plugins"] == ["screenshot-qa"]


def test_r03_06_thinking_screenshot_qa_enabled(run_client: TestClient) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, task_type="explain"),
    )
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["thinking_enabled"] is True


def test_r03_07_thinking_screenshot_qa_on_qwen(run_client: TestClient) -> None:
    _put_settings(
        run_client,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_enabled=True,
    )
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    assert response.json()["data"]["meta"]["thinking_enabled"] is True


def test_r03_09_log_plugins_translate(
    run_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="lumina.run")
    response = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert response.status_code == 200
    logs = [
        getattr(r, "extra_fields", {})
        for r in caplog.records
        if r.message == "run call completed"
    ]
    assert logs[-1]["plugins"] == "screenshot-qa"


def test_r03_10_log_plugins_screenshot_qa(
    run_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="lumina.run")
    response = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, task_type="chat", user_input="hi"),
    )
    assert response.status_code == 200
    logs = [
        getattr(r, "extra_fields", {})
        for r in caplog.records
        if r.message == "run call completed"
    ]
    assert logs[-1]["plugins"] == "screenshot-qa"


def test_l02_screenshot_qa_then_translate_follow_up(run_client: TestClient) -> None:
    first = run_client.post(
        "/api/v1/run",
        json=run_payload(
            run_client,
            task_type="chat",
            plugins=[],
            user_input="hello",
        ),
    )
    session_id = first.json()["data"]["session_id"]
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(
            session_id,
            task_type="translate",
            plugins=["translate"],
        ),
    )
    assert second.status_code == 200
    assert second.json()["data"]["meta"]["plugins"] == ["translate"]


def test_l03_screenshot_qa_then_dictionary_follow_up(run_client: TestClient) -> None:
    first = run_client.post(
        "/api/v1/run",
        json=run_payload(run_client, plugins=["translate", "explain"]),
    )
    session_id = first.json()["data"]["session_id"]
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(
            session_id,
            plugins=["dictionary"],
        ),
    )
    assert second.status_code == 200
    assert second.json()["data"]["meta"]["plugins"] == ["dictionary"]


def test_run_settings_change_takes_effect_immediately(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    session_id = first.json()["data"]["session_id"]
    assert first.json()["data"]["meta"]["model"] == "gpt-4o"

    _put_settings(run_client, translate="gpt-4o-mini")
    second = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert second.json()["data"]["meta"]["model"] == "gpt-4o-mini"


def test_v112_first_turn_screenshot_qa_success(run_client: TestClient) -> None:
    provider = MockRunProvider(
        response_text="<ocr>OCR content</ocr><answer>Answer content</answer>"
    )
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = run_payload(
        run_client,
        task_type="translate",
        plugins=["translate"],
        user_input="Explain this image",
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == "Answer content"
    assert data["extracted_text"] == "OCR content"
    assert data["meta"]["task_type"] == "screenshot-qa"
    assert data["meta"]["plugins"] == ["screenshot-qa"]
    session_id = data["session_id"]
    session = asyncio.run(get_session_store().get(session_id))
    assert session is not None
    assert session.extracted_text == "OCR content"
    assert session.task_type == "screenshot-qa"


def test_v112_first_turn_parse_failure(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="Just plain text without any tags.")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    resp = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == "Just plain text without any tags."
    assert data["extracted_text"] is None
    session_id = data["session_id"]
    session = asyncio.run(get_session_store().get(session_id))
    assert session is not None
    assert session.extracted_text == ""


def test_v112_followup_ocr_unavailable(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="Just plain text without any tags.")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    provider.invoke_count = 0
    resp = run_client.post(
        "/api/v1/run",
        json={
            "task_type": "chat",
            "plugins": [],
            "user_input": "继续追问",
            "session_id": session_id,
            "selection": None,
            "image": None,
            "options": {"target_lang": "zh-CN"},
        },
    )
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "OCR_TEXT_UNAVAILABLE"
    assert "识别文本缺失" in err["message"]
    assert provider.invoke_count == 0


def test_v112_followup_cross_plugin_explain(run_client: TestClient) -> None:
    provider = MockRunProvider(
        response_text="<ocr>OCR content</ocr><answer>Answer content</answer>"
    )
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client))
    session_id = first.json()["data"]["session_id"]
    resp = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(
            session_id,
            task_type="explain",
            plugins=["explain"],
            options={"target_lang": "zh-CN", "user_question": "再详细说说"},
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["meta"]["plugins"] == ["explain"]


def test_v112_legacy_translate_coerced(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = run_payload(
        run_client,
        task_type="translate",
        user_input=None,
        options={"target_lang": "zh-CN", "user_question": "翻译这段"},
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["meta"]["task_type"] == "screenshot-qa"
    assert data["meta"]["plugins"] == ["screenshot-qa"]
    user_text = provider.all_requests[0].messages[-1].content[0].text
    assert "翻译这段" in user_text


def test_text_first_turn_translate(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="translated text")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = text_selection_payload(run_client.default_pdf_id, plugins=["translate"])
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["extracted_text"] == "Hello, world."
    assert data["meta"]["task_type"] == "translate"
    assert data["meta"]["plugins"] == ["translate"]
    assert provider.invoke_count == 1
    assert provider.last_request is not None
    assert not _request_has_image_part(provider.last_request)


def test_text_first_turn_explain(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="explained")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = text_selection_payload(
        run_client.default_pdf_id,
        plugins=["explain"],
        user_input="为什么",
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    assert resp.json()["data"]["meta"]["task_type"] == "explain"


def test_text_first_turn_dictionary_legal(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="dict")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = text_selection_payload(
        run_client.default_pdf_id,
        text="hello world",
        plugins=["dictionary"],
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    assert resp.json()["data"]["meta"]["plugins"] == ["dictionary"]


def test_text_first_turn_dictionary_overword(run_client: TestClient) -> None:
    body = text_selection_payload(
        run_client.default_pdf_id,
        text="one two three four five six seven eight nine ten",
        plugins=["dictionary"],
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_text_first_turn_chat(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="chat reply")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    body = text_selection_payload(
        run_client.default_pdf_id,
        plugins=[],
        user_input="hi",
        task_type="chat",
    )
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 200
    assert resp.json()["data"]["meta"]["task_type"] == "chat"


def test_text_first_turn_with_image_rejected(run_client: TestClient) -> None:
    body = text_selection_payload(run_client.default_pdf_id)
    body["image"] = {
        "mime": "image/png",
        "data": MINIMAL_PNG_B64,
        "width": 1,
        "height": 1,
    }
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_text_first_turn_overlong_text(run_client: TestClient, monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LUMINA_SELECTION_TEXT_MAX_CHARS", "5000")
    get_settings.cache_clear()
    run_client.app.dependency_overrides[get_settings] = lambda: Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
        selection_text_max_chars=5000,
    )
    body = text_selection_payload(run_client.default_pdf_id, text="a" * 5001)
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    get_settings.cache_clear()


def test_text_first_turn_extracted_text_in_response(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="ok")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    text = "Sample paragraph."
    body = text_selection_payload(run_client.default_pdf_id, text=text)
    resp = run_client.post("/api/v1/run", json=body)
    assert resp.json()["data"]["extracted_text"] == text


def test_text_first_turn_selection_row_persisted(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="ok")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    text = "Persist me."
    body = text_selection_payload(run_client.default_pdf_id, text=text)
    resp = run_client.post("/api/v1/run", json=body)
    session_id = resp.json()["data"]["session_id"]
    from lumina.db.engine import get_connection
    from lumina.db.models import get_conversation, get_selection

    session = asyncio.run(get_session_store().get(session_id))
    assert session is not None
    conn = get_connection(session.project_id)
    conv = get_conversation(conn, session_id)
    assert conv is not None
    sel = get_selection(conn, conv.selection_id)
    assert sel is not None
    assert sel.type == "text"
    assert sel.text == text
    assert sel.x is None
    assert sel.thumbnail_png is None


def test_image_first_turn_default_type(run_client: TestClient) -> None:
    resp = run_client.post("/api/v1/run", json=run_payload(run_client))
    assert resp.status_code == 200
    assert resp.json()["data"]["meta"]["task_type"] == "screenshot-qa"


def test_image_first_turn_explicit_type_image_with_text_rejected(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["selection"]["type"] = "image"
    payload["selection"]["text"] = "foo"
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_text_followup_same_plugin(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="answer")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post(
        "/api/v1/run",
        json=text_selection_payload(run_client.default_pdf_id, plugins=["translate"]),
    )
    session_id = first.json()["data"]["session_id"]
    session = asyncio.run(get_session_store().get(session_id))
    assert session is not None
    assert session.selection_type == "text"
    assert session.extracted_text == "Hello, world."
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, plugins=["translate"]),
    )
    assert second.status_code == 200


def test_text_followup_cross_plugin(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="answer")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post(
        "/api/v1/run",
        json=text_selection_payload(run_client.default_pdf_id, plugins=["translate"]),
    )
    session_id = first.json()["data"]["session_id"]
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(
            session_id,
            task_type="explain",
            plugins=["explain"],
            options={"target_lang": "zh-CN", "user_question": "再解释"},
        ),
    )
    assert second.status_code == 200
    assert second.json()["data"]["meta"]["plugins"] == ["explain"]


def test_text_followup_no_ocr_error(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="answer")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post(
        "/api/v1/run",
        json=text_selection_payload(run_client.default_pdf_id, plugins=["translate"]),
    )
    session_id = first.json()["data"]["session_id"]
    store = get_session_store()
    session = asyncio.run(store.get(session_id))
    assert session is not None
    session.extracted_text = ""
    async def _patch():
        async with store._lock:
            store._sessions[session_id] = session
    asyncio.run(_patch())
    resp = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, plugins=["explain"]),
    )
    assert resp.status_code == 200


def test_session_miss_load_recovers_selection_type_text(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="answer")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post(
        "/api/v1/run",
        json=text_selection_payload(run_client.default_pdf_id, plugins=["translate"]),
    )
    session_id = first.json()["data"]["session_id"]
    store = get_session_store()
    async def _evict():
        async with store._lock:
            store._sessions.pop(session_id, None)
    asyncio.run(_evict())
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, plugins=["translate"]),
    )
    assert second.status_code == 200
    session = asyncio.run(store.get(session_id))
    assert session is not None
    assert session.selection_type == "text"


# V1.2.4：concept-recall 非流式链路（409 校验 / 检索注入 / 双落空短路 / data.sources）


def _seed_memory_ready(conn, pdf_id):
    """播种 ready 记忆 + 一条概念，供 concept-recall 命中。"""
    from lumina.db.models import (
        MemoryConceptRow, MemoryMetaRow, MemoryUnitRow,
        replace_memory_units, replace_unit_concepts, upsert_memory_meta,
    )
    upsert_memory_meta(conn, MemoryMetaRow(pdf_id=pdf_id, status="ready", unit_total=1, unit_done=1))
    replace_memory_units(conn, pdf_id, [
        MemoryUnitRow(id="mu_a", pdf_id=pdf_id, seq=0, title="第1章", start_page=1, end_page=5, status="ok"),
    ])
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_1", pdf_id=pdf_id, unit_id="mu_a", term="梯度下降", definition="优化算法", page=3, created_at=1),
    ])


def _conn_for(client):
    from lumina.db.engine import get_connection
    from lumina.projects.manager import lookup_project_by_pdf_id
    entry = lookup_project_by_pdf_id(client.default_pdf_id)
    return get_connection(entry.id), entry.id


def test_concept_recall_concept_hit_non_stream(run_client: TestClient) -> None:
    provider = MockRunProvider(response_text="综述文本")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    conn, _ = _conn_for(run_client)
    _seed_memory_ready(conn, run_client.default_pdf_id)
    payload = text_selection_payload(
        run_client.default_pdf_id, text="梯度下降", plugins=["concept-recall"]
    )
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == "综述文本"
    assert data["sources"] and data["sources"][0]["kind"] == "concept"
    assert data["sources"][0]["term"] == "梯度下降"
    assert data["sources"][0]["page"] == 3
    # 参考块随 user 消息注入 → provider 收到的 user 文本含定义
    last_user = provider.last_request.messages[-1].content[0].text
    assert "优化算法" in last_user


def test_concept_recall_double_empty_skips_llm(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    conn, _ = _conn_for(run_client)
    _seed_memory_ready(conn, run_client.default_pdf_id)  # 有记忆但选区不命中且全文无
    payload = text_selection_payload(
        run_client.default_pdf_id, text="完全不存在XYZ", plugins=["concept-recall"]
    )
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "完全不存在XYZ" in data["text"]  # 固定话术含术语
    assert data["sources"] == []
    assert provider.invoke_count == 0  # 未调用 LLM
    # 消息落库 model 为 NULL
    from lumina.db.models import get_first_assistant_message
    row = get_first_assistant_message(conn, data["conversation_id"])
    assert row.model is None


def test_concept_recall_409_when_memory_not_ready(run_client: TestClient) -> None:
    payload = text_selection_payload(
        run_client.default_pdf_id, text="梯度下降", plugins=["concept-recall"]
    )  # 未播种记忆 → status none
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MEMORY_UNAVAILABLE"


def test_concept_recall_followup_does_not_rerun_retrieval(run_client: TestClient) -> None:
    """追问轮不应重新触发检索：data.sources 应为空/缺省，且参考块经历史消息持久化可见。"""
    provider = MockRunProvider(response_text="综述文本")
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    conn, _ = _conn_for(run_client)
    _seed_memory_ready(conn, run_client.default_pdf_id)
    payload = text_selection_payload(
        run_client.default_pdf_id, text="梯度下降", plugins=["concept-recall"]
    )
    first = run_client.post("/api/v1/run", json=payload)
    assert first.status_code == 200
    session_id = first.json()["data"]["session_id"]

    provider2 = MockRunProvider(response_text="追问回答")
    run_client.app.dependency_overrides[get_provider] = lambda: provider2
    second = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, plugins=["explain"]),
    )
    assert second.status_code == 200
    data = second.json()["data"]
    assert not data.get("sources")  # 追问轮未重新检索
    # provider 收到的历史消息中应含首轮注入的参考块定义文本
    history_texts = [
        part.text
        for msg in provider2.last_request.messages
        for part in msg.content
        if hasattr(part, "text")
    ]
    assert any("优化算法" in t for t in history_texts)
