from __future__ import annotations

target_version = 6
description = (
    "V1.2.2: add pdf_toc_meta + chapters + bookmarks tables "
    "(TOC recognition + bookmark CRUD; MAY tier)."
)

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS pdf_toc_meta (
      pdf_id         TEXT PRIMARY KEY,
      status         TEXT NOT NULL,
      source         TEXT,
      chapter_count  INTEGER,
      updated_at     INTEGER,
      error          TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapters (
      id           TEXT PRIMARY KEY,
      pdf_id       TEXT NOT NULL,
      parent_id    TEXT,
      order_index  INTEGER NOT NULL,
      depth        INTEGER NOT NULL,
      title        TEXT NOT NULL,
      start_page   INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
      id            TEXT PRIMARY KEY,
      pdf_id        TEXT NOT NULL,
      name          TEXT NOT NULL,
      page          INTEGER NOT NULL,
      offset_ratio  REAL NOT NULL DEFAULT 0,
      created_at    INTEGER NOT NULL
    )
    """,
]


def apply(conn) -> None:
    # 不用 executescript：它会隐式 COMMIT，破坏迁移框架的事务包裹
    for stmt in _CREATE_STATEMENTS:
        conn.execute(stmt)
