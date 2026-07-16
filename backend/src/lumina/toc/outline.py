"""V1.2.2 第 1 层：PDF 内置 outline 提取（pypdf，本地免费，保留多级层级）。"""

from __future__ import annotations

from pathlib import Path

import pypdf

from lumina.toc.types import TocItem


def extract_outline(pdf_path: Path) -> list[TocItem]:
    """读取内置 outline 为 preorder TocItem 列表；无 outline / 整体解析失败 → []。

    显式 with 管理文件句柄（与 pdftext.extractor 同理：Windows 下与删除书籍冲突）。
    """
    items: list[TocItem] = []
    try:
        with open(pdf_path, "rb") as fh:
            reader = pypdf.PdfReader(fh)
            nodes = reader.outline
            _walk(reader, nodes, 0, items)
    except Exception:
        return []
    return items


def _walk(reader, nodes, depth: int, out: list[TocItem]) -> None:
    """pypdf outline 结构：list 中 Destination 与紧随其后的嵌套 list（= 上一项的子级）。

    单条目损坏（坏 dest / 循环引用 / 缺标题）跳过该条目继续，不让整体失败。
    """
    for node in nodes:
        if isinstance(node, list):
            _walk(reader, node, depth + 1, out)
            continue
        try:
            title = str(node.title).strip()
            page = reader.get_destination_page_number(node) + 1
        except Exception:
            continue
        if not title or page < 1:
            continue
        out.append(TocItem(title=title, page=page, depth=depth))
