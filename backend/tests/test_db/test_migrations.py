import sqlite3

import pytest

from lumina.db.migrations import (
    SCHEMA_VERSION,
    SchemaVersionTooNewError,
    initialize_schema,
    migrate,
    read_schema_version,
)
from lumina.db.models import ProjectMetaRow, insert_project_meta


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    yield connection
    connection.close()


def test_schema_version_constant():
    assert SCHEMA_VERSION == 1


def test_init_sql_creates_five_tables(conn):
    initialize_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert names >= {
        "project_meta",
        "pdfs",
        "selections",
        "conversations",
        "messages",
    }


def test_init_sql_creates_three_indexes(conn):
    initialize_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert names >= {
        "idx_selections_pdf",
        "idx_conversations_pdf",
        "idx_messages_conv",
    }


def test_init_sql_is_idempotent(conn):
    initialize_schema(conn)
    initialize_schema(conn)


def test_read_schema_version_returns_none_for_empty_db(conn):
    assert read_schema_version(conn) is None


def test_read_schema_version_returns_one_after_insert(conn):
    initialize_schema(conn)
    insert_project_meta(
        conn,
        ProjectMetaRow(id="proj_x", name="x", created_at=0, schema_version=1),
    )
    assert read_schema_version(conn) == 1


def test_migrate_no_op_when_same_version(conn):
    migrate(conn, 1, 1)


def test_migrate_raises_not_implemented_when_upgrade_needed(conn):
    with pytest.raises(NotImplementedError):
        migrate(conn, 1, 2)


def test_migrate_raises_schema_too_new(conn):
    with pytest.raises(SchemaVersionTooNewError):
        migrate(conn, 2, 1)


def test_messages_table_columns(conn):
    initialize_schema(conn)
    rows = conn.execute("PRAGMA table_info(messages)").fetchall()
    columns = {row[1] for row in rows}
    assert {
        "turn_index",
        "role",
        "content",
        "user_question",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
    } <= columns
