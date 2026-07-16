"""V1.2.1 跨页自动上下文：从全书按页文本组装参考上下文块（run 链路消费）。

组装规则见 v1.2.1/requirements.md §2 F2 / D5：
- 窗口 = [page_start - W, page_end + W]，含选区页整页原文；
- 预算 max_chars：按与选区距离由近及远整页纳入，放不下即停止；
- 距离 0（选区自身页）必进，单页超预算时截断。
"""

from __future__ import annotations

from lumina.db.engine import get_connection
from lumina.db.models import get_pdf_text_pages_range
from lumina.pdftext.service import STATUS_OK, read_status

CONTEXT_HEADER_TEMPLATE = (
    "[Reference context — full text of pages {start}-{end} of the book "
    "surrounding the user's selection. Background only; it may overlap the "
    "selection. Do not translate, summarize, or answer about this context "
    "itself unless the user explicitly asks:]"
)


def build_context_block(
    project_id: str,
    pdf_id: str,
    page_start: int,
    page_end: int,
    *,
    window_pages: int,
    max_chars: int,
) -> str | None:
    """返回组装好的参考上下文块；提取状态非 ok / 无可用文本时返回 None。"""
    meta = read_status(project_id, pdf_id)
    if meta.status != STATUS_OK:
        return None

    conn = get_connection(project_id)
    lo = max(1, page_start - window_pages)
    hi = page_end + window_pages
    rows = [
        (page, text)
        for page, text in get_pdf_text_pages_range(conn, pdf_id, lo, hi)
        if text.strip()
    ]
    if not rows:
        return None

    def distance(page: int) -> int:
        if page < page_start:
            return page_start - page
        if page > page_end:
            return page - page_end
        return 0

    selected: list[tuple[int, str]] = []
    total = 0
    for page, text in sorted(rows, key=lambda r: (distance(r[0]), r[0])):
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(text) <= remaining:
            selected.append((page, text))
            total += len(text)
        elif distance(page) == 0:
            # 选区自身页必进：预算不足时截断（距离 0 的页排序在最前）
            selected.append((page, text[:remaining]))
            total = max_chars
        else:
            # 由近及远纳入，放不下即停止（保持窗口连续性）
            break

    if not selected:
        return None

    selected.sort(key=lambda r: r[0])
    header = CONTEXT_HEADER_TEMPLATE.format(
        start=selected[0][0], end=selected[-1][0]
    )
    body = "\n\n".join(f"[Page {page}]\n{text}" for page, text in selected)
    return f"{header}\n\n{body}"
