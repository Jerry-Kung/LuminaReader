from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TocItem:
    """识别管线的统一中间产物：preorder 顺序的 (标题, 起始页, 层级)。"""

    title: str
    page: int  # 1-based
    depth: int  # 0 = 顶层
