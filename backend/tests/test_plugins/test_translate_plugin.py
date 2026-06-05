from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


def _translate_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("translate")


def test_p01_target_lang_interpolation() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(PluginContext(target_lang="en"))
    assert "target_lang=en" in segments.user


def test_p02_empty_user_input_interpolation() -> None:
    plugin = _translate_plugin()
    segments = plugin.build_segments(PluginContext(user_input=""))
    assert "user_input=" in segments.user
    assert "${user_input}" not in segments.user
