"""V1.0.4 F9: PATCH /api/v1/pdfs/{id}/reading-position + library 字段。

锁定 `claude_docs/api-contract.md §10.8` 的契约：
- 204 写入成功 / 400 越界（<1）/ 404 pdf_id 不存在
- 幂等（同值多次写不变）
- `GET /api/v1/library` 响应 `last_read_page` 反映最新写入；旧库未写过的项默认为 1
- 后端不做上界校验（前端基于 PDF.js numPages 自行 clamp）
"""

import pytest
from fastapi.testclient import TestClient

PDF_BYTES = b"%PDF-1.4 reading-position test"


def _upload(client: TestClient, name: str = "rp.pdf") -> dict:
    return client.post(
        "/api/v1/pdfs",
        files={"file": (name, PDF_BYTES, "application/pdf")},
    ).json()["data"]


def test_patch_reading_position_returns_204(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42},
    )
    assert response.status_code == 204
    assert response.content == b""


def test_patch_reading_position_reflected_in_library(client: TestClient) -> None:
    created = _upload(client)
    client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42},
    )
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_page"] == 42


def test_library_default_last_read_page_is_one(client: TestClient) -> None:
    """新上传的 PDF 默认 last_read_page=1（来自 002 迁移的 DEFAULT 子句）。"""
    created = _upload(client, "fresh.pdf")
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_page"] == 1


def test_patch_reading_position_zero_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 0},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_patch_reading_position_negative_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": -5},
    )
    assert response.status_code == 400


def test_patch_reading_position_missing_field_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={},
    )
    assert response.status_code == 400


def test_patch_reading_position_wrong_type_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": "forty-two"},
    )
    assert response.status_code == 400


def test_patch_reading_position_unknown_pdf_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/pdfs/pdf_missing/reading-position",
        json={"last_read_page": 7},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PDF_NOT_FOUND"


def test_patch_reading_position_idempotent_same_value(client: TestClient) -> None:
    created = _upload(client)
    for _ in range(3):
        response = client.patch(
            f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
            json={"last_read_page": 99},
        )
        assert response.status_code == 204
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_page"] == 99


def test_patch_reading_position_no_upper_bound_enforcement(client: TestClient) -> None:
    """契约 §10.8：后端不持有 PDF 总页数，上界校验由前端完成。
    后端只拒 < 1；超大整数（远超任何 PDF 页数）后端必须接受。"""
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 999999},
    )
    assert response.status_code == 204


def test_patch_reading_position_isolates_across_pdfs(client: TestClient) -> None:
    a = _upload(client, "a.pdf")
    b = _upload(client, "b.pdf")
    client.patch(
        f"/api/v1/pdfs/{a['pdf_id']}/reading-position",
        json={"last_read_page": 11},
    )
    client.patch(
        f"/api/v1/pdfs/{b['pdf_id']}/reading-position",
        json={"last_read_page": 222},
    )
    items = {i["pdf_id"]: i for i in client.get("/api/v1/library").json()["data"]["items"]}
    assert items[a["pdf_id"]]["last_read_page"] == 11
    assert items[b["pdf_id"]]["last_read_page"] == 222


# --- V1.1.3: last_read_offset ---


def test_patch_reading_position_with_offset_returns_204(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 0.37},
    )
    assert response.status_code == 204


def test_patch_reading_position_offset_reflected_in_library(client: TestClient) -> None:
    created = _upload(client)
    client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 0.37},
    )
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_page"] == 42
    assert target["last_read_offset"] == pytest.approx(0.37, abs=1e-6)


def test_patch_reading_position_missing_offset_defaults_zero(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42},
    )
    assert response.status_code == 204
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_offset"] == 0.0


def test_patch_reading_position_offset_boundary_zero(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 0.0},
    )
    assert response.status_code == 204


def test_patch_reading_position_offset_boundary_one(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 1.0},
    )
    assert response.status_code == 204


def test_patch_reading_position_offset_too_large_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 1.5},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_patch_reading_position_offset_negative_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": -0.1},
    )
    assert response.status_code == 400


def test_patch_reading_position_offset_wrong_type_returns_400(client: TestClient) -> None:
    created = _upload(client)
    response = client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": "abc"},
    )
    assert response.status_code == 400


def test_patch_reading_position_offset_idempotent(client: TestClient) -> None:
    created = _upload(client)
    payload = {"last_read_page": 42, "last_read_offset": 0.37}
    for _ in range(2):
        response = client.patch(
            f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
            json=payload,
        )
        assert response.status_code == 204
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_offset"] == pytest.approx(0.37, abs=1e-6)
