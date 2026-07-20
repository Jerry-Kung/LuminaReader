"""V1.2.3 切分器：顶层章节为单元 + 字符预算贪心拆分 + 无目录降级（规格 F1 / D5）。"""

from lumina.db.models import ChapterRow
from lumina.memory.segmenter import UnitSpec, build_units


def _chap(order, depth, title, page):
    return ChapterRow(
        id=f"chap_{order}", pdf_id="pdf_1", parent_id=None,
        order_index=order, depth=depth, title=title, start_page=page,
    )


def _counts(page_count, chars_per_page=100):
    return {p: chars_per_page for p in range(1, page_count + 1)}


def test_top_chapters_become_units():
    chapters = [_chap(0, 0, "C1", 3), _chap(1, 1, "C1.1", 4), _chap(2, 0, "C2", 6)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    # 首章向前扩展到第 1 页；子章节不单独成单元；末章到书末
    assert units == [
        UnitSpec(title="C1", start_page=1, end_page=5),
        UnitSpec(title="C2", start_page=6, end_page=10),
    ]


def test_oversized_chapter_split_by_page():
    chapters = [_chap(0, 0, "Big", 1)]
    # 10 页 × 100 字符，预算 350 → 每 3 页一段（第 4 页会超）
    units = build_units(chapters, 10, _counts(10), max_chars=350)
    assert [u.title for u in units] == ["Big（1/4）", "Big（2/4）", "Big（3/4）", "Big（4/4）"]
    assert units[0] == UnitSpec(title="Big（1/4）", start_page=1, end_page=3)
    assert units[-1].end_page == 10
    # 页范围连续覆盖全书
    for prev, cur in zip(units, units[1:]):
        assert cur.start_page == prev.end_page + 1


def test_no_toc_fallback_page_ranges():
    units = build_units([], 10, _counts(10), max_chars=350)
    assert [u.title for u in units] == ["第 1–3 页", "第 4–6 页", "第 7–9 页", "第 10–10 页"]


def test_no_toc_small_book_single_unit():
    units = build_units([], 5, _counts(5), max_chars=10_000)
    assert units == [UnitSpec(title="第 1–5 页", start_page=1, end_page=5)]


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


def test_start_page_lower_bound_clamp():
    # start_page 为 0 或负数时，应 clamp 到 1
    chapters = [_chap(0, 0, "C1", 0), _chap(1, 0, "C2", 5)]
    units = build_units(chapters, 10, _counts(10), max_chars=10_000)
    # C1 的 start_page=0 被 clamp 到 1；C1 [1,4]，C2 [5,10]
    assert units[0] == UnitSpec(title="C1", start_page=1, end_page=4)
    assert units[1] == UnitSpec(title="C2", start_page=5, end_page=10)
