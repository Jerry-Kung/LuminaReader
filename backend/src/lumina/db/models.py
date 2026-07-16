from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class ProjectMetaRow:
    id: str
    name: str
    created_at: int
    schema_version: int = 1


@dataclass
class PdfRow:
    id: str
    project_id: str
    filename: str
    storage_path: str
    file_size: int
    added_at: int
    schema_version: int = 1


@dataclass
class SelectionRow:
    id: str
    pdf_id: str
    page: int
    x: float | None
    y: float | None
    w: float | None
    h: float | None
    dpi: float | None
    thumbnail_png: bytes | None
    created_at: int
    type: str = "image"
    text: str | None = None
    page_end: int | None = None
    segments_json: str | None = None


@dataclass
class ConversationRow:
    id: str
    pdf_id: str
    selection_id: str
    task_type: str
    extracted_text: str
    created_at: int
    last_used_at: int
    status: str = "active"


@dataclass
class MessageRow:
    id: str
    conversation_id: str
    turn_index: int
    role: str
    content: str
    user_question: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    created_at: int


def insert_project_meta(conn, row: ProjectMetaRow) -> None:
    conn.execute(
        """
        INSERT INTO project_meta (id, name, created_at, schema_version)
        VALUES (?, ?, ?, ?)
        """,
        (row.id, row.name, row.created_at, row.schema_version),
    )


def insert_pdf(conn, row: PdfRow) -> None:
    conn.execute(
        """
        INSERT INTO pdfs (
            id, project_id, filename, storage_path, file_size, added_at, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.project_id,
            row.filename,
            row.storage_path,
            row.file_size,
            row.added_at,
            row.schema_version,
        ),
    )


def insert_selection(conn, row: SelectionRow) -> None:
    conn.execute(
        """
        INSERT INTO selections (
            id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at,
            type, text, page_end, segments_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.pdf_id,
            row.page,
            row.x,
            row.y,
            row.w,
            row.h,
            row.dpi,
            row.thumbnail_png,
            row.created_at,
            row.type,
            row.text,
            row.page_end,
            row.segments_json,
        ),
    )


def insert_conversation(conn, row: ConversationRow) -> None:
    conn.execute(
        """
        INSERT INTO conversations (
            id, pdf_id, selection_id, task_type, extracted_text,
            created_at, last_used_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.pdf_id,
            row.selection_id,
            row.task_type,
            row.extracted_text,
            row.created_at,
            row.last_used_at,
            row.status,
        ),
    )


def insert_message(conn, row: MessageRow) -> None:
    conn.execute(
        """
        INSERT INTO messages (
            id, conversation_id, turn_index, role, content, user_question,
            model, prompt_tokens, completion_tokens, latency_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.conversation_id,
            row.turn_index,
            row.role,
            row.content,
            row.user_question,
            row.model,
            row.prompt_tokens,
            row.completion_tokens,
            row.latency_ms,
            row.created_at,
        ),
    )


