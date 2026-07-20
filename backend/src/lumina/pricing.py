"""内置常见模型单价表（V1.2.2 引入输入价，V1.2.3 扩展输出价并提为共享模块）。

数值为编写时点参考价（USD / 1M tokens），标注"估算"呈现；表更新随版本走（R-V122-4）。
"""

from __future__ import annotations

import math

# model 子串 → (input, output) USD / 1M tokens；子串匹配，长 key 优先
PRICE_TABLE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4o": (2.5, 10.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1": (2.0, 8.0),
    "deepseek-chat": (0.27, 1.1),
    "deepseek-reasoner": (0.55, 2.19),
    "qwen-turbo": (0.05, 0.2),
    "qwen-plus": (0.11, 0.28),
    "qwen-max": (0.34, 1.36),
    "glm-4-flash": (0.0, 0.0),
    "claude-haiku": (1.0, 5.0),
    "claude-sonnet": (3.0, 15.0),
}


def estimate_tokens(chars: int) -> int:
    """粗估：中英混排按 2 字符 ≈ 1 token（偏保守，与 V1.2.2 同口径）。"""
    return max(1, math.ceil(chars / 2))


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float | None:
    lowered = model.lower()
    for key in sorted(PRICE_TABLE_USD_PER_MTOK, key=len, reverse=True):
        if key in lowered:
            price_in, price_out = PRICE_TABLE_USD_PER_MTOK[key]
            return (
                input_tokens / 1_000_000 * price_in
                + output_tokens / 1_000_000 * price_out
            )
    return None
