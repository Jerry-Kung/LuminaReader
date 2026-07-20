"""V1.2.3 共享单价表：输入/输出分价 + toc.llm 兼容委托。"""

from lumina import pricing
from lumina.toc import llm as toc_llm


def test_estimate_tokens():
    assert pricing.estimate_tokens(0) == 1
    assert pricing.estimate_tokens(100) == 50


def test_cost_with_output_price():
    # gpt-4o-mini: input 0.15 / output 0.6 USD per 1M tokens
    cost = pricing.estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost is not None and abs(cost - 0.75) < 1e-9


def test_longest_key_wins():
    # "gpt-4o-mini" 必须命中 mini 价而非 "gpt-4o"
    a = pricing.estimate_cost_usd("gpt-4o-mini-2024", 1_000_000)
    b = pricing.estimate_cost_usd("gpt-4o-2024", 1_000_000)
    assert a is not None and b is not None and a < b


def test_unknown_model_none():
    assert pricing.estimate_cost_usd("some-unknown-model", 1000) is None


def test_toc_llm_delegates():
    # V1.2.2 既有调用面不变：单参输入价口径
    assert toc_llm.estimate_tokens(100) == pricing.estimate_tokens(100)
    assert toc_llm.estimate_cost_usd("qwen-turbo", 1_000_000) == pricing.estimate_cost_usd(
        "qwen-turbo", 1_000_000, 0
    )
