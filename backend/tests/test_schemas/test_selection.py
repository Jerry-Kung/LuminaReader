import pytest
from pydantic import ValidationError

from lumina.config import Settings, get_settings
from lumina.schemas.api import TranslateRequest
from lumina.schemas.selection import Selection, SelectionSegment


def _text_segment(page: int = 5, text: str = "Hello, world.") -> SelectionSegment:
    return SelectionSegment(
        page=page,
        text=text,
        offset_start=0,
        offset_end=len(text),
    )


def _image_selection(**overrides: object) -> dict:
    base = {
        "type": "image",
        "pdf_id": None,
        "page": 1,
        "x": 0.0,
        "y": 0.0,
        "w": 10.0,
        "h": 10.0,
        "dpi": 144.0,
    }
    base.update(overrides)
    return base


def _text_selection(**overrides: object) -> dict:
    text = "Hello, world."
    base = {
        "type": "text",
        "pdf_id": None,
        "page": 5,
        "page_end": 5,
        "text": text,
        "segments": [_text_segment(text=text).model_dump()],
    }
    base.update(overrides)
    return base


def test_selection_image_legal() -> None:
    sel = Selection(**_image_selection())
    assert sel.type == "image"


def test_selection_image_default_type() -> None:
    data = _image_selection()
    del data["type"]
    sel = Selection(**data)
    assert sel.type == "image"


def test_selection_image_missing_coord() -> None:
    data = _image_selection()
    del data["x"]
    with pytest.raises(ValidationError):
        Selection(**data)


def test_selection_image_with_text_field() -> None:
    with pytest.raises(ValidationError):
        Selection(**_image_selection(text="foo"))


def test_selection_image_zero_w() -> None:
    with pytest.raises(ValidationError):
        Selection(**_image_selection(w=0))


def test_selection_text_legal() -> None:
    sel = Selection(**_text_selection())
    assert sel.type == "text"
    assert sel.text == "Hello, world."


def test_selection_text_with_coord() -> None:
    with pytest.raises(ValidationError):
        Selection(**_text_selection(x=1.0))


def test_selection_text_empty_text() -> None:
    with pytest.raises(ValidationError):
        Selection(**_text_selection(text=""))


def test_selection_text_missing_page_end() -> None:
    data = _text_selection()
    del data["page_end"]
    with pytest.raises(ValidationError):
        Selection(**data)


def test_selection_text_page_end_lt_page() -> None:
    with pytest.raises(ValidationError):
        Selection(**_text_selection(page=5, page_end=3))


def test_selection_text_empty_segments() -> None:
    with pytest.raises(ValidationError):
        Selection(**_text_selection(segments=[]))


def test_selection_text_overlong_text(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LUMINA_SELECTION_TEXT_MAX_CHARS", "5000")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="exceeds"):
        Selection(**_text_selection(text="a" * 5001))
    get_settings.cache_clear()


def test_segment_offset_invalid() -> None:
    with pytest.raises(ValidationError):
        SelectionSegment(page=1, text="hi", offset_start=5, offset_end=2)


def test_runrequest_text_with_image() -> None:
    with pytest.raises(ValidationError):
        TranslateRequest(
            task_type="translate",
            selection=Selection(**_text_selection()),
            image={"mime": "image/png", "data": "abc", "width": 1, "height": 1},
        )


def test_runrequest_image_missing() -> None:
    with pytest.raises(ValidationError):
        TranslateRequest(
            task_type="translate",
            selection=Selection(**_image_selection()),
            image=None,
        )


def test_runrequest_followup_no_image() -> None:
    req = TranslateRequest(task_type="translate", selection=None, image=None)
    assert req.selection is None
    assert req.image is None


def test_selection_text_max_chars_from_env(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LUMINA_SELECTION_TEXT_MAX_CHARS", "5000")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.selection_text_max_chars == 5000
    with pytest.raises(ValidationError, match="exceeds"):
        Selection(**_text_selection(text="a" * 6000))
    get_settings.cache_clear()
