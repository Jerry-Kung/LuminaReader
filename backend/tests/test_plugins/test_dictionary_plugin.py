from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


def _dictionary_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("dictionary")


def test_p06_applicable_at_max_word_count() -> None:
    plugin = _dictionary_plugin()
    assert plugin.is_applicable(PluginContext(selection_word_count=3)) is True


def test_p07_not_applicable_above_max_word_count() -> None:
    plugin = _dictionary_plugin()
    assert plugin.is_applicable(PluginContext(selection_word_count=4)) is False
