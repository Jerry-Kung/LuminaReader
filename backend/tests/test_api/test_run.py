import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderTimeout,
)

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def valid_run_payload(task_type: str = "translate", **overrides: object) -> dict:
    payload = {
        "task_type": task_type,
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
    ) -> None:
        self.response_text = response_text
        self.invoke_error = invoke_error
        self.last_request: LLMRequest | None = None

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.last_request = req
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
def run_client() -> TestClient:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    reset_provider()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: MockRunProvider()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()


def test_run_translate_success(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=valid_run_payload(task_type="translate"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["text"] == "mock"
    assert body["data"]["meta"]["request_id"].startswith("req_")
    assert body["data"]["meta"]["task_type"] == "translate"


def test_run_explain_success(run_client: TestClient) -> None:
    provider = MockRunProvider()
    run_client.app.dependency_overrides[get_provider] = lambda: provider
    response = run_client.post("/api/v1/run", json=valid_run_payload(task_type="explain"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["meta"]["task_type"] == "explain"
    assert provider.last_request is not None
    system_text = provider.last_request.messages[0].content[0].text
    assert "Explain" in system_text or "explain" in system_text


def test_run_unsupported_task(run_client: TestClient) -> None:
    response = run_client.post("/api/v1/run", json=valid_run_payload(task_type="qa"))
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_TASK"


def test_run_invalid_mime(run_client: TestClient) -> None:
    payload = valid_run_payload()
    payload["image"] = {**payload["image"], "mime": "image/jpeg"}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_invalid_base64(run_client: TestClient) -> None:
    payload = valid_run_payload()
    payload["image"] = {**payload["image"], "data": "not-valid-base64!!!"}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_missing_selection(run_client: TestClient) -> None:
    payload = valid_run_payload()
    del payload["selection"]
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_payload_too_large(run_client: TestClient) -> None:
    payload = valid_run_payload()
    payload["image"] = {**payload["image"], "data": "A" * (8 * 1024 * 1024)}
    response = run_client.post("/api/v1/run", json=payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_run_provider_timeout(run_client: TestClient) -> None:
    run_client.app.dependency_overrides[get_provider] = lambda: MockRunProvider(
        invoke_error=ProviderTimeout("timed out")
    )
    response = run_client.post("/api/v1/run", json=valid_run_payload())
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_TIMEOUT"
    assert "sk-" not in response.text


def test_run_provider_auth_error(run_client: TestClient) -> None:
    run_client.app.dependency_overrides[get_provider] = lambda: MockRunProvider(
        invoke_error=ProviderAuthError("auth failed")
    )
    response = run_client.post("/api/v1/run", json=valid_run_payload())
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
