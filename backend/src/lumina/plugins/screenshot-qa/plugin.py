from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from string import Template

from lumina.plugins.base import (
    Plugin,
    PluginContext,
    PluginParseResult,
    PluginPromptSegments,
    StructuredStreamEvent,
    ctx_to_template_vars,
)
from lumina.providers.base import LLMStreamEvent


def _load_parser_module():
    parser_path = Path(__file__).resolve().parent / "parser.py"
    module_name = "lumina.plugins._dynamic_screenshot-qa._parser"
    spec = importlib.util.spec_from_file_location(module_name, parser_path)
    if spec is None or spec.loader is None:
        raise ImportError("Failed to load screenshot-qa parser module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_parser = _load_parser_module()
StreamingTagParser = _parser.StreamingTagParser
parse_full_response = _parser.parse_full_response


class ScreenshotQaPlugin(Plugin):
    # 与 translate plugin 的 system.md 对齐的核心指令，确保截图翻译与文字翻译两条路径
    # 走到 LLM 的"翻译"语义一致（直译，无解释，无总结）。
    _TRANSLATE_SYSTEM_OVERRIDE = (
        "\n\n"
        "TASK MODE OVERRIDE — TRANSLATION:\n"
        "The user has selected the translation capability. Treat the screenshot strictly as a source-text container.\n"
        "Inside <ocr>: extract ONLY the text visible in the screenshot image. If the user message contains a\n"
        "[Reference context ...] block (full text of surrounding book pages), that block is background reference\n"
        "only — do NOT copy it into <ocr>.\n"
        "Inside <answer>: produce a high-quality direct translation of the text extracted in <ocr> into ${target_lang}.\n"
        "Translate ONLY the <ocr> content; never translate the [Reference context ...] block or any surrounding pages.\n"
        "Translate naturally in the target language, use context when available, avoid word-for-word literalism,\n"
        "and preserve technical terms and proper nouns appropriately.\n"
        "Output ONLY the translated text inside <answer> — no summaries, no explanations, no commentary,\n"
        "no preface, no meta remarks about the screenshot. Do NOT summarize, paraphrase, or interpret.\n"
        "If the user provided extra instruction in their input, treat it as a translation style hint only,\n"
        "never as a request to switch to summarization or Q&A.\n"
    )

    def __init__(
        self,
        manifest,
        prompts: dict[str, str | dict[str, str]],
    ) -> None:
        super().__init__(manifest, prompts)
        self.last_failure_reason: str | None = None

    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        system_tmpl = self._prompts["system"]
        is_translate = "translate" in (ctx.requested_plugins or [])
        if is_translate:
            user_tmpl = self._prompts["user"].get(
                "translate", self._prompts["user"]["with_input"]
            )
            system_tmpl = system_tmpl + self._TRANSLATE_SYSTEM_OVERRIDE
        elif ctx.user_input:
            user_tmpl = self._prompts["user"]["with_input"]
        else:
            user_tmpl = self._prompts["user"]["default"]
        vars_ = ctx_to_template_vars(ctx)
        return PluginPromptSegments(
            system=Template(system_tmpl).safe_substitute(vars_),
            user=Template(user_tmpl).safe_substitute(vars_),
        )

    def parse_response(self, text: str) -> PluginParseResult:
        result, failure_reason = parse_full_response(text)
        self.last_failure_reason = failure_reason
        return result

    async def wrap_stream(
        self,
        events: AsyncIterator[LLMStreamEvent],
    ) -> AsyncIterator[StructuredStreamEvent]:
        parser = StreamingTagParser()
        async for ev in parser.feed_stream(events):
            yield ev
        self.last_failure_reason = parser.failure_reason


PLUGIN_CLASS = ScreenshotQaPlugin
