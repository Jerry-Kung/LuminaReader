from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.main import create_app
from lumina import settings_store
from lumina.providers import get_provider, reset_provider
from lumina.providers.openai_compat import OpenAICompatProvider
from lumina.sessions import reset_session_store


def _settings_payload(**overrides: object) -> dict:
    payload = {
        "provider": {
            "kind": "openai_compat",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-fake-test1234",
            "default_model": "gpt-4o-mini",
            "timeout_seconds": 60,
        },
        "task_models": {"extract": None, "translate": None, "explain": None},
    }
    if overrides:
        payload.update(overrides)
    return payload


@pytest.fixture
def settings_env(data_root, monkeypatch):
    cfg = Settings(
        openai_api_key="sk-envkey123456",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
        llm_timeout_seconds=60,
    )
    get_settings.cache_clear()
    monkeypatch.setattr("lumina.settings_store.get_settings", lambda: cfg)
    return cfg


@pytest.fixture
def settings_client(settings_env) -> TestClient:
    cfg = settings_env
    settings_store._reset_state()
    reset_provider()
    reset_session_store()
    app = create_app(cfg)
    app.dependency_overrides[get_settings] = lambda: cfg
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    settings_store._reset_state()
    reset_provider()
    reset_session_store()
    close_all()


def test_get_fallback_includes_thinking_disabled(
    settings_client: TestClient, settings_env: Settings
) -> None:
    response = settings_client.get("/api/v1/settings")
    assert response.status_code == 200
    assert response.json()["data"]["thinking"]["enabled"] is False


def test_get_fallback(settings_client: TestClient, settings_env: Settings) -> None:
    response = settings_client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "env_fallback"
    assert body["data"]["provider"]["default_model"] == settings_env.openai_model
    assert body["data"]["provider"]["api_key_masked"] == "sk-***...3456"


def test_get_user_data(settings_client: TestClient, data_root) -> None:
    put = settings_client.put("/api/v1/settings", json=_settings_payload())
    assert put.status_code == 200
    response = settings_client.get("/api/v1/settings")
    body = response.json()
    assert body["data"]["source"] == "user_data"
    assert body["data"]["provider"]["default_model"] == "gpt-4o-mini"


def test_put_thinking_enabled(settings_client: TestClient) -> None:
    payload = _settings_payload(thinking={"enabled": True})
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 200
    assert response.json()["data"]["thinking"]["enabled"] is True
    get_resp = settings_client.get("/api/v1/settings")
    assert get_resp.json()["data"]["thinking"]["enabled"] is True


def test_put_thinking_unknown_field(settings_client: TestClient) -> None:
    payload = _settings_payload(thinking={"enabled": True, "budget": 1000})
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
    paths = [e["path"] for e in response.json()["error"]["field_errors"]]
    assert "thinking.budget" in paths


def test_put_valid_updates_state(settings_client: TestClient) -> None:
    put = settings_client.put("/api/v1/settings", json=_settings_payload())
    assert put.status_code == 200
    get_resp = settings_client.get("/api/v1/settings")
    assert get_resp.json()["data"]["provider"]["default_model"] == "gpt-4o-mini"


def test_put_persists_to_disk(settings_client: TestClient, data_root) -> None:
    settings_client.put("/api/v1/settings", json=_settings_payload())
    import json

    saved = json.loads((data_root / "settings.json").read_text(encoding="utf-8"))
    assert saved["provider"]["default_model"] == "gpt-4o-mini"


