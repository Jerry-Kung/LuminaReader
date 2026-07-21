"""V1.2.4 概念回查检索：确定性检索（索引匹配 → 全文降级 → 双落空）。

检索发生在 LLM 调用之前，结果双通道输出：
- ref_block：注入 user 文本末尾供 LLM 综述（复用 V1.2.1 context_pages 尾部注入机制）
- sources：结构化出处，供前端渲染可点击 chips + 持久化

匹配为字面检索（归一化后精确 / 子串），不引入语义 / 向量检索（总纲 §5）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from lumina.db.models import ConceptHitRow, get_pdf_text_pages_range, list_concept_hits


def normalize(text: str) -> str:
    """归一化：trim + casefold（大小写不敏感匹配基础）。"""
    return text.strip().casefold()


@dataclass
class SourceRef:
    kind: Literal["concept", "text"]
    page: int
    term: str | None = None
    unit_title: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict:
        # 剔除 None：concept 命中不含 snippet，text 降级不含 term/unit_title
        d: dict = {"kind": self.kind, "page": self.page}
        if self.term is not None:
            d["term"] = self.term
        if self.unit_title is not None:
            d["unit_title"] = self.unit_title
        if self.snippet is not None:
            d["snippet"] = self.snippet
        return d


@dataclass
class RecallResult:
    ref_block: str | None
    sources: list[SourceRef] = field(default_factory=list)
    is_empty: bool = False


# 匹配层级（数值越小优先级越高）：精确 → 不区分大小写（归一化已统一，二者等价合并）→ 双向子串
_TIER_EXACT = 0
_TIER_SUBSTRING = 1


def _match_tier(norm_sel: str, norm_term: str) -> int | None:
    """返回匹配层级；不匹配返回 None。"""
    if norm_sel == norm_term:
        return _TIER_EXACT
    # 双向子串：术语含选区 或 选区含术语
    if norm_term in norm_sel or norm_sel in norm_term:
        return _TIER_SUBSTRING
    return None


def _match_concepts(conn, pdf_id: str, selection_text: str, max_concepts: int) -> list[ConceptHitRow]:
    """归一化匹配概念索引，返回排序 + 截断后的命中行（携带 definition，供参考块组装）。"""
    norm_sel = normalize(selection_text)
    if not norm_sel:
        return []
    scored: list[tuple[int, int, int, ConceptHitRow]] = []  # (tier, unit_seq, page, row)
    for hit in list_concept_hits(conn, pdf_id):
        tier = _match_tier(norm_sel, normalize(hit.term))
        if tier is None:
            continue
        scored.append((tier, hit.unit_seq, hit.page, hit))
    # 高层级优先、层内按单元 seq + page 排序；截断时优先保留高层级
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [h for _, _, _, h in scored[:max_concepts]]


def _fallback_text(conn, pdf_id: str, selection_text: str, max_text_pages: int, snippet_chars: int) -> list[SourceRef]:
    norm_sel = normalize(selection_text)
    if not norm_sel:
        return []
    # 全书全页扫描：字面 casefold 子串匹配（page 升序取前 N 个命中页）
    rows = get_pdf_text_pages_range(conn, pdf_id, 1, 10_000_000)
    sources: list[SourceRef] = []
    for page, text in rows:
        norm_text = text.casefold()
        idx = norm_text.find(norm_sel)
        if idx == -1:
            continue
        # 以该页首个命中位置为锚，截取前后共 snippet_chars 字符的窗口（每页一个片段）
        half = snippet_chars // 2
        lo = max(0, idx - half)
        hi = min(len(text), idx + len(selection_text) + half)
        snippet = text[lo:hi].strip()
        sources.append(SourceRef(kind="text", page=page, snippet=snippet))
        if len(sources) >= max_text_pages:
            break
    return sources


_CONCEPT_HEADER = (
    "[概念回查参考资料 — 以下条目来自本书的概念索引。请仅依据这些参考资料、"
    "按出处综述用户选中术语的含义，不要引用参考资料之外的内容：]"
)
_TEXT_HEADER = (
    "[概念回查参考资料 — 以下片段来自本书全文检索（而非概念索引），"
    "请仅依据这些片段综述用户选中内容的含义：]"
)


def _build_concept_block(sources: list[SourceRef], max_ref_chars: int, definitions: list[str]) -> str:
    parts = [_CONCEPT_HEADER]
    total = len(_CONCEPT_HEADER)
    for s, definition in zip(sources, definitions):
        unit = f"{s.unit_title} · " if s.unit_title else ""
        entry = f"\n\n[{unit}p.{s.page}] {s.term}：{definition}"
        if total + len(entry) > max_ref_chars:
            break
        parts.append(entry)
        total += len(entry)
    return "".join(parts)


def _build_text_block(sources: list[SourceRef], max_ref_chars: int) -> str:
    parts = [_TEXT_HEADER]
    total = len(_TEXT_HEADER)
    for s in sources:
        entry = f"\n\n[p.{s.page}]\n{s.snippet or ''}"
        if total + len(entry) > max_ref_chars:
            break
        parts.append(entry)
        total += len(entry)
    return "".join(parts)


def build_recall(
    conn,
    pdf_id: str,
    selection_text: str,
    *,
    max_concepts: int,
    max_text_pages: int,
    snippet_chars: int,
    max_ref_chars: int,
) -> RecallResult:
    # 1. 概念索引匹配（主路径）
    concept_hits = _match_concepts(conn, pdf_id, selection_text, max_concepts)
    if concept_hits:
        sources = [
            SourceRef(kind="concept", term=h.term, page=h.page, unit_title=h.unit_title)
            for h in concept_hits
        ]
        # definition 随命中行携带，按序传递到参考块组装（防止同名术语定义串写）
        definitions = [h.definition for h in concept_hits]
        return RecallResult(
            ref_block=_build_concept_block(sources, max_ref_chars, definitions),
            sources=sources,
        )

    # 2. 降级全书文本字面检索
    text_sources = _fallback_text(conn, pdf_id, selection_text, max_text_pages, snippet_chars)
    if text_sources:
        return RecallResult(
            ref_block=_build_text_block(text_sources, max_ref_chars),
            sources=text_sources,
        )

    # 3. 双落空：不注入、不调用 LLM（由链路层短路）
    return RecallResult(ref_block=None, sources=[], is_empty=True)
