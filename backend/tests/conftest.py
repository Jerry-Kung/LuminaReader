import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.sessions import reset_session_store
from lumina.providers.base import LLMRequest, LLMResponse, Provider


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return self._ready


@pytest.fixture
def settings_with_key() -> Settings:
    return Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )


@pytest.fixture
def settings_without_key() -> Settings:
    return Settings(
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )


@pytest.fixture
def client(settings_with_key: Settings) -> TestClient:
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings_with_key)
    app.dependency_overrides[get_settings] = lambda: settings_with_key
    app.dependency_overrides[get_provider] = lambda: FakeProvider(ready=True)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    reset_session_store()


@pytest.fixture
def client_no_key(settings_without_key: Settings) -> TestClient:
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings_without_key)
    app.dependency_overrides[get_settings] = lambda: settings_without_key
    app.dependency_overrides[get_provider] = lambda: FakeProvider(ready=False)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
