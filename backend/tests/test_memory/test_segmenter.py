"""V1.2.6 切分器：全目录条目区间（任意深度）+ 小节合并 + 贪心拆分 + 无目录降级。

覆盖规格 v1.2.6 F1~F4（取代 V1.2.3 D5 顶层粒度契约）。
"""

from lumina.db.models import ChapterRow
from lumina.memory.segmenter import UnitSpec, build_units


def _chap(order, depth, title, page):
    return ChapterRow(
        id=f"chap_{order}", pdf_id="pdf_1", parent_id=None,
        order_index=order, depth=depth, title=title, start_page=page,
    )


def _counts(page_count, chars_per_page=100):
    return {p: chars_per_page for p in range(1, page_count + 1)}


# ---------- F1：全目录条目区间（任意深度） ----------


def test_leaf_sections_become_units():
    # 二级目录：单元 = 小节区间，标题用原始小节标题（ISSUE-014 核心行为）
    chapters = [
        _chap(0, 0, "1. Functions", 3),
        _chap(1, 1, "1.1 Graphs", 3),
        _chap(2, 1, "1.2 Combining", 6),
        _chap(3, 0, "2. Limits", 9),
    ]
    units = build_units(chapters, 12, _counts(12), max_chars=10_000)
    # 首条区间向前扩展到第 1 页：扉页 / 前言并入父条目"1. Functions"的引言区间 [1,2]
    assert units == [
        UnitSpec(title="1. Functions", start_page=1, end_page=2),
        UnitSpec(title="1.1 Graphs", start_page=3, end_page=5),
        UnitSpec(title="1.2 Combining", start_page=6, end_page=8),
        UnitSpec(title="2. Limits", start_page=9, end_page=12),
    ]


def test_parent_intro_becomes_own_unit():
    # 父条目起始页早于首个子条目：引言段独立成单元，沿用父标题
    chapters = [
        _chap(0, 0, "1. Functions", 1),
        _chap(1, 1, "1.1 Graphs", 4),
        _chap(2, 1, "1.2 Combining", 7),
    ]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    assert units == [
        UnitSpec(title="1. Functions", start_page=1, end_page=3),
        UnitSpec(title="1.1 Graphs", start_page=4, end_page=6),
        UnitSpec(title="1.2 Combining", start_page=7, end_page=10),
    ]


def test_three_level_toc_leaves_recognized():
    # 三级目录：最深叶子（1.1.1 / 1.1.2）按对应结构切分
    chapters = [
        _chap(0, 0, "1. Functions", 1),
        _chap(1, 1, "1.1 Graphs", 1),
        _chap(2, 2, "1.1.1 Domain", 1),
        _chap(3, 2, "1.1.2 Range", 4),
        _chap(4, 1, "1.2 Combining", 7),
    ]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    assert units == [
        UnitSpec(title="1.1.1 Domain", start_page=1, end_page=3),
        UnitSpec(title="1.1.2 Range", start_page=4, end_page=6),
        UnitSpec(title="1.2 Combining", start_page=7, end_page=10),
    ]


