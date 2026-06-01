from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from filelock import FileLock

from lumina.logging import get_logger, log_with_fields
from lumina.projects.paths import catalog_path, projects_root

logger = get_logger("lumina.projects.catalog")

CATALOG_LOCK_TIMEOUT = 5.0
CATALOG_VERSION = 1


@dataclass
class CatalogEntry:
    id: str
    name: str
    path: str
    created_at: int
    last_opened_at: int
    primary_pdf_id: str
    primary_pdf_filename: str
    primary_pdf_size: int
    auto_created: bool = True


@dataclass
class Catalog:
    version: int
    projects: list[CatalogEntry] = field(default_factory=list)


def _lock_path() -> str:
    return str(catalog_path()) + ".lock"


def _entry_from_dict(data: dict) -> CatalogEntry:
    return CatalogEntry(
        id=data["id"],
        name=data["name"],
        path=data["path"],
        created_at=data["created_at"],
        last_opened_at=data["last_opened_at"],
        primary_pdf_id=data["primary_pdf_id"],
        primary_pdf_filename=data["primary_pdf_filename"],
        primary_pdf_size=data["primary_pdf_size"],
        auto_created=data.get("auto_created", True),
    )


def _catalog_from_dict(data: dict) -> Catalog:
    return Catalog(
        version=data.get("version", CATALOG_VERSION),
        projects=[_entry_from_dict(p) for p in data.get("projects", [])],
    )


def _catalog_to_dict(catalog: Catalog) -> dict:
    return {
        "version": catalog.version,
        "projects": [asdict(entry) for entry in catalog.projects],
    }


def save_catalog(catalog: Catalog) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(_lock_path(), timeout=CATALOG_LOCK_TIMEOUT):
        path.write_text(
            json.dumps(_catalog_to_dict(catalog), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def load_catalog() -> Catalog:
    path = catalog_path()
    if not path.exists():
        catalog = Catalog(version=CATALOG_VERSION, projects=[])
        save_catalog(catalog)
        return catalog
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _catalog_from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        log_with_fields(
            logger,
            logging.WARNING,
            "catalog.json corrupted; rebuilding from manifests",
        )
        catalog = rebuild_from_manifests()
        save_catalog(catalog)
        return catalog


def add_entry(entry: CatalogEntry) -> None:
    catalog = load_catalog()
    catalog.projects.append(entry)
    save_catalog(catalog)


def remove_entry(project_id: str) -> None:
    catalog = load_catalog()
    catalog.projects = [p for p in catalog.projects if p.id != project_id]
    save_catalog(catalog)


def update_entry(project_id: str, **changes) -> None:
    catalog = load_catalog()
    updated: list[CatalogEntry] = []
    for entry in catalog.projects:
        if entry.id == project_id:
            data = asdict(entry)
            data.update(changes)
            updated.append(CatalogEntry(**data))
        else:
            updated.append(entry)
    catalog.projects = updated
    save_catalog(catalog)


def find_by_name_and_size(name: str, file_size: int) -> CatalogEntry | None:
    catalog = load_catalog()
    for entry in catalog.projects:
        if entry.name == name and entry.primary_pdf_size == file_size:
            return entry
    return None


def find_by_pdf_id(pdf_id: str) -> CatalogEntry | None:
    catalog = load_catalog()
    for entry in catalog.projects:
        if entry.primary_pdf_id == pdf_id:
            return entry
    return None


def find_by_project_id(project_id: str) -> CatalogEntry | None:
    catalog = load_catalog()
    for entry in catalog.projects:
        if entry.id == project_id:
            return entry
    return None


def list_entries(sort: str = "last_opened_at_desc") -> list[CatalogEntry]:
    catalog = load_catalog()
    entries = list(catalog.projects)
    if sort == "last_opened_at_desc":
        entries.sort(key=lambda e: e.last_opened_at, reverse=True)
    elif sort == "created_at_desc":
        entries.sort(key=lambda e: e.created_at, reverse=True)
    elif sort == "name_asc":
        entries.sort(key=lambda e: e.name.lower())
    return entries


def rebuild_from_manifests() -> Catalog:
    entries: list[CatalogEntry] = []
    root = projects_root()
    if root.exists():
        for manifest_path in root.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                project = data["project"]
                project_id = project["id"]
                created_at = project["created_at"]
                entries.append(
                    CatalogEntry(
                        id=project_id,
                        name=project["name"],
                        path=f"projects/{project_id}/",
                        created_at=created_at,
                        last_opened_at=created_at,
                        primary_pdf_id=project["primary_pdf_id"],
                        primary_pdf_filename=project["primary_pdf_filename"],
                        primary_pdf_size=project["primary_pdf_size"],
                        auto_created=True,
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                continue
    return Catalog(version=CATALOG_VERSION, projects=entries)
