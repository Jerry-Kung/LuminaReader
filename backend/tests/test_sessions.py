import asyncio
import logging
import time
from unittest.mock import patch

import pytest
from ulid import ULID

from lumina.config import get_settings
from lumina.db.engine import close_all
from lumina.db.models import SelectionRow
from lumina.projects.manager import auto_create_project
from lumina.providers.base import LLMMessage, TextPart
from lumina.sessions import (
    SessionStore,
    cleanup_loop,
    get_session_store,
    init_session_store,
    reset_session_store,
)

PDF_BYTES = b"%PDF-1.4 session test"


@pytest.fixture(autouse=True)
def _reset_engine(data_root):
    close_all()
    yield
    close_all()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def _create_session(
    store: SessionStore,
    *,
    extracted_text: str = "hello",
    task_type: str = "translate",
) -> object:
    created = auto_create_project(PDF_BYTES, f"book-{ULID()}.pdf")
    conversation_id = f"conv_{ULID()}"
    selection_id = f"sel_{ULID()}"
    return await store.create(
        conversation_id=conversation_id,
        project_id=created.project_id,
        pdf_id=created.pdf_id,
        selection_id=selection_id,
        task_type=task_type,
        extracted_text=extracted_text,
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
        first_user_content=extracted_text,
        first_assistant_text="answer",
        first_assistant_meta={"model": "gpt-4o"},
        meta={"page": 1},
    )


@pytest.mark.asyncio
async def test_create_and_get_roundtrip() -> None:
    store = SessionStore()
    session = await _create_session(store)

    assert session.session_id.startswith("conv_")
    assert session.task_type == "translate"
    assert session.extracted_text == "hello"
    assert len(session.messages) == 2
    assert session.meta == {"page": 1}

    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.session_id == session.session_id


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    store = SessionStore()
    assert await store.get("conv_does_not_exist") is None


@pytest.mark.asyncio
async def test_append_turn_adds_two_messages() -> None:
    store = SessionStore()
    session = await _create_session(store)
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])

    updated = await store.append_turn(
        session.session_id,
        user_message=user_msg,
        assistant_message=ai_msg,
        turn_index=1,
    )

    assert updated is not None
    assert len(updated.messages) == 4
    assert updated.messages[2].role == "user"
    assert updated.messages[3].role == "assistant"


@pytest.mark.asyncio
async def test_append_turn_missing_returns_none() -> None:
    store = SessionStore()
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])
    assert await store.append_turn("missing", user_message=user_msg, assistant_message=ai_msg) is None


@pytest.mark.asyncio
async def test_delete_existing_returns_true_and_idempotent() -> None:
    store = SessionStore()
    session = await _create_session(store)

    assert await store.delete(session.session_id) is True
    assert await store.delete(session.session_id) is False


@pytest.mark.asyncio
async def test_delete_then_get_returns_none() -> None:
    store = SessionStore()
    session = await _create_session(store)
    await store.delete(session.session_id)
    assert await store.get(session.session_id) is None


@pytest.mark.asyncio
async def test_lru_evicts_oldest_when_exceeding_max_entries() -> None:
    store = SessionStore(max_entries=3)
    s1 = await _create_session(store, extracted_text="1")
    s2 = await _create_session(store, extracted_text="2")
    s3 = await _create_session(store, extracted_text="3")
    s4 = await _create_session(store, extracted_text="4")

    assert s1.session_id not in store._sessions
    assert await store.get(s2.session_id) is not None
    assert await store.get(s3.session_id) is not None
    assert await store.get(s4.session_id) is not None


@pytest.mark.asyncio
async def test_get_refreshes_lru_position() -> None:
    store = SessionStore(max_entries=3)
    s1 = await _create_session(store, extracted_text="1")
    s2 = await _create_session(store, extracted_text="2")
    s3 = await _create_session(store, extracted_text="3")

    await store.get(s1.session_id)
    await _create_session(store, extracted_text="4")

    assert s2.session_id not in store._sessions
    assert await store.get(s1.session_id) is not None
    assert await store.get(s3.session_id) is not None


@pytest.mark.asyncio
async def test_append_turn_refreshes_lru_position() -> None:
    store = SessionStore(max_entries=3)
    s1 = await _create_session(store, extracted_text="1")
    s2 = await _create_session(store, extracted_text="2")
    s3 = await _create_session(store, extracted_text="3")

    user_msg = LLMMessage(role="user", content=[TextPart(text="q")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a")])
    await store.append_turn(s1.session_id, user_message=user_msg, assistant_message=ai_msg, turn_index=1)
    await _create_session(store, extracted_text="4")

    assert s2.session_id not in store._sessions
    assert await store.get(s1.session_id) is not None
    assert await store.get(s3.session_id) is not None


@pytest.mark.asyncio
async def test_get_returns_none_when_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    session = await _create_session(store)
    await asyncio.sleep(0.1)
    reloaded = await store.get(session.session_id)
    assert reloaded is not None
    assert len(store) >= 1


@pytest.mark.asyncio
async def test_get_within_ttl_still_alive() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=2.0)
    session = await _create_session(store)
    previous_last_used = session.last_used_at
    await asyncio.sleep(0.05)
    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.last_used_at >= previous_last_used


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    s1 = await _create_session(store, extracted_text="1")
    await asyncio.sleep(0.1)
    s2 = await _create_session(store, extracted_text="2")

    removed = await store.cleanup()
    assert removed == 1
    assert s1.session_id not in store._sessions
    assert await store.get(s2.session_id) is not None


@pytest.mark.asyncio
async def test_cleanup_zero_when_nothing_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=3600.0)
    await _create_session(store)
    assert await store.cleanup() == 0


