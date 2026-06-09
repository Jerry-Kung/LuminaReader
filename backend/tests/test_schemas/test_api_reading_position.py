import pytest
from pydantic import ValidationError

from lumina.schemas.api import LibraryItem, ReadingPositionUpdate


def test_reading_position_update_with_offset():
    body = ReadingPositionUpdate(last_read_page=1, last_read_offset=0.5)
    assert body.last_read_offset == 0.5


def test_reading_position_update_default_offset():
    body = ReadingPositionUpdate(last_read_page=1)
    assert body.last_read_offset == 0.0


def test_reading_position_update_offset_too_large():
    with pytest.raises(ValidationError):
        ReadingPositionUpdate(last_read_page=1, last_read_offset=1.5)


def test_reading_position_update_offset_negative():
    with pytest.raises(ValidationError):
        ReadingPositionUpdate(last_read_page=1, last_read_offset=-0.1)


def test_library_item_default_offset():
    item = LibraryItem(
        pdf_id="pdf_x",
        name="book",
        primary_pdf_filename="book.pdf",
        primary_pdf_size=100,
        created_at=0,
        last_opened_at=0,
    )
    assert item.last_read_offset == 0.0
