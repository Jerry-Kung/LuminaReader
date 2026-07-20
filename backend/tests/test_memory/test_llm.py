"""V1.2.3 单元加工 LLM 调用：JSON 校验（围栏容忍 / 越界 clamp / 坏条目跳过）。"""

import json

import pytest

from lumina.memory.llm import (
    ConceptDraft,
    MemoryLlmInvalidError,
    parse_unit_response,
    summarize_book,
    summarize_unit,
)
from lumina.providers.base import LLMRequest, LLMResponse, Provider


class CannedProvider(Provider):
    name = "canned"

    def __init__(self, text: str) -> None:
        self.text = text
        self.last_request: LLMRequest | None = None

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.last_request = req
        return LLMResponse(text=self.text, model="fake-model")

    async def invoke_stream(self, req):
        raise NotImplementedError
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        return True


def _payload(**kw):
    base = {
        "summary": "## 要点\n- a",
        "concepts": [{"term": "t", "definition": "d", "page": 3}],
    }
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def test_parse_ok():
    summary, concepts = parse_unit_response(_payload(), 1, 5)
    assert summary.startswith("## 要点")
    assert concepts == [ConceptDraft(term="t", definition="d", page=3)]


def test_parse_tolerates_code_fence():
    text = f"```json\n{_payload()}\n```"
    summary, _ = parse_unit_response(text, 1, 5)
    assert summary.startswith("## 要点")


def test_page_out_of_range_clamped():
    _, concepts = parse_unit_response(
        _payload(concepts=[{"term": "t", "definition": "d", "page": 99}]), 2, 5
    )
    assert concepts[0].page == 5
    _, concepts = parse_unit_response(
        _payload(concepts=[{"term": "t", "definition": "d", "page": 1}]), 2, 5
    )
    assert concepts[0].page == 2


def test_bad_concept_entries_skipped():
    _, concepts = parse_unit_response(
        _payload(concepts=[
            {"term": "", "definition": "d", "page": 3},        # 空 term → 跳过
            {"term": "t", "definition": "", "page": 3},        # 空 definition → 跳过
            {"term": "t", "definition": "d", "page": "x"},     # 非整数 page → 跳过
            "not-an-object",                                     # 非对象 → 跳过
            {"term": "ok", "definition": "fine", "page": 4},
        ]),
        1, 5,
    )
    assert concepts == [ConceptDraft(term="ok", definition="fine", page=4)]


def test_concepts_capped_at_50():
    many = [{"term": f"t{i}", "definition": "d", "page": 1} for i in range(80)]
    _, concepts = parse_unit_response(_payload(concepts=many), 1, 5)
    assert len(concepts) == 50


def test_empty_summary_invalid():
    with pytest.raises(MemoryLlmInvalidError):
        parse_unit_response(_payload(summary="  "), 1, 5)


def test_not_json_invalid():
    with pytest.raises(MemoryLlmInvalidError):
        parse_unit_response("plain prose", 1, 5)


def test_concepts_not_list_invalid():
    with pytest.raises(MemoryLlmInvalidError):
        parse_unit_response(_payload(concepts="oops"), 1, 5)


@pytest.mark.asyncio
async def test_summarize_unit_request_shape():
    provider = CannedProvider(_payload())
    summary, concepts = await summarize_unit(
        provider, model_override="cheap-model", title="C1",
        pages=[(3, "page three text"), (4, "page four text")],
        start_page=3, end_page=4,
    )
    assert summary and len(concepts) == 1
    req = provider.last_request
    assert req is not None and req.stream is False and req.thinking is False
    assert req.temperature == 0.2
    assert req.extras.get("model_override") == "cheap-model"
    user_text = req.messages[1].content[0].text
    assert "[Page 3]" in user_text and "[Page 4]" in user_text and "C1" in user_text


@pytest.mark.asyncio
async def test_summarize_unit_no_override():
    provider = CannedProvider(_payload())
    await summarize_unit(
        provider, model_override=None, title="C1",
        pages=[(1, "x")], start_page=1, end_page=1,
    )
    assert "model_override" not in provider.last_request.extras


@pytest.mark.asyncio
async def test_summarize_book_ok_and_empty():
    provider = CannedProvider("# 全书总结\n...")
    text = await summarize_book(
        provider, model_override=None, items=[("C1", "s1"), ("C2", "s2")]
    )
    assert text.startswith("# 全书总结")
    user_text = provider.last_request.messages[1].content[0].text
    assert "C1" in user_text and "s2" in user_text

    with pytest.raises(MemoryLlmInvalidError):
        await summarize_book(CannedProvider("   "), model_override=None, items=[("C1", "s1")])
