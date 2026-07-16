"""V1.2.2 数据访问层：pdf_toc_meta / chapters / bookmarks（MAY 档）。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    BookmarkRow,
    ChapterRow,
    PdfTocMetaRow,
    delete_bookmark,
    get_pdf_toc_meta,
    insert_bookmark,
    list_bookmarks,
    list_chapters,
    rename_bookmark,
    replace_chapters,
    upsert_pdf_toc_meta,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(c)
    yield c
    c.close()


def _chapter(cid: str, order: int, page: int, parent: str | None = None, depth: int = 0):
    return ChapterRow(
        id=cid, pdf_id="pdf_1", parent_id=parent,
        order_index=order, depth=depth, title=f"Ch {order}", start_page=page,
    )


def test_toc_meta_roundtrip_and_upsert(conn):
    assert get_pdf_toc_meta(conn, "pdf_1") is None
    upsert_pdf_toc_meta(conn, PdfTocMetaRow(pdf_id="pdf_1", status="none"))
    row = get_pdf_toc_meta(conn, "pdf_1")
    assert row.status == "none" and row.source is None
    upsert_pdf_toc_meta(
        conn,
        PdfTocMetaRow(pdf_id="pdf_1", status="ready", source="outline",
                      chapter_count=3, updated_at=123),
    )
    row = get_pdf_toc_meta(conn, "pdf_1")
    assert (row.status, row.source, row.chapter_count) == ("ready", "outline", 3)


def test_replace_chapters_swaps_atomically(conn):
    replace_chapters(conn, "pdf_1", [_chapter("chap_a", 0, 1), _chapter("chap_b", 1, 5)])
    assert [c.id for c in list_chapters(conn, "pdf_1")] == ["chap_a", "chap_b"]
    replace_chapters(conn, "pdf_1", [_chapter("chap_c", 0, 2)])
    got = list_chapters(conn, "pdf_1")
    assert [c.id for c in got] == ["chap_c"]
    assert got[0].parent_id is None and got[0].start_page == 2


def test_chapters_parent_and_order(conn):
    rows = [
        _chapter("chap_p", 0, 1),
        _chapter("chap_c1", 1, 2, parent="chap_p", depth=1),
        _chapter("chap_q", 2, 9),
    ]
    replace_chapters(conn, "pdf_1", rows)
    got = list_chapters(conn, "pdf_1")
    assert [c.order_index for c in got] == [0, 1, 2]
    assert got[1].parent_id == "chap_p" and got[1].depth == 1


def test_bookmark_crud(conn):
    insert_bookmark(conn, BookmarkRow(
        id="bm_1", pdf_id="pdf_1", name="第 9 页", page=9, offset_ratio=0.5, created_at=1,
    ))
    insert_bookmark(conn, BookmarkRow(
        id="bm_2", pdf_id="pdf_1", name="开头", page=2, offset_ratio=0.0, created_at=2,
    ))
    got = list_bookmarks(conn, "pdf_1")
    assert [b.id for b in got] == ["bm_2", "bm_1"]  # 按 page 排序
    assert rename_bookmark(conn, "pdf_1", "bm_1", "核心论证") == 1
    assert list_bookmarks(conn, "pdf_1")[1].name == "核心论证"
    assert rename_bookmark(conn, "pdf_1", "bm_missing", "x") == 0
    assert delete_bookmark(conn, "pdf_1", "bm_1") == 1
    assert delete_bookmark(conn, "pdf_1", "bm_1") == 0  # 重复删除幂等
    assert len(list_bookmarks(conn, "pdf_1")) == 1


def test_may_tier_fallback_on_missing_tables():
    # MAY 档兜底：表缺失时读函数返回空，不抛异常
    bare = sqlite3.connect(":memory:", isolation_level=None)
    assert get_pdf_toc_meta(bare, "pdf_1") is None
    assert list_chapters(bare, "pdf_1") == []
    assert list_bookmarks(bare, "pdf_1") == []
    bare.close()
