import logging

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.main import create_app
from lumina.providers import get_provider, reset_provider
from lumina.sessions import reset_session_store
from tests.test_api.test_run import MINIMAL_PNG_B64, MockRunProvider, run_payload, valid_run_payload


@pytest.fixture
def conv_run_client(data_root):
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    from lumina.projects.manager import auto_create_project

    PDF_BYTES = b"%PDF-1.4 conv test"
    pdf_id = auto_create_project(PDF_BYTES, "convbook.pdf").pdf_id
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: MockRunProvider()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.default_pdf_id = pdf_id
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_provider()
    reset_session_store()


def test_conversation_messages_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/conversations/conv_missing/messages")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_conversation_messages_after_run(conv_run_client: TestClient) -> None:
    first = conv_run_client.post(
        "/api/v1/run",
        json=run_payload(conv_run_client),
    )
    assert first.status_code == 200
    conv_id = first.json()["data"]["conversation_id"]
    response = conv_run_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["conversation_id"] == conv_id
    assert body["extracted_text"]
    assert len(body["messages"]) >= 2
