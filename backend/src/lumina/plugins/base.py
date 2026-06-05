from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lumina.providers.base import LLMMessage


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


class PluginPromptSegments(BaseModel):
    system: str
    user: str


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
