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
    sources_json: str | None = None  # V1.2.4：concept-recall 结构化出处（JSON 数组序列化），MAY 档可空


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
            model, prompt_tokens, completion_tokens, latency_ms, created_at,
            sources_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            row.sources_json,
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
               model, prompt_tokens, completion_tokens, latency_ms, created_at,
               sources_json
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
    sources_json: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE messages
        SET content = ?, model = ?, prompt_tokens = ?, completion_tokens = ?,
            latency_ms = ?, sources_json = ?
        WHERE conversation_id = ? AND turn_index = ? AND role = 'assistant'
        """,
        (
            content,
            model,
            prompt_tokens,
            completion_tokens,
            latency_ms,
            sources_json,
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
               model, prompt_tokens, completion_tokens, latency_ms, created_at,
               sources_json
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


# ---------------------------------------------------------------------------
# V1.2.3: 记忆加工（memory_meta / memory_units / memory_concepts，MAY 演化档）
# ---------------------------------------------------------------------------


@dataclass
class MemoryMetaRow:
    pdf_id: str
    status: str  # "running" | "partial" | "ready" | "failed"
    toc_source: str | None = None  # "outline" | "heuristic" | "llm" | "pages"
    toc_updated_at: int | None = None
    unit_total: int = 0
    unit_done: int = 0
    model: str | None = None
    book_summary: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    error: str | None = None


@dataclass
class MemoryUnitRow:
    id: str
    pdf_id: str
    seq: int
    title: str
    start_page: int
    end_page: int
    status: str  # "pending" | "ok" | "failed"
    summary: str | None = None
    error: str | None = None
    updated_at: int | None = None


@dataclass
class MemoryConceptRow:
    id: str
    pdf_id: str
    unit_id: str
    term: str
    definition: str
    page: int
    created_at: int


def get_memory_meta(conn, pdf_id: str) -> MemoryMetaRow | None:
    try:
        row = conn.execute(
            """
            SELECT pdf_id, status, toc_source, toc_updated_at, unit_total, unit_done,
                   model, book_summary, created_at, updated_at, error
            FROM memory_meta WHERE pdf_id = ?
            """,
            (pdf_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return MemoryMetaRow(*row)


def upsert_memory_meta(conn, row: MemoryMetaRow) -> None:
    conn.execute(
        """
        INSERT INTO memory_meta (
            pdf_id, status, toc_source, toc_updated_at, unit_total, unit_done,
            model, book_summary, created_at, updated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pdf_id) DO UPDATE SET
            status = excluded.status,
            toc_source = excluded.toc_source,
            toc_updated_at = excluded.toc_updated_at,
            unit_total = excluded.unit_total,
            unit_done = excluded.unit_done,
            model = excluded.model,
            book_summary = excluded.book_summary,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            error = excluded.error
        """,
        (
            row.pdf_id, row.status, row.toc_source, row.toc_updated_at,
            row.unit_total, row.unit_done, row.model, row.book_summary,
            row.created_at, row.updated_at, row.error,
        ),
    )


def list_memory_units(conn, pdf_id: str) -> list[MemoryUnitRow]:
    try:
        rows = conn.execute(
            """
            SELECT id, pdf_id, seq, title, start_page, end_page, status,
                   summary, error, updated_at
            FROM memory_units WHERE pdf_id = ? ORDER BY seq ASC
            """,
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [MemoryUnitRow(*row) for row in rows]


def replace_memory_units(conn, pdf_id: str, rows: list[MemoryUnitRow]) -> None:
    """整体替换某 PDF 的加工单元快照（调用方负责事务包裹）。"""
    conn.execute("DELETE FROM memory_units WHERE pdf_id = ?", (pdf_id,))
    conn.executemany(
        """
        INSERT INTO memory_units (
            id, pdf_id, seq, title, start_page, end_page, status, summary, error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (r.id, r.pdf_id, r.seq, r.title, r.start_page, r.end_page,
             r.status, r.summary, r.error, r.updated_at)
            for r in rows
        ],
    )


def set_memory_unit_result(
    conn, unit_id: str, *, status: str, summary: str | None,
    error: str | None, updated_at: int,
) -> None:
    conn.execute(
        "UPDATE memory_units SET status = ?, summary = ?, error = ?, updated_at = ? WHERE id = ?",
        (status, summary, error, updated_at, unit_id),
    )


