from __future__ import annotations

target_version = 3
description = "V1.1.3: add pdfs.last_read_offset REAL NOT NULL DEFAULT 0."


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def apply(conn) -> None:
    if _has_column(conn, "pdfs", "last_read_offset"):
        return
    conn.execute(
        "ALTER TABLE pdfs ADD COLUMN last_read_offset REAL NOT NULL DEFAULT 0"
    )
