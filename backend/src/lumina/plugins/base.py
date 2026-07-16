from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lumina.providers.base import ImagePart, LLMMessage, LLMStreamEvent, LLMUsage


class SelectionWordCountRule(BaseModel):
    min: int | None = None
    max: int | None = None


class SelectionTypeRule(BaseModel):
    in_: list[Literal["text", "image"]] = Field(alias="in")

    model_config = ConfigDict(populate_by_name=True)


class ApplicableWhen(BaseModel):
    selection_word_count: SelectionWordCountRule | None = None
    selection_type: SelectionTypeRule | None = None

    model_config = ConfigDict(populate_by_name=True)


class PluginManifest(BaseModel):
    id: str
    label: str
    icon: str
    applicable_to: list[Literal["text", "image"]]
    applicable_when: ApplicableWhen | None = None
    thinking_default: bool = False
    prompt_files: dict[str, str | dict[str, str]]

    model_config = ConfigDict(extra="forbid")


class PluginContext(BaseModel):
    selection_text: str | None = None
    selection_type: Literal["text", "image"] = "image"
    selection_word_count: int = 0
    user_input: str | None = None
    target_lang: str = "zh-CN"
    history: list[LLMMessage] = Field(default_factory=list)
    image: ImagePart | None = None
    # V1.1.4：原始请求中的 plugin chip 列表。image 路径下后端强制激活 screenshot-qa，
    # 但 screenshot-qa 需要感知用户真正点的是哪个 chip（translate / explain / dictionary）
    # 才能让 <answer> 段的任务语义与对应文本路径的 plugin 保持一致。
    requested_plugins: list[str] = Field(default_factory=list)
    # V1.2.1：跨页自动上下文。run 层组装好的完整参考块（含框架文案与页码标注），
    # PluginPipeline.build_request 统一追加到 user 文本末尾；None = 不注入。
    context_pages: str | None = None


class PluginPromptSegments(BaseModel):
    system: str
    user: str


class PluginParseResult(BaseModel):
    answer: str
    extracted_text: str | None = None


class StructuredStreamEvent(BaseModel):
    type: Literal["text_delta", "usage", "done", "error", "extracted_text"]
    section: Literal["ocr", "answer"] | None = None
    delta: str | None = None
    usage: LLMUsage | None = None
    model: str | None = None
    thinking_enabled: bool | None = None
    code: str | None = None
    message: str | None = None
    retriable: bool | None = None
    text: str | None = None

    @classmethod
    def passthrough(cls, ev: LLMStreamEvent) -> StructuredStreamEvent:
        return cls(
            type=ev.type,
            section=None,
            delta=ev.delta,
            usage=ev.usage,
            model=ev.model,
            thinking_enabled=ev.thinking_enabled,
            code=ev.code,
            message=ev.message,
            retriable=ev.retriable,
            text=None,
        )


def evaluate_applicable_when(
    rule: ApplicableWhen | None,
    ctx: PluginContext,
) -> bool:
    if rule is None:
        return True
    if rule.selection_word_count is not None:
        wc = ctx.selection_word_count
        if rule.selection_word_count.min is not None and wc < rule.selection_word_count.min:
            return False
        if rule.selection_word_count.max is not None and wc > rule.selection_word_count.max:
            return False
    if rule.selection_type is not None:
        if ctx.selection_type not in rule.selection_type.in_:
            return False
    return True


def estimate_word_count(text: str | None) -> int:
    if not text:
        return 0
    tokens = re.findall(r"[一-鿿]|[A-Za-z]+|[0-9]+", text)
    return len(tokens)


def ctx_to_template_vars(ctx: PluginContext) -> dict[str, str]:
    return {
        "selection_text": ctx.selection_text or "",
        "selection_type": ctx.selection_type,
        "selection_word_count": str(ctx.selection_word_count),
        "user_input": ctx.user_input or "",
        "target_lang": ctx.target_lang,
    }


class Plugin(ABC):
    manifest: PluginManifest

    def __init__(
        self,
        manifest: PluginManifest,
        prompts: dict[str, str | dict[str, str]],
    ) -> None:
        self.manifest = manifest
        self._prompts = prompts

    def is_applicable(self, ctx: PluginContext) -> bool:
        if ctx.selection_type not in self.manifest.applicable_to:
            return False
        return evaluate_applicable_when(self.manifest.applicable_when, ctx)

    @abstractmethod
    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        """Select template segments and interpolate via string.Template."""

    def parse_response(self, text: str) -> PluginParseResult:
        return PluginParseResult(answer=text, extracted_text=None)

    async def wrap_stream(
        self,
        events: AsyncIterator[LLMStreamEvent],
    ) -> AsyncIterator[StructuredStreamEvent]:
        async for ev in events:
            yield StructuredStreamEvent.passthrough(ev)
