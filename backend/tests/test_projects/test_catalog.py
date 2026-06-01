import json
import time

import pytest

from lumina.config import get_settings
from lumina.db.engine import close_all
from lumina.projects.catalog import (
    Catalog,
    CatalogEntry,
    add_entry,
    find_by_name_and_size,
    find_by_pdf_id,
    find_by_project_id,
    list_entries,
    load_catalog,
    rebuild_from_manifests,
    save_catalog,
)
from lumina.projects.paths import catalog_path, project_manifest_path


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


def _sample_entry(**overrides) -> CatalogEntry:
    data = {
        "id": "proj_01TEST000000000000000001",
        "name": "ddia",
        "path": "projects/proj_01TEST000000000000000001/",
        "created_at": 1000,
        "last_opened_at": 2000,
        "primary_pdf_id": "pdf_01TEST000000000000000001",
        "primary_pdf_filename": "ddia.pdf",
        "primary_pdf_size": 1234,
        "auto_created": True,
    }
    data.update(overrides)
    return CatalogEntry(**data)


def test_load_empty_catalog_creates_skeleton(data_root):
    catalog = load_catalog()
    assert catalog.version == 1
    assert catalog.projects == []
    assert catalog_path().exists()


def test_save_then_load_roundtrip(data_root):
    catalog = Catalog(version=1, projects=[_sample_entry()])
    save_catalog(catalog)
    loaded = load_catalog()
    assert len(loaded.projects) == 1
    assert loaded.projects[0].id == "proj_01TEST000000000000000001"


def test_add_entry_appends(data_root):
    add_entry(_sample_entry())
    entries = list_entries()
    assert len(entries) == 1


def test_remove_entry(data_root):
    add_entry(_sample_entry())
    from lumina.projects.catalog import remove_entry

    remove_entry("proj_01TEST000000000000000001")
    assert find_by_project_id("proj_01TEST000000000000000001") is None


def test_find_by_name_and_size_exact_match(data_root):
    add_entry(_sample_entry())
    hit = find_by_name_and_size("ddia", 1234)
    assert hit is not None
    assert hit.id == "proj_01TEST000000000000000001"


def test_find_by_name_and_size_size_mismatch_returns_none(data_root):
    add_entry(_sample_entry())
    assert find_by_name_and_size("ddia", 9999) is None


def test_find_by_pdf_id(data_root):
    add_entry(_sample_entry())
    hit = find_by_pdf_id("pdf_01TEST000000000000000001")
    assert hit is not None


def test_list_entries_sort_options(data_root):
    add_entry(_sample_entry(name="c", last_opened_at=100, created_at=10))
    add_entry(
        _sample_entry(
            id="proj_02",
            name="a",
            path="projects/proj_02/",
            primary_pdf_id="pdf_02",
            last_opened_at=300,
            created_at=30,
        )
    )
    add_entry(
        _sample_entry(
            id="proj_03",
            name="b",
            path="projects/proj_03/",
            primary_pdf_id="pdf_03",
            last_opened_at=200,
            created_at=20,
        )
    )
    by_opened = [e.name for e in list_entries("last_opened_at_desc")]
    assert by_opened == ["a", "b", "c"]
    by_created = [e.name for e in list_entries("created_at_desc")]
    assert by_created == ["a", "b", "c"]
    by_name = [e.name for e in list_entries("name_asc")]
    assert by_name == ["a", "b", "c"]


def test_corrupted_catalog_triggers_rebuild(data_root, monkeypatch):
    project_id = "proj_rebuild"
    project_manifest_path(project_id).parent.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "project": {
            "id": project_id,
            "name": "rebuilt",
            "created_at": 123,
            "primary_pdf_id": "pdf_rebuild",
            "primary_pdf_filename": "rebuilt.pdf",
            "primary_pdf_size": 42,
        },
    }
    project_manifest_path(project_id).write_text(json.dumps(manifest), encoding="utf-8")
    catalog_path().write_text("{not valid json", encoding="utf-8")
    catalog = load_catalog()
    assert len(catalog.projects) >= 1
    assert catalog_path().read_text(encoding="utf-8").startswith("{")


def test_filelock_acquired_on_save(data_root, monkeypatch):
    acquired = []

    class TrackingLock:
        def __init__(self, path, timeout=-1):
            acquired.append(path)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("lumina.projects.catalog.FileLock", TrackingLock)
    save_catalog(Catalog(version=1, projects=[]))
    assert any(".lock" in p for p in acquired)
