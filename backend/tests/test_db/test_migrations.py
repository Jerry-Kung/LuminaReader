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


def test_schema_version_constant_is_9():
    assert SCHEMA_VERSION == 9


def test_registry_contains_001_through_009_in_order():
    migrations = registered_migrations()
    versions = [m.target_version for m in migrations]
    filenames = [m.filename for m in migrations]
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert filenames[0] == "001_initial.py"
    assert filenames[1] == "002_add_pdf_last_read_page.py"
    assert filenames[2] == "003_add_pdf_last_read_offset.py"
    assert filenames[3] == "004_selection_text_columns.py"
    assert filenames[4] == "005_pdf_text_tables.py"
    assert filenames[5] == "006_toc_bookmark_tables.py"
    assert filenames[6] == "007_memory_tables.py"
    assert filenames[7] == "008_add_message_sources.py"
    assert filenames[8] == "009_notes_table.py"


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
        "sources_json",
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

    assert new_version == SCHEMA_VERSION
    assert read_schema_version(conn) == SCHEMA_VERSION
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


def test_apply_pending_008_idempotent_when_column_pre_exists(conn):
    """messages.sources_json 已被手工 ALTER 加入时，008 迁移应静默跳过而非报重复列。"""
    _seed_v3_db(conn)  # 复用既有 v3 种子库（含 messages 表，schema_version 落后于 008）
    conn.execute("ALTER TABLE messages ADD COLUMN sources_json TEXT")
    # 不应抛 "duplicate column name: sources_json"
    new_version = apply_pending(conn)
    assert new_version == SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert "sources_json" in cols


def test_apply_pending_009_idempotent_when_table_pre_exists(conn):
    """notes 表已存在时重跑 009 不报错（CREATE TABLE/INDEX IF NOT EXISTS 幂等）。"""
    initialize_schema(conn)  # 建库时已含 notes 表（IF NOT EXISTS，幂等）
    insert_project_meta(
        conn,
        ProjectMetaRow(id="proj_test", name="test", created_at=0, schema_version=8),
    )
    new_version = apply_pending(conn)
    assert new_version == SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    assert "anchor_rects_json" in cols


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


def test_initialize_schema_at_v4_clean_db(conn):
    initialize_schema(conn)
    insert_project_meta(
        conn,
        ProjectMetaRow(id="proj_x", name="x", created_at=0, schema_version=4),
    )
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(selections)").fetchall()}
    assert len(cols) == 14
    assert cols["type"][2] == "TEXT"
    assert cols["type"][3] == 1  # NOT NULL
    assert cols["type"][4] == "'image'"
    for name in ("x", "y", "w", "h", "dpi", "thumbnail_png"):
        assert cols[name][3] == 0  # notnull=0
    assert cols["page"][3] == 1  # notnull=1
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(selections)").fetchall()
    }
    assert "idx_selections_pdf" in indexes


