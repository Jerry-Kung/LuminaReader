"""V1.2.3 加工单元切分：顶层章节为单元 + 字符预算贪心拆分 + 无目录降级（规格 F1 / D5）。

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


def build_units(
    chapters: list[ChapterRow],
    page_count: int,
    char_counts: dict[int, int],
    max_chars: int,
) -> list[UnitSpec]:
    if page_count < 1:
        return []

    tops = sorted((c for c in chapters if c.depth == 0), key=lambda c: c.order_index)
    ranges: list[tuple[str, int, int]] = []
    if tops:
        starts = [(c.title, min(max(c.start_page, 1), page_count)) for c in tops]
        for i, (title, page) in enumerate(starts):
            # 首章向前扩展到第 1 页（序言 / 扉页并入首个单元，不丢内容）
            range_start = 1 if i == 0 else page
            range_end = starts[i + 1][1] - 1 if i + 1 < len(starts) else page_count
            if range_end < range_start:
                continue  # 同页多章节起点：空区间跳过
            ranges.append((title, range_start, range_end))

    units: list[UnitSpec] = []
    if ranges:
        for title, start, end in ranges:
            parts = _split_pages(start, end, char_counts, max_chars)
            if len(parts) == 1:
                units.append(UnitSpec(title=title, start_page=start, end_page=end))
            else:
                units.extend(
                    UnitSpec(
                        title=f"{title}（{i}/{len(parts)}）", start_page=s, end_page=e
                    )
                    for i, (s, e) in enumerate(parts, start=1)
                )
    else:
        # 无目录降级：整书走同一贪心拆分，单元标题 = 页码范围
        units.extend(
            UnitSpec(title=f"第 {s}–{e} 页", start_page=s, end_page=e)
            for s, e in _split_pages(1, page_count, char_counts, max_chars)
        )
    return units
