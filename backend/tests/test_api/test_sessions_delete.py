import asyncio
import time

import pytest
from ulid import ULID

from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.db.models import SelectionRow
from lumina.main import create_app
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider, reset_provider
from lumina.providers.base import LLMRequest, LLMStreamEvent, Provider, ProviderAuthError
from lumina.providers.errors import StreamUnsupportedError
from lumina.sessions import SessionStore, get_session_store, reset_session_store

PDF_BYTES = b"%PDF-1.4 delete test"


async def _create_session(store: SessionStore):
    created = auto_create_project(PDF_BYTES, f"del-{ULID()}.pdf")
    conversation_id = f"conv_{ULID()}"
    selection_id = f"sel_{ULID()}"
    return await store.create(
        conversation_id=conversation_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id=selection_id,
        task_type="translate",
        extracted_text="hi",
        selection_row=SelectionRow(
            id=selection_id,
            pdf_id=created.pdf_id,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
            thumbnail_png=None,
            created_at=int(time.time()),
        ),
        first_user_question=None,
        first_user_content="hi",
        first_assistant_text="answer",
        first_assistant_meta={"model": "gpt-4o"},
    )


class CountingProvider(Provider):
    name = "counting"

    def __init__(self) -> None:
        self.invoke_count = 0

    async def invoke(self, req: LLMRequest):
        self.invoke_count += 1
        raise ProviderAuthError("should not be called")

    async def invoke_stream(self, req: LLMRequest):
        raise StreamUnsupportedError("streaming not supported")
        yield LLMStreamEvent(type="done")  # pragma: no cover

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def delete_client(data_root) -> tuple[TestClient, SessionStore]:
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
    close_all()
    reset_provider()
    reset_session_store()


def test_delete_existing_session_returns_204(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, store = delete_client
    session = asyncio.run(_create_session(store))
    response = client.delete(f"/api/v1/sessions/{session.session_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert asyncio.run(store.get(session.session_id)) is None


def test_delete_missing_session_returns_404(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, _store = delete_client
    response = client.delete("/api/v1/sessions/conv_does_not_exist")
    assert response.status_code == 404


def test_delete_is_idempotent(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, store = delete_client
    session = asyncio.run(_create_session(store))
    first = client.delete(f"/api/v1/sessions/{session.session_id}")
    second = client.delete(f"/api/v1/sessions/{session.session_id}")
    assert first.status_code == 204
    assert second.status_code == 404


def test_delete_does_not_invoke_provider(data_root) -> None:
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

    session = asyncio.run(_create_session(store))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/v1/sessions/{session.session_id}")
        assert response.status_code == 204
        assert provider.invoke_count == 0

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    close_all()
    reset_provider()
    reset_session_store()


def test_delete_not_mounted_under_v0(delete_client: tuple[TestClient, SessionStore]) -> None:
    client, _store = delete_client
    response = client.delete("/api/v0/sessions/whatever")
    assert response.status_code == 404
