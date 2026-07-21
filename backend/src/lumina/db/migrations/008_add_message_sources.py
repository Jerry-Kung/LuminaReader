from __future__ import annotations

target_version = 8
description = (
    "V1.2.4: add messages.sources_json column "
    "(concept-recall structured sources; MAY tier, nullable)."
)


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)  # row[1] = 列名


def apply(conn) -> None:
    # 幂等加列（同 002 先例）：列已存在则跳过，避免存量库重复升级报错
    if _has_column(conn, "messages", "sources_json"):
        return
    conn.execute("ALTER TABLE messages ADD COLUMN sources_json TEXT")
