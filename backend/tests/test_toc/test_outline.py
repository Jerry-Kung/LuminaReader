"""V1.2.2 第 1 层：pypdf outline 提取。"""

from lumina.toc.outline import _walk, extract_outline
from lumina.toc.types import TocItem

from tests.test_pdftext.pdf_fixtures import make_outline_pdf, make_text_pdf

PAGES = [f"Page {i} body text long enough to be textual." for i in range(1, 11)]


def test_extract_nested_outline(tmp_path):
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(make_outline_pdf(
        PAGES,
        [
            ("Chapter 1", 1, [("Section 1.1", 2)]),
            ("Chapter 2", 5, []),
        ],
    ))
    items = extract_outline(pdf)
    assert items == [
        TocItem(title="Chapter 1", page=1, depth=0),
        TocItem(title="Section 1.1", page=2, depth=1),
        TocItem(title="Chapter 2", page=5, depth=0),
    ]


def test_no_outline_returns_empty(tmp_path):
    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(make_text_pdf(PAGES))
    assert extract_outline(pdf) == []


def test_walk_skips_broken_entries():
    # 单条目解析失败（坏 dest）跳过，不整体失败
    class _Node:
        def __init__(self, title):
            self.title = title

    class _Reader:
        def get_destination_page_number(self, node):
            if node.title == "bad":
                raise ValueError("broken dest")
            return 3

    out: list[TocItem] = []
    _walk(_Reader(), [_Node("good"), _Node("bad"), _Node("also good")], 0, out)
    assert [i.title for i in out] == ["good", "also good"]
    assert all(i.page == 4 for i in out)
