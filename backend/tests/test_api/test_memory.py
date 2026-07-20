"""V1.2.3 memory 端点：GET/estimate/build/rebuild/cancel。"""

import json
import time

from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project
from lumina.providers import get_provider
from lumina.providers.base import LLMRequest, LLMResponse, Provider

from tests.test_pdftext.pdf_fixtures import make_text_pdf

PAGES = [f"page {i} body text " * 10 for i in range(1, 9)]
UNIT_JSON = json.dumps(
    {"summary": "## 要点\n- x", "concepts": [{"term": "t", "definition": "d", "page": 1}]},
    ensure_ascii=False,
)


class CannedProvider(Provider):
    name = "canned"

    def __init__(self, unit_text: str = UNIT_JSON, book_text: str = "# 全书总结") -> None:
        self.unit_text = unit_text
        self.book_text = book_text

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        # 总结调用的 system prompt 不要求 JSON —— 以 user 内容含 "##" 摘要块粗判
        text = req.messages[0].content[0].text
        is_book = "book-level recap" in text
        return LLMResponse(text=self.book_text if is_book else self.unit_text, model="fake")

    async def invoke_stream(self, req):
        raise NotImplementedError
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        return True


def _make_book(with_text=True):
    created = auto_create_project(make_text_pdf(PAGES), f"m{time.time_ns()}.pdf")
    if with_text:
        run_extraction_sync(created.project_id, created.pdf_id)
    return created


def _wait_done(client, pdf_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/pdfs/{pdf_id}/memory").json()["data"]
        if data["status"] not in ("running",):
            return data
        time.sleep(0.02)
    raise AssertionError("memory batch did not finish")


def test_memory_404(client):
    assert client.get("/api/v1/pdfs/pdf_missing/memory").status_code == 404


def test_memory_none_initial(client, data_root):
    created = _make_book()
    data = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory").json()["data"]
    assert data["status"] == "none" and data["units"] == [] and data["toc_changed"] is False


def test_estimate_409_without_text(client, data_root):
    created = _make_book(with_text=False)
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory/estimate")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MEMORY_UNAVAILABLE"


def test_estimate_ok(client, data_root):
    created = _make_book()
    data = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory/estimate").json()["data"]
    assert data["scope"] == "full" and data["unit_count"] >= 1
    assert data["currency"] == "USD" and data["estimated_input_tokens"] > 0


def test_estimate_scope_full_query_param(client, data_root):
    """scope=full 查询参数透传（花费预估与重建实际行为对齐的回归项）；plain 请求不受影响。"""
    created = _make_book()
    plain = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory/estimate").json()["data"]
    assert plain["scope"] == "full"
    scoped = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory/estimate?scope=full").json()["data"]
    assert scoped["scope"] == "full"
    assert scoped["unit_count"] == plain["unit_count"]


def test_estimate_invalid_scope_400(client, data_root):
    created = _make_book()
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/memory/estimate?scope=bogus")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_build_flow_to_ready(client, data_root):
    created = _make_book()
    client.app.dependency_overrides[get_provider] = lambda: CannedProvider()
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/build")
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "running"
    data = _wait_done(client, created.pdf_id)
    assert data["status"] == "ready" and data["book_summary"] == "# 全书总结"
    assert data["unit_done"] == data["unit_total"] >= 1
    assert all(u["status"] == "ok" and u["summary"] for u in data["units"])

    # ready 后 build → 409 指引 rebuild
    again = client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/build")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "MEMORY_ALREADY_READY"


def test_build_409_without_text(client, data_root):
    created = _make_book(with_text=False)
    client.app.dependency_overrides[get_provider] = lambda: CannedProvider()
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/build")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MEMORY_UNAVAILABLE"


def test_rebuild_and_cancel_idempotent(client, data_root):
    created = _make_book()
    client.app.dependency_overrides[get_provider] = lambda: CannedProvider()
    client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/build")
    _wait_done(client, created.pdf_id)

    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/rebuild")
    assert resp.status_code == 202
    data = _wait_done(client, created.pdf_id)
    assert data["status"] == "ready"

    # 非 running 时 cancel 幂等 200
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/memory/cancel")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"
