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
