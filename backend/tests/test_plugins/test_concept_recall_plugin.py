"""V1.2.4 concept-recall 插件：模板插值 / 适用性边界 / 默认透传。"""

from lumina.plugins import get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.plugins.registry import PluginRegistry


def _recall_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("concept-recall")


def test_manifest_fields():
    p = _recall_plugin()
    assert p.manifest.label == "回查"
    assert p.manifest.applicable_to == ["text"]
    assert p.manifest.thinking_default is False
    assert p.manifest.applicable_when.selection_word_count.max == 6


def test_applicable_text_within_word_limit():
    p = _recall_plugin()
    ctx = PluginContext(selection_text="梯度下降", selection_type="text", selection_word_count=2)
    assert p.is_applicable(ctx) is True


def test_not_applicable_over_word_limit():
    p = _recall_plugin()
    ctx = PluginContext(selection_text="a b c d e f g", selection_type="text", selection_word_count=7)
    assert p.is_applicable(ctx) is False


def test_not_applicable_for_image():
    p = _recall_plugin()
    ctx = PluginContext(selection_type="image", selection_word_count=1)
    assert p.is_applicable(ctx) is False


def test_build_segments_interpolates_selection():
    p = _recall_plugin()
    ctx = PluginContext(selection_text="梯度下降", selection_type="text", selection_word_count=2)
    seg = p.build_segments(ctx)
    assert "梯度下降" in seg.user


def test_default_passthrough_parse():
    p = _recall_plugin()
    assert p.parse_response("hello").answer == "hello"
