"""V1.2.1 跨页自动上下文注入：/api/v1/run 首轮行为。"""

from lumina.db.engine import get_connection
from lumina.db.models import (
    PdfTextMetaRow,
    replace_pdf_text_pages,
    upsert_pdf_text_meta,
)
from lumina import settings_store
from lumina.projects.catalog import find_by_pdf_id
from lumina.sessions import get_session_store

from tests.test_api.test_run import (  # noqa: F401
    default_pdf_id,
    follow_up_payload,
    run_client,
    run_payload,
    text_selection_payload,
)

CONTEXT_MARKER = "[Reference context"


def _seed_book_text(pdf_id: str, pages: list[str], status: str = "ok") -> None:
    entry = find_by_pdf_id(pdf_id)
    conn = get_connection(entry.id)
    replace_pdf_text_pages(conn, pdf_id, pages)
    upsert_pdf_text_meta(
        conn,
        PdfTextMetaRow(
            pdf_id=pdf_id,
            status=status,
            page_count=len(pages),
            textual_page_count=len(pages),
            char_count=sum(len(t) for t in pages),
        ),
    )


def _pages(n: int = 10) -> list[str]:
    return [f"book-page-{i} " + "z" * 40 for i in range(1, n + 1)]


def _last_user_text(provider) -> str:
    req = provider.last_request
    user_msg = req.messages[-1]
    return "".join(
        part.text for part in user_msg.content if hasattr(part, "text")
    )


def _provider(client):
    from lumina.providers import get_provider as dep

    return client.app.dependency_overrides[dep]()


def test_text_selection_injects_context(run_client):
    pdf_id = run_client.default_pdf_id
    _seed_book_text(pdf_id, _pages())

    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider(response_text="回答")
    run_client.app.dependency_overrides[dep] = lambda: provider

    payload = text_selection_payload(pdf_id, page=5)
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200

    user_text = _last_user_text(provider)
    assert CONTEXT_MARKER in user_text
    # 默认窗口 2：第 3~7 页
    for i in (3, 4, 5, 6, 7):
        assert f"[Page {i}]" in user_text
    assert "[Page 2]" not in user_text and "[Page 8]" not in user_text


def test_screenshot_selection_injects_context(run_client):
    pdf_id = run_client.default_pdf_id
    _seed_book_text(pdf_id, _pages())

    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider()
    run_client.app.dependency_overrides[dep] = lambda: provider

    payload = run_payload(run_client)
    payload["selection"]["page"] = 5
    resp = run_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200

    user_text = _last_user_text(provider)
    assert CONTEXT_MARKER in user_text
    for i in (3, 4, 5, 6, 7):
        assert f"[Page {i}]" in user_text


def test_no_injection_when_status_not_ok(run_client):
    pdf_id = run_client.default_pdf_id
    _seed_book_text(pdf_id, _pages(), status="unsupported")

    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider(response_text="回答")
    run_client.app.dependency_overrides[dep] = lambda: provider

    resp = run_client.post("/api/v1/run", json=text_selection_payload(pdf_id, page=5))
    assert resp.status_code == 200
    assert CONTEXT_MARKER not in _last_user_text(provider)


def test_no_injection_when_no_text_extracted(run_client):
    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider(response_text="回答")
    run_client.app.dependency_overrides[dep] = lambda: provider

    resp = run_client.post(
        "/api/v1/run", json=text_selection_payload(run_client.default_pdf_id, page=5)
    )
    assert resp.status_code == 200
    assert CONTEXT_MARKER not in _last_user_text(provider)


def test_no_injection_when_setting_disabled(run_client):
    pdf_id = run_client.default_pdf_id
    _seed_book_text(pdf_id, _pages())

    current = settings_store.get_current()
    settings_store._current = settings_store.ResolvedSettings(
        provider_kind=current.provider_kind,
        base_url=current.base_url,
        api_key=current.api_key,
        default_model=current.default_model,
        timeout_seconds=current.timeout_seconds,
        task_models=current.task_models,
        thinking=current.thinking,
        context_expansion=settings_store.ContextExpansionSettings(enabled=False),
        source=current.source,
    )

    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider(response_text="回答")
    run_client.app.dependency_overrides[dep] = lambda: provider

    resp = run_client.post("/api/v1/run", json=text_selection_payload(pdf_id, page=5))
    assert resp.status_code == 200
    assert CONTEXT_MARKER not in _last_user_text(provider)


def test_follow_up_sees_context_via_history_without_reinjection(run_client):
    pdf_id = run_client.default_pdf_id
    _seed_book_text(pdf_id, _pages())

    from lumina.providers import get_provider as dep
    from tests.test_api.test_run import MockRunProvider

    provider = MockRunProvider(response_text="回答")
    run_client.app.dependency_overrides[dep] = lambda: provider

    resp = run_client.post("/api/v1/run", json=text_selection_payload(pdf_id, page=5))
    assert resp.status_code == 200
    session_id = resp.json()["data"]["session_id"]

    resp = run_client.post("/api/v1/run", json=follow_up_payload(session_id))
    assert resp.status_code == 200

    req = provider.last_request
    # 追问轮：当前 user 消息不重复注入
    current_user_text = "".join(
        part.text for part in req.messages[-1].content if hasattr(part, "text")
    )
    assert CONTEXT_MARKER not in current_user_text
    # 但首轮 user 历史消息中携带上下文
    history_texts = [
        "".join(part.text for part in m.content if hasattr(part, "text"))
        for m in req.messages[1:-1]
    ]
    assert any(CONTEXT_MARKER in t for t in history_texts)
