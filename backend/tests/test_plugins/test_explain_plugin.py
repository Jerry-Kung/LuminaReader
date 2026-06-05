from lumina.providers.base import LLMMessage, TextPart

from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


def _explain_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("explain")


def test_p03_user_input_uses_qa_branch() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(PluginContext(user_input="why?"))
    assert "[explain user_qa prompt placeholder]" in segments.user


def test_p04_empty_input_and_history_uses_full_branch() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(PluginContext(user_input="", history=[]))
    assert "[explain user_full prompt placeholder]" in segments.user


def test_p05_history_only_uses_qa_branch() -> None:
    plugin = _explain_plugin()
    history = [
        LLMMessage(role="user", content=[TextPart(text="hi")]),
    ]
    segments = plugin.build_segments(
        PluginContext(user_input="", history=history)
    )
    assert "[explain user_qa prompt placeholder]" in segments.user
