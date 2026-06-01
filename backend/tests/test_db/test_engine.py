import sqlite3

import pytest

from lumina.config import Settings, get_settings
from lumina.db import engine
from lumina.db.engine import close_all, evict, get_connection


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    close_all()
    yield
    close_all()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_get_connection_returns_same_for_same_project_id(data_root):
    conn1 = get_connection("proj_X")
    conn2 = get_connection("proj_X")
    assert conn1 is conn2


def test_get_connection_returns_different_for_different_project_id(data_root):
    conn_x = get_connection("proj_X")
    conn_y = get_connection("proj_Y")
    assert conn_x is not conn_y


def test_busy_timeout_applied(data_root):
    conn = get_connection("proj_timeout")
    row = conn.execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == get_settings().lumina_sqlite_busy_timeout_ms


def test_foreign_keys_enabled(data_root):
    conn = get_connection("proj_fk")
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1


def test_evict_releases_connection(data_root):
    conn = get_connection("proj_evict")
    evict("proj_evict")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_close_all_clears_cache(data_root):
    conn = get_connection("proj_close")
    close_all()
    assert "proj_close" not in engine._CONNECTIONS
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
