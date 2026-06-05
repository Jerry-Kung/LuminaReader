from lumina.providers.base import LLMMessage, TextPart

from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext


def _explain_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("explain")


def test_e01_empty_input_uses_full_branch() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(PluginContext(user_input="", history=[]))
    assert "Describe what it is about" in segments.user


def test_e02_user_input_uses_qa_branch() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(PluginContext(user_input="why?"))
    assert "Stay focused on the user's question" in segments.user
    assert "why?" in segments.user


def test_e03_history_only_uses_qa_branch() -> None:
    plugin = _explain_plugin()
    history = [
        LLMMessage(role="user", content=[TextPart(text="hi")]),
    ]
    segments = plugin.build_segments(
        PluginContext(user_input="", history=history)
    )
    assert "Stay focused on the user's question" in segments.user


def test_e04_system_no_word_for_word_translation() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(PluginContext())
    assert "word-for-word" in segments.system


def test_e05_user_full_selection_text_replaced() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(
        PluginContext(selection_text="Some paragraph text")
    )
    assert "Some paragraph text" in segments.user
    assert "${selection_text}" not in segments.user


def test_e06_user_qa_both_fields_replaced() -> None:
    plugin = _explain_plugin()
    segments = plugin.build_segments(
        PluginContext(
            user_input="What does this mean?",
            selection_text="ephemeral",
        )
    )
    assert "What does this mean?" in segments.user
    assert "ephemeral" in segments.user
    assert "${user_input}" not in segments.user
    assert "${selection_text}" not in segments.user
