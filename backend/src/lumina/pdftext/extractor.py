"""V1.2.1 全书文本提取：基于 PDF 文本层的本地免费提取（pypdf，不调用 LLM）。

承诺面：标准排版的文本型 PDF（known limitations 见 v1.2.1/requirements.md §9）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pypdf

# 单页文本 strip 后达到该字符数记为"有文本页"（textual page）
TEXTUAL_PAGE_MIN_CHARS = 20
# 有文本页占比达到该阈值判定整本书为文本型（否则 unsupported）
TEXTUAL_BOOK_MIN_RATIO = 0.5


@dataclass
class ExtractionResult:
    page_texts: list[str]
    page_count: int
    textual_page_count: int
    char_count: int
    extractor: str

    @property
    def is_textual_book(self) -> bool:
        if self.page_count == 0:
            return False
        return self.textual_page_count / self.page_count >= TEXTUAL_BOOK_MIN_RATIO


def extract_pdf_text(pdf_path: Path) -> ExtractionResult:
    """同步全量提取；调用方负责放入线程池。加密 / 损坏文件抛异常由上层落 failed。

    显式 with 管理文件句柄（PdfReader(path) 会惰性持有句柄直到 GC，
    Windows 下与删除书籍的 rmtree 冲突）。
    """
    page_texts: list[str] = []
    textual_page_count = 0
    extractor_version = f"pypdf/{pypdf.__version__}"
    with open(pdf_path, "rb") as fh:
        reader = pypdf.PdfReader(fh)
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                # 单页解析失败按空页计，不让个别坏页拖垮整本书
                text = ""
            text = text.replace("\x00", "")
            page_texts.append(text)
            if len(text.strip()) >= TEXTUAL_PAGE_MIN_CHARS:
                textual_page_count += 1
    return ExtractionResult(
        page_texts=page_texts,
        page_count=len(page_texts),
        textual_page_count=textual_page_count,
        char_count=sum(len(t) for t in page_texts),
        extractor=extractor_version,
    )
