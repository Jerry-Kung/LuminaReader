"""V1.2.2 TOC service：惰性编排、三层兜底、先成功后替换、失败状态语义。"""

import json

import pytest

from lumina.db.engine import get_connection
from lumina.db.models import get_pdf_toc_meta, list_chapters
from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project
from lumina.providers.base import LLMRequest, LLMResponse, Provider
from lumina.toc.llm import TocLlmInvalidError
from lumina.toc.service import (
    get_or_recognize,
    llm_estimate,
    run_free_recognition,
    run_llm_recognition,
)

from tests.test_pdftext.pdf_fixtures import make_outline_pdf, make_text_pdf


class CannedProvider(Provider):
    name = "canned"

    def __init__(self, text: str) -> None:
        self.text = text

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        return LLMResponse(text=self.text, model="fake-model")

    async def invoke_stream(self, req: LLMRequest):
        raise NotImplementedError
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        return True


OUTLINE_PAGES = [f"Page {i} body text long enough here." for i in range(1, 11)]
HEURISTIC_PAGES = (
    ["第一章 引言\n" + "正文内容 " * 30]
    + ["正文内容 " * 30] * 7
    + ["第二章 方法\n" + "正文内容 " * 30]
    + ["正文内容 " * 30] * 10
    + ["第三章 结论\n" + "正文内容 " * 30]
    + ["正文内容 " * 30] * 5
)
PLAIN_PAGES = ["ordinary body text without any chapter heading " * 3] * 10


def _book(data_root, pdf_bytes, name):
    created = auto_create_project(pdf_bytes, name)
    return created.project_id, created.pdf_id


def test_outline_book_recognized_on_first_get(data_root):
    project_id, pdf_id = _book(
        data_root,
        make_outline_pdf(OUTLINE_PAGES, [("Chapter 1", 1, [("Sec 1.1", 2)]), ("Chapter 2", 5, [])]),
        "outline.pdf",
    )
    result = get_or_recognize(project_id, pdf_id)
    assert result.status == "ready" and result.source == "outline"
    assert [c.title for c in result.chapters] == ["Chapter 1", "Sec 1.1", "Chapter 2"]
    assert result.chapters[1].parent_id == result.chapters[0].id
    assert result.chapters[1].depth == 1
    # 第二次 GET 直接读库，不重跑
    again = get_or_recognize(project_id, pdf_id)
    assert [c.id for c in again.chapters] == [c.id for c in result.chapters]


def test_heuristic_fallback_when_no_outline(data_root):
    project_id, pdf_id = _book(data_root, make_text_pdf(HEURISTIC_PAGES), "heuristic.pdf")
    run_extraction_sync(project_id, pdf_id)  # 启发式依赖全书文本
    result = get_or_recognize(project_id, pdf_id)
    assert result.status == "ready" and result.source == "heuristic"
    assert [c.start_page for c in result.chapters] == [1, 9, 20]


def test_no_result_when_text_pending(data_root):
    # 无 outline 且文本未提取 → 惰性识别只跑第 1 层，状态 none 且 llm 不可用
    project_id, pdf_id = _book(data_root, make_text_pdf(HEURISTIC_PAGES), "pending.pdf")
    result = get_or_recognize(project_id, pdf_id)
    assert result.status == "none"
    assert result.llm_available is False
    assert result.text_status == "none"


def test_plain_book_exposes_llm_entry(data_root):
    project_id, pdf_id = _book(data_root, make_text_pdf(PLAIN_PAGES), "plain.pdf")
    run_extraction_sync(project_id, pdf_id)
    result = get_or_recognize(project_id, pdf_id)
    assert result.status == "none" and result.llm_available is True
    est = llm_estimate(project_id, pdf_id)
    assert est is not None and est["estimated_input_tokens"] >= 1
    assert est["currency"] == "USD"


@pytest.mark.asyncio
async def test_llm_recognition_persists(data_root):
    project_id, pdf_id = _book(data_root, make_text_pdf(PLAIN_PAGES), "llm.pdf")
    run_extraction_sync(project_id, pdf_id)
    get_or_recognize(project_id, pdf_id)
    payload = json.dumps([
        {"title": "Intro", "page": 1, "level": 0},
        {"title": "Middle", "page": 4, "level": 0},
    ])
    result = await run_llm_recognition(project_id, pdf_id, CannedProvider(payload))
    assert result.status == "ready" and result.source == "llm"
    assert [c.title for c in result.chapters] == ["Intro", "Middle"]


@pytest.mark.asyncio
async def test_llm_failure_keeps_old_toc(data_root):
    # 已有旧目录（outline）时 LLM 失败 → 保留 ready 不动（规格 F1 失败状态语义）
    project_id, pdf_id = _book(
        data_root,
        make_outline_pdf(OUTLINE_PAGES, [("Chapter 1", 1, []), ("Chapter 2", 5, [])]),
        "keep-old.pdf",
    )
    run_extraction_sync(project_id, pdf_id)
    get_or_recognize(project_id, pdf_id)
    with pytest.raises(TocLlmInvalidError):
        await run_llm_recognition(project_id, pdf_id, CannedProvider("not json"))
    conn = get_connection(project_id)
    assert get_pdf_toc_meta(conn, pdf_id).status == "ready"
    assert len(list_chapters(conn, pdf_id)) == 2


@pytest.mark.asyncio
async def test_llm_failure_without_old_toc_marks_failed(data_root):
    project_id, pdf_id = _book(data_root, make_text_pdf(PLAIN_PAGES), "mark-failed.pdf")
    run_extraction_sync(project_id, pdf_id)
    get_or_recognize(project_id, pdf_id)
    with pytest.raises(TocLlmInvalidError):
        await run_llm_recognition(project_id, pdf_id, CannedProvider("not json"))
    result = get_or_recognize(project_id, pdf_id)
    assert result.status == "failed" and result.error
    assert result.llm_available is True  # failed 后仍可重试


def test_rerun_replaces_previous_result(data_root):
    project_id, pdf_id = _book(
        data_root,
        make_outline_pdf(OUTLINE_PAGES, [("Chapter 1", 1, []), ("Chapter 2", 5, [])]),
        "rerun.pdf",
    )
    first = get_or_recognize(project_id, pdf_id)
    second = run_free_recognition(project_id, pdf_id)
    assert second.status == "ready"
    # 重跑生成新 chapter id（删旧写新），条目内容一致
    assert [c.title for c in second.chapters] == [c.title for c in first.chapters]
    assert second.chapters[0].id != first.chapters[0].id
