import pytest

from lumina.providers.base import ImagePart, TextPart
from lumina.schemas.selection import ImagePayload, Selection
from lumina.tasks import get_task
from lumina.tasks.base import TaskContext, UnsupportedTaskError
from lumina.tasks.explain import ExplainTask
from lumina.tasks.translate import TranslateTask

MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAD0lEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def _context(*, target_lang: str | None = None, temperature: float | None = None) -> TaskContext:
    options: dict = {}
    if target_lang is not None:
        options["target_lang"] = target_lang
    if temperature is not None:
        options["temperature"] = temperature
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
    task = ExplainTask()
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


def test_build_request_default_target_lang_is_zh_cn() -> None:
    task = ExplainTask()
    req = task.build_request(_context())

    user_text = req.messages[1].content[0].text
    assert "zh-CN" in user_text


def test_build_request_explicit_target_lang() -> None:
    task = ExplainTask()
    req = task.build_request(_context(target_lang="en"))

    user_text = req.messages[1].content[0].text
    assert "en" in user_text


def test_build_request_default_temperature() -> None:
    task = ExplainTask(default_temperature=0.2)
    req = task.build_request(_context())
    assert req.temperature == 0.2


def test_build_request_respects_temperature_override() -> None:
    task = ExplainTask(default_temperature=0.2)
    req = task.build_request(_context(temperature=0.7))
    assert req.temperature == 0.7


def test_get_task_explain() -> None:
    task = get_task("explain")
    assert isinstance(task, ExplainTask)
    assert task.task_type == "explain"


def test_get_task_translate_still_registered() -> None:
    task = get_task("translate")
    assert isinstance(task, TranslateTask)
    assert task.task_type == "translate"


def test_get_task_unsupported_raises() -> None:
    with pytest.raises(UnsupportedTaskError):
        get_task("qa")
