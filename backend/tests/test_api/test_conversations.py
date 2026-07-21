import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.config import Settings, get_settings
from lumina.db.engine import get_connection
from lumina.db.models import ConversationRow, MessageRow, insert_conversation, insert_message
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


def test_l04_legacy_translate_task_type_in_messages(conv_run_client: TestClient) -> None:
    first = conv_run_client.post(
        "/api/v1/run",
        json=run_payload(conv_run_client, task_type="translate"),
    )
    conv_id = first.json()["data"]["conversation_id"]
    response = conv_run_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert response.status_code == 200
    assert response.json()["data"]["task_type"] == "screenshot-qa"


def test_l05_legacy_explain_task_type_in_messages(conv_run_client: TestClient) -> None:
    first = conv_run_client.post(
        "/api/v1/run",
        json=run_payload(conv_run_client, task_type="explain"),
    )
    conv_id = first.json()["data"]["conversation_id"]
    response = conv_run_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert response.status_code == 200
    assert response.json()["data"]["task_type"] == "screenshot-qa"


def test_l06_chat_task_type_in_messages(conv_run_client: TestClient) -> None:
    first = conv_run_client.post(
        "/api/v1/run",
        json=run_payload(
            conv_run_client,
            task_type="chat",
            plugins=[],
            user_input="hi",
        ),
    )
    conv_id = first.json()["data"]["conversation_id"]
    response = conv_run_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert response.status_code == 200
    assert response.json()["data"]["task_type"] == "screenshot-qa"


def test_l07_pdf_conversations_list_includes_chat(conv_run_client: TestClient) -> None:
    first = conv_run_client.post(
        "/api/v1/run",
        json=run_payload(
            conv_run_client,
            task_type="chat",
            plugins=[],
            user_input="hi",
        ),
    )
    pdf_id = conv_run_client.default_pdf_id
    conv_id = first.json()["data"]["conversation_id"]
    response = conv_run_client.get(f"/api/v1/pdfs/{pdf_id}/conversations")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    matching = [i for i in items if i["conversation_id"] == conv_id]
    assert len(matching) == 1
    assert matching[0]["task_type"] == "screenshot-qa"


def test_l08_no_session_task_mismatch_tests_in_run_suite() -> None:
    source = Path(__file__).resolve().parents[1] / "test_api" / "test_run.py"
    assert "SESSION_TASK_MISMATCH" not in source.read_text(encoding="utf-8")


def test_l09_run_core_no_session_task_mismatch_trigger() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "lumina"
        / "api"
        / "_run_core.py"
    )
    code_lines = [
        ln for ln in source.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("#")
    ]
    assert "SESSION_TASK_MISMATCH" not in "\n".join(code_lines)


def _seed_conversation(pdf_project, *, conversation_id, task_type, sources_json):
    # V1.2.4：绕过 /run，直连 DB 造一问一答会话，专测历史读取 API 对 sources_json 的解析
    conn = get_connection(pdf_project.project_id)
    now = int(time.time())
    insert_conversation(
        conn,
        ConversationRow(
            id=conversation_id,
            pdf_id=pdf_project.pdf_id,
            selection_id="sel_seed",
            task_type=task_type,
            extracted_text="extracted",
            created_at=now,
            last_used_at=now,
        ),
    )
    insert_message(
        conn,
        MessageRow(
            id=f"{conversation_id}_u",
            conversation_id=conversation_id,
            turn_index=0,
            role="user",
            content="question",
            user_question="question",
            model=None,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=None,
            created_at=now,
        ),
    )
    insert_message(
        conn,
        MessageRow(
            id=f"{conversation_id}_a",
            conversation_id=conversation_id,
            turn_index=0,
            role="assistant",
            content="answer",
            user_question=None,
            model="gpt-4o",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            created_at=now,
            sources_json=sources_json,
        ),
    )
    return conn


def test_conversation_messages_include_sources(client: TestClient, pdf_project) -> None:
    _seed_conversation(
        pdf_project,
        conversation_id="conv_recall",
        task_type="concept-recall",
        sources_json='[{"kind": "concept", "term": "entropy", "page": 12}]',
    )
    resp = client.get("/api/v1/conversations/conv_recall/messages")
    assert resp.status_code == 200
    msgs = resp.json()["data"]["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant")
    assert assistant["sources"][0]["kind"] == "concept"


def test_conversation_messages_sources_null_for_normal(client: TestClient, pdf_project) -> None:
    _seed_conversation(
        pdf_project,
        conversation_id="conv_normal",
        task_type="screenshot-qa",
        sources_json=None,
    )
    resp = client.get("/api/v1/conversations/conv_normal/messages")
    assert resp.status_code == 200
    msgs = resp.json()["data"]["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant")
    # 普通消息 sources_json 为 NULL -> 序列化后字段缺省（exclude_none）
    assert "sources" not in assistant or assistant["sources"] is None


def test_conversation_messages_sources_corrupt_json_silent(client: TestClient, pdf_project) -> None:
    _seed_conversation(
        pdf_project,
        conversation_id="conv_corrupt",
        task_type="concept-recall",
        sources_json="{not json",
    )
    resp = client.get("/api/v1/conversations/conv_corrupt/messages")
    assert resp.status_code == 200
    msgs = resp.json()["data"]["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant")
    # 解析失败静默：字段缺省/None，正文不受影响
    assert "sources" not in assistant or assistant["sources"] is None
    assert assistant["content"] == "answer"
