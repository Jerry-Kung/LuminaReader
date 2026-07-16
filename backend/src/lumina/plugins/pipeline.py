from __future__ import annotations

from collections.abc import AsyncIterator
from string import Template

from lumina.plugins.base import PluginContext, PluginPromptSegments
from lumina.plugins.registry import PluginRegistry
from lumina.providers.base import (
    ImagePart,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    Provider,
    TextPart,
)


class PluginPipeline:
    CHAT_SYSTEM_PROMPT_TEMPLATE = (
        "You are LuminaReader's AI reading assistant. The user is reading a PDF and may "
        "ask questions about the content, request explanations, or seek clarifications. "
        "Respond in ${target_lang}. Be accurate, concise, and helpful. "
        "Any selected text or extracted screenshot content provided as [Selected content for context] "
        "is background reference only — it is NOT a topical constraint. The user is free to ask anything: "
        "follow-ups grounded in the selected content, broader background questions, or topics entirely "
        "unrelated to it. You MUST answer to the best of your knowledge in every case. NEVER refuse on "
        "the grounds that the question is off-topic, not covered by the selected content, or otherwise "
        "unrelated. If the selected content does not contain information needed to answer, simply answer "
        "from your own knowledge without prefacing the answer with disclaimers about scope."
    )

    def __init__(
        self,
        registry: PluginRegistry,
        provider: Provider,
        settings_thinking_enabled: bool,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._settings_thinking_enabled = settings_thinking_enabled

    def decide_thinking(self, plugin_ids: list[str]) -> bool:
        return self._decide_thinking(plugin_ids)

    def build_request(
        self,
        plugin_ids: list[str],
        ctx: PluginContext,
    ) -> LLMRequest:
        if not plugin_ids:
            system_text = Template(self.CHAT_SYSTEM_PROMPT_TEMPLATE).safe_substitute(
                target_lang=ctx.target_lang
            )
            user_text = _build_chat_user_text(ctx)
        else:
            plugins = [self._registry.get(pid) for pid in plugin_ids]
            segments = [p.build_segments(ctx) for p in plugins]
            system_text = "\n\n".join(s.system for s in segments)
            user_text = _join_user_segments(segments)

        # V1.2.1：跨页自动上下文统一追加（run 层已组装好完整参考块）
        if ctx.context_pages:
            user_text = f"{user_text}\n\n{ctx.context_pages}"

        thinking = self._decide_thinking(plugin_ids)
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=[TextPart(text=system_text)])
        ]
        if ctx.history:
            messages.extend(ctx.history)
        user_content: list[TextPart | ImagePart] = [TextPart(text=user_text)]
        if ctx.image is not None:
            user_content.append(ctx.image)
        messages.append(LLMMessage(role="user", content=user_content))

        return LLMRequest(messages=messages, thinking=thinking)

    async def run(
        self,
        plugin_ids: list[str],
        ctx: PluginContext,
    ) -> LLMResponse:
        req = self.build_request(plugin_ids, ctx)
        return await self._provider.invoke(req)

    async def run_stream(
        self,
        plugin_ids: list[str],
        ctx: PluginContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        req = self.build_request(plugin_ids, ctx)
        req = req.model_copy(update={"stream": True})
        async for event in self._provider.invoke_stream(req):
            yield event

    def _decide_thinking(self, plugin_ids: list[str]) -> bool:
        if not self._settings_thinking_enabled:
            return False
        if not plugin_ids:
            return True
        return any(
            self._registry.get(pid).manifest.thinking_default for pid in plugin_ids
        )


def _build_chat_user_text(ctx: PluginContext) -> str:
    parts: list[str] = []
    if ctx.user_input:
        parts.append(ctx.user_input)
    if ctx.selection_text:
        parts.append(f"\n\n[Selected content for context]:\n{ctx.selection_text}")
    return "".join(parts)


def _join_user_segments(segments: list[PluginPromptSegments]) -> str:
    return "\n\n---\n\n".join(s.user for s in segments)