@pytest.mark.asyncio
async def test_cleanup_loop_invokes_cleanup_periodically() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    task = asyncio.create_task(cleanup_loop(store, interval_seconds=0.05))
    session = await _create_session(store)
    await asyncio.sleep(0.2)
    assert session.session_id not in store._sessions
    assert await store.get(session.session_id) is not None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cleanup_loop_swallows_unexpected_exceptions() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=3600.0)
    with patch.object(store, "cleanup", side_effect=RuntimeError("boom")):
        task = asyncio.create_task(cleanup_loop(store, interval_seconds=0.05))
        await asyncio.sleep(0.15)
        assert task.done() is False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_init_and_reset_session_store() -> None:
    reset_session_store()
    init_session_store(max_entries=10, ttl_seconds=3600.0)
    assert get_session_store() is not None
    reset_session_store()
    with pytest.raises(RuntimeError):
        get_session_store()


@pytest.mark.asyncio
async def test_append_turn_db_failure_marks_dirty_not_raise() -> None:
    from unittest.mock import patch

    store = SessionStore()
    session = await _create_session(store)
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])

    with patch("lumina.sessions.insert_message", side_effect=RuntimeError("db fail")):
        updated = await store.append_turn(
            session.session_id,
            user_message=user_msg,
            assistant_message=ai_msg,
            turn_index=1,
        )

    assert updated is not None
    assert updated.dirty is True
    assert len(updated.messages) == 4


@pytest.mark.asyncio
async def test_append_turn_dirty_retry_succeeds() -> None:
    from unittest.mock import patch

    from lumina.db.engine import get_connection
    from lumina.db.models import count_messages

    store = SessionStore()
    session = await _create_session(store)
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])

    with patch("lumina.sessions.insert_message", side_effect=RuntimeError("db fail")):
        await store.append_turn(
            session.session_id,
            user_message=user_msg,
            assistant_message=ai_msg,
            turn_index=1,
        )

    await store.cleanup()
    conn = get_connection(session.project_id)
    assert count_messages(conn, session.session_id) == 4
    reloaded = store._sessions[session.session_id]
    assert reloaded.dirty is False
    assert reloaded.dirty_attempts == 0


@pytest.mark.asyncio
async def test_append_turn_dirty_retry_gives_up_after_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import patch

    caplog.set_level(logging.WARNING, logger="lumina.sessions")
    store = SessionStore()
    session = await _create_session(store)
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])

    with patch("lumina.sessions.insert_message", side_effect=RuntimeError("db fail")):
        await store.append_turn(
            session.session_id,
            user_message=user_msg,
            assistant_message=ai_msg,
            turn_index=1,
        )

    call_count = 0

    def failing_insert(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("still failing")

    with patch("lumina.sessions.insert_message", side_effect=failing_insert):
        for _ in range(4):
            await store.cleanup()

    assert session.dirty_attempts == 3
    assert any("dirty retry exhausted" in r.message for r in caplog.records)
    assert call_count == 3


@pytest.mark.asyncio
async def test_get_miss_load_does_not_touch_last_used_at() -> None:
    from lumina.db.engine import get_connection
    from lumina.db.models import get_conversation

    store = SessionStore()
    session = await _create_session(store)
    store._sessions.clear()
    conn = get_connection(session.project_id)
    before = get_conversation(conn, session.session_id).last_used_at
    await store.get(session.session_id)
    after = get_conversation(conn, session.session_id).last_used_at
    assert after == before


@pytest.mark.asyncio
async def test_get_messages_sorted() -> None:
    store = SessionStore()
    session = await _create_session(store)
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])
    await store.append_turn(
        session.session_id,
        user_message=user_msg,
        assistant_message=ai_msg,
        turn_index=1,
    )
    store._sessions.clear()
    reloaded = await store.get(session.session_id)
    assert reloaded is not None
    roles = [msg.role for msg in reloaded.messages]
    assert roles == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_get_miss_load_404_when_db_status_cleared() -> None:
    store = SessionStore()
    session = await _create_session(store)
    await store.delete(session.session_id)
    store._sessions.clear()
    assert await store.get(session.session_id) is None


@pytest.mark.asyncio
async def test_evict_by_pdf_id_clears_only_matching_sessions() -> None:
    from lumina.db.engine import get_connection
    from lumina.db.models import get_conversation

    store = SessionStore()
    s1 = await _create_session(store)
    s2 = await _create_session(store)
    removed = await store.evict_by_pdf_id(s1.pdf_id)
    assert removed == 1
    assert s1.session_id not in store._sessions
    assert s2.session_id in store._sessions
    conn1 = get_connection(s1.project_id)
    conn2 = get_connection(s2.project_id)
    assert get_conversation(conn1, s1.session_id).status == "active"
    assert get_conversation(conn2, s2.session_id).status == "active"


@pytest.mark.asyncio
async def test_delete_db_failure_raises() -> None:
    from unittest.mock import patch

    from lumina.sessions import DbWriteError

    store = SessionStore()
    session = await _create_session(store)
    with patch(
        "lumina.sessions.mark_conversation_cleared",
        side_effect=RuntimeError("db fail"),
    ):
        with pytest.raises(DbWriteError):
            await store.delete(session.session_id)
