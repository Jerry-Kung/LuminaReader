import sqlite3
import time

import pytest

from lumina.db.migrations import initialize_schema
from lumina.db.models import (
    PdfRow,
    ProjectMetaRow,
    get_pdf_last_read_page,
    get_pdf_reading_position,
    insert_pdf,
    insert_project_meta,
    update_pdf_last_read_page,
    update_pdf_reading_position,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    initialize_schema(connection)
    insert_project_meta(
        connection,
        ProjectMetaRow(id="proj_test", name="test", created_at=0, schema_version=3),
    )
    insert_pdf(
        connection,
        PdfRow(
            id="pdf_test",
            project_id="proj_test",
            filename="book.pdf",
            storage_path="original.pdf",
            file_size=1024,
            added_at=int(time.time()),
            schema_version=3,
        ),
    )
    yield connection
    connection.close()


def test_update_and_get_reading_position_roundtrip(conn):
    update_pdf_reading_position(conn, "pdf_test", 42, 0.37)
    page, offset = get_pdf_reading_position(conn, "pdf_test")
    assert page == 42
    assert offset == pytest.approx(0.37, abs=1e-6)


def test_reading_position_boundary_zero(conn):
    update_pdf_reading_position(conn, "pdf_test", 1, 0.0)
    page, offset = get_pdf_reading_position(conn, "pdf_test")
    assert page == 1
    assert offset == pytest.approx(0.0, abs=1e-6)


def test_reading_position_boundary_one(conn):
    update_pdf_reading_position(conn, "pdf_test", 100, 1.0)
    page, offset = get_pdf_reading_position(conn, "pdf_test")
    assert page == 100
    assert offset == pytest.approx(1.0, abs=1e-6)


def test_update_pdf_last_read_page_wrapper_sets_offset_zero(conn):
    update_pdf_last_read_page(conn, "pdf_test", 42)
    page, offset = get_pdf_reading_position(conn, "pdf_test")
    assert page == 42
    assert offset == pytest.approx(0.0, abs=1e-6)


def test_get_pdf_last_read_page_wrapper_returns_page_only(conn):
    update_pdf_reading_position(conn, "pdf_test", 77, 0.5)
    assert get_pdf_last_read_page(conn, "pdf_test") == 77
