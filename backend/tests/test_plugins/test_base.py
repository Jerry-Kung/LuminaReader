import pytest

from lumina.plugins.base import (
    Plugin,
    PluginManifest,
    PluginParseResult,
    StructuredStreamEvent,
)
from lumina.providers.base import LLMStreamEvent, LLMUsage


def test_plugin_abstract_not_instantiable() -> None:
    manifest = PluginManifest.model_validate(
        {
            "id": "x",
            "label": "x",
            "icon": "x",
            "applicable_to": ["image"],
            "prompt_files": {"system": "a.md", "user": "b.md"},
        }
    )
    with pytest.raises(TypeError):
        Plugin(manifest=manifest, prompts={})  # type: ignore[abstract]


def test_plugin_parse_result_defaults() -> None:
    result = PluginParseResult(answer="x")
    assert result.extracted_text is None


def test_structured_stream_event_passthrough() -> None:
    ev = LLMStreamEvent(
        type="text_delta",
        delta="hello",
        model="m",
        thinking_enabled=True,
    )
    out = StructuredStreamEvent.passthrough(ev)
    assert out.type == "text_delta"
    assert out.delta == "hello"
    assert out.section is None
    assert out.model == "m"
    assert out.thinking_enabled is True
    assert out.text is None


def test_structured_stream_event_passthrough_usage() -> None:
    usage = LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    ev = LLMStreamEvent(type="usage", usage=usage)
    out = StructuredStreamEvent.passthrough(ev)
    assert out.type == "usage"
    assert out.usage == usage
    assert out.section is None
