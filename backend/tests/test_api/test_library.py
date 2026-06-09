import pytest
from fastapi.testclient import TestClient

from lumina.projects.manager import auto_create_project

PDF_BYTES = b"%PDF-1.4 library test"


def test_library_empty(client: TestClient) -> None:
    response = client.get("/api/v1/library")
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_library_lists_uploaded_pdf(client: TestClient) -> None:
    client.post(
        "/api/v1/pdfs",
        files={"file": ("lib.pdf", PDF_BYTES, "application/pdf")},
    )
    response = client.get("/api/v1/library")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "lib"


def test_library_invalid_sort(client: TestClient) -> None:
    response = client.get("/api/v1/library?sort=invalid")
    assert response.status_code == 400


def test_library_includes_last_read_offset_after_patch(client: TestClient) -> None:
    created = client.post(
        "/api/v1/pdfs",
        files={"file": ("offset.pdf", PDF_BYTES, "application/pdf")},
    ).json()["data"]
    client.patch(
        f"/api/v1/pdfs/{created['pdf_id']}/reading-position",
        json={"last_read_page": 42, "last_read_offset": 0.37},
    )
    items = client.get("/api/v1/library").json()["data"]["items"]
    target = next(i for i in items if i["pdf_id"] == created["pdf_id"])
    assert target["last_read_page"] == 42
    assert target["last_read_offset"] == pytest.approx(0.37, abs=1e-6)


def test_library_default_last_read_offset_is_zero(client: TestClient) -> None:
    client.post(
        "/api/v1/pdfs",
        files={"file": ("fresh-offset.pdf", PDF_BYTES, "application/pdf")},
    )
    items = client.get("/api/v1/library").json()["data"]["items"]
    assert items[0]["last_read_offset"] == 0.0
