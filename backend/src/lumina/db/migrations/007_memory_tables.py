from __future__ import annotations

target_version = 7
description = (
    "V1.2.3: add memory_meta + memory_units + memory_concepts tables "
    "(chapter-batch LLM memory pipeline; MAY tier)."
)

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS memory_meta (
      pdf_id          TEXT PRIMARY KEY,
      status          TEXT NOT NULL,
      toc_source      TEXT,
      toc_updated_at  INTEGER,
      unit_total      INTEGER NOT NULL DEFAULT 0,
      unit_done       INTEGER NOT NULL DEFAULT 0,
      model           TEXT,
      book_summary    TEXT,
      created_at      INTEGER,
      updated_at      INTEGER,
      error           TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_units (
      id           TEXT PRIMARY KEY,
      pdf_id       TEXT NOT NULL,
      seq          INTEGER NOT NULL,
      title        TEXT NOT NULL,
      start_page   INTEGER NOT NULL,
      end_page     INTEGER NOT NULL,
      status       TEXT NOT NULL,
      summary      TEXT,
      error        TEXT,
      updated_at   INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_concepts (
      id           TEXT PRIMARY KEY,
      pdf_id       TEXT NOT NULL,
      unit_id      TEXT NOT NULL,
      term         TEXT NOT NULL,
      definition   TEXT NOT NULL,
      page         INTEGER NOT NULL,
      created_at   INTEGER NOT NULL
    )
    """,
]


def apply(conn) -> None:
    # 不用 executescript：它会隐式 COMMIT，破坏迁移框架的事务包裹
    for stmt in _CREATE_STATEMENTS:
        conn.execute(stmt)
