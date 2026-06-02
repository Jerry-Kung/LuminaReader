from __future__ import annotations

from pathlib import Path

from lumina.config import get_settings


def resolve_data_root() -> Path:
    raw = get_settings().lumina_data_root
    if not raw:
        import lumina as _l

        repo_root = Path(_l.__file__).resolve().parents[3]
        return (repo_root / "user_data").resolve()
    return Path(raw).expanduser().resolve()


def settings_json_path() -> Path:
    return resolve_data_root() / "settings.json"


def catalog_path() -> Path:
    return resolve_data_root() / "catalog.json"


def projects_root() -> Path:
    return resolve_data_root() / "projects"


def project_dir(project_id: str) -> Path:
    return projects_root() / project_id


def project_sqlite_path(project_id: str) -> Path:
    return project_dir(project_id) / "lumina.sqlite"


def project_manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "manifest.json"


def project_pdf_path(project_id: str, storage_path: str = "original.pdf") -> Path:
    return project_dir(project_id) / storage_path
