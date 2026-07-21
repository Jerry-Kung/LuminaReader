"""V1.2.4 概念索引检索读查询（JOIN units 取单元标题/seq；MAY 档兜底）。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    ConceptHitRow,
    MemoryConceptRow,
    MemoryUnitRow,
    list_concept_hits,
    replace_memory_units,
    replace_unit_concepts,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(c)
    c.execute(
        "INSERT INTO project_meta (id, name, created_at, schema_version) VALUES ('proj_x', 'x', 0, 8)"
    )
    replace_memory_units(c, "pdf_1", [
        MemoryUnitRow(id="mu_a", pdf_id="pdf_1", seq=0, title="第1章 基础", start_page=1, end_page=5, status="ok"),
        MemoryUnitRow(id="mu_b", pdf_id="pdf_1", seq=1, title="第2章 进阶", start_page=6, end_page=9, status="ok"),
    ])
    replace_unit_concepts(c, "mu_a", [
        MemoryConceptRow(id="mc_1", pdf_id="pdf_1", unit_id="mu_a", term="张量", definition="多维数组", page=3, created_at=1),
    ])
    replace_unit_concepts(c, "mu_b", [
        MemoryConceptRow(id="mc_2", pdf_id="pdf_1", unit_id="mu_b", term="梯度下降", definition="优化算法", page=7, created_at=2),
    ])
    yield c
    c.close()


def test_list_concept_hits_joins_unit_title(conn):
    hits = list_concept_hits(conn, "pdf_1")
    by_term = {h.term: h for h in hits}
    assert by_term["张量"].definition == "多维数组"
    assert by_term["张量"].page == 3
    assert by_term["张量"].unit_title == "第1章 基础"
    assert by_term["张量"].unit_seq == 0
    assert by_term["梯度下降"].unit_seq == 1


def test_list_concept_hits_empty_for_unknown_pdf(conn):
    assert list_concept_hits(conn, "pdf_none") == []


def test_list_concept_hits_fallback_on_missing_table():
    c = sqlite3.connect(":memory:", isolation_level=None)  # 未建表
    assert list_concept_hits(c, "pdf_1") == []
    c.close()
