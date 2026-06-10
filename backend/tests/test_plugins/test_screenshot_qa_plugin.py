import pytest

from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import PluginContext
from lumina.providers.base import LLMStreamEvent


def _screenshot_qa_plugin():
    registry = PluginRegistry.load_all(get_plugins_root())
    return registry.get("screenshot-qa")


async def _iter_events(events: list[LLMStreamEvent]):
    for ev in events:
        yield ev


def test_sq01_build_segments_with_user_input() -> None:
    plugin = _screenshot_qa_plugin()
    ctx = PluginContext(user_input="这张图说什么？", target_lang="zh-CN")
    seg = plugin.build_segments(ctx)
    assert "${user_input}" not in seg.user
    assert "这张图说什么？" in seg.user
    assert "${target_lang}" not in seg.system
    assert "zh-CN" in seg.system


def test_sq02_build_segments_without_user_input() -> None:
    plugin = _screenshot_qa_plugin()
    ctx = PluginContext(user_input=None, target_lang="zh-CN")
    seg = plugin.build_segments(ctx)
    assert "请提取图中" in seg.user
    assert "${" not in seg.user


def test_sq03_parse_response_success() -> None:
    plugin = _screenshot_qa_plugin()
    text = "<ocr>OCR content</ocr><answer>Answer content</answer>"
    result = plugin.parse_response(text)
    assert result.extracted_text == "OCR content"
    assert result.answer == "Answer content"
    assert plugin.last_failure_reason is None


def test_sq04_parse_response_failure_fallback() -> None:
    plugin = _screenshot_qa_plugin()
    text = "Just plain text without tags."
    result = plugin.parse_response(text)
    assert result.extracted_text is None
    assert result.answer == "Just plain text without tags."
    assert plugin.last_failure_reason == "non_stream_regex_failed"


def test_sq05_parse_response_resets_failure_reason_on_success() -> None:
    plugin = _screenshot_qa_plugin()
    plugin.parse_response("no tags")
    assert plugin.last_failure_reason == "non_stream_regex_failed"
    plugin.parse_response("<ocr>A</ocr><answer>B</answer>")
    assert plugin.last_failure_reason is None


@pytest.mark.asyncio
async def test_sq06_wrap_stream_drives_parser() -> None:
    plugin = _screenshot_qa_plugin()
    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>OCR</ocr><answer>Ans</answer>"),
        LLMStreamEvent(type="done", model="m"),
    ]
    out = [ev async for ev in plugin.wrap_stream(_iter_events(events))]
    assert any(e.type == "text_delta" and e.section == "ocr" for e in out)
    assert any(e.type == "extracted_text" and e.text == "OCR" for e in out)
    assert any(e.type == "text_delta" and e.section == "answer" for e in out)
    assert plugin.last_failure_reason is None


@pytest.mark.asyncio
async def test_sq07_wrap_stream_no_tag_fragments() -> None:
    plugin = _screenshot_qa_plugin()
    events = [
        LLMStreamEvent(type="text_delta", delta="<ocr>OCR</ocr><answer>Ans</answer>"),
        LLMStreamEvent(type="done", model="m"),
    ]
    out = [ev async for ev in plugin.wrap_stream(_iter_events(events))]
    combined = "".join(e.delta or "" for e in out if e.type == "text_delta")
    for tag in ("<ocr>", "</ocr>", "<answer>", "</answer>"):
        assert tag not in combined


def test_sq08_translate_mode_aligns_with_translate_plugin() -> None:
    """V1.1.4：requested_plugins 含 translate 时，<answer> 段应被强制为翻译语义，
    与 translate plugin 文本路径保持一致；user 段切到 user_translate.md，
    system 段追加翻译模式覆盖指令。"""
    plugin = _screenshot_qa_plugin()
    ctx = PluginContext(
        selection_type="image",
        user_input=None,
        target_lang="zh-CN",
        requested_plugins=["translate"],
    )
    seg = plugin.build_segments(ctx)
    # user 段使用 user_translate.md：含明确"translate ... into zh-CN"指令，
    # 不能落到 user_default 的"提取并总结"指令
    assert "Translate the source content" in seg.user
    assert "总结" not in seg.user
    # system 段追加 TASK MODE OVERRIDE：禁止总结/解释
    assert "TASK MODE OVERRIDE" in seg.system
    assert "Do NOT summarize" in seg.system


def test_sq09_non_translate_mode_unchanged() -> None:
    plugin = _screenshot_qa_plugin()
    # requested_plugins 不含 translate → 不应注入 OVERRIDE，走原默认 user/with_input
    ctx = PluginContext(
        selection_type="image",
        user_input="问个问题",
        target_lang="zh-CN",
        requested_plugins=["explain"],
    )
    seg = plugin.build_segments(ctx)
    assert "TASK MODE OVERRIDE" not in seg.system
    assert "问个问题" in seg.user
