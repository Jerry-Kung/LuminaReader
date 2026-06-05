import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import LLMStreamEvent, Provider
from lumina.providers.errors import StreamUnsupportedError
from lumina.sessions import reset_session_store


class NoOpProvider(Provider):
    name = "noop"

    async def invoke(self, req):
        raise AssertionError("provider should not be called")

    async def invoke_stream(self, req):
        raise StreamUnsupportedError("streaming not supported")
        yield LLMStreamEvent(type="done")  # pragma: no cover

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def gone_client(data_root) -> TestClient:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
    )
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: NoOpProvider()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()


def test_v0_health_returns_410_gone(gone_client: TestClient) -> None:
    response = gone_client.get("/api/v0/health")
    assert response.status_code == 410
    body = response.json()
    assert body["error"]["code"] == "GONE"
    assert body["error"]["message"]
    assert body["error"]["request_id"].startswith("req_")


def test_v0_health_does_not_call_provider(gone_client: TestClient) -> None:
    gone_client.get("/api/v0/health")


def test_v0_translate_returns_410_gone(gone_client: TestClient) -> None:
    response = gone_client.post("/api/v0/translate")
    assert response.status_code == 410
    body = response.json()
    assert body["error"]["code"] == "GONE"


def test_v0_translate_with_body_still_returns_410(gone_client: TestClient) -> None:
    response = gone_client.post(
        "/api/v0/translate",
        json={"task_type": "translate", "invalid": True},
    )
    assert response.status_code == 410


def test_v0_translate_does_not_call_provider(gone_client: TestClient) -> None:
    gone_client.post("/api/v0/translate", json={"task_type": "translate"})


def test_v0_response_request_id_format(gone_client: TestClient) -> None:
    response = gone_client.get("/api/v0/health")
    request_id = response.json()["error"]["request_id"]
    assert request_id.startswith("req_")


def test_v0_no_sensitive_info_in_response(gone_client: TestClient) -> None:
    response = gone_client.post("/api/v0/translate", json={"task_type": "translate"})
    text = response.text
    assert "sk-" not in text
    assert "Traceback" not in text


def test_v0_translate_does_not_call_provider_or_extract(gone_client: TestClient) -> None:
    provider = AsyncMock()
    provider.invoke = AsyncMock()
    extract_run = AsyncMock()
    gone_client.app.dependency_overrides[get_provider] = lambda: provider
    with patch("lumina.tasks.extract.EXTRACT_TASK.run", extract_run):
        response = gone_client.post("/api/v0/translate", json={"task_type": "translate"})
    assert response.status_code == 410
    assert provider.invoke.await_count == 0
    assert extract_run.await_count == 0


def test_v0_translate_does_not_touch_session_store(gone_client: TestClient) -> None:
    with (
        patch("lumina.sessions.SessionStore.create", new_callable=AsyncMock) as create_mock,
        patch("lumina.sessions.SessionStore.get", new_callable=AsyncMock) as get_mock,
        patch("lumina.sessions.SessionStore.append_turn", new_callable=AsyncMock) as append_mock,
        patch("lumina.sessions.SessionStore.delete", new_callable=AsyncMock) as delete_mock,
    ):
        response = gone_client.post("/api/v0/translate", json={"task_type": "translate"})
    assert response.status_code == 410
    assert create_mock.await_count == 0
    assert get_mock.await_count == 0
    assert append_mock.await_count == 0
    assert delete_mock.await_count == 0


def test_v0_translate_does_not_query_task_registry(gone_client: TestClient) -> None:
    with patch("lumina.tasks.resolve_legacy_task_type") as resolve_mock:
        response = gone_client.post("/api/v0/translate", json={"task_type": "translate"})
    assert response.status_code == 410
    resolve_mock.assert_not_called()


def test_v0_logs_api_version_gone(gone_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="lumina.v0")
    response = gone_client.post("/api/v0/translate")
    assert response.status_code == 410
    v0_logs = [
        getattr(record, "extra_fields", {})
        for record in caplog.records
        if record.name == "lumina.v0"
    ]
    assert v0_logs
    fields = v0_logs[-1]
    assert fields["api_version"] == "gone"
    assert fields["error_code"] == "GONE"
    assert fields["http_status"] == 410


def test_v0_startup_banner_logged_once(data_root, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
    )
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: NoOpProvider()

    with TestClient(app, raise_server_exceptions=False) as client:
        startup_out = capsys.readouterr().out
        assert startup_out.count("event=v0_gone") == 1
        client.post("/api/v0/translate")
        client.post("/api/v0/translate")
        after_out = capsys.readouterr().out
        assert "event=v0_gone" not in after_out

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
