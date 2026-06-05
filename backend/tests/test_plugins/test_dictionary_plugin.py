from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


def _dictionary_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("dictionary")


def test_d01_selection_text_in_user() -> None:
    plugin = _dictionary_plugin()
    segments = plugin.build_segments(
        PluginContext(selection_text="ephemeral")
    )
    assert "ephemeral" in segments.user


def test_d02_system_contains_structure_instructions() -> None:
    plugin = _dictionary_plugin()
    segments = plugin.build_segments(PluginContext())
    assert "Part of speech" in segments.system
    assert "IPA" in segments.system
    assert "Definitions" in segments.system
    assert "Example sentences" in segments.system


def test_d03_system_contains_fallback_instruction() -> None:
    plugin = _dictionary_plugin()
    segments = plugin.build_segments(PluginContext())
    assert "Input is not a single word" in segments.system


def test_d04_applicable_at_one_word() -> None:
    plugin = _dictionary_plugin()
    assert plugin.is_applicable(PluginContext(selection_word_count=1)) is True


def test_d05_applicable_at_max_word_count() -> None:
    plugin = _dictionary_plugin()
    assert plugin.is_applicable(PluginContext(selection_word_count=3)) is True


def test_d06_not_applicable_above_max_word_count() -> None:
    plugin = _dictionary_plugin()
    assert plugin.is_applicable(PluginContext(selection_word_count=4)) is False


def test_d07_thinking_default_false() -> None:
    plugin = _dictionary_plugin()
    assert plugin.manifest.thinking_default is False


def test_d08_applicable_when_max_word_count() -> None:
    plugin = _dictionary_plugin()
    rule = plugin.manifest.applicable_when
    assert rule is not None
    assert rule.selection_word_count is not None
    assert rule.selection_word_count.max == 3
