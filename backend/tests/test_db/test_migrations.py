import sqlite3
from pathlib import Path

import pytest

from lumina.db.migrations import (
    INIT_SQL,
    SCHEMA_VERSION,
    MigrationError,
    SchemaVersionTooNewError,
    apply_pending,
    initialize_schema,
    migrate,
    read_schema_version,
    registered_migrations,
)
from lumina.db.models import ProjectMetaRow, insert_project_meta


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    yield connection
    connection.close()


def _seed_v1_project_meta(conn) -> None:
    """Initialize a V1.0.3-shaped DB: tables built + a project_meta row at version 1.

    Uses INIT_SQL directly (not the V1.0.4 initialize_schema, which auto-applies
    every registered migration) so the seed is faithful to a pre-V1.0.4 sqlite.
    """
    conn.executescript(INIT_SQL)
    insert_project_meta(
        conn,
        ProjectMetaRow(id="proj_test", name="test", created_at=0, schema_version=1),
    )


# ---------------------------------------------------------------------------
# Registry & SCHEMA_VERSION
# ---------------------------------------------------------------------------


def test_schema_version_is_three_in_v113():
    assert SCHEMA_VERSION == 3


def test_registry_contains_001_002_003_in_order():
    migrations = registered_migrations()
    versions = [m.target_version for m in migrations]
    filenames = [m.filename for m in migrations]
    assert versions == [1, 2, 3]
    assert filenames[0] == "001_initial.py"
    assert filenames[1] == "002_add_pdf_last_read_page.py"
    assert filenames[2] == "003_add_pdf_last_read_offset.py"


# ---------------------------------------------------------------------------
# initialize_schema (idempotent) + table inventory
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# read_schema_version
# ---------------------------------------------------------------------------


def test_read_schema_version_returns_none_for_empty_db(conn):
    assert read_schema_version(conn) is None


def test_read_schema_version_returns_one_after_insert(conn):
    initialize_schema(conn)
    insert_project_meta(
        conn,
        ProjectMetaRow(id="proj_x", name="x", created_at=0, schema_version=1),
    )
    assert read_schema_version(conn) == 1


# ---------------------------------------------------------------------------
# migrate() (legacy signature)
# ---------------------------------------------------------------------------


def test_migrate_no_op_when_same_version(conn):
    migrate(conn, 1, 1)


def test_migrate_raises_schema_too_new(conn):
    with pytest.raises(SchemaVersionTooNewError):
        migrate(conn, 3, 2)


def test_migrate_to_unregistered_version_raises_not_implemented(conn):
    _seed_v1_project_meta(conn)
    with pytest.raises(NotImplementedError):
        migrate(conn, 1, 99)


# ---------------------------------------------------------------------------
# apply_pending — the V1.0.4 entry point
# ---------------------------------------------------------------------------


def test_apply_pending_returns_zero_on_fresh_db(conn):
    # Empty DB: no project_meta row yet; apply_pending must be a no-op so that
    # auto_create_project's initialize_schema path is not double-applied.
    assert apply_pending(conn) == 0


def test_apply_pending_upgrades_v103_db_to_current(conn):
    _seed_v1_project_meta(conn)
    # A pristine V1.0.3 DB has no `last_read_page` column.
    cols_before = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_page" not in cols_before
    assert "last_read_offset" not in cols_before

    new_version = apply_pending(conn)

    assert new_version == SCHEMA_VERSION == 3
    assert read_schema_version(conn) == 3
    cols_after = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_page" in cols_after
    assert "last_read_offset" in cols_after


def test_apply_pending_default_value_for_existing_pdfs(conn):
    """Mirrors the requirements §6.3 case: a V1.0.3 DB with 5 books upgrades cleanly."""
    _seed_v1_project_meta(conn)
    for i in range(5):
        conn.execute(
            """
            INSERT INTO pdfs (id, project_id, filename, storage_path,
                              file_size, added_at, schema_version)
            VALUES (?, 'proj_test', ?, 'original.pdf', 1024, 0, 1)
            """,
            (f"pdf_{i:03d}", f"book{i}.pdf"),
        )

    apply_pending(conn)

    rows = conn.execute(
        "SELECT id, last_read_page, last_read_offset FROM pdfs ORDER BY id"
    ).fetchall()
    assert len(rows) == 5
    assert all(row[1] == 1 for row in rows)
    assert all(row[2] == 0.0 for row in rows)


