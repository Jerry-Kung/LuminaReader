import pytest

from lumina.providers.base import ImagePart, TextPart
from lumina.schemas.selection import ImagePayload, Selection
from lumina.tasks import get_task
from lumina.tasks.base import TaskContext, UnsupportedTaskError
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
    task = TranslateTask()
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
    task = TranslateTask()
    req = task.build_request(_context())

    user_text = req.messages[1].content[0].text
    assert "zh-CN" in user_text


def test_build_request_explicit_target_lang() -> None:
    task = TranslateTask()
    req = task.build_request(_context(target_lang="en"))

    user_text = req.messages[1].content[0].text
    assert "en" in user_text


def test_build_request_default_temperature() -> None:
    task = TranslateTask(default_temperature=0.2)
    req = task.build_request(_context())
    assert req.temperature == 0.2


def test_build_request_respects_temperature_override() -> None:
    task = TranslateTask(default_temperature=0.2)
    req = task.build_request(_context(temperature=0.7))
    assert req.temperature == 0.7


def test_get_task_translate() -> None:
    task = get_task("translate")
    assert isinstance(task, TranslateTask)
    assert task.task_type == "translate"


def test_get_task_unsupported_raises() -> None:
    with pytest.raises(UnsupportedTaskError):
        get_task("qa")


def _context_extracted(**kwargs: object) -> TaskContext:
    options = kwargs.pop("options", {})
    return TaskContext(
        selection=None,
        image=None,
        extracted_text=kwargs.pop("extracted_text", "# Hello\n\nWorld."),
        user_question=kwargs.pop("user_question", None),
        history=kwargs.pop("history", []),
        options=options if isinstance(options, dict) else {},
    )


def test_build_request_uses_extracted_text_when_provided() -> None:
    task = TranslateTask()
    req = task.build_request(
        _context_extracted(options={"target_lang": "zh-CN"}, extracted_text="# Hello\n\nWorld.")
    )

    assert len(req.messages) == 2
    assert req.messages[1].role == "user"
    assert all(part.type != "image" for part in req.messages[1].content)
    combined = "".join(part.text for part in req.messages[1].content if part.type == "text")
    assert "Hello" in combined
    assert "World" in combined


def test_build_request_prefers_extracted_text_over_image_when_both_present() -> None:
    task = TranslateTask()
    ctx = _context()
    ctx = ctx.model_copy(update={"extracted_text": "abc"})
    req = task.build_request(ctx)
    assert all(part.type != "image" for part in req.messages[1].content)


def test_build_request_falls_back_to_image_when_extracted_text_is_none() -> None:
    task = TranslateTask()
    req = task.build_request(_context())
    assert any(part.type == "image" for part in req.messages[1].content)


def test_build_request_raises_when_both_image_and_extracted_text_missing() -> None:
    with pytest.raises(ValueError):
        TranslateTask().build_request(TaskContext(image=None, extracted_text=None))


def test_build_request_appends_user_question_in_first_turn() -> None:
    task = TranslateTask()
    req = task.build_request(
        _context_extracted(user_question="为什么 V=8？", options={"target_lang": "zh-CN"})
    )
    combined = "".join(part.text for part in req.messages[1].content if part.type == "text")
    assert "为什么 V=8？" in combined


def test_build_request_includes_history_in_follow_up_turn() -> None:
    from lumina.providers.base import LLMMessage, TextPart

    history = [
        LLMMessage(role="user", content=[TextPart(text="prev q")]),
        LLMMessage(role="assistant", content=[TextPart(text="prev a")]),
    ]
    task = TranslateTask()
    messages = task.build_request(
        _context_extracted(
            user_question="next q",
            history=history,
            options={"target_lang": "zh-CN"},
        )
    ).messages

    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"
    assert messages[3].role == "user"
    current_text = "".join(part.text for part in messages[3].content if part.type == "text")
    assert "next q" in current_text


def test_build_request_follow_up_does_not_include_image_part() -> None:
    from lumina.providers.base import LLMMessage, TextPart

    history = [
        LLMMessage(role="user", content=[TextPart(text="prev q")]),
        LLMMessage(role="assistant", content=[TextPart(text="prev a")]),
    ]
    task = TranslateTask()
    messages = task.build_request(
        _context_extracted(user_question="next q", history=history, options={"target_lang": "zh-CN"})
    ).messages
    for message in messages:
        assert all(part.type != "image" for part in message.content)


def test_build_request_follow_up_raises_when_user_question_missing() -> None:
    from lumina.providers.base import LLMMessage, TextPart

    history = [LLMMessage(role="user", content=[TextPart(text="prev q")])]
    with pytest.raises(ValueError):
        TranslateTask().build_request(_context_extracted(history=history, user_question=None))
