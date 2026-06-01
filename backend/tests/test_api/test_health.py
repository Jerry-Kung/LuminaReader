from fastapi import APIRouter
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.schemas.api import TranslateRequest


def test_health_with_valid_config(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["service"] == "lumina-backend"
    assert body["data"]["version"] == "0.1.0"
    assert body["data"]["provider_ready"] is True


def test_v0_health_returns_gone(client: TestClient) -> None:
    response = client.get("/api/v0/health")
    assert response.status_code == 410
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "GONE"


def test_health_without_api_key(client_no_key: TestClient) -> None:
    response = client_no_key.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["provider_ready"] is False


def test_cors_allows_localhost_3000(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_internal_error_returns_envelope(client: TestClient) -> None:
    router = APIRouter()

    @router.get("/api/v0/_test/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    client.app.include_router(router)
    response = client.get("/api/v0/_test/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["request_id"].startswith("req_")
    assert "boom" not in response.text
    assert "Traceback" not in response.text


def test_validation_error_returns_envelope() -> None:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    router = APIRouter()

    @router.post("/api/v0/_test/validate")
    def validate(body: TranslateRequest) -> dict:
        return {"ok": True, "data": {}}

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post("/api/v0/_test/validate", json={"task_type": 123})
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["request_id"].startswith("req_")
