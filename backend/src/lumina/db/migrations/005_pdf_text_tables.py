from __future__ import annotations

target_version = 5
description = (
    "V1.2.1: add pdf_text_meta + pdf_text_pages tables "
    "(full-book text extraction foundation; MAY tier)."
)

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS pdf_text_meta (
      pdf_id              TEXT PRIMARY KEY,
      status              TEXT NOT NULL,
      page_count          INTEGER,
      textual_page_count  INTEGER,
      char_count          INTEGER,
      extractor           TEXT,
      extracted_at        INTEGER,
      error               TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pdf_text_pages (
      pdf_id      TEXT NOT NULL,
      page        INTEGER NOT NULL,
      text        TEXT NOT NULL,
      char_count  INTEGER NOT NULL,
      PRIMARY KEY (pdf_id, page)
    )
    """,
]


def apply(conn) -> None:
    # 不用 executescript：它会隐式 COMMIT，破坏迁移框架的事务包裹
    for stmt in _CREATE_STATEMENTS:
        conn.execute(stmt)
