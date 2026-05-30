import asyncio

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import LLMRequest, Provider, ProviderAuthError
from lumina.sessions import SessionStore, get_session_store, reset_session_store


class CountingProvider(Provider):
    name = "counting"

    def __init__(self) -> None:
        self.invoke_count = 0

    async def invoke(self, req: LLMRequest):
        self.invoke_count += 1
        raise ProviderAuthError("should not be called")

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def delete_client() -> tuple[TestClient, SessionStore]:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    store = SessionStore()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_store] = lambda: store
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()


def test_delete_existing_session_returns_204(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, store = delete_client
    session = asyncio.run(store.create(task_type="translate", extracted_text="hi"))
    response = client.delete(f"/api/v1/sessions/{session.session_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert asyncio.run(store.get(session.session_id)) is None


def test_delete_missing_session_returns_404(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, _store = delete_client
    response = client.delete("/api/v1/sessions/sess_does_not_exist")
    assert response.status_code == 404


def test_delete_is_idempotent(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, store = delete_client
    session = asyncio.run(store.create(task_type="translate", extracted_text="hi"))
    first = client.delete(f"/api/v1/sessions/{session.session_id}")
    second = client.delete(f"/api/v1/sessions/{session.session_id}")
    assert first.status_code == 204
    assert second.status_code == 404


def test_delete_does_not_invoke_provider() -> None:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    store = SessionStore()
    provider = CountingProvider()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_provider] = lambda: provider

    session = asyncio.run(store.create(task_type="translate", extracted_text="hi"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/v1/sessions/{session.session_id}")
        assert response.status_code == 204
        assert provider.invoke_count == 0

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()


def test_delete_not_mounted_under_v0(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, _store = delete_client
    response = client.delete("/api/v0/sessions/whatever")
    assert response.status_code == 404
