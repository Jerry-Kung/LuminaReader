"""V1.2.6 加工单元切分：全目录条目区间（任意深度）+ 小节合并 + 字符预算贪心拆分 + 无目录降级。

骨架规则（规格 v1.2.6 F1~F3，取代 V1.2.3 D5 的顶层粒度）：
- 按 order_index 文档序取全部目录条目为区间边界，叶子小节即基本单元，
  父条目自身区间为其"引言段"（至首个子条目前；同页起始则为空被跳过）；
- 小于 min_chars 的连续小区间在同一顶层章节内贪心合并（标题 " / " 连接），
  合并累计不超 max_chars，不跨顶层章节；
- 单一区间超 max_chars 仍按页贪心拆分附"（i/N）"后缀（兜底，正常小节少触发）。

有目录与无目录共用同一套按页贪心拆分机制；无目录 = 整书视为单一"章节"，
单元标题改用"第 X–Y 页"（兑现 V1.2.2 D4 的按页均分降级）。
"""

from __future__ import annotations

from dataclasses import dataclass

from lumina.db.models import ChapterRow


@dataclass(frozen=True)
class UnitSpec:
    title: str
    start_page: int
    end_page: int


@dataclass(frozen=True)
class _Interval:
    group: int  # 所属顶层章节序号（合并不跨组）
    title: str
    start_page: int
    end_page: int


def _split_pages(
    start: int, end: int, char_counts: dict[int, int], max_chars: int
) -> list[tuple[int, int]]:
    """按页边界贪心切分 [start, end]：累计字符将超预算即开新段；每段至少一页。"""
    parts: list[tuple[int, int]] = []
    part_start = start
    acc = 0
    for page in range(start, end + 1):
        chars = char_counts.get(page, 0)
        if acc > 0 and acc + chars > max_chars:
            parts.append((part_start, page - 1))
            part_start = page
            acc = 0
        acc += chars
    parts.append((part_start, end))
    return parts


def _range_chars(start: int, end: int, char_counts: dict[int, int]) -> int:
    return sum(char_counts.get(p, 0) for p in range(start, end + 1))


def _build_intervals(chapters: list[ChapterRow], page_count: int) -> list[_Interval]:
    """全目录条目 → 页区间：下一条目（不论深度）的起始页即本条区间的右界。

    首条区间向前扩展到第 1 页（扉页 / 前言并入，不丢内容）；空区间跳过
    （同页多条目起点，known limitation 承接 V1.2.2 R-V122-6）。
    顶层分组：depth=0 开新组；首个 depth=0 之前的游离条目各自独立成组。
    """
    ordered = sorted(chapters, key=lambda c: c.order_index)
    starts = [min(max(c.start_page, 1), page_count) for c in ordered]

    intervals: list[_Interval] = []
    group = -1
    seen_top = False
    for i, chap in enumerate(ordered):
        if chap.depth == 0 or not seen_top:
            group += 1
            seen_top = seen_top or chap.depth == 0
        range_start = 1 if i == 0 else starts[i]
        range_end = starts[i + 1] - 1 if i + 1 < len(ordered) else page_count
        if range_end < range_start:
            continue
        intervals.append(
            _Interval(group=group, title=chap.title, start_page=range_start, end_page=range_end)
        )
    return intervals


def _emit_split(
    units: list[UnitSpec], title: str, start: int, end: int,
    char_counts: dict[int, int], max_chars: int,
) -> None:
    """单区间成单元；超预算按页贪心拆分附序号后缀。"""
    parts = _split_pages(start, end, char_counts, max_chars)
    if len(parts) == 1:
        units.append(UnitSpec(title=title, start_page=start, end_page=end))
    else:
        units.extend(
            UnitSpec(title=f"{title}（{i}/{len(parts)}）", start_page=s, end_page=e)
            for i, (s, e) in enumerate(parts, start=1)
        )


def build_units(
    chapters: list[ChapterRow],
    page_count: int,
    char_counts: dict[int, int],
    max_chars: int,
    min_chars: int = 0,
) -> list[UnitSpec]:
    if page_count < 1:
        return []

    intervals = _build_intervals(chapters, page_count)
    if not intervals:
        # 无目录降级：整书走同一贪心拆分，单元标题 = 页码范围
        return [
            UnitSpec(title=f"第 {s}–{e} 页", start_page=s, end_page=e)
            for s, e in _split_pages(1, page_count, char_counts, max_chars)
        ]

    units: list[UnitSpec] = []
    i = 0
    while i < len(intervals):
        cur = intervals[i]
        chars = _range_chars(cur.start_page, cur.end_page, char_counts)
        if min_chars <= 0 or chars >= min_chars:
            _emit_split(units, cur.title, cur.start_page, cur.end_page, char_counts, max_chars)
            i += 1
            continue
        # 小区间：向后吸收同组内连续小区间，累计将超 max_chars 即封口
        titles = [cur.title]
        acc = chars
        end = cur.end_page
        j = i + 1
        while j < len(intervals):
            nxt = intervals[j]
            nxt_chars = _range_chars(nxt.start_page, nxt.end_page, char_counts)
            if nxt.group != cur.group or nxt_chars >= min_chars or acc + nxt_chars > max_chars:
                break
            titles.append(nxt.title)
            acc += nxt_chars
            end = nxt.end_page
            j += 1
        if len(titles) == 1:
            # 孤立小区间（前后无可合并对象）：独立成单元
            _emit_split(units, cur.title, cur.start_page, cur.end_page, char_counts, max_chars)
        else:
            units.append(UnitSpec(title=" / ".join(titles), start_page=cur.start_page, end_page=end))
        i = j
    return units
