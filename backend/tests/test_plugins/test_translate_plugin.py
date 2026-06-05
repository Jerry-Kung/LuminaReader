import pytest

from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.providers.base import ImagePart, LLMStreamEvent


def _translate_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("translate")


def test_t01_target_lang_interpolation() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(PluginContext(target_lang="en"))
    assert "Translate the source content into en" in segments.user


def test_t02_selection_text_interpolation() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(
        PluginContext(selection_text="Hello world")
    )
    assert "Hello world" in segments.user


def test_t03_user_input_interpolation() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(
        PluginContext(user_input="please be formal")
    )
    assert "please be formal" in segments.user


def test_t04_empty_user_input_no_literal_placeholder() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(PluginContext(user_input=None))
    assert "${user_input}" not in segments.user


def test_t05_system_contains_professional_translator() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(PluginContext())
    assert "professional translator" in segments.system


def test_t06_default_parse_response_passthrough() -> None:
    plugin = _translate_plugin()
    result = plugin.parse_response("hello world")
    assert result.answer == "hello world"
    assert result.extracted_text is None


@pytest.mark.asyncio
async def test_t07_default_wrap_stream_passthrough() -> None:
    plugin = _translate_plugin()
    events = [
        LLMStreamEvent(type="text_delta", delta="hi"),
        LLMStreamEvent(type="done", model="m"),
    ]

    async def _iter():
        for ev in events:
            yield ev

    out = [ev async for ev in plugin.wrap_stream(_iter())]
    assert out[0].type == "text_delta"
    assert out[0].delta == "hi"
    assert out[0].section is None
    assert out[1].type == "done"


def test_t08_image_field_ignored_by_build_segments() -> None:
    plugin = _translate_plugin()
    baseline = plugin.build_segments(PluginContext(selection_text="Hello"))
    with_image = plugin.build_segments(
        PluginContext(
            selection_text="Hello",
            image=ImagePart(mime="image/png", data_b64="abc"),
        )
    )
    assert with_image == baseline
