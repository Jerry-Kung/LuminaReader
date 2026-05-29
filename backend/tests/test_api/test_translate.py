import pytest
from fastapi.testclient import TestClient

from lumina.api._run_core import is_payload_too_large
from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider
from lumina.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderTimeout,
)
from lumina.providers import reset_provider

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

    def __init__(
        self,
        *,
        response_text: str = "mock translation",
        invoke_error: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.invoke_error = invoke_error

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        if self.invoke_error is not None:
            raise self.invoke_error
        return LLMResponse(
            text=self.response_text,
            model="gpt-4o",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def translate_client() -> TestClient:
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
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()


def test_translate_success(translate_client: TestClient) -> None:
    response = translate_client.post("/api/v0/translate", json=valid_translate_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["text"] == "mock translation"
    assert body["data"]["meta"]["request_id"].startswith("req_")
    assert body["data"]["meta"]["model"] == "gpt-4o"
    assert isinstance(body["data"]["meta"]["latency_ms"], int)
    assert body["data"]["meta"]["usage"]["total_tokens"] == 15


def test_translate_unsupported_task(translate_client: TestClient) -> None:
    # v0 must reject explain even after it is registered in TASK_REGISTRY
    response = translate_client.post(
        "/api/v0/translate",
        json=valid_translate_payload(task_type="explain"),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_TASK"


def test_translate_invalid_mime(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "mime": "image/jpeg"}
    response = translate_client.post("/api/v0/translate", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_translate_invalid_base64(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "data": "not-valid-base64!!!"}
    response = translate_client.post("/api/v0/translate", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_translate_missing_selection(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    del payload["selection"]
    response = translate_client.post("/api/v0/translate", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_translate_provider_timeout(translate_client: TestClient) -> None:
    translate_client.app.dependency_overrides[get_provider] = lambda: MockTranslateProvider(
        invoke_error=ProviderTimeout("timed out")
    )
    response = translate_client.post("/api/v0/translate", json=valid_translate_payload())
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_TIMEOUT"
    assert "sk-" not in response.text


def test_translate_provider_auth_error(translate_client: TestClient) -> None:
    translate_client.app.dependency_overrides[get_provider] = lambda: MockTranslateProvider(
        invoke_error=ProviderAuthError("auth failed")
    )
    response = translate_client.post("/api/v0/translate", json=valid_translate_payload())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert "auth failed" not in response.text


def test_payload_too_large_by_content_length() -> None:
    assert is_payload_too_large(8 * 1024 * 1024 + 1, "abc") is True


def test_payload_too_large_by_image_data() -> None:
    huge_b64 = "A" * (8 * 1024 * 1024)
    assert is_payload_too_large(None, huge_b64) is True


def test_translate_payload_too_large(translate_client: TestClient) -> None:
    payload = valid_translate_payload()
    payload["image"] = {**payload["image"], "data": "A" * (8 * 1024 * 1024)}
    response = translate_client.post("/api/v0/translate", json=payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_v0_translate_matches_v1_run_for_translate(translate_client: TestClient) -> None:
    provider = MockTranslateProvider()
    translate_client.app.dependency_overrides[get_provider] = lambda: provider

    v0_response = translate_client.post("/api/v0/translate", json=valid_translate_payload())
    v1_response = translate_client.post(
        "/api/v1/run",
        json=valid_translate_payload(task_type="translate"),
    )

    assert v0_response.status_code == 200
    assert v1_response.status_code == 200

    v0_body = v0_response.json()
    v1_body = v1_response.json()

    assert v0_body["data"]["text"] == v1_body["data"]["text"]
    assert "error" not in v0_body
    assert "error" not in v1_body
    assert v0_body["data"]["meta"]["model"] == v1_body["data"]["meta"]["model"]
    assert v1_body["data"]["meta"]["task_type"] == "translate"


def test_v0_deprecation_warning_emitted_once(capsys: pytest.CaptureFixture[str]) -> None:
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
    assert captured.count("event=v0_deprecated") == 1

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
