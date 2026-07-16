from pathlib import Path

import pytest

from lumina.pdftext.extractor import extract_pdf_text

from tests.test_pdftext.pdf_fixtures import make_text_pdf

TEXT_PAGES = [
    "Page one talks about distributed systems and consistency guarantees.",
    "Page two continues the discussion with replication strategies.",
    "Page three wraps up with a summary of partitioning approaches.",
]


def _write_pdf(tmp_path: Path, pages: list[str]) -> Path:
    path = tmp_path / "book.pdf"
    path.write_bytes(make_text_pdf(pages))
    return path


def test_extract_text_pdf(tmp_path):
    result = extract_pdf_text(_write_pdf(tmp_path, TEXT_PAGES))
    assert result.page_count == 3
    assert result.textual_page_count == 3
    assert result.is_textual_book
    assert result.char_count == sum(len(t) for t in result.page_texts)
    for expected, actual in zip(TEXT_PAGES, result.page_texts):
        assert expected in actual
    assert result.extractor.startswith("pypdf/")


def test_scanned_book_is_unsupported(tmp_path):
    # 4 页中仅 1 页有文本（25% < 50% 阈值）→ 判定为非文本型
    result = extract_pdf_text(_write_pdf(tmp_path, [TEXT_PAGES[0], "", "", ""]))
    assert result.page_count == 4
    assert result.textual_page_count == 1
    assert not result.is_textual_book


def test_short_page_not_textual(tmp_path):
    # 单页 strip 后 < 20 字符不算有文本页
    result = extract_pdf_text(_write_pdf(tmp_path, ["short", TEXT_PAGES[0]]))
    assert result.textual_page_count == 1


def test_corrupt_pdf_raises(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 definitely not a valid pdf body")
    try:
        extract_pdf_text(path)
    except Exception:
        return
    raise AssertionError("expected extraction failure on corrupt pdf")


def test_make_text_pdf_rejects_oversized_charset():
    # 超出单字节码空间（>251 个不同字符）应快速失败而非死循环
    text = "".join(chr(0x4E00 + i) for i in range(300))
    with pytest.raises(ValueError, match="too many unique characters"):
        make_text_pdf([text])

