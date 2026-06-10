import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

from ulid import ULID

from lumina.db.engine import get_connection
from lumina.db.models import (
    ConversationRow,
    MessageRow,
    SelectionRow,
    delete_messages_of_conversation,
    get_conversation,
    get_selection_type,
    insert_conversation,
    insert_message,
    insert_selection,
    list_messages,
    mark_conversation_cleared,
    count_messages,
    update_assistant_message_at_turn,
    update_conversation_extracted_text,
    update_conversation_last_used,
)
from lumina.logging import get_logger, log_with_fields
from lumina.providers.base import LLMMessage, TextPart
from lumina.projects.manager import (
    ProjectNotFoundError,
    lookup_project_by_conversation_id,
)

logger = get_logger("lumina.sessions")

DIRTY_RETRY_MAX = 3


class SessionNotFoundError(Exception):
    pass


class DbWriteError(Exception):
    pass


@dataclass
class Session:
    session_id: str
    task_type: str
    extracted_text: str
    messages: list[LLMMessage] = field(default_factory=list)
    created_at: float = 0.0
    last_used_at: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    pdf_id: str = ""
    selection_type: Literal["text", "image"] = "image"
    dirty: bool = False
    dirty_attempts: int = 0


def _message_row_to_llm(row: MessageRow) -> LLMMessage:
    return LLMMessage(role=row.role, content=[TextPart(text=row.content)])


