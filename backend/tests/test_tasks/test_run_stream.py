from unittest.mock import MagicMock

import pytest

from lumina.providers.base import LLMRequest, ProviderConfigError, TextPart, LLMMessage


@pytest.mark.asyncio
async def test_openai_compat_invoke_stream_requires_stream_flag() -> None:
    from lumina.providers.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        timeout_seconds=60,
        client=MagicMock(),
    )
    req = LLMRequest(
        messages=[LLMMessage(role="user", content=[TextPart(text="hi")])],
        stream=False,
    )
    with pytest.raises(ProviderConfigError, match="req.stream=False"):
        async for _ in provider.invoke_stream(req):
            pass
