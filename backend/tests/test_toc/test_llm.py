"""V1.2.2 第 3 层：LLM 识别（样本压缩 / 输出校验 / 花费预估）。"""

import json

import pytest

from lumina.providers.base import LLMRequest, LLMResponse, Provider
from lumina.toc.llm import (
    TocLlmInvalidError,
    build_sample,
    estimate_cost_usd,
    estimate_tokens,
    recognize_with_llm,
)


class CannedProvider(Provider):
    name = "canned"

    def __init__(self, text: str) -> None:
        self.text = text
        self.last_request: LLMRequest | None = None

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        self.last_request = req
        return LLMResponse(text=self.text, model="fake-model")

    async def invoke_stream(self, req: LLMRequest):
        raise NotImplementedError
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        return True


def test_build_sample_keeps_page_anchors_and_candidates():
    pages = [
        (1, "第一章 引言\nsome body\nmore body\nextra line 4\nextra line 5"),
        (2, "plain body only\nsecond line\nthird line\nfourth line"),
    ]
    sample = build_sample(pages, max_chars=10_000)
    assert "[Page 1]" in sample and "[Page 2]" in sample
    assert "第一章 引言" in sample
    assert "extra line 5" not in sample  # 每页仅取头部行 + 候选行


def test_build_sample_respects_max_chars():
    pages = [(p, "第一章 引言\n" + "x" * 200) for p in range(1, 200)]
    sample = build_sample(pages, max_chars=500)
    assert len(sample) <= 500


def test_estimates():
    assert estimate_tokens(1000) == 500
    assert estimate_cost_usd("gpt-4o-mini-2024", 1_000_000) == pytest.approx(0.15)
    assert estimate_cost_usd("totally-unknown-model", 1000) is None


@pytest.mark.asyncio
async def test_recognize_parses_valid_json():
    payload = json.dumps([
        {"title": "第一章", "page": 1, "level": 0},
        {"title": "1.1 背景", "page": 2, "level": 1},
        {"title": "第二章", "page": 9, "level": 0},
    ])
    provider = CannedProvider(f"```json\n{payload}\n```")  # 容忍 code fence
    items = await recognize_with_llm(provider, [(1, "第一章")], page_count=20)
    assert [(i.title, i.page, i.depth) for i in items] == [
        ("第一章", 1, 0), ("1.1 背景", 2, 1), ("第二章", 9, 0),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        "[]",  # 空列表
        json.dumps([{"title": "x", "page": 999, "level": 0}]),  # 页码越界
        json.dumps([{"title": "a", "page": 5, "level": 0}, {"title": "b", "page": 3, "level": 0}]),  # 页码降序
        json.dumps([{"title": "", "page": 1, "level": 0}]),  # 空标题
    ],
)
async def test_recognize_rejects_invalid_output(bad):
    provider = CannedProvider(bad)
    with pytest.raises(TocLlmInvalidError):
        await recognize_with_llm(provider, [(1, "第一章")], page_count=20)
