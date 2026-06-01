import io

import pytest
from fastapi.testclient import TestClient

from lumina.config import get_settings
from lumina.db.engine import close_all
from lumina.projects.catalog import find_by_pdf_id
from lumina.projects.manager import auto_create_project
from lumina.projects.paths import project_dir

PDF_BYTES = b"%PDF-1.4 api pdf test"


@pytest.fixture
def pdf_client(client) -> TestClient:
    return client


def test_upload_pdf_success(pdf_client: TestClient) -> None:
    response = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("book.pdf", PDF_BYTES, "application/pdf")},
        data={"force_create_new": "false"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["pdf_id"].startswith("pdf_")
    assert body["data"]["project_id"].startswith("proj_")
    assert body["data"]["name"] == "book"


def test_upload_pdf_conflict(pdf_client: TestClient) -> None:
    pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("dup.pdf", PDF_BYTES, "application/pdf")},
    )
    response = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("dup.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "PROJECT_NAME_CONFLICT"
    assert "existing" in body["error"]
    assert "force_create_new_hint" in body["error"]


def test_upload_pdf_force_create_new(pdf_client: TestClient) -> None:
    pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("dup.pdf", PDF_BYTES, "application/pdf")},
    )
    response = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("dup.pdf", PDF_BYTES, "application/pdf")},
        data={"force_create_new": "true"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["name"] == "dup (2)"


def test_upload_non_pdf_returns_415(pdf_client: TestClient) -> None:
    response = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("bad.bin", b"NOTPDF", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_get_pdf_raw(pdf_client: TestClient) -> None:
    created = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("raw.pdf", PDF_BYTES, "application/pdf")},
    ).json()["data"]
    response = pdf_client.get(f"/api/v1/pdfs/{created['pdf_id']}/raw")
    assert response.status_code == 200
    assert response.content == PDF_BYTES


def test_get_pdf_raw_not_found(pdf_client: TestClient) -> None:
    response = pdf_client.get("/api/v1/pdfs/pdf_missing/raw")
    assert response.status_code == 404


def test_delete_pdf(pdf_client: TestClient) -> None:
    created = pdf_client.post(
        "/api/v1/pdfs",
        files={"file": ("del.pdf", PDF_BYTES, "application/pdf")},
    ).json()["data"]
    response = pdf_client.delete(f"/api/v1/pdfs/{created['pdf_id']}")
    assert response.status_code == 204
    assert find_by_pdf_id(created["pdf_id"]) is None
    assert not project_dir(created["project_id"]).exists()
