from __future__ import annotations

target_version = 9
description = "V1.2.5: add notes table (lightweight sidebar notes; MAY tier)."

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS notes (
      id                 TEXT PRIMARY KEY,
      pdf_id             TEXT NOT NULL,
      content            TEXT NOT NULL,
      page               INTEGER NOT NULL,
      offset_ratio       REAL,
      anchor_text        TEXT,
      anchor_rects_json  TEXT,
      source             TEXT NOT NULL DEFAULT 'manual',
      created_at         INTEGER NOT NULL,
      updated_at         INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_pdf ON notes(pdf_id, page)",
]


def apply(conn) -> None:
    # 不用 executescript：它会隐式 COMMIT，破坏迁移框架的事务包裹
    for stmt in _CREATE_STATEMENTS:
        conn.execute(stmt)
