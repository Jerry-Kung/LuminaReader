import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.main import create_app
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderTimeout,
)
from lumina.sessions import get_session_store, reset_session_store

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


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
        response_text: str = "mock",
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
        return LLMResponse(
            text=self.response_text,
            model=model,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

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


def test_run_translate_success(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["text"] == "mock"
    assert body["data"]["meta"]["request_id"].startswith("req_")
    assert body["data"]["meta"]["task_type"] == "translate"
    assert body["data"]["session_id"]
    assert body["data"]["meta"]["turn_index"] == 0


def test_run_explain_success(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="explain"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["meta"]["task_type"] == "explain"
    assert body["data"]["session_id"]
    assert body["data"]["meta"]["turn_index"] == 0
    assert provider.last_request is not None
    system_text = provider.last_request.messages[0].content[0].text
    assert "Explain" in system_text or "explain" in system_text


def test_run_unsupported_task(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="qa"))
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_TASK"


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


def test_run_first_turn_invokes_extract_then_driving_task(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    assert len(provider.all_requests) == 2
    extract_system = provider.all_requests[0].messages[0].content[0].text.lower()
    assert "extract" in extract_system or "markdown" in extract_system
    drive_system = provider.all_requests[1].messages[0].content[0].text.lower()
    assert "translator" in drive_system or "translate" in drive_system
    assert all(
        part.type != "image"
        for part in provider.all_requests[1].messages[-1].content
    )


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
    drive_user = provider.all_requests[1].messages[-1].content
    combined = "".join(part.text for part in drive_user if part.type == "text")
    assert "为什么 V=8?" in combined


def test_run_first_turn_missing_image(run_client: TestClient) -> None:
    payload = run_payload(run_client)
    payload["image"] = None
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_first_turn_extract_task_failure_does_not_create_session(
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


def test_run_follow_up_task_type_mismatch(run_client: TestClient) -> None:
    first = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    session_id = first.json()["data"]["session_id"]
    response = run_client.post(
        "/api/v1/run",
        json=follow_up_payload(session_id, task_type="explain"),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_TASK_MISMATCH"


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
    assert isinstance(fields["extract_latency_ms"], int)
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
    assert follow_up_log["extract_latency_ms"] == ""
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


def _put_settings(run_client: TestClient, **task_overrides: str | None) -> None:
    payload = {
        "provider": {
            "kind": "openai_compat",
            "base_url": "https://api.openai.com/v1",
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
    response = run_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 200


def test_run_translate_uses_task_model_override(run_client: TestClient) -> None:
    _put_settings(run_client, translate="gpt-4o-mini")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    assert provider.all_requests[1].extras.get("model_override") == "gpt-4o-mini"
    assert response.json()["data"]["meta"]["model"] == "gpt-4o-mini"


def test_run_explain_falls_back_to_default(run_client: TestClient) -> None:
    _put_settings(run_client, translate="gpt-4o-mini")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="explain"))
    assert response.status_code == 200
    assert provider.all_requests[1].extras.get("model_override") is None
    assert response.json()["data"]["meta"]["model"] == "gpt-4o"


def test_run_extract_uses_task_model_override(run_client: TestClient) -> None:
    _put_settings(run_client, extract="vlm-special")
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    assert response.status_code == 200
    assert provider.all_requests[0].extras.get("model_override") == "vlm-special"
    assert provider.all_requests[1].extras.get("model_override") is None
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


def test_run_settings_change_takes_effect_immediately(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    first = run_client.post("/api/v1/run", json=run_payload(run_client, task_type="translate"))
    session_id = first.json()["data"]["session_id"]
    assert first.json()["data"]["meta"]["model"] == "gpt-4o"

    _put_settings(run_client, translate="gpt-4o-mini")
    second = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert second.json()["data"]["meta"]["model"] == "gpt-4o-mini"
