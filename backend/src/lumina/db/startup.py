"""Startup hooks for the persistence layer.

Currently only runs pending DB migrations for every Project listed in catalog.json.
Imported and invoked by `lumina.main.create_app`'s lifespan.
"""
from __future__ import annotations

import logging

from lumina.db.engine import get_connection
from lumina.db.migrations import (
    MigrationError,
    SCHEMA_VERSION,
    SchemaVersionTooNewError,
    apply_pending,
    read_schema_version,
)
from lumina.logging import get_logger, log_with_fields
from lumina.projects.catalog import list_entries
from lumina.projects.paths import project_sqlite_path

logger = get_logger("lumina.db.startup")


def apply_pending_for_all_projects() -> None:
    """Iterate every Project in catalog.json and run pending migrations.

    Behavior:
      - For each Project: open its sqlite (engine creates the file on demand if missing;
        but apply_pending() short-circuits when project_meta is empty, so newly created
        files are unaffected).
      - Reads schema_version, applies migrations registered with target_version > current.
      - MUST-tier failure: re-raises (lifespan aborts; main process exits before serving).
      - DB newer than backend code (SchemaVersionTooNewError): re-raises (same).
    """
    entries = list_entries()
    if not entries:
        log_with_fields(
            logger,
            logging.INFO,
            "no projects in catalog; skipping migration sweep",
            backend_schema_version=SCHEMA_VERSION,
        )
        return

    log_with_fields(
        logger,
        logging.INFO,
        "scanning projects for pending migrations",
        backend_schema_version=SCHEMA_VERSION,
        project_count=len(entries),
    )
    for entry in entries:
        sqlite_path = project_sqlite_path(entry.id)
        if not sqlite_path.exists():
            # Project directory or sqlite is missing; do not auto-create here — the file
            # is built on demand at upload time. Surface the gap for the operator.
            log_with_fields(
                logger,
                logging.WARNING,
                "project sqlite missing; skipping migration for this entry",
                project_id=entry.id,
                expected_path=str(sqlite_path),
            )
            continue
        conn = get_connection(entry.id)
        try:
            before = read_schema_version(conn)
            new_version = apply_pending(conn)
            if before is not None and new_version > before:
                log_with_fields(
                    logger,
                    logging.INFO,
                    "applied pending migrations",
                    project_id=entry.id,
                    from_version=before,
                    to_version=new_version,
                )
        except SchemaVersionTooNewError:
            log_with_fields(
                logger,
                logging.ERROR,
                "DB schema_version newer than backend; refusing to start",
                project_id=entry.id,
            )
            raise
        except MigrationError:
            log_with_fields(
                logger,
                logging.ERROR,
                "MUST-tier migration failed; refusing to start. "
                "To recover: roll back the backend, or delete the affected "
                "user_data/projects/<project_id>/lumina.sqlite (the original.pdf and "
                "catalog.json remain and the DB will be rebuilt on next upload).",
                project_id=entry.id,
            )
            raise
