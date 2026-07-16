"""V1.2.2 书签端点：/api/v1/pdfs/{pdf_id}/bookmarks*。"""

from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project

from tests.test_pdftext.pdf_fixtures import make_text_pdf

PAGES = [f"Page {i} body text long enough here." for i in range(1, 11)]


def _book(client):
    created = auto_create_project(make_text_pdf(PAGES), "bm.pdf")
    return created


def test_list_empty_and_404(client, data_root):
    created = _book(client)
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/bookmarks")
    assert resp.status_code == 200
    assert resp.json()["data"]["bookmarks"] == []
    assert client.get("/api/v1/pdfs/pdf_missing/bookmarks").status_code == 404


def test_create_with_default_name_and_sort(client, data_root):
    created = _book(client)
    r1 = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks",
        json={"page": 9, "offset_ratio": 0.5},
    )
    assert r1.status_code == 201
    b1 = r1.json()["data"]
    assert b1["name"] == "第 9 页" and b1["id"].startswith("bm_")
    r2 = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks",
        json={"name": "开头", "page": 2},
    )
    assert r2.status_code == 201
    assert r2.json()["data"]["offset_ratio"] == 0.0
    got = client.get(f"/api/v1/pdfs/{created.pdf_id}/bookmarks").json()["data"]["bookmarks"]
    assert [b["page"] for b in got] == [2, 9]  # 按页码排序


def test_create_page_out_of_range(client, data_root):
    created = _book(client)
    run_extraction_sync(created.project_id, created.pdf_id)  # page_count 可知后才校验上界
    resp = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks",
        json={"page": 999},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BOOKMARK_PAGE_OUT_OF_RANGE"


def test_rename_and_delete(client, data_root):
    created = _book(client)
    bid = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks", json={"page": 3}
    ).json()["data"]["id"]

    patch = client.patch(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks/{bid}", json={"name": "核心论证"}
    )
    assert patch.status_code == 200
    assert patch.json()["data"]["name"] == "核心论证"

    missing = client.patch(
        f"/api/v1/pdfs/{created.pdf_id}/bookmarks/bm_missing", json={"name": "x"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "BOOKMARK_NOT_FOUND"

    assert client.delete(f"/api/v1/pdfs/{created.pdf_id}/bookmarks/{bid}").status_code == 204
    # 重复删除幂等 204
    assert client.delete(f"/api/v1/pdfs/{created.pdf_id}/bookmarks/{bid}").status_code == 204
    assert client.get(f"/api/v1/pdfs/{created.pdf_id}/bookmarks").json()["data"]["bookmarks"] == []