def get_conversation(conn, conversation_id: str) -> ConversationRow | None:
    row = conn.execute(
        """
        SELECT id, pdf_id, selection_id, task_type, extracted_text,
               created_at, last_used_at, status
        FROM conversations WHERE id = ?
        """,
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return ConversationRow(*row)


def list_messages(conn, conversation_id: str) -> list[MessageRow]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, turn_index, role, content, user_question,
               model, prompt_tokens, completion_tokens, latency_ms, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY turn_index ASC, CASE role WHEN 'user' THEN 0 ELSE 1 END ASC
        """,
        (conversation_id,),
    ).fetchall()
    return [MessageRow(*row) for row in rows]


def mark_conversation_cleared(conn, conversation_id: str) -> None:
    conn.execute(
        "UPDATE conversations SET status = 'cleared' WHERE id = ?",
        (conversation_id,),
    )


def delete_messages_of_conversation(conn, conversation_id: str) -> None:
    conn.execute(
        "DELETE FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    )


def update_assistant_message_at_turn(
    conn,
    conversation_id: str,
    turn_index: int,
    *,
    content: str,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None,
) -> None:
    conn.execute(
        """
        UPDATE messages
        SET content = ?, model = ?, prompt_tokens = ?, completion_tokens = ?, latency_ms = ?
        WHERE conversation_id = ? AND turn_index = ? AND role = 'assistant'
        """,
        (
            content,
            model,
            prompt_tokens,
            completion_tokens,
            latency_ms,
            conversation_id,
            turn_index,
        ),
    )


def update_conversation_last_used(conn, conversation_id: str, ts: int) -> None:
    conn.execute(
        "UPDATE conversations SET last_used_at = ? WHERE id = ?",
        (ts, conversation_id),
    )


def update_conversation_extracted_text(
    conn,
    conversation_id: str,
    extracted_text: str,
) -> None:
    conn.execute(
        "UPDATE conversations SET extracted_text = ? WHERE id = ?",
        (extracted_text, conversation_id),
    )


def list_conversations_by_pdf(
    conn, pdf_id: str, *, include_cleared: bool = False
) -> list[ConversationRow]:
    if include_cleared:
        rows = conn.execute(
            """
            SELECT id, pdf_id, selection_id, task_type, extracted_text,
                   created_at, last_used_at, status
            FROM conversations
            WHERE pdf_id = ?
            ORDER BY last_used_at DESC
            """,
            (pdf_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, pdf_id, selection_id, task_type, extracted_text,
                   created_at, last_used_at, status
            FROM conversations
            WHERE pdf_id = ? AND status = 'active'
            ORDER BY last_used_at DESC
            """,
            (pdf_id,),
        ).fetchall()
    return [ConversationRow(*row) for row in rows]


def get_selection(conn, selection_id: str) -> SelectionRow | None:
    row = conn.execute(
        """
        SELECT id, pdf_id, page, x, y, w, h, dpi, thumbnail_png, created_at,
               type, text, page_end, segments_json
        FROM selections WHERE id = ?
        """,
        (selection_id,),
    ).fetchone()
    if row is None:
        return None
    return SelectionRow(
        id=row[0],
        pdf_id=row[1],
        page=row[2],
        x=row[3],
        y=row[4],
        w=row[5],
        h=row[6],
        dpi=row[7],
        thumbnail_png=row[8],
        created_at=row[9],
        type=row[10],
        text=row[11],
        page_end=row[12],
        segments_json=row[13],
    )


def get_selection_type(conn, selection_id: str) -> str | None:
    """Lightweight query for follow-up routing fallback path."""
    row = conn.execute(
        "SELECT type FROM selections WHERE id = ?",
        (selection_id,),
    ).fetchone()
    return row[0] if row else None


