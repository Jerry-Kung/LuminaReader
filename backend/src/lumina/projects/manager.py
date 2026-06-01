from __future__ import annotations

import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from ulid import ULID

from lumina.db.engine import evict, get_connection
from lumina.db.migrations import SCHEMA_VERSION, initialize_schema
from lumina.db.models import PdfRow, ProjectMetaRow, insert_pdf, insert_project_meta
from lumina.projects.catalog import (
    CatalogEntry,
    add_entry,
    find_by_name_and_size,
    find_by_pdf_id,
    find_by_project_id,
    remove_entry,
    update_entry,
)
from lumina.projects.paths import (
    project_dir,
    project_manifest_path,
    project_pdf_path,
)


class ProjectNameConflictError(Exception):
    def __init__(self, existing: CatalogEntry):
        self.existing = existing
        super().__init__(f"Project name conflict: existing={existing.id}")


class PdfNotFoundError(Exception):
    pass


class ProjectNotFoundError(Exception):
    pass


@dataclass
class CreatedProject:
    project_id: str
    pdf_id: str
    name: str
    primary_pdf_filename: str
    primary_pdf_size: int
    created_at: int


def strip_ext(filename: str) -> str:
    stem = Path(filename).stem
    return stem if stem else filename


def next_available_suffix(base_name: str) -> str:
    from lumina.projects.catalog import list_entries

    used_suffixes: set[int] = {1}
    for entry in list_entries():
        if entry.name == base_name:
            used_suffixes.add(1)
        elif entry.name.startswith(f"{base_name} (") and entry.name.endswith(")"):
            inner = entry.name[len(base_name) + 2 : -1]
            if inner.isdigit():
                used_suffixes.add(int(inner))
    n = 2
    while n in used_suffixes:
        n += 1
    return f"{base_name} ({n})"


def _write_manifest(
    *,
    project_id: str,
    name: str,
    created_at: int,
    pdf_id: str,
    primary_pdf_filename: str,
    primary_pdf_size: int,
) -> None:
    manifest = {
        "schema_version": 1,
        "project": {
            "id": project_id,
            "name": name,
            "created_at": created_at,
            "primary_pdf_id": pdf_id,
            "primary_pdf_filename": primary_pdf_filename,
            "primary_pdf_size": primary_pdf_size,
        },
    }
    project_manifest_path(project_id).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _rollback_project(project_id: str) -> None:
    evict(project_id)
    dir_path = project_dir(project_id)
    if dir_path.exists():
        _rmtree(dir_path)
    try:
        remove_entry(project_id)
    except Exception:
        pass


def _rmtree(path: Path) -> None:
    def onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=onerror)


def auto_create_project(
    file_bytes: bytes,
    original_filename: str,
    force_create_new: bool = False,
) -> CreatedProject:
    name = strip_ext(original_filename)
    file_size = len(file_bytes)
    existing = find_by_name_and_size(name, file_size)
    if existing is not None and not force_create_new:
        raise ProjectNameConflictError(existing)
    if existing is not None and force_create_new:
        name = next_available_suffix(name)

    project_id = f"proj_{ULID()}"
    pdf_id = f"pdf_{ULID()}"
    created_at = int(time.time())
    storage_path = "original.pdf"

    dir_path = project_dir(project_id)
    catalog_written = False

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        project_pdf_path(project_id, storage_path).write_bytes(file_bytes)

        conn = get_connection(project_id)
        initialize_schema(conn)
        conn.execute("BEGIN")
        try:
            insert_project_meta(
                conn,
                ProjectMetaRow(
                    id=project_id,
                    name=name,
                    created_at=created_at,
                    schema_version=SCHEMA_VERSION,
                ),
            )
            insert_pdf(
                conn,
                PdfRow(
                    id=pdf_id,
                    project_id=project_id,
                    filename=original_filename,
                    storage_path=storage_path,
                    file_size=file_size,
                    added_at=created_at,
                    schema_version=SCHEMA_VERSION,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        _write_manifest(
            project_id=project_id,
            name=name,
            created_at=created_at,
            pdf_id=pdf_id,
            primary_pdf_filename=original_filename,
            primary_pdf_size=file_size,
        )

        add_entry(
            CatalogEntry(
                id=project_id,
                name=name,
                path=f"projects/{project_id}/",
                created_at=created_at,
                last_opened_at=created_at,
                primary_pdf_id=pdf_id,
                primary_pdf_filename=original_filename,
                primary_pdf_size=file_size,
                auto_created=True,
            )
        )
        catalog_written = True

        return CreatedProject(
            project_id=project_id,
            pdf_id=pdf_id,
            name=name,
            primary_pdf_filename=original_filename,
            primary_pdf_size=file_size,
            created_at=created_at,
        )
    except Exception:
        if catalog_written:
            remove_entry(project_id)
        _rollback_project(project_id)
        raise


def delete_project(project_id: str) -> None:
    entry = find_by_project_id(project_id)
    dir_exists = project_dir(project_id).exists()
    if entry is None and not dir_exists:
        raise ProjectNotFoundError(project_id)

    evict(project_id)
    if entry is not None:
        remove_entry(project_id)
    if dir_exists:
        _rmtree(project_dir(project_id))


def lookup_project_by_pdf_id(pdf_id: str) -> CatalogEntry:
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        raise PdfNotFoundError(pdf_id)
    return entry


def lookup_project_by_conversation_id(conversation_id: str) -> CatalogEntry:
    from lumina.projects.catalog import list_entries

    for entry in list_entries():
        conn = get_connection(entry.id)
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if row is not None:
            return entry
    raise ProjectNotFoundError(conversation_id)


def touch_last_opened_at(project_id: str) -> None:
    ts = int(time.time())
    update_entry(project_id, last_opened_at=ts)