def test_apply_pending_is_idempotent(conn):
    _seed_v1_project_meta(conn)
    apply_pending(conn)
    # Second call must be a no-op: schema_version already current, no column re-add.
    apply_pending(conn)
    apply_pending(conn)
    assert read_schema_version(conn) == SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    last_read_page_count = sum(1 for c in cols if c == "last_read_page")
    last_read_offset_count = sum(1 for c in cols if c == "last_read_offset")
    assert last_read_page_count == 1
    assert last_read_offset_count == 1


def test_apply_pending_002_idempotent_when_column_pre_exists(conn):
    """Directly verifies the PRAGMA-detection branch of 002 itself.

    Mirrors what would happen if a developer ran the ALTER TABLE manually before
    the migration registry caught up.
    """
    _seed_v1_project_meta(conn)
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_page INTEGER NOT NULL DEFAULT 1"
    )
    # schema_version is still 1, but the column already exists. apply_pending must
    # succeed without re-adding the column (which would raise duplicate column error).
    new_version = apply_pending(conn)
    assert new_version == SCHEMA_VERSION
    assert read_schema_version(conn) == SCHEMA_VERSION


def test_apply_pending_003_idempotent_when_column_pre_exists(conn):
    """Directly verifies the PRAGMA-detection branch of 003 itself."""
    _seed_v104_schema2_db(conn)
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_offset REAL NOT NULL DEFAULT 0"
    )
    # schema_version=2 but last_read_offset already exists; 003 must skip.
    new_version = apply_pending(conn)
    assert new_version == SCHEMA_VERSION
    assert read_schema_version(conn) == SCHEMA_VERSION


def _seed_v104_schema2_db(conn) -> None:
    """Simulate a V1.0.4 schema=2 DB: has last_read_page but not last_read_offset."""
    _seed_v1_project_meta(conn)
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_page INTEGER NOT NULL DEFAULT 1"
    )
    conn.execute("UPDATE project_meta SET schema_version = 2")
    for i in range(3):
        conn.execute(
            """
            INSERT INTO pdfs (id, project_id, filename, storage_path,
                              file_size, added_at, schema_version, last_read_page)
            VALUES (?, 'proj_test', ?, 'original.pdf', 1024, 0, 1, ?)
            """,
            (f"pdf_{i:03d}", f"book{i}.pdf", i + 10),
        )


def test_apply_pending_upgrades_v104_schema2_to_v113(conn):
    _seed_v104_schema2_db(conn)
    cols_before = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_page" in cols_before
    assert "last_read_offset" not in cols_before

    apply_pending(conn)

    assert read_schema_version(conn) == SCHEMA_VERSION
    cols_after = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_offset" in cols_after
    rows = conn.execute(
        "SELECT id, last_read_page, last_read_offset FROM pdfs ORDER BY id"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0] == ("pdf_000", 10, 0.0)
    assert rows[1] == ("pdf_001", 11, 0.0)
    assert rows[2] == ("pdf_002", 12, 0.0)


def test_apply_pending_v104_schema2_upgrade_is_idempotent(conn):
    _seed_v104_schema2_db(conn)
    apply_pending(conn)
    rows_before = conn.execute(
        "SELECT id, last_read_page, last_read_offset FROM pdfs ORDER BY id"
    ).fetchall()
    apply_pending(conn)
    rows_after = conn.execute(
        "SELECT id, last_read_page, last_read_offset FROM pdfs ORDER BY id"
    ).fetchall()
    assert rows_before == rows_after
    assert read_schema_version(conn) == SCHEMA_VERSION