def get_first_assistant_message(conn, conversation_id: str) -> MessageRow | None:
    row = conn.execute(
        """
        SELECT id, conversation_id, turn_index, role, content, user_question,
               model, prompt_tokens, completion_tokens, latency_ms, created_at
        FROM messages
        WHERE conversation_id = ? AND role = 'assistant'
        ORDER BY turn_index ASC
        LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return MessageRow(*row)


def count_messages(conn, conversation_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    return row[0] if row else 0


def list_pdfs(conn, project_id: str) -> list[PdfRow]:
    rows = conn.execute(
        """
        SELECT id, project_id, filename, storage_path, file_size, added_at, schema_version
        FROM pdfs WHERE project_id = ?
        ORDER BY added_at DESC
        """,
        (project_id,),
    ).fetchall()
    return [PdfRow(*row) for row in rows]


def list_conversations_brief(conn) -> list[ConversationRow]:
    rows = conn.execute(
        """
        SELECT id, pdf_id, selection_id, task_type, extracted_text,
               created_at, last_used_at, status
        FROM conversations
        ORDER BY last_used_at DESC
        """
    ).fetchall()
    return [ConversationRow(*row) for row in rows]


def get_pdf_reading_position(conn, pdf_id: str) -> tuple[int, float] | None:
    row = conn.execute(
        "SELECT last_read_page, last_read_offset FROM pdfs WHERE id = ?",
        (pdf_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), float(row[1])


def update_pdf_reading_position(
    conn,
    pdf_id: str,
    last_read_page: int,
    last_read_offset: float,
) -> int:
    cursor = conn.execute(
        "UPDATE pdfs SET last_read_page = ?, last_read_offset = ? WHERE id = ?",
        (last_read_page, last_read_offset, pdf_id),
    )
    return cursor.rowcount


def get_pdf_last_read_page(conn, pdf_id: str) -> int | None:
    position = get_pdf_reading_position(conn, pdf_id)
    return position[0] if position is not None else None


def update_pdf_last_read_page(conn, pdf_id: str, last_read_page: int) -> int:
    return update_pdf_reading_position(conn, pdf_id, last_read_page, 0.0)


# ---------------------------------------------------------------------------
# V1.2.1: 全书文本地基（pdf_text_meta / pdf_text_pages，MAY 演化档）
# ---------------------------------------------------------------------------


@dataclass
class PdfTextMetaRow:
    pdf_id: str
    status: str  # "pending" | "ok" | "unsupported" | "failed"
    page_count: int | None = None
    textual_page_count: int | None = None
    char_count: int | None = None
    extractor: str | None = None
    extracted_at: int | None = None
    error: str | None = None


def get_pdf_text_meta(conn, pdf_id: str) -> PdfTextMetaRow | None:
    try:
        row = conn.execute(
            """
            SELECT pdf_id, status, page_count, textual_page_count, char_count,
                   extractor, extracted_at, error
            FROM pdf_text_meta WHERE pdf_id = ?
            """,
            (pdf_id,),
        ).fetchone()
    except sqlite3.Error:
        # MAY 档兜底：表缺失 / 损坏一律呈现为"未提取"
        return None
    if row is None:
        return None
    return PdfTextMetaRow(*row)


def upsert_pdf_text_meta(conn, row: PdfTextMetaRow) -> None:
    conn.execute(
        """
        INSERT INTO pdf_text_meta (
            pdf_id, status, page_count, textual_page_count, char_count,
            extractor, extracted_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pdf_id) DO UPDATE SET
            status = excluded.status,
            page_count = excluded.page_count,
            textual_page_count = excluded.textual_page_count,
            char_count = excluded.char_count,
            extractor = excluded.extractor,
            extracted_at = excluded.extracted_at,
            error = excluded.error
        """,
        (
            row.pdf_id,
            row.status,
            row.page_count,
            row.textual_page_count,
            row.char_count,
            row.extractor,
            row.extracted_at,
            row.error,
        ),
    )


def replace_pdf_text_pages(conn, pdf_id: str, page_texts: list[str]) -> None:
    """整体替换某 PDF 的按页文本（调用方负责事务包裹）。page_texts[0] = 第 1 页。"""
    conn.execute("DELETE FROM pdf_text_pages WHERE pdf_id = ?", (pdf_id,))
    conn.executemany(
        """
        INSERT INTO pdf_text_pages (pdf_id, page, text, char_count)
        VALUES (?, ?, ?, ?)
        """,
        [
            (pdf_id, page_no, text, len(text))
            for page_no, text in enumerate(page_texts, start=1)
        ],
    )


def get_pdf_text_pages_range(
    conn, pdf_id: str, page_start: int, page_end: int
) -> list[tuple[int, str]]:
    """返回 [page_start, page_end] 闭区间内的 (page, text)，按页码升序。"""
    try:
        rows = conn.execute(
            """
            SELECT page, text FROM pdf_text_pages
            WHERE pdf_id = ? AND page BETWEEN ? AND ?
            ORDER BY page ASC
            """,
            (pdf_id, page_start, page_end),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [(int(row[0]), row[1]) for row in rows]


# ---------------------------------------------------------------------------
# V1.2.2: 目录与书签（pdf_toc_meta / chapters / bookmarks，MAY 演化档）
# ---------------------------------------------------------------------------


@dataclass
class PdfTocMetaRow:
    pdf_id: str
    status: str  # "none" | "ready" | "failed"
    source: str | None = None  # "outline" | "heuristic" | "llm"
    chapter_count: int | None = None
    updated_at: int | None = None
    error: str | None = None


@dataclass
class ChapterRow:
    id: str
    pdf_id: str
    parent_id: str | None
    order_index: int
    depth: int
    title: str
    start_page: int


@dataclass
class BookmarkRow:
    id: str
    pdf_id: str
    name: str
    page: int
    offset_ratio: float
    created_at: int


def get_pdf_toc_meta(conn, pdf_id: str) -> PdfTocMetaRow | None:
    try:
        row = conn.execute(
            """
            SELECT pdf_id, status, source, chapter_count, updated_at, error
            FROM pdf_toc_meta WHERE pdf_id = ?
            """,
            (pdf_id,),
        ).fetchone()
    except sqlite3.Error:
        # MAY 档兜底：表缺失 / 损坏一律呈现为"未识别"
        return None
    if row is None:
        return None
    return PdfTocMetaRow(*row)


def upsert_pdf_toc_meta(conn, row: PdfTocMetaRow) -> None:
    conn.execute(
        """
        INSERT INTO pdf_toc_meta (
            pdf_id, status, source, chapter_count, updated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(pdf_id) DO UPDATE SET
            status = excluded.status,
            source = excluded.source,
            chapter_count = excluded.chapter_count,
            updated_at = excluded.updated_at,
            error = excluded.error
        """,
        (row.pdf_id, row.status, row.source, row.chapter_count, row.updated_at, row.error),
    )


def list_chapters(conn, pdf_id: str) -> list[ChapterRow]:
    try:
        rows = conn.execute(
            """
            SELECT id, pdf_id, parent_id, order_index, depth, title, start_page
            FROM chapters WHERE pdf_id = ?
            ORDER BY order_index ASC
            """,
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [ChapterRow(*row) for row in rows]


def replace_chapters(conn, pdf_id: str, rows: list[ChapterRow]) -> None:
    """整体替换某 PDF 的章节结构（调用方负责事务包裹，"先成功后替换"）。"""
    conn.execute("DELETE FROM chapters WHERE pdf_id = ?", (pdf_id,))
    conn.executemany(
        """
        INSERT INTO chapters (id, pdf_id, parent_id, order_index, depth, title, start_page)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (r.id, r.pdf_id, r.parent_id, r.order_index, r.depth, r.title, r.start_page)
            for r in rows
        ],
    )


def list_bookmarks(conn, pdf_id: str) -> list[BookmarkRow]:
    try:
        rows = conn.execute(
            """
            SELECT id, pdf_id, name, page, offset_ratio, created_at
            FROM bookmarks WHERE pdf_id = ?
            ORDER BY page ASC, offset_ratio ASC
            """,
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [BookmarkRow(*row) for row in rows]


def insert_bookmark(conn, row: BookmarkRow) -> None:
    conn.execute(
        """
        INSERT INTO bookmarks (id, pdf_id, name, page, offset_ratio, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (row.id, row.pdf_id, row.name, row.page, row.offset_ratio, row.created_at),
    )


def rename_bookmark(conn, pdf_id: str, bookmark_id: str, name: str) -> int:
    cursor = conn.execute(
        "UPDATE bookmarks SET name = ? WHERE id = ? AND pdf_id = ?",
        (name, bookmark_id, pdf_id),
    )
    return cursor.rowcount


def delete_bookmark(conn, pdf_id: str, bookmark_id: str) -> int:
    cursor = conn.execute(
        "DELETE FROM bookmarks WHERE id = ? AND pdf_id = ?",
        (bookmark_id, pdf_id),
    )
    return cursor.rowcount
