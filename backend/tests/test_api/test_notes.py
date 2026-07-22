"""V1.2.5 笔记端点：/api/v1/pdfs/{pdf_id}/notes*。"""

from lumina.pdftext.service import run_extraction_sync
from lumina.projects.manager import auto_create_project

from tests.test_pdftext.pdf_fixtures import make_text_pdf

PAGES = [f"Page {i} body text long enough here." for i in range(1, 11)]


def _book(client):
    return auto_create_project(make_text_pdf(PAGES), "notes.pdf")


def test_list_empty_and_404(client, data_root):
    created = _book(client)
    resp = client.get(f"/api/v1/pdfs/{created.pdf_id}/notes")
    assert resp.status_code == 200
    assert resp.json()["data"]["notes"] == []
    assert client.get("/api/v1/pdfs/pdf_missing/notes").status_code == 404


def test_create_full_fields_and_sort(client, data_root):
    created = _book(client)
    r1 = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/notes",
        json={
            "content": "选区笔记正文",
            "page": 9,
            "offset_ratio": 0.5,
            "anchor_text": "被选中的原文",
            "anchor_rects_json": '[{"page":9,"rects":[{"left":0.1,"top":0.5,"width":0.5,"height":0.02}]}]',
            "source": "selection",
        },
    )
    assert r1.status_code == 201
    n1 = r1.json()["data"]
    assert n1["id"].startswith("nt_") and n1["source"] == "selection"
    assert n1["anchor_text"] == "被选中的原文"
    # 最小字段创建（页级笔记）：offset_ratio/anchor 缺省为 NULL，source 缺省 manual
    r2 = client.post(f"/api/v1/pdfs/{created.pdf_id}/notes", json={"content": "页级", "page": 2})
    assert r2.status_code == 201
    n2 = r2.json()["data"]
    assert n2["offset_ratio"] is None and n2["anchor_text"] is None and n2["source"] == "manual"
    got = client.get(f"/api/v1/pdfs/{created.pdf_id}/notes").json()["data"]["notes"]
    assert [n["page"] for n in got] == [2, 9]  # 按页码排序


def test_create_validation(client, data_root):
    created = _book(client)
    # content 空白 → 400（全局校验映射，同 BookmarkRename 先例）
    assert client.post(
        f"/api/v1/pdfs/{created.pdf_id}/notes", json={"content": "   ", "page": 1}
    ).status_code == 400
    # page < 1 → 400
    assert client.post(
        f"/api/v1/pdfs/{created.pdf_id}/notes", json={"content": "x", "page": 0}
    ).status_code == 400
    # source 非法 → 400
    assert client.post(
        f"/api/v1/pdfs/{created.pdf_id}/notes",
        json={"content": "x", "page": 1, "source": "bogus"},
    ).status_code == 400


def test_create_page_out_of_range(client, data_root):
    created = _book(client)
    run_extraction_sync(created.project_id, created.pdf_id)  # page_count 可知后才校验上界
    resp = client.post(f"/api/v1/pdfs/{created.pdf_id}/notes", json={"content": "x", "page": 999})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NOTE_PAGE_OUT_OF_RANGE"


def test_patch_and_delete(client, data_root):
    created = _book(client)
    nid = client.post(
        f"/api/v1/pdfs/{created.pdf_id}/notes", json={"content": "原文", "page": 3}
    ).json()["data"]["id"]

    patch = client.patch(
        f"/api/v1/pdfs/{created.pdf_id}/notes/{nid}", json={"content": "改后的正文"}
    )
    assert patch.status_code == 200
    assert patch.json()["data"]["content"] == "改后的正文"
    got = client.get(f"/api/v1/pdfs/{created.pdf_id}/notes").json()["data"]["notes"]
    assert got[0]["content"] == "改后的正文"

    missing = client.patch(
        f"/api/v1/pdfs/{created.pdf_id}/notes/nt_missing", json={"content": "x"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOTE_NOT_FOUND"

    assert client.delete(f"/api/v1/pdfs/{created.pdf_id}/notes/{nid}").status_code == 204
    # 重复删除幂等 204
    assert client.delete(f"/api/v1/pdfs/{created.pdf_id}/notes/{nid}").status_code == 204
    assert client.get(f"/api/v1/pdfs/{created.pdf_id}/notes").json()["data"]["notes"] == []
