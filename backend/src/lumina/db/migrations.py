SCHEMA_VERSION = 1

INIT_SQL = """
CREATE TABLE IF NOT EXISTS project_meta (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  created_at      INTEGER NOT NULL,
  schema_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pdfs (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL,
  filename        TEXT NOT NULL,
  storage_path    TEXT NOT NULL,
  file_size       INTEGER NOT NULL,
  added_at        INTEGER NOT NULL,
  schema_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS selections (
  id              TEXT PRIMARY KEY,
  pdf_id          TEXT NOT NULL,
  page            INTEGER NOT NULL,
  x               REAL NOT NULL,
  y               REAL NOT NULL,
  w               REAL NOT NULL,
  h               REAL NOT NULL,
  dpi             REAL NOT NULL,
  thumbnail_png   BLOB,
  created_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id              TEXT PRIMARY KEY,
  pdf_id          TEXT NOT NULL,
  selection_id    TEXT NOT NULL,
  task_type       TEXT NOT NULL,
  extracted_text  TEXT NOT NULL,
  created_at      INTEGER NOT NULL,
  last_used_at    INTEGER NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS messages (
  id                TEXT PRIMARY KEY,
  conversation_id   TEXT NOT NULL,
  turn_index        INTEGER NOT NULL,
  role              TEXT NOT NULL,
  content           TEXT NOT NULL,
  user_question     TEXT,
  model             TEXT,
  prompt_tokens     INTEGER,
  completion_tokens INTEGER,
  latency_ms        INTEGER,
  created_at        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_selections_pdf    ON selections(pdf_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_pdf ON conversations(pdf_id, last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv     ON messages(conversation_id, turn_index);
"""


class SchemaVersionTooNewError(RuntimeError):
    pass


def initialize_schema(conn) -> None:
    conn.executescript(INIT_SQL)


def read_schema_version(conn) -> int | None:
    try:
        row = conn.execute("SELECT schema_version FROM project_meta LIMIT 1").fetchone()
    except Exception:
        return None
    return row[0] if row else None


def migrate(conn, from_version: int, to_version: int) -> None:
    if from_version == to_version:
        return
    if from_version < to_version:
        raise NotImplementedError(
            f"No migration registered from {from_version} to {to_version}"
        )
    raise SchemaVersionTooNewError(
        f"DB schema_version={from_version} > backend SCHEMA_VERSION={to_version}; "
        "please upgrade the backend."
    )
