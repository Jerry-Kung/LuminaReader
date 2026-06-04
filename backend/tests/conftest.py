import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.main import create_app
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider, reset_provider
from lumina.sessions import reset_session_store
from lumina.providers.base import LLMRequest, LLMResponse, LLMStreamEvent, Provider
from lumina.providers.errors import StreamUnsupportedError

PDF_BYTES = b"%PDF-1.4 test fixture"


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def invoke_stream(self, req: LLMRequest):
        raise StreamUnsupportedError("streaming not supported in fake provider")
        yield LLMStreamEvent(type="done")  # pragma: no cover

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
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    close_all()
    get_settings.cache_clear()


@pytest.fixture
def pdf_project(data_root):
    return auto_create_project(PDF_BYTES, "testbook.pdf")


@pytest.fixture
def client(settings_with_key: Settings, data_root) -> TestClient:
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
def client_no_key(settings_without_key: Settings, data_root) -> TestClient:
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
