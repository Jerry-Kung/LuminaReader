"""V1.2.5 notes 表模型层：CRUD + 排序 + MAY 档兜底。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import NoteRow, delete_note, insert_note, list_notes, update_note


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _row(note_id: str, page: int, offset: float | None, created: int, title: str | None = None, pdf_id: str = "pdf_1", content: str | None = None) -> NoteRow:
    return NoteRow(
        id=note_id,
        pdf_id=pdf_id,
        content=content if content is not None else f"note {note_id}",
        page=page,
        offset_ratio=offset,
        anchor_text=None,
        anchor_rects_json=None,
        source="manual",
        created_at=created,
        updated_at=created,
        title=title,
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
    assert update_note(conn, "pdf_1", "n1", content="新内容", title=None, updated_at=999) == 1
    row = list_notes(conn, "pdf_1")[0]
    assert row.content == "新内容" and row.updated_at == 999
    # pdf_id 不匹配 / note 不存在 → rowcount 0
    assert update_note(conn, "pdf_x", "n1", content="x", title=None, updated_at=1) == 0
    assert update_note(conn, "pdf_1", "missing", content="x", title=None, updated_at=1) == 0


def test_delete(conn):
    insert_note(conn, _row("n1", 1, None, 1))
    assert delete_note(conn, "pdf_1", "n1") == 1
    assert delete_note(conn, "pdf_1", "n1") == 0  # 重复删除幂等
    assert list_notes(conn, "pdf_1") == []


def test_list_may_tier_fallback(conn):
    # MAY 档兜底：表缺失时返回空列表而非抛异常
    conn.execute("DROP TABLE notes")
    assert list_notes(conn, "pdf_1") == []


def test_insert_and_list_roundtrips_title(conn):
    insert_note(conn, _row(note_id="nt_1", page=1, offset=None, created=100, pdf_id="pdf_x", title="我的标题"))
    got = list_notes(conn, "pdf_x")
    assert got[0].title == "我的标题"


def test_update_note_title_only(conn):
    insert_note(conn, _row(note_id="nt_1", page=1, offset=None, created=100, pdf_id="pdf_x", content="原文", title=None))
    n = update_note(conn, "pdf_x", "nt_1", content=None, title="新标题", updated_at=123)
    assert n == 1
    got = list_notes(conn, "pdf_x")
    assert got[0].title == "新标题"
    assert got[0].content == "原文"  # 未传 content 不改
    assert got[0].updated_at == 123


def test_update_note_content_only(conn):
    insert_note(conn, _row(note_id="nt_1", page=1, offset=None, created=100, pdf_id="pdf_x", content="原文", title="标题"))
    update_note(conn, "pdf_x", "nt_1", content="改后", title=None, updated_at=200)
    got = list_notes(conn, "pdf_x")
    assert got[0].content == "改后"
    assert got[0].title == "标题"  # 未传 title 不改
