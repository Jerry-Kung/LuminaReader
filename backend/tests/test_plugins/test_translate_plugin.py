from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


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
