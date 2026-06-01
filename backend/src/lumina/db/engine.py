from __future__ import annotations

import sqlite3
import threading

from lumina.config import get_settings

_CONNECTIONS: dict[str, sqlite3.Connection] = {}
_LOCK = threading.Lock()


def get_connection(project_id: str) -> sqlite3.Connection:
    from lumina.projects.paths import project_sqlite_path
    with _LOCK:
        if project_id in _CONNECTIONS:
            return _CONNECTIONS[project_id]
        settings = get_settings()
        path = project_sqlite_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            path,
            isolation_level=None,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.execute(f"PRAGMA busy_timeout = {settings.lumina_sqlite_busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        _CONNECTIONS[project_id] = conn
        return conn


def close_all() -> None:
    with _LOCK:
        for conn in _CONNECTIONS.values():
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _CONNECTIONS.clear()


def evict(project_id: str) -> None:
    with _LOCK:
        conn = _CONNECTIONS.pop(project_id, None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
