import logging

import pytest
from fastapi.testclient import TestClient

from lumina.api._run_core import is_payload_too_large
from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import LLMRequest, LLMResponse, LLMStreamEvent, LLMUsage, Provider
from lumina.providers.errors import StreamUnsupportedError
from lumina.sessions import reset_session_store

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def valid_translate_payload(**overrides: object) -> dict:
    payload = {
        "task_type": "translate",
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


class MockTranslateProvider(Provider):
    name = "mock_translate"

    def __init__(self) -> None:
        self.invoke_count = 0

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.invoke_count += 1
        return LLMResponse(
            text="mock translation",
            model="gpt-4o",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def invoke_stream(self, req: LLMRequest):
        raise StreamUnsupportedError("streaming not supported in mock translate provider")
        yield LLMStreamEvent(type="done")  # pragma: no cover

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def translate_client(data_root) -> TestClient:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    provider = MockTranslateProvider()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(app, raise_server_exceptions=False) as client:
        client.mock_provider = provider
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()


def _assert_gone(response) -> None:
    assert response.status_code == 410
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "GONE"
    assert body["error"]["request_id"].startswith("req_")


def test_translate_success(translate_client: TestClient) -> None:
    _assert_gone(translate_client.post("/api/v0/translate", json=valid_translate_payload()))
    assert translate_client.mock_provider.invoke_count == 0


def test_translate_unsupported_task(translate_client: TestClient) -> None:
    _assert_gone(
        translate_client.post(
            "/api/v0/translate",
            json=valid_translate_payload(task_type="explain"),
        )
    )


def test_translate_invalid_mime(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "mime": "image/jpeg"}
    _assert_gone(translate_client.post("/api/v0/translate", json=payload))


def test_translate_invalid_base64(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "data": "not-valid-base64!!!"}
    _assert_gone(translate_client.post("/api/v0/translate", json=payload))


def test_translate_missing_selection(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    del payload["selection"]
    _assert_gone(translate_client.post("/api/v0/translate", json=payload))


def test_translate_provider_timeout(translate_client: TestClient) -> None:
    _assert_gone(translate_client.post("/api/v0/translate", json=valid_translate_payload()))


def test_translate_provider_auth_error(translate_client: TestClient) -> None:
    _assert_gone(translate_client.post("/api/v0/translate", json=valid_translate_payload()))


def test_payload_too_large_by_content_length() -> None:
    assert is_payload_too_large(8 * 1024 * 1024 + 1, "abc") is True


def test_payload_too_large_by_image_data() -> None:
    huge_b64 = "A" * (8 * 1024 * 1024)
    assert is_payload_too_large(None, huge_b64) is True


def test_translate_payload_too_large(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "data": "A" * (8 * 1024 * 1024)}
    _assert_gone(translate_client.post("/api/v0/translate", json=payload))


def test_v0_translate_matches_v1_run_for_translate(translate_client: TestClient) -> None:
    _assert_gone(translate_client.post("/api/v0/translate", json=valid_translate_payload()))


def test_v0_translate_rejects_session_id(translate_client: TestClient) -> None:
    _assert_gone(
        translate_client.post(
            "/api/v0/translate",
            json=valid_translate_payload(session_id="sess_abc"),
        )
    )


def test_v0_translate_ignores_user_question(translate_client: TestClient) -> None:
    _assert_gone(
        translate_client.post(
            "/api/v0/translate",
            json=valid_translate_payload(
                options={"target_lang": "zh-CN", "user_question": "ignored"}
            ),
        )
    )


def test_v0_gone_banner_emitted_once(capsys: pytest.CaptureFixture[str]) -> None:
    from lumina.config import Settings, get_settings
    from lumina.main import create_app
    from lumina.providers import get_provider, reset_provider
    from lumina.sessions import reset_session_store

    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    reset_provider()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: MockTranslateProvider()

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/api/v0/health")

    captured = capsys.readouterr().out
    assert "endpoints are gone" in captured

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
