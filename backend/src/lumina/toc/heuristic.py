"""V1.2.2 第 2 层：基于全书按页文本的启发式章节识别。

置信门槛"宁缺毋滥"（规格 D7）：不满足即返回 []，宁可无目录也不产出
脏章节结构传导给 V1.2.3。正则集合与阈值以本文件单测锁定（规格 §11）。
"""

from __future__ import annotations

import re

from lumina.toc.types import TocItem

# 顶层章节模式（depth=0）
TOP_PATTERNS: list[re.Pattern] = [
    re.compile(r"^第\s*[0-9０-９一二三四五六七八九十百千两]+\s*[章卷部篇]"),
    re.compile(r"^(Chapter|CHAPTER)\s+\d+\b"),
    re.compile(r"^(Part|PART)\s+[IVXLCDM\d]+\b"),
]
# 次级模式（depth=1）
SUB_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\d+\.\d+(\.\d+)?\s+\S"),
    re.compile(r"^第\s*[0-9０-９一二三四五六七八九十百]+\s*节"),
]
# LLM 层样本压缩复用的候选行判定（Task 4）
CANDIDATE_PATTERNS: list[re.Pattern] = TOP_PATTERNS + SUB_PATTERNS

MAX_TITLE_CHARS = 50  # 标题行长约束：超长的编号行多为正文引用
MIN_TOP_CHAPTERS = 3
MAX_TOP_CHAPTERS = 300
TOC_LISTING_PAGE_MIN_HITS = 4  # 单页顶层命中数达到该值视为"目录页"整页剔除
UNIQUE_TITLE_MIN_RATIO = 0.8  # 顶层标题去重后占比低于该值视为大面积重复


def recognize_from_pages(pages: list[tuple[int, str]]) -> list[TocItem]:
    items: list[TocItem] = []
    for page_no, text in pages:
        page_items: list[TocItem] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or len(line) > MAX_TITLE_CHARS:
                continue
            if any(p.match(line) for p in TOP_PATTERNS):
                page_items.append(TocItem(title=line, page=page_no, depth=0))
            elif any(p.match(line) for p in SUB_PATTERNS):
                page_items.append(TocItem(title=line, page=page_no, depth=1))
        top_hits = sum(1 for i in page_items if i.depth == 0)
        if top_hits >= TOC_LISTING_PAGE_MIN_HITS:
            continue  # 目录页本身，整页剔除
        items.extend(page_items)

    top = [i for i in items if i.depth == 0]
    if not (MIN_TOP_CHAPTERS <= len(top) <= MAX_TOP_CHAPTERS):
        return []
    top_pages = [i.page for i in top]
    if any(b <= a for a, b in zip(top_pages, top_pages[1:])):
        return []
    titles = [i.title for i in top]
    if len(set(titles)) < len(titles) * UNIQUE_TITLE_MIN_RATIO:
        return []
    return items
