from __future__ import annotations

import importlib.util
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from lumina.db.migrations._base import Migration

_MIGRATIONS_DIR = Path(__file__).resolve().parent
_FILE_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.py$")


class SchemaVersionTooNewError(RuntimeError):
    pass


class MigrationError(RuntimeError):
    """MUST 档迁移失败时抛出；主进程 lifespan 阶段应据此中止启动。"""


@dataclass(frozen=True)
class _LoadedMigration:
    target_version: int
    description: str
    filename: str
    apply_fn: object


def _load_migration(path: Path) -> _LoadedMigration:
    module_name = f"lumina.db.migrations._loaded_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"Cannot load migration spec: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target_version = getattr(module, "target_version", None)
    description = getattr(module, "description", "")
    apply_fn = getattr(module, "apply", None)
    if not isinstance(target_version, int):
        raise MigrationError(f"{path.name} missing int target_version")
    if not callable(apply_fn):
        raise MigrationError(f"{path.name} missing callable apply()")
    return _LoadedMigration(
        target_version=target_version,
        description=description,
        filename=path.name,
        apply_fn=apply_fn,
    )


def _discover() -> list[_LoadedMigration]:
    entries: list[_LoadedMigration] = []
    seen_versions: set[int] = set()
    for path in sorted(_MIGRATIONS_DIR.iterdir()):
        if not path.is_file():
            continue
        if not _FILE_PATTERN.match(path.name):
            continue
        migration = _load_migration(path)
        if migration.target_version in seen_versions:
            raise MigrationError(
                f"Duplicate target_version={migration.target_version} in {migration.filename}"
            )
        seen_versions.add(migration.target_version)
        entries.append(migration)
    entries.sort(key=lambda m: m.target_version)
    return entries


_REGISTRY: list[_LoadedMigration] = _discover()
SCHEMA_VERSION: int = max((m.target_version for m in _REGISTRY), default=0)
INIT_SQL: str = ""  # populated below


def _load_init_sql() -> str:
    initial = _MIGRATIONS_DIR / "001_initial.py"
    spec = importlib.util.spec_from_file_location("lumina.db.migrations._init_sql", initial)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "INIT_SQL", "")


INIT_SQL = _load_init_sql()


def initialize_schema(conn) -> None:
    """Build a fresh schema at the current SCHEMA_VERSION (idempotent).

    Process:
      1. Run 001_initial.INIT_SQL (CREATE TABLE IF NOT EXISTS — idempotent).
      2. Apply every migration with target_version > 1 in registry order. Each
         migration script is itself idempotent (002 uses PRAGMA detection), so
         calling this on an already-current schema is a no-op.

    Used by `auto_create_project` when materializing a brand-new Project.
    Callers are responsible for inserting the project_meta row with
    `schema_version = SCHEMA_VERSION` afterwards.
    """
    conn.executescript(INIT_SQL)
    for migration in _REGISTRY:
        if migration.target_version == 1:
            continue
        migration.apply_fn(conn)


def read_schema_version(conn) -> int | None:
    """Return the project_meta.schema_version of the first row, or None when empty."""
    try:
        row = conn.execute("SELECT schema_version FROM project_meta LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _write_schema_version(conn, version: int) -> None:
    conn.execute("UPDATE project_meta SET schema_version = ?", (version,))


def migrate(conn, from_version: int, to_version: int) -> None:
    """Legacy signature kept for backwards compatibility with V1.0.3 callers/tests.

    Raises:
        NotImplementedError: when `to_version` is not a registered target_version,
            or when no migration covers the (from_version, to_version] range.
        SchemaVersionTooNewError: when from_version > to_version.
    """
    if from_version == to_version:
        return
    if from_version > to_version:
        raise SchemaVersionTooNewError(
            f"DB schema_version={from_version} > backend SCHEMA_VERSION={to_version}; "
            "please upgrade the backend."
        )
    registered_targets = {m.target_version for m in _REGISTRY}
    if to_version not in registered_targets:
        raise NotImplementedError(
            f"No migration registered with target_version={to_version}"
        )
    pending = [m for m in _REGISTRY if from_version < m.target_version <= to_version]
    if not pending:
        raise NotImplementedError(
            f"No migration registered from {from_version} to {to_version}"
        )
    for m in pending:
        _run_one(conn, m)


def apply_pending(conn) -> int:
    """Apply all registered migrations whose target_version > current DB schema_version.

    Behavior:
      - If project_meta is empty (fresh DB), do nothing — `initialize_schema()` is the
        caller's responsibility on Project creation; this function is for *existing* DBs.
      - If DB schema_version > code SCHEMA_VERSION, raise SchemaVersionTooNewError.
      - Otherwise run each pending migration in ascending target_version order, writing
        project_meta.schema_version after each one inside the same transaction.
      - Any migration failure raises MigrationError (MUST-tier semantics; lifespan aborts).

    Returns:
      The new schema_version after migrations (== SCHEMA_VERSION) or 0 when the DB is fresh.
    """
    current = read_schema_version(conn)
    if current is None:
        return 0
    if current > SCHEMA_VERSION:
        raise SchemaVersionTooNewError(
            f"DB schema_version={current} > backend SCHEMA_VERSION={SCHEMA_VERSION}; "
            "please upgrade the backend."
        )
    pending = [m for m in _REGISTRY if m.target_version > current]
    for m in pending:
        _run_one(conn, m)
    return SCHEMA_VERSION if pending else current


def _run_one(conn, m: _LoadedMigration) -> None:
    try:
        conn.execute("BEGIN")
        m.apply_fn(conn)
        _write_schema_version(conn, m.target_version)
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise MigrationError(
            f"Migration {m.filename} (target_version={m.target_version}) failed: {exc}"
        ) from exc


def registered_migrations() -> list[Migration]:
    """Read-only view of the registry for tests / introspection."""
    return list(_REGISTRY)  # type: ignore[return-value]


__all__ = [
    "INIT_SQL",
    "MigrationError",
    "SCHEMA_VERSION",
    "SchemaVersionTooNewError",
    "apply_pending",
    "initialize_schema",
    "migrate",
    "read_schema_version",
    "registered_migrations",
]