def test_put_invalid_base_url(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["provider"]["base_url"] = "not a url"
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_SETTINGS"
    paths = [e["path"] for e in body["error"]["field_errors"]]
    assert "provider.base_url" in paths


def test_put_invalid_kind(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["provider"]["kind"] = "anthropic"
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422


def test_put_unknown_task_key(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["task_models"] = {"summary": "gpt-4o"}
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
    paths = [e["path"] for e in response.json()["error"]["field_errors"]]
    assert "task_models" in paths


def test_put_api_key_omitted_preserves(settings_client: TestClient) -> None:
    settings_client.put("/api/v1/settings", json=_settings_payload())
    before = settings_client.get("/api/v1/settings").json()["data"]["provider"]["api_key_masked"]
    payload = _settings_payload()
    del payload["provider"]["api_key"]
    settings_client.put("/api/v1/settings", json=payload)
    after = settings_client.get("/api/v1/settings").json()["data"]["provider"]["api_key_masked"]
    assert after == before


def test_put_api_key_null_clears(settings_client: TestClient) -> None:
    settings_client.put("/api/v1/settings", json=_settings_payload())
    payload = _settings_payload()
    payload["provider"]["api_key"] = None
    settings_client.put("/api/v1/settings", json=payload)
    body = settings_client.get("/api/v1/settings").json()
    assert body["data"]["provider"]["api_key_masked"] is None
    assert body["data"]["provider_ready"] is False


def test_put_api_key_string_replaces(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["provider"]["api_key"] = "sk-newvalue1234"
    settings_client.put("/api/v1/settings", json=payload)
    masked = settings_client.get("/api/v1/settings").json()["data"]["provider"]["api_key_masked"]
    assert masked == "sk-***...1234"


def test_put_api_key_masked_rejected(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["provider"]["api_key"] = "sk-***...1234"
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422


def test_put_persist_failure(settings_client: TestClient) -> None:
    settings_client.put("/api/v1/settings", json=_settings_payload())
    before = settings_client.get("/api/v1/settings").json()["data"]["provider"]["default_model"]
    payload = _settings_payload()
    payload["provider"]["default_model"] = "gpt-should-not-stick"
    with patch(
        "lumina.settings_store._atomic_write",
        side_effect=settings_store.SettingsPersistError("failed"),
    ):
        response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SETTINGS_PERSIST_FAILED"
    after = settings_client.get("/api/v1/settings").json()["data"]["provider"]["default_model"]
    assert after == before


def test_put_no_api_key_log(settings_client: TestClient, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    settings_client.put("/api/v1/settings", json=_settings_payload())
    for record in caplog.records:
        assert "sk-fake-test1234" not in record.getMessage()


def test_get_writable_true(settings_client: TestClient) -> None:
    body = settings_client.get("/api/v1/settings").json()
    assert body["data"]["writable"] is True


def test_provider_rebuild_after_put(settings_client: TestClient) -> None:
    settings_client.put("/api/v1/settings", json=_settings_payload())
    provider = get_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# V1.2.1: context_expansion
# ---------------------------------------------------------------------------


def test_get_default_context_expansion_enabled(settings_client: TestClient) -> None:
    response = settings_client.get("/api/v1/settings")
    assert response.json()["data"]["context_expansion"]["enabled"] is True


def test_put_context_expansion_disabled(settings_client: TestClient) -> None:
    payload = _settings_payload(context_expansion={"enabled": False})
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 200
    assert response.json()["data"]["context_expansion"]["enabled"] is False
    get_resp = settings_client.get("/api/v1/settings")
    assert get_resp.json()["data"]["context_expansion"]["enabled"] is False


def test_put_context_expansion_omitted_preserves(settings_client: TestClient) -> None:
    put = settings_client.put(
        "/api/v1/settings", json=_settings_payload(context_expansion={"enabled": False})
    )
    assert put.status_code == 200
    put2 = settings_client.put("/api/v1/settings", json=_settings_payload())
    assert put2.status_code == 200
    assert put2.json()["data"]["context_expansion"]["enabled"] is False


def test_put_context_expansion_unknown_field(settings_client: TestClient) -> None:
    payload = _settings_payload(context_expansion={"enabled": True, "pages": 3})
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
    paths = [e["path"] for e in response.json()["error"]["field_errors"]]
    assert "context_expansion.pages" in paths


def test_put_context_expansion_non_bool(settings_client: TestClient) -> None:
    payload = _settings_payload(context_expansion={"enabled": "yes"})
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# V1.2.3: task_models.memory
# ---------------------------------------------------------------------------


def test_task_models_memory_roundtrip(settings_client: TestClient) -> None:
    resp = settings_client.get("/api/v1/settings")
    assert "memory" in resp.json()["data"]["task_models"]

    put = settings_client.put(
        "/api/v1/settings",
        json=_settings_payload(task_models={"memory": "qwen-turbo"}),
    )
    assert put.status_code == 200
    assert put.json()["data"]["task_models"]["memory"] == "qwen-turbo"

    # 清回 null → 回落 default_model
    put2 = settings_client.put(
        "/api/v1/settings",
        json=_settings_payload(task_models={"memory": None}),
    )
    assert put2.status_code == 200
    assert put2.json()["data"]["task_models"]["memory"] is None


def test_task_models_unknown_key_rejected_still(settings_client: TestClient) -> None:
    payload = _settings_payload()
    payload["task_models"] = {"bogus": "m"}
    response = settings_client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