def test_apply_pending_upgrades_v112_schema2_full_data(conn):
    """Mirrors V1.1.2 schema=2 with conversations/messages; all data must survive."""
    _seed_v1_project_meta(conn)
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_page INTEGER NOT NULL DEFAULT 1"
    )
    conn.execute("UPDATE project_meta SET schema_version = 2")
    conn.execute(
        """
        INSERT INTO pdfs (id, project_id, filename, storage_path,
                          file_size, added_at, schema_version, last_read_page)
        VALUES ('pdf_a', 'proj_test', 'a.pdf', 'original.pdf', 100, 0, 1, 5),
               ('pdf_b', 'proj_test', 'b.pdf', 'original.pdf', 200, 1, 1, 8)
        """
    )
    for i in range(3):
        conn.execute(
            """
            INSERT INTO conversations (
                id, pdf_id, selection_id, task_type, extracted_text,
                created_at, last_used_at, status
            ) VALUES (?, 'pdf_a', 'sel_x', 'translate', 'text', 0, 0, 'active')
            """,
            (f"conv_{i}",),
        )
    for i in range(6):
        conn.execute(
            """
            INSERT INTO messages (
                id, conversation_id, turn_index, role, content,
                user_question, model, prompt_tokens, completion_tokens,
                latency_ms, created_at
            ) VALUES (?, 'conv_0', ?, 'user', 'hi', 'hi', NULL, NULL, NULL, NULL, 0)
            """,
            (f"msg_{i}", i),
        )

    apply_pending(conn)

    assert read_schema_version(conn) == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 6
    rows = conn.execute(
        "SELECT id, last_read_page, last_read_offset FROM pdfs ORDER BY id"
    ).fetchall()
    assert rows == [("pdf_a", 5, 0.0), ("pdf_b", 8, 0.0)]


def test_apply_pending_rejects_newer_db(conn):
    _seed_v1_project_meta(conn)
    conn.execute("UPDATE project_meta SET schema_version = 999")
    with pytest.raises(SchemaVersionTooNewError):
        apply_pending(conn)


# ---------------------------------------------------------------------------
# MUST-tier failure path (MigrationError)
# ---------------------------------------------------------------------------


def test_apply_pending_wraps_failure_in_migration_error(monkeypatch, conn):
    """If 002.apply() raises, apply_pending must abort with MigrationError so the
    main lifespan can refuse to enter serve()."""
    _seed_v1_project_meta(conn)

    from lumina.db import migrations as mig

    def explode(_conn):  # pragma: no cover - control flow asserts handled below
        raise RuntimeError("simulated MUST-tier failure")

    # Replace the registered 002 migration's apply_fn with the exploder.
    original = list(mig._REGISTRY)
    patched = []
    for entry in mig._REGISTRY:
        if entry.target_version == 2:
            patched.append(
                mig._LoadedMigration(
                    target_version=entry.target_version,
                    description=entry.description,
                    filename=entry.filename,
                    apply_fn=explode,
                )
            )
        else:
            patched.append(entry)
    monkeypatch.setattr(mig, "_REGISTRY", patched)

    try:
        with pytest.raises(MigrationError):
            apply_pending(conn)
        # schema_version must NOT have advanced past 1 — the transaction rolled back.
        assert read_schema_version(conn) == 1
    finally:
        monkeypatch.setattr(mig, "_REGISTRY", original)


# ---------------------------------------------------------------------------
# 001 INIT_SQL still ships the V1.0.3 schema (no last_read_page yet)
# ---------------------------------------------------------------------------


def test_init_sql_does_not_include_last_read_page():
    """001_initial.py must keep the V1.0.3 schema verbatim; 002 owns the new column.

    Why: a fresh DB at SCHEMA_VERSION=N is built via initialize_schema() + apply_pending();
    if 001 already had last_read_page we'd lose the test surface for 002's PRAGMA branch.
    """
    assert "last_read_page" not in INIT_SQL


def test_init_sql_does_not_include_last_read_offset():
    """003 owns last_read_offset; 001 must not pre-ship it."""
    assert "last_read_offset" not in INIT_SQL


def test_initialize_schema_includes_last_read_offset_column(conn):
    initialize_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_offset" in cols