def replace_unit_concepts(conn, unit_id: str, rows: list[MemoryConceptRow]) -> None:
    """按单元整体替换概念（单元重试时旧概念不残留；调用方负责事务包裹）。"""
    conn.execute("DELETE FROM memory_concepts WHERE unit_id = ?", (unit_id,))
    conn.executemany(
        """
        INSERT INTO memory_concepts (id, pdf_id, unit_id, term, definition, page, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(r.id, r.pdf_id, r.unit_id, r.term, r.definition, r.page, r.created_at) for r in rows],
    )


def count_ok_memory_units(conn, pdf_id: str) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM memory_units WHERE pdf_id = ? AND status = 'ok'",
            (pdf_id,),
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0])


def delete_memory_all(conn, pdf_id: str) -> None:
    """整体重建前清空该 PDF 的全部记忆产物（调用方负责事务包裹）。"""
    conn.execute("DELETE FROM memory_concepts WHERE pdf_id = ?", (pdf_id,))
    conn.execute("DELETE FROM memory_units WHERE pdf_id = ?", (pdf_id,))
    conn.execute("DELETE FROM memory_meta WHERE pdf_id = ?", (pdf_id,))


def list_running_memory_pdf_ids(conn) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT pdf_id FROM memory_meta WHERE status = 'running'"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [row[0] for row in rows]


def get_pdf_text_char_counts(conn, pdf_id: str) -> dict[int, int]:
    """切分器与花费预估的数据基础：页码 → 该页字符数。"""
    try:
        rows = conn.execute(
            "SELECT page, char_count FROM pdf_text_pages WHERE pdf_id = ?",
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {int(row[0]): int(row[1]) for row in rows}


@dataclass
class ConceptHitRow:
    """V1.2.4 概念回查检索行：概念条目 + 其所属单元的标题/序号（LEFT JOIN units）。"""
    term: str
    definition: str
    page: int
    unit_id: str
    unit_title: str | None
    unit_seq: int


def list_concept_hits(conn, pdf_id: str) -> list[ConceptHitRow]:
    """回查检索基础数据：本书全部概念 + 所属单元标题/seq。

    归一化匹配、排序、上限截断均在 Python 侧（recall.py）处理——DB 侧只做全量拉取，
    条目量级为本书章节概念数（可控），不在 SQL 里做 LIKE 以保持检索逻辑可单测。
    MAY 档兜底：表缺失 / 未加工时返回 []。
    """
    try:
        rows = conn.execute(
            """
            SELECT c.term, c.definition, c.page, c.unit_id, u.title, u.seq
            FROM memory_concepts c
            LEFT JOIN memory_units u ON c.unit_id = u.id
            WHERE c.pdf_id = ?
            """,
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [
        ConceptHitRow(
            term=row[0],
            definition=row[1],
            page=int(row[2]),
            unit_id=row[3],
            unit_title=row[4],
            unit_seq=int(row[5]) if row[5] is not None else 0,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# V1.2.5: 轻量侧边栏笔记（notes，MAY 演化档）
# ---------------------------------------------------------------------------


@dataclass
class NoteRow:
    id: str
    pdf_id: str
    content: str
    page: int
    offset_ratio: float | None
    anchor_text: str | None
    anchor_rects_json: str | None
    source: str
    created_at: int
    updated_at: int
    title: str | None = None  # V1.2.7 加列（末尾，避免 NoteRow(*row) 位置错位）


def list_notes(conn, pdf_id: str) -> list[NoteRow]:
    try:
        rows = conn.execute(
            """
            SELECT id, pdf_id, content, page, offset_ratio, anchor_text,
                   anchor_rects_json, source, created_at, updated_at, title
            FROM notes WHERE pdf_id = ?
            ORDER BY page ASC, offset_ratio ASC, created_at ASC
            """,
            (pdf_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [NoteRow(*row) for row in rows]


def insert_note(conn, row: NoteRow) -> None:
    conn.execute(
        """
        INSERT INTO notes (id, pdf_id, content, page, offset_ratio, anchor_text,
                           anchor_rects_json, source, created_at, updated_at, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id, row.pdf_id, row.content, row.page, row.offset_ratio,
            row.anchor_text, row.anchor_rects_json, row.source,
            row.created_at, row.updated_at, row.title,
        ),
    )


def update_note(
    conn, pdf_id: str, note_id: str, *, content: str | None, title: str | None, updated_at: int
) -> int:
    # 仅更新传入的非 None 字段；updated_at 恒刷新。至少一项由调用方（Pydantic）保证
    sets = ["updated_at = ?"]
    params: list = [updated_at]
    if content is not None:
        sets.append("content = ?")
        params.append(content)
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    params.extend([note_id, pdf_id])
    cursor = conn.execute(
        f"UPDATE notes SET {', '.join(sets)} WHERE id = ? AND pdf_id = ?",
        params,
    )
    return cursor.rowcount



def delete_note(conn, pdf_id: str, note_id: str) -> int:
    cursor = conn.execute(
        "DELETE FROM notes WHERE id = ? AND pdf_id = ?",
        (note_id, pdf_id),
    )
    return cursor.rowcount
