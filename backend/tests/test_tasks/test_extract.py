import pytest

from lumina.providers.base import ImagePart, LLMResponse, TextPart
from lumina.schemas.selection import ImagePayload, Selection
from lumina.tasks import TASK_REGISTRY, get_task
from lumina.tasks.base import TaskContext, UnsupportedTaskError
from lumina.tasks.extract import ExtractTask

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def _context(*, temperature: float | None = None, target_lang: str | None = None) -> TaskContext:
    options: dict = {}
    if temperature is not None:
        options["temperature"] = temperature
    if target_lang is not None:
        options["target_lang"] = target_lang
    return TaskContext(
        selection=Selection(
            pdf_id=None,
            page=1,
            x=0.0,
            y=0.0,
            w=10.0,
            h=10.0,
            dpi=144.0,
        ),
        image=ImagePayload(
            mime="image/png",
            data=MINIMAL_PNG_B64,
            width=1,
            height=1,
        ),
        options=options,
    )


def test_build_request_contains_system_user_and_image() -> None:
    task = ExtractTask()
    req = task.build_request(_context())

    assert len(req.messages) == 2
    assert req.messages[0].role == "system"
    assert len(req.messages[0].content) == 1
    assert isinstance(req.messages[0].content[0], TextPart)

    assert req.messages[1].role == "user"
    assert len(req.messages[1].content) == 2
    assert isinstance(req.messages[1].content[0], TextPart)
    assert isinstance(req.messages[1].content[1], ImagePart)
    assert req.messages[1].content[1].mime == "image/png"
    assert req.messages[1].content[1].data_b64 == MINIMAL_PNG_B64


def test_system_prompt_constrains_markdown_structure() -> None:
    prompt = ExtractTask.SYSTEM_PROMPT.lower()
    keywords = ["markdown", "$$", "$", "list", "table", "do not translate", "do not explain"]
    matches = sum(1 for keyword in keywords if keyword in prompt)
    assert matches >= 3


def test_user_instruction_is_short_extraction_directive() -> None:
    assert "extract" in ExtractTask.USER_INSTRUCTION.lower()


def test_build_request_default_temperature() -> None:
    task = ExtractTask(default_temperature=0.2)
    req = task.build_request(_context())
    assert req.temperature == 0.2


def test_build_request_respects_temperature_override() -> None:
    task = ExtractTask(default_temperature=0.2)
    req = task.build_request(_context(temperature=0.0))
    assert req.temperature == 0.0


def test_target_lang_is_ignored() -> None:
    task = ExtractTask()
    req = task.build_request(_context(target_lang="en"))
    user_text = req.messages[1].content[0].text
    assert "zh-CN" not in user_text
    assert "into en" not in user_text
    assert req.messages[1].content[0].text == ExtractTask.USER_INSTRUCTION


def test_missing_image_raises() -> None:
    ctx = TaskContext(image=None)
    with pytest.raises(ValueError, match="ExtractTask requires ctx.image"):
        ExtractTask().build_request(ctx)


def test_extract_task_not_registered() -> None:
    assert "extract" not in TASK_REGISTRY
    with pytest.raises(UnsupportedTaskError):
        get_task("extract")


def test_parse_response_returns_text_as_is() -> None:
    resp = LLMResponse(text="# Heading\n\nParagraph", model="m")
    result = ExtractTask().parse_response(resp)
    assert result.text == "# Heading\n\nParagraph"