def test_top_only_toc_backward_compatible():
    # 仅顶层目录：行为与 V1.2.3 等价（顶层区间 + 首章扩展 + 末章至书末）
    chapters = [_chap(0, 0, "C1", 3), _chap(1, 0, "C2", 6)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    assert units == [
        UnitSpec(title="C1", start_page=1, end_page=5),
        UnitSpec(title="C2", start_page=6, end_page=10),
    ]


def test_units_cover_book_contiguously():
    chapters = [
        _chap(0, 0, "1", 2),
        _chap(1, 1, "1.1", 3),
        _chap(2, 1, "1.2", 5),
        _chap(3, 0, "2", 8),
        _chap(4, 1, "2.1", 8),
    ]
    units = build_units(chapters, 12, _counts(12), max_chars=10_000)
    assert units[0].start_page == 1 and units[-1].end_page == 12
    for prev, cur in zip(units, units[1:]):
        assert cur.start_page == prev.end_page + 1


# ---------- F2：小节合并 ----------


def test_small_adjacent_sections_merge_within_top():
    # 章末习题类小节（各 1 页 × 100 字符 < min）连续合并，标题 " / " 连接
    chapters = [
        _chap(0, 0, "1. Functions", 1),
        _chap(1, 1, "1.1 Graphs", 1),
        _chap(2, 1, "Questions", 8),
        _chap(3, 1, "Practice", 9),
        _chap(4, 1, "Additional", 10),
        _chap(5, 0, "2. Limits", 11),
    ]
    units = build_units(chapters, 14, _counts(14), max_chars=10_000, min_chars=300)
    assert units == [
        UnitSpec(title="1.1 Graphs", start_page=1, end_page=7),
        UnitSpec(title="Questions / Practice / Additional", start_page=8, end_page=10),
        UnitSpec(title="2. Limits", start_page=11, end_page=14),
    ]


def test_merge_never_crosses_top_chapter():
    # 相邻小区间分属不同顶层章节：不合并（Copyright / Preface 各自独立）
    chapters = [_chap(0, 0, "Copyright", 1), _chap(1, 0, "Preface", 2), _chap(2, 0, "1. Functions", 3)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000, min_chars=500)
    assert [u.title for u in units] == ["Copyright", "Preface", "1. Functions"]


def test_merge_capped_by_max_chars():
    # 合并累计将超 max_chars 即封口开新单元
    chapters = [_chap(0, 0, "C1", 1)] + [
        _chap(i, 1, f"S{i}", i) for i in range(1, 7)
    ]
    # 每小节 1 页 × 100 字符，min=300 全为小区间；max=250 → 每 2 节封口
    units = build_units(chapters, 6, _counts(6), max_chars=250, min_chars=300)
    assert [u.title for u in units] == ["S1 / S2", "S3 / S4", "S5 / S6"]


def test_isolated_small_section_stays_alone():
    # 孤立小区间（前后均为大区间）：不与大区间合并，独立成单元
    chapters = [
        _chap(0, 0, "C1", 1),
        _chap(1, 1, "S1", 1),
        _chap(2, 1, "Tiny", 6),
        _chap(3, 1, "S2", 7),
    ]
    units = build_units(chapters, 12, _counts(12), max_chars=10_000, min_chars=300)
    assert [u.title for u in units] == ["S1", "Tiny", "S2"]
    assert units[1] == UnitSpec(title="Tiny", start_page=6, end_page=6)


def test_min_chars_zero_disables_merge():
    chapters = [_chap(0, 0, "C1", 1), _chap(1, 1, "S1", 1), _chap(2, 1, "S2", 2)]
    units = build_units(chapters, 4, _counts(4), max_chars=10_000, min_chars=0)
    assert [u.title for u in units] == ["S1", "S2"]


# ---------- F3：超预算拆分兜底 ----------


def test_oversized_section_split_by_page():
    chapters = [_chap(0, 0, "Big", 1)]
    # 10 页 × 100 字符，预算 350 → 每 3 页一段（第 4 页会超）
    units = build_units(chapters, 10, _counts(10), max_chars=350)
    assert [u.title for u in units] == ["Big（1/4）", "Big（2/4）", "Big（3/4）", "Big（4/4）"]
    assert units[0] == UnitSpec(title="Big（1/4）", start_page=1, end_page=3)
    assert units[-1].end_page == 10
    for prev, cur in zip(units, units[1:]):
        assert cur.start_page == prev.end_page + 1


def test_oversized_leaf_section_split_with_suffix():
    # 超预算的是二级小节：拆分后缀挂在小节标题上
    chapters = [_chap(0, 0, "C1", 1), _chap(1, 1, "S1", 1), _chap(2, 1, "S2", 7)]
    units = build_units(chapters, 8, _counts(8), max_chars=350, min_chars=0)
    assert [u.title for u in units] == ["S1（1/2）", "S1（2/2）", "S2"]


# ---------- F4：无目录降级（不变） ----------


def test_no_toc_fallback_page_ranges():
    units = build_units([], 10, _counts(10), max_chars=350)
    assert [u.title for u in units] == ["第 1–3 页", "第 4–6 页", "第 7–9 页", "第 10–10 页"]


def test_no_toc_small_book_single_unit():
    units = build_units([], 5, _counts(5), max_chars=10_000)
    assert units == [UnitSpec(title="第 1–5 页", start_page=1, end_page=5)]


def test_single_page_over_budget_still_one_page_unit():
    # 单页字符已超预算：不可再拆，该页独立成段（贪心保证每段至少一页）
    units = build_units([], 3, {1: 500, 2: 500, 3: 500}, max_chars=100)
    assert [(u.start_page, u.end_page) for u in units] == [(1, 1), (2, 2), (3, 3)]


def test_empty_book():
    assert build_units([], 0, {}, max_chars=100) == []


def test_exact_budget_fit_stays_in_segment():
    # 累计恰好 == max_chars 不提前开新段（拆分条件是严格 >）
    units = build_units([], 4, {1: 100, 2: 100, 3: 100, 4: 100}, max_chars=200)
    assert [(u.start_page, u.end_page) for u in units] == [(1, 2), (3, 4)]


# ---------- 边界 clamp（沿用） ----------


def test_same_page_chapters_skip_empty_range():
    chapters = [_chap(0, 0, "A", 1), _chap(1, 0, "B", 1), _chap(2, 0, "C", 5)]
    units = build_units(chapters, 8, _counts(8), max_chars=10_000)
    # A 的区间 [1, 0] 为空被跳过（同页多章节起点，known limitation 承接 V1.2.2 R-V122-6）
    assert [u.title for u in units] == ["B", "C"]


def test_start_page_clamped():
    chapters = [_chap(0, 0, "C1", 1), _chap(1, 0, "C2", 99)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    # 越界起始页 clamp 到书末；C2 区间 [10,10]，C1 [1,9]
    assert units[0].end_page == 9 and units[1] == UnitSpec(title="C2", start_page=10, end_page=10)


def test_start_page_lower_bound_clamp():
    # start_page 为 0 或负数时，应 clamp 到 1
    chapters = [_chap(0, 0, "C1", 0), _chap(1, 0, "C2", 5)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    assert units[0] == UnitSpec(title="C1", start_page=1, end_page=4)
    assert units[1] == UnitSpec(title="C2", start_page=5, end_page=10)


def test_stray_deep_entries_before_first_top_are_independent():
    # 首个 depth=0 之前的游离深层条目：各自独立成组，不与后续章节合并
    chapters = [_chap(0, 1, "Stray A", 1), _chap(1, 1, "Stray B", 2), _chap(2, 0, "C1", 3)]
    units = build_units(chapters, 6, _counts(6), max_chars=10_000, min_chars=500)
    assert [u.title for u in units] == ["Stray A", "Stray B", "C1"]
