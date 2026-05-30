import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from lumina.logging import get_logger, log_with_fields
from lumina.providers.base import LLMMessage

logger = get_logger("lumina.sessions")


@dataclass
class Session:
    session_id: str
    task_type: str
    extracted_text: str
    messages: list[LLMMessage] = field(default_factory=list)
    created_at: float = 0.0
    last_used_at: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self, *, max_entries: int = 100, ttl_seconds: float = 3600.0) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        task_type: str,
        extracted_text: str,
        meta: dict | None = None,
    ) -> Session:
        async with self._lock:
            now = time.time()
            session = Session(
                session_id=f"sess_{uuid.uuid4().hex}",
                task_type=task_type,
                extracted_text=extracted_text,
                created_at=now,
                last_used_at=now,
                meta=meta or {},
            )
            self._sessions[session.session_id] = session
            self._sessions.move_to_end(session.session_id)
            while len(self._sessions) > self._max_entries:
                self._sessions.popitem(last=False)
            return session

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session.last_used_at > self._ttl_seconds:
                self._sessions.pop(session_id, None)
                return None
            session.last_used_at = time.time()
            self._sessions.move_to_end(session_id)
            return session

    async def append_turn(
        self,
        session_id: str,
        *,
        user_message: LLMMessage,
        assistant_message: LLMMessage,
    ) -> Session | None:
        session = await self.get(session_id)
        if session is None:
            return None
        async with self._lock:
            session.messages.append(user_message)
            session.messages.append(assistant_message)
            session.last_used_at = time.time()
            self._sessions.move_to_end(session_id)
            return session

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

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
