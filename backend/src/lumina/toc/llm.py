"""V1.2.2 第 3 层：LLM 兜底识别（手动触发，输入用候选行压缩样本控成本）。

花费预估（规格 D9）：token 估算 + 单价表委托至 lumina/pricing（未命中只报 token 量）。
单价表数值为编写时点参考价，标注"估算"呈现；表更新随版本走（R-V122-4）。
"""

from __future__ import annotations

import json
import re

from lumina.providers.base import LLMMessage, LLMRequest, Provider, TextPart
from lumina.toc.heuristic import CANDIDATE_PATTERNS, MAX_TITLE_CHARS
from lumina.toc.types import TocItem


class TocLlmInvalidError(Exception):
    """模型输出不合法（非 JSON / 页码越界 / 空标题等），不落库，可重试。"""


# 每页取开头 N 个非空行（章节标题多在页首）+ 全页候选模式命中行
_HEAD_LINES_PER_PAGE = 3

_SYSTEM_PROMPT = (
    "You are a table-of-contents extraction assistant. The user gives you "
    "sampled lines from a book, each group prefixed with its page number like "
    "[Page 12]. Identify the chapter/section structure of the book.\n"
    "Reply with ONLY a JSON array, no prose, no markdown fence. Each element: "
    '{"title": string, "page": int (1-based page where the chapter starts), '
    '"level": int (0 = top-level chapter, 1 = sub-section, max 2)}. '
    "Entries must be in reading order (non-decreasing page). If you cannot "
    "identify any structure, reply with []."
)


def build_sample(pages: list[tuple[int, str]], max_chars: int) -> str:
    """每页取头部行 + 候选标题行组成带页码锚点的压缩样本，超预算即停。"""
    parts: list[str] = []
    used = 0
    for page_no, text in pages:
        lines: list[str] = []
        seen: set[str] = set()
        non_empty = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in non_empty[:_HEAD_LINES_PER_PAGE]:
            if ln not in seen:
                seen.add(ln)
                lines.append(ln)
        for ln in non_empty:
            if len(ln) <= MAX_TITLE_CHARS and any(p.match(ln) for p in CANDIDATE_PATTERNS):
                if ln not in seen:
                    seen.add(ln)
                    lines.append(ln)
        if not lines:
            continue
        block = f"[Page {page_no}]\n" + "\n".join(lines) + "\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def estimate_tokens(sample_chars: int) -> int:
    """粗估：中英混排按 2 字符 ≈ 1 token（偏保守）。

    V1.2.3 起委托共享单价表。
    """
    from lumina.pricing import estimate_tokens as _shared

    return _shared(sample_chars)


def estimate_cost_usd(model: str, input_tokens: int) -> float | None:
    """V1.2.2 既有调用面（仅输入价口径）；V1.2.3 起委托 lumina.pricing。"""
    from lumina.pricing import estimate_cost_usd as _shared

    return _shared(model, input_tokens, 0)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def _validate(raw: object, page_count: int) -> list[TocItem]:
    if not isinstance(raw, list) or not (1 <= len(raw) <= 500):
        raise TocLlmInvalidError(f"entry count invalid: {len(raw) if isinstance(raw, list) else 'not a list'}")
    items: list[TocItem] = []
    prev_page = 0
    for entry in raw:
        if not isinstance(entry, dict):
            raise TocLlmInvalidError("entry is not an object")
        title = str(entry.get("title", "")).strip()
        page = entry.get("page")
        level = entry.get("level", 0)
        if not title:
            raise TocLlmInvalidError("empty title")
        if not isinstance(page, int) or not (1 <= page <= page_count):
            raise TocLlmInvalidError(f"page out of range: {page!r}")
        if page < prev_page:
            raise TocLlmInvalidError("pages not in non-decreasing order")
        prev_page = page
        depth = level if isinstance(level, int) and 0 <= level <= 2 else 0
        items.append(TocItem(title=title[:200], page=page, depth=depth))
    return items


async def recognize_with_llm(
    provider: Provider,
    pages: list[tuple[int, str]],
    page_count: int,
    max_chars: int = 60000,
) -> list[TocItem]:
    """一次性调用；ProviderError 原样上抛（上层映射 502），校验失败抛 TocLlmInvalidError（422）。"""
    sample = build_sample(pages, max_chars)
    req = LLMRequest(
        messages=[
            LLMMessage(role="system", content=[TextPart(text=_SYSTEM_PROMPT)]),
            LLMMessage(
                role="user",
                content=[TextPart(text=f"The book has {page_count} pages.\n\n{sample}")],
            ),
        ],
        temperature=0.0,
    )
    resp = await provider.invoke(req)
    try:
        raw = json.loads(_strip_code_fence(resp.text))
    except json.JSONDecodeError as exc:
        raise TocLlmInvalidError(f"not valid JSON: {exc}") from exc
    return _validate(raw, page_count)
