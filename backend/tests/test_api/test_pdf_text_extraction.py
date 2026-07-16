"""V1.2.1 提取端点：GET / POST /api/v1/pdfs/{pdf_id}/text-extraction。"""

import time

from lumina.projects.manager import auto_create_project

from tests.test_pdftext.pdf_fixtures import make_text_pdf

TEXT_PAGES = [
    f"Page {i} content that is definitely long enough to be textual."
    for i in range(1, 6)
]


def _wait_for_terminal(client, pdf_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/pdfs/{pdf_id}/text-extraction")
        assert resp.status_code == 200
        data = resp.json()["data"]
        if data["status"] not in ("pending", "none"):
            return data
        time.sleep(0.05)
    raise AssertionError("extraction did not reach a terminal status in time")


def test_get_status_none_for_legacy_book(client, pdf_project):
    resp = client.get(f"/api/v1/pdfs/{pdf_project.pdf_id}/text-extraction")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["pdf_id"] == pdf_project.pdf_id
    assert body["data"]["status"] == "none"


def test_get_status_404(client):
    resp = client.get("/api/v1/pdfs/pdf_missing/text-extraction")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PDF_NOT_FOUND"


def test_post_trigger_404(client):
    resp = client.post("/api/v1/pdfs/pdf_missing/text-extraction")
    assert resp.status_code == 404


def test_manual_extraction_reaches_ok(client, data_root):
    created = auto_create_project(make_text_pdf(TEXT_PAGES), "extract-ok.pdf")
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/text-extraction")
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"

    data = _wait_for_terminal(client, created.pdf_id)
    assert data["status"] == "ok"
    assert data["page_count"] == 5
    assert data["textual_page_count"] == 5
    assert data["char_count"] > 0
    assert data["extracted_at"] is not None


def test_manual_extraction_failed_on_corrupt_pdf(client, pdf_project):
    # conftest 的 PDF_BYTES 不是合法 PDF → 提取应落 failed 且可见 error
    resp = client.post(f"/api/v1/pdfs/{pdf_project.pdf_id}/text-extraction")
    assert resp.status_code == 202
    data = _wait_for_terminal(client, pdf_project.pdf_id)
    assert data["status"] == "failed"
    assert data["error"]


def test_upload_triggers_extraction_automatically(client, data_root):
    files = {"file": ("autobook.pdf", make_text_pdf(TEXT_PAGES), "application/pdf")}
    resp = client.post("/api/v1/pdfs", files=files)
    assert resp.status_code == 201
    pdf_id = resp.json()["data"]["pdf_id"]

    data = _wait_for_terminal(client, pdf_id)
    assert data["status"] == "ok"
    assert data["page_count"] == 5


def test_upload_scanned_pdf_marked_unsupported(client, data_root):
    pages = [TEXT_PAGES[0], "", "", ""]
    files = {"file": ("scanned.pdf", make_text_pdf(pages), "application/pdf")}
    resp = client.post("/api/v1/pdfs", files=files)
    assert resp.status_code == 201
    pdf_id = resp.json()["data"]["pdf_id"]

    data = _wait_for_terminal(client, pdf_id)
    assert data["status"] == "unsupported"
