"""V1.2.5 notes 表模型层：CRUD + 排序 + MAY 档兜底。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import NoteRow, delete_note, insert_note, list_notes, update_note_content


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _row(note_id: str, page: int, offset: float | None, created: int) -> NoteRow:
    return NoteRow(
        id=note_id,
        pdf_id="pdf_1",
        content=f"note {note_id}",
        page=page,
        offset_ratio=offset,
        anchor_text=None,
        anchor_rects_json=None,
        source="manual",
        created_at=created,
        updated_at=created,
    )


def test_insert_and_list_sorted(conn):
    # 排序：page ASC → offset_ratio ASC（NULL 最前）→ created_at ASC
    insert_note(conn, _row("n3", 5, 0.8, 100))
    insert_note(conn, _row("n1", 2, None, 300))
    insert_note(conn, _row("n2", 5, None, 200))
    insert_note(conn, _row("n4", 5, 0.1, 400))
    got = [n.id for n in list_notes(conn, "pdf_1")]
    assert got == ["n1", "n2", "n4", "n3"]


def test_list_filters_by_pdf(conn):
    insert_note(conn, _row("n1", 1, None, 1))
    other = _row("n9", 1, None, 1)
    other.pdf_id = "pdf_other"
    insert_note(conn, other)
    assert [n.id for n in list_notes(conn, "pdf_1")] == ["n1"]


def test_update_content(conn):
    insert_note(conn, _row("n1", 1, None, 1))
    assert update_note_content(conn, "pdf_1", "n1", "新内容", 999) == 1
    row = list_notes(conn, "pdf_1")[0]
    assert row.content == "新内容" and row.updated_at == 999
    # pdf_id 不匹配 / note 不存在 → rowcount 0
    assert update_note_content(conn, "pdf_x", "n1", "x", 1) == 0
    assert update_note_content(conn, "pdf_1", "missing", "x", 1) == 0


def test_delete(conn):
    insert_note(conn, _row("n1", 1, None, 1))
    assert delete_note(conn, "pdf_1", "n1") == 1
    assert delete_note(conn, "pdf_1", "n1") == 0  # 重复删除幂等
    assert list_notes(conn, "pdf_1") == []


def test_list_may_tier_fallback(conn):
    # MAY 档兜底：表缺失时返回空列表而非抛异常
    conn.execute("DROP TABLE notes")
    assert list_notes(conn, "pdf_1") == []
