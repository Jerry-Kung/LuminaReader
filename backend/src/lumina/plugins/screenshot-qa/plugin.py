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
    def __init__(
        self,
        manifest,
        prompts: dict[str, str | dict[str, str]],
    ) -> None:
        super().__init__(manifest, prompts)
        self.last_failure_reason: str | None = None

    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        system_tmpl = self._prompts["system"]
        if ctx.user_input:
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
