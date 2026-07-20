"""V1.2.3 memory_* 三表数据访问函数（MAY 档兜底：sqlite3.Error → 空）。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    MemoryConceptRow,
    MemoryMetaRow,
    MemoryUnitRow,
    count_ok_memory_units,
    delete_memory_all,
    get_memory_meta,
    get_pdf_text_char_counts,
    list_memory_units,
    list_running_memory_pdf_ids,
    replace_memory_units,
    replace_unit_concepts,
    set_memory_unit_result,
    upsert_memory_meta,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(c)
    c.execute(
        "INSERT INTO project_meta (id, name, created_at, schema_version) VALUES ('proj_x', 'x', 0, 7)"
    )
    yield c
    c.close()


def _meta(**kw) -> MemoryMetaRow:
    base = dict(
        pdf_id="pdf_1", status="running", toc_source="outline", toc_updated_at=100,
        unit_total=2, unit_done=0, model="m", book_summary=None,
        created_at=1, updated_at=1, error=None,
    )
    base.update(kw)
    return MemoryMetaRow(**base)


def test_meta_upsert_roundtrip(conn):
    upsert_memory_meta(conn, _meta())
    upsert_memory_meta(conn, _meta(status="partial", unit_done=1, error="e"))
    row = get_memory_meta(conn, "pdf_1")
    assert row is not None and row.status == "partial" and row.unit_done == 1
    assert get_memory_meta(conn, "pdf_other") is None


def test_units_replace_and_result(conn):
    rows = [
        MemoryUnitRow(id="mu_a", pdf_id="pdf_1", seq=0, title="C1", start_page=1, end_page=5, status="pending"),
        MemoryUnitRow(id="mu_b", pdf_id="pdf_1", seq=1, title="C2", start_page=6, end_page=9, status="pending"),
    ]
    replace_memory_units(conn, "pdf_1", rows)
    assert [u.id for u in list_memory_units(conn, "pdf_1")] == ["mu_a", "mu_b"]
    set_memory_unit_result(conn, "mu_a", status="ok", summary="s", error=None, updated_at=2)
    set_memory_unit_result(conn, "mu_b", status="failed", summary=None, error="boom", updated_at=2)
    units = list_memory_units(conn, "pdf_1")
    assert units[0].status == "ok" and units[0].summary == "s"
    assert units[1].status == "failed" and units[1].error == "boom"
    assert count_ok_memory_units(conn, "pdf_1") == 1


def test_concepts_replace_by_unit(conn):
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_1", pdf_id="pdf_1", unit_id="mu_a", term="t", definition="d", page=3, created_at=1),
    ])
    # 重试同一单元：旧概念被整体替换
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_2", pdf_id="pdf_1", unit_id="mu_a", term="t2", definition="d2", page=4, created_at=2),
    ])
    got = conn.execute("SELECT id FROM memory_concepts WHERE unit_id='mu_a'").fetchall()
    assert [r[0] for r in got] == ["mc_2"]


def test_delete_memory_all(conn):
    upsert_memory_meta(conn, _meta())
    replace_memory_units(conn, "pdf_1", [
        MemoryUnitRow(id="mu_a", pdf_id="pdf_1", seq=0, title="C1", start_page=1, end_page=5, status="pending"),
    ])
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_1", pdf_id="pdf_1", unit_id="mu_a", term="t", definition="d", page=3, created_at=1),
    ])
    delete_memory_all(conn, "pdf_1")
    assert get_memory_meta(conn, "pdf_1") is None
    assert list_memory_units(conn, "pdf_1") == []
    assert conn.execute("SELECT COUNT(*) FROM memory_concepts").fetchone()[0] == 0


def test_list_running(conn):
    upsert_memory_meta(conn, _meta(pdf_id="pdf_1", status="running"))
    upsert_memory_meta(conn, _meta(pdf_id="pdf_2", status="ready"))
    assert list_running_memory_pdf_ids(conn) == ["pdf_1"]


def test_char_counts(conn):
    conn.executemany(
        "INSERT INTO pdf_text_pages (pdf_id, page, text, char_count) VALUES (?, ?, ?, ?)",
        [("pdf_1", 1, "ab", 2), ("pdf_1", 2, "abcd", 4)],
    )
    assert get_pdf_text_char_counts(conn, "pdf_1") == {1: 2, 2: 4}


def test_broken_table_fallbacks():
    c = sqlite3.connect(":memory:", isolation_level=None)  # 未建表
    assert get_memory_meta(c, "pdf_1") is None
    assert list_memory_units(c, "pdf_1") == []
    assert list_running_memory_pdf_ids(c) == []
    assert get_pdf_text_char_counts(c, "pdf_1") == {}
    c.close()