def _seed_v3_db(conn, selections_rows: list[tuple] | None = None) -> None:
    """Simulate a V1.1.3 schema=3 DB with optional selection rows."""
    _seed_v1_project_meta(conn)
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_page INTEGER NOT NULL DEFAULT 1"
    )
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_offset REAL NOT NULL DEFAULT 0"
    )
    conn.execute("UPDATE project_meta SET schema_version = 3")
    if selections_rows:
        for row in selections_rows:
            conn.execute(
                """
                INSERT INTO selections (
                    id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )


def test_migration_004_from_v3_preserves_image_rows(conn):
    thumb = b"\x89PNG\r\n\x1a\n"
    rows = [
        ("sel_1", "pdf_x", 1, 1.0, 2.0, 10.0, 20.0, 144.0, thumb, 100),
        ("sel_2", "pdf_x", 2, 3.0, 4.0, 11.0, 21.0, 150.0, None, 101),
        ("sel_3", "pdf_y", 5, 5.0, 6.0, 12.0, 22.0, 96.0, thumb, 102),
    ]
    _seed_v3_db(conn, rows)
    apply_pending(conn)
    assert read_schema_version(conn) == SCHEMA_VERSION
    upgraded = conn.execute(
        """
        SELECT id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at,
               type, text, page_end, segments_json
        FROM selections ORDER BY id
        """
    ).fetchall()
    assert len(upgraded) == 3
    for original, row in zip(rows, upgraded):
        assert row[0] == original[0]
        assert row[1] == original[1]
        assert row[2] == original[2]
        assert row[3] == original[3]
        assert row[4] == original[4]
        assert row[5] == original[5]
        assert row[6] == original[6]
        assert row[7] == original[7]
        assert row[8] == original[8]
        assert row[9] == original[9]
        assert row[10] == "image"
        assert row[11] is None
        assert row[12] is None
        assert row[13] is None


def test_migration_004_idempotent(conn):
    _seed_v3_db(conn, [("sel_1", "pdf_x", 1, 1.0, 2.0, 10.0, 20.0, 144.0, None, 100)])
    apply_pending(conn)
    info_before = conn.execute("PRAGMA table_info(selections)").fetchall()
    count_before = conn.execute("SELECT COUNT(*) FROM selections").fetchone()[0]
    version_before = read_schema_version(conn)
    apply_pending(conn)
    assert conn.execute("PRAGMA table_info(selections)").fetchall() == info_before
    assert conn.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == count_before
    assert read_schema_version(conn) == version_before


def test_migration_004_keeps_index(conn):
    _seed_v3_db(conn)
    apply_pending(conn)
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(selections)").fetchall()
    }
    assert "idx_selections_pdf" in indexes
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM selections WHERE pdf_id='pdf_x' ORDER BY created_at DESC"
    ).fetchall()
    plan_text = " ".join(str(cell) for row in plan for cell in row)
    assert "idx_selections_pdf" in plan_text or "USING INDEX" in plan_text


def test_migration_004_preserves_conversation_fk(conn):
    _seed_v3_db(conn, [("sel_x", "pdf_a", 1, 1.0, 2.0, 10.0, 20.0, 144.0, None, 100)])
    conn.execute(
        """
        INSERT INTO conversations (
            id, pdf_id, selection_id, task_type, extracted_text,
            created_at, last_used_at, status
        ) VALUES ('conv_1', 'pdf_a', 'sel_x', 'translate', 'text', 0, 0, 'active')
        """
    )
    apply_pending(conn)
    conv = conn.execute(
        "SELECT selection_id FROM conversations WHERE id='conv_1'"
    ).fetchone()
    assert conv[0] == "sel_x"
    sel = conn.execute("SELECT type FROM selections WHERE id='sel_x'").fetchone()
    assert sel[0] == "image"


def test_migration_004_empty_selections_table(conn):
    _seed_v3_db(conn)
    apply_pending(conn)
    assert read_schema_version(conn) == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == 0
    assert len(conn.execute("PRAGMA table_info(selections)").fetchall()) == 14


def test_apply_pending_runs_004_005_006_007_008_and_009_when_at_v3(monkeypatch, conn):
    _seed_v3_db(conn)
    from lumina.db import migrations as mig

    calls: list[int] = []
    original = list(mig._REGISTRY)
    patched = []
    for entry in mig._REGISTRY:
        original_apply = entry.apply_fn

        def _spy(apply_fn=original_apply, version=entry.target_version):
            def wrapped(c):
                calls.append(version)
                return apply_fn(c)

            return wrapped

        patched.append(
            mig._LoadedMigration(
                target_version=entry.target_version,
                description=entry.description,
                filename=entry.filename,
                apply_fn=_spy(),
            )
        )
    monkeypatch.setattr(mig, "_REGISTRY", patched)
    try:
        apply_pending(conn)
        assert calls == [4, 5, 6, 7, 8, 9]
    finally:
        monkeypatch.setattr(mig, "_REGISTRY", original)


def test_initialize_schema_includes_last_read_offset_column(conn):
    initialize_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
    assert "last_read_offset" in cols
    sel_cols = {row[1] for row in conn.execute("PRAGMA table_info(selections)").fetchall()}
    assert {"type", "text", "page_end", "segments_json"} <= sel_cols
