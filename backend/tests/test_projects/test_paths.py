from pathlib import Path

import pytest

from lumina.config import get_settings
from lumina.projects.paths import (
    project_dir,
    project_sqlite_path,
    resolve_data_root,
)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_resolve_data_root_defaults_to_repo_user_data(monkeypatch):
    monkeypatch.delenv("LUMINA_DATA_ROOT", raising=False)
    get_settings.cache_clear()
    root = resolve_data_root()
    assert root.name == "user_data"
    assert root.is_absolute()
    get_settings.cache_clear()


def test_resolve_data_root_respects_explicit(data_root):
    assert resolve_data_root() == data_root.resolve()


def test_project_dir_composition(data_root):
    assert project_dir("proj_X") == resolve_data_root() / "projects" / "proj_X"
    assert project_sqlite_path("proj_X").name == "lumina.sqlite"


def test_paths_are_pathlib_not_str(data_root):
    assert isinstance(resolve_data_root(), Path)
    assert isinstance(project_dir("proj_X"), Path)
