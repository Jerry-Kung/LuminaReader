from __future__ import annotations

target_version = 4
description = "V1.1.4: rebuild selections table with type discriminator + text path columns."


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def apply(conn) -> None:
    if _has_column(conn, "selections", "type"):
        return
    conn.execute(
        """
        CREATE TABLE selections_v2 (
          id              TEXT PRIMARY KEY,
          pdf_id          TEXT NOT NULL,
          page            INTEGER NOT NULL,
          x               REAL,
          y               REAL,
          w               REAL,
          h               REAL,
          dpi             REAL,
          thumbnail_png   BLOB,
          created_at      INTEGER NOT NULL,
          type            TEXT NOT NULL DEFAULT 'image',
          text            TEXT,
          page_end        INTEGER,
          segments_json   TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO selections_v2 (
          id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at,
          type, text, page_end, segments_json
        )
        SELECT
          id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at,
          'image', NULL, NULL, NULL
        FROM selections
        """
    )
    conn.execute("DROP INDEX IF EXISTS idx_selections_pdf")
    conn.execute("DROP TABLE selections")
    conn.execute("ALTER TABLE selections_v2 RENAME TO selections")
    conn.execute(
        "CREATE INDEX idx_selections_pdf ON selections(pdf_id, created_at DESC)"
    )
