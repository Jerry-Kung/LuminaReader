import asyncio
from unittest.mock import patch

import pytest

from lumina.providers.base import LLMMessage, TextPart
from lumina.sessions import (
    SessionStore,
    cleanup_loop,
    get_session_store,
    init_session_store,
    reset_session_store,
)


@pytest.mark.asyncio
async def test_create_and_get_roundtrip() -> None:
    store = SessionStore()
    session = await store.create(task_type="translate", extracted_text="hello", meta={"page": 1})

    assert session.session_id.startswith("sess_")
    assert session.task_type == "translate"
    assert session.extracted_text == "hello"
    assert session.messages == []
    assert session.meta == {"page": 1}

    fetched = await store.get(session.session_id)
    assert fetched is session


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    store = SessionStore()
    assert await store.get("sess_does_not_exist") is None


@pytest.mark.asyncio
async def test_append_turn_adds_two_messages() -> None:
    store = SessionStore()
    session = await store.create(task_type="translate", extracted_text="hello")
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])

    updated = await store.append_turn(
        session.session_id,
        user_message=user_msg,
        assistant_message=ai_msg,
    )

    assert updated is not None
    assert len(updated.messages) == 2
    assert updated.messages[0].role == "user"
    assert updated.messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_append_turn_missing_returns_none() -> None:
    store = SessionStore()
    user_msg = LLMMessage(role="user", content=[TextPart(text="q1")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a1")])
    assert await store.append_turn("missing", user_message=user_msg, assistant_message=ai_msg) is None


@pytest.mark.asyncio
async def test_delete_existing_returns_true_and_idempotent() -> None:
    store = SessionStore()
    session = await store.create(task_type="translate", extracted_text="hello")

    assert await store.delete(session.session_id) is True
    assert await store.delete(session.session_id) is False


@pytest.mark.asyncio
async def test_delete_then_get_returns_none() -> None:
    store = SessionStore()
    session = await store.create(task_type="translate", extracted_text="hello")
    await store.delete(session.session_id)
    assert await store.get(session.session_id) is None


@pytest.mark.asyncio
async def test_lru_evicts_oldest_when_exceeding_max_entries() -> None:
    store = SessionStore(max_entries=3)
    s1 = await store.create(task_type="translate", extracted_text="1")
    s2 = await store.create(task_type="translate", extracted_text="2")
    s3 = await store.create(task_type="translate", extracted_text="3")
    s4 = await store.create(task_type="translate", extracted_text="4")

    assert await store.get(s1.session_id) is None
    assert await store.get(s2.session_id) is not None
    assert await store.get(s3.session_id) is not None
    assert await store.get(s4.session_id) is not None
    assert s4.session_id


@pytest.mark.asyncio
async def test_get_refreshes_lru_position() -> None:
    store = SessionStore(max_entries=3)
    s1 = await store.create(task_type="translate", extracted_text="1")
    s2 = await store.create(task_type="translate", extracted_text="2")
    s3 = await store.create(task_type="translate", extracted_text="3")

    await store.get(s1.session_id)
    await store.create(task_type="translate", extracted_text="4")

    assert await store.get(s2.session_id) is None
    assert await store.get(s1.session_id) is not None
    assert await store.get(s3.session_id) is not None


@pytest.mark.asyncio
async def test_append_turn_refreshes_lru_position() -> None:
    store = SessionStore(max_entries=3)
    s1 = await store.create(task_type="translate", extracted_text="1")
    s2 = await store.create(task_type="translate", extracted_text="2")
    s3 = await store.create(task_type="translate", extracted_text="3")

    user_msg = LLMMessage(role="user", content=[TextPart(text="q")])
    ai_msg = LLMMessage(role="assistant", content=[TextPart(text="a")])
    await store.append_turn(s1.session_id, user_message=user_msg, assistant_message=ai_msg)
    await store.create(task_type="translate", extracted_text="4")

    assert await store.get(s2.session_id) is None
    assert await store.get(s1.session_id) is not None
    assert await store.get(s3.session_id) is not None


@pytest.mark.asyncio
async def test_get_returns_none_when_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    session = await store.create(task_type="translate", extracted_text="hello")
    await asyncio.sleep(0.1)
    assert await store.get(session.session_id) is None
    assert len(store) == 0


@pytest.mark.asyncio
async def test_get_within_ttl_still_alive() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=2.0)
    session = await store.create(task_type="translate", extracted_text="hello")
    previous_last_used = session.last_used_at
    await asyncio.sleep(0.05)
    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.last_used_at >= previous_last_used


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    s1 = await store.create(task_type="translate", extracted_text="1")
    await asyncio.sleep(0.1)
    s2 = await store.create(task_type="translate", extracted_text="2")

    removed = await store.cleanup()
    assert removed == 1
    assert await store.get(s1.session_id) is None
    assert await store.get(s2.session_id) is not None


@pytest.mark.asyncio
async def test_cleanup_zero_when_nothing_expired() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=3600.0)
    await store.create(task_type="translate", extracted_text="hello")
    assert await store.cleanup() == 0


@pytest.mark.asyncio
async def test_cleanup_loop_invokes_cleanup_periodically() -> None:
    store = SessionStore(max_entries=10, ttl_seconds=0.05)
    task = asyncio.create_task(cleanup_loop(store, interval_seconds=0.05))
    session = await store.create(task_type="translate", extracted_text="hello")
    await asyncio.sleep(0.2)
    assert await store.get(session.session_id) is None
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
