"""Integration coverage for `apply_pending_for_all_projects` (V1.0.4 §6.1).

These tests stand in for the requirements §6.3 cases that exercise the lifespan
hook — a V1.0.3-shaped sqlite under user_data must end up at SCHEMA_VERSION=2
after startup, and a forced MUST-tier failure must raise so the FastAPI lifespan
aborts before serve().
"""
from __future__ import annotations

import sqlite3

import pytest

from lumina.config import get_settings
from lumina.db.engine import close_all
from lumina.db.migrations import (
    INIT_SQL,
    MigrationError,
    SCHEMA_VERSION,
    apply_pending,
    read_schema_version,
)
from lumina.db.models import (
    PdfRow,
    ProjectMetaRow,
    insert_pdf,
    insert_project_meta,
)
from lumina.db.startup import apply_pending_for_all_projects
from lumina.projects.catalog import CatalogEntry, add_entry
from lumina.projects.paths import project_dir, project_sqlite_path


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    close_all()
    yield tmp_path
    close_all()
    get_settings.cache_clear()


def _seed_v103_project(project_id: str, *, pdf_id: str = "pdf_seed") -> None:
    """Build a Project on disk that mimics what V1.0.3 would have left behind:
    catalog entry + sqlite with project_meta row at schema_version=1 + a pdf row
    in the old shape (no last_read_page column).

    Uses INIT_SQL directly rather than initialize_schema() — the latter now
    auto-applies every registered migration as part of V1.0.4's fresh-DB path.
    """
    project_dir(project_id).mkdir(parents=True, exist_ok=True)
    (project_dir(project_id) / "original.pdf").write_bytes(b"%PDF-1.4 fake")
    sqlite_path = project_sqlite_path(project_id)
    conn = sqlite3.connect(sqlite_path, isolation_level=None)
    try:
        conn.executescript(INIT_SQL)
        insert_project_meta(
            conn,
            ProjectMetaRow(
                id=project_id, name="seedbook", created_at=0, schema_version=1
            ),
        )
        insert_pdf(
            conn,
            PdfRow(
                id=pdf_id,
                project_id=project_id,
                filename="seedbook.pdf",
                storage_path="original.pdf",
                file_size=13,
                added_at=0,
                schema_version=1,
            ),
        )
    finally:
        conn.close()
    add_entry(
        CatalogEntry(
            id=project_id,
            name="seedbook",
            path=f"projects/{project_id}/",
            created_at=0,
            last_opened_at=0,
            primary_pdf_id=pdf_id,
            primary_pdf_filename="seedbook.pdf",
            primary_pdf_size=13,
            auto_created=True,
        )
    )


def test_startup_upgrades_v103_projects_to_v104(data_root):
    _seed_v103_project("proj_alpha")
    _seed_v103_project("proj_beta", pdf_id="pdf_beta")

    apply_pending_for_all_projects()

    for project_id in ("proj_alpha", "proj_beta"):
        conn = sqlite3.connect(project_sqlite_path(project_id))
        try:
            assert read_schema_version(conn) == SCHEMA_VERSION == 2
            cols = {row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()}
            assert "last_read_page" in cols
            # Existing pdf row gets the default value, not NULL.
            row = conn.execute(
                "SELECT last_read_page FROM pdfs LIMIT 1"
            ).fetchone()
            assert row[0] == 1
        finally:
            conn.close()


def test_startup_is_idempotent(data_root):
    _seed_v103_project("proj_idem")
    apply_pending_for_all_projects()
    apply_pending_for_all_projects()
    apply_pending_for_all_projects()
    conn = sqlite3.connect(project_sqlite_path("proj_idem"))
    try:
        assert read_schema_version(conn) == 2
        cols = [row[1] for row in conn.execute("PRAGMA table_info(pdfs)").fetchall()]
        assert cols.count("last_read_page") == 1
    finally:
        conn.close()


def test_startup_skips_projects_with_missing_sqlite(data_root):
    """If catalog references a Project whose sqlite went missing (manual edit,
    partial restore), startup must log + skip rather than auto-create an empty DB."""
    add_entry(
        CatalogEntry(
            id="proj_ghost",
            name="ghost",
            path="projects/proj_ghost/",
            created_at=0,
            last_opened_at=0,
            primary_pdf_id="pdf_ghost",
            primary_pdf_filename="ghost.pdf",
            primary_pdf_size=0,
            auto_created=True,
        )
    )
    # Should not raise and must not materialize a new sqlite file.
    apply_pending_for_all_projects()
    assert not project_sqlite_path("proj_ghost").exists()


def test_startup_aborts_on_must_tier_failure(data_root, monkeypatch):
    _seed_v103_project("proj_break")

    from lumina.db import migrations as mig

    def explode(_conn):  # pragma: no cover - assertion handled below
        raise RuntimeError("simulated MUST-tier failure")

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

    with pytest.raises(MigrationError):
        apply_pending_for_all_projects()

    # The Project's DB must still be at schema_version=1 — the transaction rolled back.
    conn = sqlite3.connect(project_sqlite_path("proj_break"))
    try:
        assert read_schema_version(conn) == 1
    finally:
        conn.close()
