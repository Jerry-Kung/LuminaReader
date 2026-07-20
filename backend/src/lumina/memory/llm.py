"""V1.2.3 记忆加工 LLM 调用：单元摘要 + 概念（结构化 JSON）与全书总结（规格 F3）。

Prompt 为模块常量（后台管线不属于插件体系，同 V1.2.2 toc LLM 先例）；
校验宽松取向：page 越界 clamp、坏概念条目跳过，仅 summary 缺失 / 非 JSON 判失败。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from lumina.providers.base import LLMMessage, LLMRequest, Provider, TextPart

MAX_CONCEPTS_PER_UNIT = 50


class MemoryLlmInvalidError(Exception):
    """模型输出不合法（非 JSON / summary 缺失等），该单元置 failed，可重试。"""


@dataclass(frozen=True)
class ConceptDraft:
    term: str
    definition: str
    page: int


_UNIT_SYSTEM_PROMPT = (
    "You are a reading-memory assistant inside a PDF reader app. The user gives "
    "you the full text of one chapter (or page range) of a book they are reading. "
    "Each page is prefixed with its page number like [Page 12].\n"
    "Reply with ONLY a JSON object, no prose, no markdown fence:\n"
    '{"summary": string, "concepts": [{"term": string, "definition": string, "page": int}]}\n'
    "- summary: the chapter's key points as Markdown in Simplified Chinese "
    "(short bullet lists, optionally brief sub-headings; roughly 150-400 Chinese "
    "characters; focus on what a reader would want to recall later).\n"
    "- concepts: up to 20 important terms or concepts that this chapter INTRODUCES "
    "or EXPLAINS. definition: 1-2 sentences in Simplified Chinese. page: the page "
    "number where the term is explained, using the [Page N] anchors.\n"
    'If the text is empty or meaningless, return {"summary": "（本章无有效文本）", '
    '"concepts": []}.'
)

_BOOK_SYSTEM_PROMPT = (
    "You are a reading-memory assistant. The user gives you the per-chapter "
    "key-point summaries of one book they just read. Write a book-level recap in "
    "Simplified Chinese, as Markdown, answering: what did I learn from this book? "
    "Cover the main themes, how the chapters connect, and the most important "
    "takeaways. Roughly 300-600 Chinese characters. Reply with the Markdown text "
    "only — no JSON, no code fence."
)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def parse_unit_response(
    text: str, start_page: int, end_page: int
) -> tuple[str, list[ConceptDraft]]:
    try:
        raw = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        raise MemoryLlmInvalidError(f"not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise MemoryLlmInvalidError("top-level is not an object")
    summary = str(raw.get("summary", "")).strip()
    if not summary:
        raise MemoryLlmInvalidError("empty summary")
    concepts_raw = raw.get("concepts", [])
    if not isinstance(concepts_raw, list):
        raise MemoryLlmInvalidError("concepts is not a list")
    concepts: list[ConceptDraft] = []
    for entry in concepts_raw:
        if len(concepts) >= MAX_CONCEPTS_PER_UNIT:
            break
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term", "")).strip()
        definition = str(entry.get("definition", "")).strip()
        page = entry.get("page")
        # 宽松校验：坏条目跳过不整体拒绝（规格 F3）；越界 clamp 到单元页范围
        if not term or not definition or isinstance(page, bool) or not isinstance(page, int):
            continue
        concepts.append(
            ConceptDraft(
                term=term[:200],
                definition=definition[:2000],
                page=min(max(page, start_page), end_page),
            )
        )
    return summary, concepts


def _build_request(system: str, user: str, model_override: str | None) -> LLMRequest:
    extras: dict = {}
    if model_override:
        extras["model_override"] = model_override
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content=[TextPart(text=system)]),
            LLMMessage(role="user", content=[TextPart(text=user)]),
        ],
        temperature=0.2,
        extras=extras,
    )


async def summarize_unit(
    provider: Provider,
    *,
    model_override: str | None,
    title: str,
    pages: list[tuple[int, str]],
    start_page: int,
    end_page: int,
) -> tuple[str, list[ConceptDraft]]:
    body = "\n".join(f"[Page {page_no}]\n{text}" for page_no, text in pages)
    user = f'Chapter title: "{title}"\n\n{body}'
    resp = await provider.invoke(_build_request(_UNIT_SYSTEM_PROMPT, user, model_override))
    return parse_unit_response(resp.text, start_page, end_page)


async def summarize_book(
    provider: Provider,
    *,
    model_override: str | None,
    items: list[tuple[str, str]],
) -> str:
    body = "\n\n".join(f"## {title}\n{summary}" for title, summary in items)
    resp = await provider.invoke(_build_request(_BOOK_SYSTEM_PROMPT, body, model_override))
    text = resp.text.strip()
    if not text:
        raise MemoryLlmInvalidError("empty book summary")
    return text