class SessionStore:
    def __init__(self, *, max_entries: int = 100, ttl_seconds: float = 3600.0) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    def _touch_lru(self, session_id: str) -> None:
        self._sessions.move_to_end(session_id)

    def _evict_lru_if_needed(self) -> None:
        while len(self._sessions) > self._max_entries:
            self._sessions.popitem(last=False)

    async def create(
        self,
        *,
        conversation_id: str,
        project_id: str,
        pdf_id: str,
        selection_id: str,
        task_type: str,
        extracted_text: str,
        selection_row: SelectionRow,
        first_user_question: str | None,
        first_user_content: str,
        first_assistant_text: str,
        first_assistant_meta: dict,
        meta: dict | None = None,
        selection_type: Literal["text", "image"] = "image",
    ) -> Session:
        now = time.time()
        ts = int(now)
        conn = get_connection(project_id)
        user_msg_id = f"msg_{ULID()}"
        assistant_msg_id = f"msg_{ULID()}"

        try:
            conn.execute("BEGIN")
            insert_selection(conn, selection_row)
            insert_conversation(
                conn,
                ConversationRow(
                    id=conversation_id,
                    pdf_id=pdf_id,
                    selection_id=selection_id,
                    task_type=task_type,
                    extracted_text=extracted_text,
                    created_at=ts,
                    last_used_at=ts,
                    status="active",
                ),
            )
            insert_message(
                conn,
                MessageRow(
                    id=user_msg_id,
                    conversation_id=conversation_id,
                    turn_index=0,
                    role="user",
                    content=first_user_content,
                    user_question=first_user_question,
                    model=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    latency_ms=None,
                    created_at=ts,
                ),
            )
            insert_message(
                conn,
                MessageRow(
                    id=assistant_msg_id,
                    conversation_id=conversation_id,
                    turn_index=0,
                    role="assistant",
                    content=first_assistant_text,
                    user_question=None,
                    model=first_assistant_meta.get("model"),
                    prompt_tokens=first_assistant_meta.get("prompt_tokens"),
                    completion_tokens=first_assistant_meta.get("completion_tokens"),
                    latency_ms=first_assistant_meta.get("latency_ms"),
                    created_at=ts,
                ),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise DbWriteError("Failed to persist session") from exc

        user_llm = LLMMessage(role="user", content=[TextPart(text=first_user_content)])
        assistant_llm = LLMMessage(
            role="assistant", content=[TextPart(text=first_assistant_text)]
        )
        session = Session(
            session_id=conversation_id,
            task_type=task_type,
            extracted_text=extracted_text,
            messages=[user_llm, assistant_llm],
            created_at=now,
            last_used_at=now,
            meta=meta or {},
            project_id=project_id,
            pdf_id=pdf_id,
            selection_type=selection_type,
            dirty=False,
        )
        async with self._lock:
            self._sessions[session.session_id] = session
            self._touch_lru(session.session_id)
            self._evict_lru_if_needed()
        return session

    async def _load_from_db(self, session_id: str) -> Session:
        try:
            entry = lookup_project_by_conversation_id(session_id)
        except ProjectNotFoundError as exc:
            raise SessionNotFoundError(session_id) from exc

        conn = get_connection(entry.id)
        conv = get_conversation(conn, session_id)
        if conv is None or conv.status != "active":
            raise SessionNotFoundError(session_id)

        message_rows = list_messages(conn, session_id)
        messages = [_message_row_to_llm(row) for row in message_rows]
        selection_type: Literal["text", "image"] = (
            get_selection_type(conn, conv.selection_id) or "image"
        )
        now = time.time()
        session = Session(
            session_id=conv.id,
            task_type=conv.task_type,
            extracted_text=conv.extracted_text,
            messages=messages,
            created_at=float(conv.created_at),
            last_used_at=now,
            meta={},
            project_id=entry.id,
            pdf_id=conv.pdf_id,
            selection_type=selection_type,
            dirty=False,
        )
        async with self._lock:
            self._sessions[session_id] = session
            self._touch_lru(session_id)
            self._evict_lru_if_needed()
        return session

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                if time.time() - session.last_used_at > self._ttl_seconds:
                    del self._sessions[session_id]
                    session = None
                else:
                    session.last_used_at = time.time()
                    self._touch_lru(session_id)
                    return session

        try:
            return await self._load_from_db(session_id)
        except SessionNotFoundError:
            return None

    async def append_turn(
        self,
        session_id: str,
        *,
        user_message: LLMMessage,
        assistant_message: LLMMessage,
        turn_index: int | None = None,
        assistant_meta: dict | None = None,
        interrupted: bool = False,
    ) -> Session | None:
        session = await self.get(session_id)
        if session is None:
            return None

        if turn_index is None:
            turn_index = len(session.messages) // 2

        user_text = user_message.content[0].text if user_message.content else ""
        assistant_text = (
            assistant_message.content[0].text if assistant_message.content else ""
        )
        if interrupted:
            assistant_text = f"{assistant_text}\n\n[interrupted]"
        meta = dict(assistant_meta or {})
        if interrupted:
            meta["completion_tokens"] = None
        ts = int(time.time())

        final_assistant = LLMMessage(
            role="assistant", content=[TextPart(text=assistant_text)]
        )
        async with self._lock:
            session.messages.append(user_message)
            session.messages.append(final_assistant)
            session.last_used_at = time.time()
            self._touch_lru(session_id)

        try:
            conn = get_connection(session.project_id)
            conn.execute("BEGIN")
            insert_message(
                conn,
                MessageRow(
                    id=f"msg_{ULID()}",
                    conversation_id=session_id,
                    turn_index=turn_index,
                    role="user",
                    content=user_text,
                    user_question=user_text,
                    model=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    latency_ms=None,
                    created_at=ts,
                ),
            )
            insert_message(
                conn,
                MessageRow(
                    id=f"msg_{ULID()}",
                    conversation_id=session_id,
                    turn_index=turn_index,
                    role="assistant",
                    content=assistant_text,
                    user_question=None,
                    model=meta.get("model"),
                    prompt_tokens=meta.get("prompt_tokens"),
                    completion_tokens=meta.get("completion_tokens"),
                    latency_ms=meta.get("latency_ms"),
                    created_at=ts,
                ),
            )
            update_conversation_last_used(conn, session_id, ts)
            conn.execute("COMMIT")
            session.dirty = False
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            session.dirty = True

        return session

    async def finalize_streaming_assistant(
        self,
        session_id: str,
        *,
        turn_index: int,
        assistant_text: str,
        interrupted: bool = False,
        assistant_meta: dict | None = None,
        extracted_text_override: str | None = None,
    ) -> Session | None:
        session = await self.get(session_id)
        if session is None:
            return None

        final_text = assistant_text
        if interrupted:
            final_text = f"{assistant_text}\n\n[interrupted]"
        meta = dict(assistant_meta or {})
        if interrupted:
            meta["completion_tokens"] = None
        ts = int(time.time())
        assistant_idx = turn_index * 2 + 1

        async with self._lock:
            if assistant_idx < len(session.messages):
                session.messages[assistant_idx] = LLMMessage(
                    role="assistant", content=[TextPart(text=final_text)]
                )
            session.last_used_at = time.time()
            self._touch_lru(session_id)

        try:
            conn = get_connection(session.project_id)
            conn.execute("BEGIN")
            update_assistant_message_at_turn(
                conn,
                session_id,
                turn_index,
                content=final_text,
                model=meta.get("model"),
                prompt_tokens=meta.get("prompt_tokens"),
                completion_tokens=meta.get("completion_tokens"),
                latency_ms=meta.get("latency_ms"),
            )
            update_conversation_last_used(conn, session_id, ts)
            if extracted_text_override is not None:
                update_conversation_extracted_text(
                    conn, session_id, extracted_text_override
                )
                session.extracted_text = extracted_text_override
            conn.execute("COMMIT")
            session.dirty = False
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            session.dirty = True

        return session

    async def delete(self, session_id: str) -> bool:
        try:
            entry = lookup_project_by_conversation_id(session_id)
        except ProjectNotFoundError:
            return False

        async with self._lock:
            self._sessions.pop(session_id, None)

        conn = get_connection(entry.id)
        conv = get_conversation(conn, session_id)
        if conv is None or conv.status == "cleared":
            return False

        try:
            conn.execute("BEGIN")
            mark_conversation_cleared(conn, session_id)
            delete_messages_of_conversation(conn, session_id)
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise DbWriteError("Failed to clear session in DB") from exc
        return True

    async def evict_by_pdf_id(self, pdf_id: str) -> int:
        removed = 0
        async with self._lock:
            to_remove = [
                sid
                for sid, session in self._sessions.items()
                if session.pdf_id == pdf_id
            ]
            for sid in to_remove:
                del self._sessions[sid]
                removed += 1
        return removed

    async def retry_dirty_sessions(self) -> None:
        async with self._lock:
            candidates = [
                session
                for session in self._sessions.values()
                if session.dirty and session.dirty_attempts < DIRTY_RETRY_MAX
            ]

        for session in candidates:
            session_id = session.session_id
            conn = None
            try:
                conn = get_connection(session.project_id)
                db_count = count_messages(conn, session_id)
                missing = session.messages[db_count:]
                if not missing:
                    session.dirty = False
                    session.dirty_attempts = 0
                    continue

                ts = int(time.time())
                conn.execute("BEGIN")
                for offset, msg in enumerate(missing):
                    index = db_count + offset
                    turn_index = index // 2
                    content = msg.content[0].text if msg.content else ""
                    insert_message(
                        conn,
                        MessageRow(
                            id=f"msg_{ULID()}",
                            conversation_id=session_id,
                            turn_index=turn_index,
                            role=msg.role,
                            content=content,
                            user_question=content if msg.role == "user" else None,
                            model=None,
                            prompt_tokens=None,
                            completion_tokens=None,
                            latency_ms=None,
                            created_at=ts,
                        ),
                    )
                update_conversation_last_used(conn, session_id, ts)
                conn.execute("COMMIT")
                session.dirty = False
                session.dirty_attempts = 0
                log_with_fields(
                    logger,
                    logging.INFO,
                    "dirty session retry succeeded",
                    session_id=session_id,
                )
            except Exception:
                if conn is not None:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                session.dirty_attempts += 1
                if session.dirty_attempts >= DIRTY_RETRY_MAX:
                    log_with_fields(
                        logger,
                        logging.WARNING,
                        f"session {session_id} dirty retry exhausted after {session.dirty_attempts} attempts",
                        session_id=session_id,
                        dirty_attempts=session.dirty_attempts,
                    )

    async def cleanup(self) -> int:
        async with self._lock:
            now = time.time()
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.last_used_at > self._ttl_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
        await self.retry_dirty_sessions()
        return len(expired)

    def __len__(self) -> int:
        return len(self._sessions)


async def cleanup_loop(store: SessionStore, interval_seconds: float = 60.0) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removed = await store.cleanup()
            if removed > 0:
                log_with_fields(
                    logger,
                    logging.INFO,
                    "session cleanup removed entries",
                    removed=removed,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log_with_fields(
                logger,
                logging.WARNING,
                "session cleanup loop error",
            )


_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    if _session_store is None:
        raise RuntimeError("SessionStore not initialized; call init_session_store() in app lifespan.")
    return _session_store


def init_session_store(*, max_entries: int, ttl_seconds: float) -> SessionStore:
    global _session_store
    _session_store = SessionStore(max_entries=max_entries, ttl_seconds=ttl_seconds)
    return _session_store


def reset_session_store() -> None:
    global _session_store
    _session_store = None
