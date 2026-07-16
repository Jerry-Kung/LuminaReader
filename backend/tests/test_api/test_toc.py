"""V1.2.2 TOC 端点：GET/POST /api/v1/pdfs/{pdf_id}/toc*。"""

import json

from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider
from lumina.providers.base import LLMRequest, LLMResponse, Provider

from tests.test_pdftext.pdf_fixtures import make_outline_pdf, make_text_pdf

OUTLINE_PAGES = [f"Page {i} body text long enough here." for i in range(1, 11)]
PLAIN_PAGES = ["ordinary body text without chapter heading " * 3] * 10


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


def test_get_toc_404(client):
    resp = client.get("/api/v1/pdfs/pdf_missing/toc")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PDF_NOT_FOUND"


def test_get_toc_outline_book(client, data_root):
    created = auto_create_project(
        make_outline_pdf(OUTLINE_PAGES, [("Chapter 1", 1, [("Sec 1.1", 2)]), ("Chapter 2", 5, [])]),
        "outline.pdf",
    )
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/toc")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ready" and data["source"] == "outline"
    chapters = data["chapters"]
    assert [c["title"] for c in chapters] == ["Chapter 1", "Sec 1.1", "Chapter 2"]
    assert chapters[1]["parent_id"] == chapters[0]["id"]
    assert chapters[0]["page"] == 1 and chapters[0]["depth"] == 0
    assert data["llm_available"] is False


def test_recognize_rerun(client, data_root):
    created = auto_create_project(
        make_outline_pdf(OUTLINE_PAGES, [("Chapter 1", 1, []), ("Chapter 2", 5, [])]),
        "rerun.pdf",
    )
    first = client.get(f"/api/v1/pdfs/{created.pdf_id}/toc").json()["data"]
    second = client.post(f"/api/v1/pdfs/{created.pdf_id}/toc/recognize").json()["data"]
    assert second["status"] == "ready"
    assert second["chapters"][0]["id"] != first["chapters"][0]["id"]


def test_llm_estimate_409_when_text_unavailable(client, data_root):
    created = auto_create_project(make_text_pdf(PLAIN_PAGES), "noext.pdf")
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/toc/llm-estimate")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TOC_LLM_UNAVAILABLE"


def test_llm_estimate_and_recognize(client, data_root):
    created = auto_create_project(make_text_pdf(PLAIN_PAGES), "llm.pdf")
    run_extraction_sync(created.project_id, created.pdf_id)
    client.get(f"/api/v1/pdfs/{created.pdf_id}/toc")  # 惰性识别 → none

    est = client.get(f"/api/v1/pdfs/{created.pdf_id}/toc/llm-estimate")
    assert est.status_code == 200
    assert est.json()["data"]["estimated_input_tokens"] >= 1
    assert est.json()["data"]["currency"] == "USD"

    payload = json.dumps([
        {"title": "Intro", "page": 1, "level": 0},
        {"title": "End", "page": 8, "level": 0},
    ])
    client.app.dependency_overrides[get_provider] = lambda: CannedProvider(payload)
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/toc/recognize-llm")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ready" and data["source"] == "llm"
    assert [c["title"] for c in data["chapters"]] == ["Intro", "End"]


def test_llm_invalid_output_422(client, data_root):
    created = auto_create_project(make_text_pdf(PLAIN_PAGES), "bad.pdf")
    run_extraction_sync(created.project_id, created.pdf_id)
    client.get(f"/api/v1/pdfs/{created.pdf_id}/toc")
    client.app.dependency_overrides[get_provider] = lambda: CannedProvider("not json")
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/toc/recognize-llm")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TOC_LLM_INVALID"
    # 失败后 GET 呈现 failed 且保留 LLM 重试入口
    data = client.get(f"/api/v1/pdfs/{created.pdf_id}/toc").json()["data"]
    assert data["status"] == "failed" and data["llm_available"] is True


def test_recognize_llm_409_when_text_unavailable(client, data_root):
    created = auto_create_project(make_text_pdf(PLAIN_PAGES), "unavail.pdf")
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/toc/recognize-llm")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TOC_LLM_UNAVAILABLE"
