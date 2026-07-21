"""V1.2.4 概念回查检索纯逻辑单测（索引匹配 → 全文降级 → 双落空）。"""

import sqlite3

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    MemoryConceptRow,
    MemoryUnitRow,
    replace_memory_units,
    replace_unit_concepts,
)
from lumina.memory.recall import RecallResult, SourceRef, build_recall, normalize

RECALL_KW = dict(
    max_concepts=20, max_text_pages=5, snippet_chars=600, max_ref_chars=12000
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(c)
    c.execute(
        "INSERT INTO project_meta (id, name, created_at, schema_version) VALUES ('p', 'x', 0, 8)"
    )
    replace_memory_units(c, "pdf_1", [
        MemoryUnitRow(id="mu_a", pdf_id="pdf_1", seq=0, title="第1章", start_page=1, end_page=5, status="ok"),
        MemoryUnitRow(id="mu_b", pdf_id="pdf_1", seq=1, title="第2章", start_page=6, end_page=9, status="ok"),
    ])
    replace_unit_concepts(c, "mu_a", [
        MemoryConceptRow(id="mc_1", pdf_id="pdf_1", unit_id="mu_a", term="Gradient Descent", definition="优化算法", page=3, created_at=1),
    ])
    replace_unit_concepts(c, "mu_b", [
        MemoryConceptRow(id="mc_2", pdf_id="pdf_1", unit_id="mu_b", term="梯度下降", definition="优化算法中文", page=7, created_at=2),
    ])
    yield c
    c.close()


def _seed_text(conn, pdf_id, pages):
    conn.executemany(
        "INSERT INTO pdf_text_pages (pdf_id, page, text, char_count) VALUES (?, ?, ?, ?)",
        [(pdf_id, p, t, len(t)) for p, t in pages],
    )


def test_normalize():
    assert normalize("  Gradient DESCENT  ") == "gradient descent"


def test_exact_concept_hit(conn):
    res = build_recall(conn, "pdf_1", "梯度下降", **RECALL_KW)
    assert res.is_empty is False
    assert res.ref_block is not None and "优化算法中文" in res.ref_block
    assert any(s.kind == "concept" and s.term == "梯度下降" and s.page == 7 for s in res.sources)
    assert all(s.kind == "concept" for s in res.sources)


def test_case_insensitive_hit(conn):
    res = build_recall(conn, "pdf_1", "gradient descent", **RECALL_KW)
    assert any(s.term == "Gradient Descent" and s.page == 3 for s in res.sources)


def test_substring_hit_selection_contains_term(conn):
    # 选区含术语："梯度下降算法" 含术语 "梯度下降"
    res = build_recall(conn, "pdf_1", "梯度下降算法", **RECALL_KW)
    assert any(s.term == "梯度下降" for s in res.sources)


def test_concept_sources_carry_unit_title(conn):
    res = build_recall(conn, "pdf_1", "梯度下降", **RECALL_KW)
    hit = next(s for s in res.sources if s.term == "梯度下降")
    assert hit.unit_title == "第2章"


def test_text_fallback_when_no_concept(conn):
    _seed_text(conn, "pdf_1", [(2, "前文 反向传播 出现在这里。"), (8, "反向传播 再次出现。")])
    res = build_recall(conn, "pdf_1", "反向传播", **RECALL_KW)
    assert res.is_empty is False
    assert all(s.kind == "text" for s in res.sources)
    pages = sorted(s.page for s in res.sources)
    assert pages == [2, 8]
    assert res.sources[0].snippet and "反向传播" in res.sources[0].snippet
    assert "全文检索" in res.ref_block  # prompt 注明来自全文而非概念索引


def test_double_empty(conn):
    _seed_text(conn, "pdf_1", [(1, "无关内容")])
    res = build_recall(conn, "pdf_1", "不存在的术语XYZ", **RECALL_KW)
    assert res.is_empty is True
    assert res.ref_block is None
    assert res.sources == []


def test_concept_cap_truncates_low_priority(conn):
    # 精确匹配优先保留：造 30 个子串命中，max_concepts=2 时截断
    # id 前缀加 cap_ 前缀避免与 fixture 里的 mc_1/mc_2（全局主键）冲突
    rows = [
        MemoryConceptRow(id=f"mc_cap_{i}", pdf_id="pdf_1", unit_id="mu_a",
                         term=f"数据{i}", definition="d", page=i + 1, created_at=i)
        for i in range(30)
    ]
    replace_unit_concepts(conn, "mu_a", rows)
    res = build_recall(conn, "pdf_1", "数据", max_concepts=2, max_text_pages=5,
                       snippet_chars=600, max_ref_chars=12000)
    assert len([s for s in res.sources if s.kind == "concept"]) == 2


def test_orphaned_concept_matches_without_unit_prefix(conn):
    # unit_id 指向不存在的 memory_units 行（孤儿概念，LEFT JOIN 未命中）：
    # 仍应正常匹配，SourceRef.unit_title 为 None，参考块渲染不带 "unit · " 前缀。
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_orphan", pdf_id="pdf_1", unit_id="mu_missing",
                         term="孤儿概念", definition="无所属单元", page=42, created_at=1),
    ])
    res = build_recall(conn, "pdf_1", "孤儿概念", **RECALL_KW)
    assert res.is_empty is False
    hit = next(s for s in res.sources if s.term == "孤儿概念")
    assert hit.kind == "concept"
    assert hit.unit_title is None
    assert res.ref_block is not None
    assert "[p.42] 孤儿概念：无所属单元" in res.ref_block
    assert "· p.42" not in res.ref_block


def test_duplicate_term_different_definitions_per_unit(conn):
    # 回归测试：两个单元分别定义同一术语但定义不同。
    # 原问题：dict 压缩导致只保留最后一个定义，其他单元的条目显示错误定义。
    # 修复后：每个命中条目应携带其自身的定义，不论是否重名。
    replace_unit_concepts(conn, "mu_a", [
        MemoryConceptRow(id="mc_dup_a", pdf_id="pdf_1", unit_id="mu_a",
                         term="熵", definition="热力学定义", page=2, created_at=1),
    ])
    replace_unit_concepts(conn, "mu_b", [
        MemoryConceptRow(id="mc_dup_b", pdf_id="pdf_1", unit_id="mu_b",
                         term="熵", definition="信息论定义", page=8, created_at=2),
    ])
    res = build_recall(conn, "pdf_1", "熵", **RECALL_KW)
    assert res.is_empty is False
    assert res.ref_block is not None
    # 两个定义都应出现
    assert "热力学定义" in res.ref_block
    assert "信息论定义" in res.ref_block
    # 第1章 p.2 应携带热力学定义
    assert "[第1章 · p.2] 熵：热力学定义" in res.ref_block
    # 第2章 p.8 应携带信息论定义
    assert "[第2章 · p.8] 熵：信息论定义" in res.ref_block
    # 验证来源结构
    assert len(res.sources) == 2
    assert all(s.kind == "concept" and s.term == "熵" for s in res.sources)
