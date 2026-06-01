import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from lumina.config import get_settings
from lumina.db.engine import close_all, get_connection
from lumina.db.migrations import read_schema_version
from lumina.projects.manager import (
    ProjectNameConflictError,
    PdfNotFoundError,
    ProjectNotFoundError,
    auto_create_project,
    delete_project,
    lookup_project_by_conversation_id,
    lookup_project_by_pdf_id,
    touch_last_opened_at,
)
from lumina.projects.paths import project_dir, project_manifest_path, project_pdf_path
from lumina.projects.catalog import find_by_project_id
from lumina.db.models import ConversationRow, insert_conversation


PDF_BYTES = b"%PDF-1.4 minimal test content"


@pytest.fixture(autouse=True)
def _reset_engine():
    close_all()
    yield
    close_all()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_auto_create_project_creates_dir_pdf_sqlite_manifest_catalog(data_root):
    created = auto_create_project(PDF_BYTES, "ddia.pdf")
    assert project_dir(created.project_id).exists()
    assert project_pdf_path(created.project_id).read_bytes() == PDF_BYTES
    conn = get_connection(created.project_id)
    assert read_schema_version(conn) == 1
    meta_count = conn.execute("SELECT COUNT(*) FROM project_meta").fetchone()[0]
    pdf_count = conn.execute("SELECT COUNT(*) FROM pdfs").fetchone()[0]
    assert meta_count == 1
    assert pdf_count == 1
    manifest = json.loads(project_manifest_path(created.project_id).read_text())
    assert manifest["project"]["id"] == created.project_id
    entry = find_by_project_id(created.project_id)
    assert entry is not None


def test_auto_create_project_returns_ids_with_correct_prefix(data_root):
    created = auto_create_project(PDF_BYTES, "book.pdf")
    assert created.project_id.startswith("proj_")
    assert created.pdf_id.startswith("pdf_")
    assert len(created.project_id) == len("proj_") + 26
    assert len(created.pdf_id) == len("pdf_") + 26


def test_auto_create_project_name_strips_extension(data_root):
    created = auto_create_project(PDF_BYTES, "ddia.pdf")
    assert created.name == "ddia"


def test_name_conflict_raises_when_not_forced(data_root):
    first = auto_create_project(PDF_BYTES, "ddia.pdf")
    with pytest.raises(ProjectNameConflictError) as exc:
        auto_create_project(PDF_BYTES, "ddia.pdf", force_create_new=False)
    assert exc.value.existing.id == first.project_id


def test_name_conflict_force_create_new_appends_suffix(data_root):
    auto_create_project(PDF_BYTES, "ddia.pdf")
    second = auto_create_project(PDF_BYTES, "ddia.pdf", force_create_new=True)
    assert second.name == "ddia (2)"


def test_name_conflict_force_create_new_finds_next_suffix(data_root):
    auto_create_project(PDF_BYTES, "ddia.pdf")
    auto_create_project(PDF_BYTES, "ddia.pdf", force_create_new=True)
    third = auto_create_project(PDF_BYTES, "ddia.pdf", force_create_new=True)
    assert third.name == "ddia (3)"


def test_name_conflict_same_name_different_size_creates_normally(data_root):
    first = auto_create_project(PDF_BYTES, "ddia.pdf")
    second = auto_create_project(PDF_BYTES + b"x", "ddia.pdf")
    assert first.name == "ddia"
    assert second.name == "ddia"


def test_auto_create_rolls_back_on_failure(data_root, monkeypatch):
    original_write_bytes = type(data_root).write_bytes

    def failing_write_bytes(self, data):
        if self.name == "original.pdf":
            raise OSError("write failed")
        return original_write_bytes(self, data)

    monkeypatch.setattr("pathlib.Path.write_bytes", failing_write_bytes)
    with pytest.raises(OSError):
        auto_create_project(PDF_BYTES, "fail.pdf")
    projects = list((data_root / "projects").glob("*")) if (data_root / "projects").exists() else []
    assert projects == []
    from lumina.projects.catalog import load_catalog

    assert load_catalog().projects == []


def test_lookup_project_by_pdf_id_hit_and_miss(data_root):
    created = auto_create_project(PDF_BYTES, "hit.pdf")
    entry = lookup_project_by_pdf_id(created.pdf_id)
    assert entry.id == created.project_id
    with pytest.raises(PdfNotFoundError):
        lookup_project_by_pdf_id("pdf_missing")


def test_lookup_project_by_conversation_id_scans_all_projects(data_root):
    c1 = auto_create_project(PDF_BYTES, "a.pdf")
    c2 = auto_create_project(PDF_BYTES + b"2", "b.pdf")
    conv_id = "conv_test123456789012345678901"
    conn = get_connection(c2.project_id)
    now = int(time.time())
    insert_conversation(
        conn,
        ConversationRow(
            id=conv_id,
            pdf_id=c2.pdf_id,
            selection_id="sel_test",
            task_type="translate",
            extracted_text="text",
            created_at=now,
            last_used_at=now,
        ),
    )
    entry = lookup_project_by_conversation_id(conv_id)
    assert entry.id == c2.project_id
    with pytest.raises(ProjectNotFoundError):
        lookup_project_by_conversation_id("conv_missing")


def test_delete_project_removes_dir_catalog_and_evicts_connection(data_root):
    created = auto_create_project(PDF_BYTES, "del.pdf")
    conn1 = get_connection(created.project_id)
    delete_project(created.project_id)
    assert not project_dir(created.project_id).exists()
    assert find_by_project_id(created.project_id) is None
    conn2 = get_connection(created.project_id)
    assert conn1 is not conn2


def test_delete_project_missing_raises(data_root):
    with pytest.raises(ProjectNotFoundError):
        delete_project("proj_nonexistent")


def test_touch_last_opened_at_updates_catalog(data_root):
    created = auto_create_project(PDF_BYTES, "touch.pdf")
    before = find_by_project_id(created.project_id).last_opened_at
    time.sleep(0.01)
    touch_last_opened_at(created.project_id)
    after = find_by_project_id(created.project_id).last_opened_at
    assert after >= before
