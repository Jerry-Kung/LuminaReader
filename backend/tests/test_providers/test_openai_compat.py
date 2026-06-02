from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from lumina.config import Settings
from lumina.providers import build_provider_from_config
from lumina.providers.base import (
    ImagePart,
    LLMMessage,
    LLMRequest,
    LLMUsage,
    ProviderAuthError,
    ProviderTimeout,
    ProviderUpstreamError,
    TextPart,
)
from lumina.providers.openai_compat import OpenAICompatProvider


def _make_provider(
    *,
    return_raw: bool = False,
    create_mock: AsyncMock | None = None,
) -> OpenAICompatProvider:
    client = MagicMock()
    client.chat.completions.create = create_mock or AsyncMock()
    return OpenAICompatProvider(
        api_key="sk-test-not-real",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        timeout_seconds=60,
        return_raw=return_raw,
        client=client,
    )


def _sample_request(*, temperature: float | None = 0.2, max_tokens: int | None = None) -> LLMRequest:
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content=[TextPart(text="You are a translator.")]),
            LLMMessage(
                role="user",
                content=[
                    TextPart(text="Translate this image."),
                    ImagePart(mime="image/png", data_b64="abc123"),
                ],
            ),
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _mock_completion(*, content: str = "translated", with_usage: bool = True, model: str = "gpt-4o"):
    usage = None
    if with_usage:
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    response.model = model
    response.usage = usage
    response.model_dump.return_value = {"id": "chatcmpl-test", "model": model}
    return response


@pytest.mark.asyncio
async def test_invoke_maps_messages_and_model() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)

    await provider.invoke(_sample_request())

    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == [{"type": "text", "text": "You are a translator."}]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0] == {"type": "text", "text": "Translate this image."}
    assert messages[1]["content"][1]["type"] == "image_url"
    assert messages[1]["content"][1]["image_url"]["url"] == "data:image/png;base64,abc123"


@pytest.mark.asyncio
async def test_invoke_passes_temperature_and_max_tokens_when_set() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)

    await provider.invoke(_sample_request(temperature=0.5, max_tokens=128))
    kwargs = create.await_args.kwargs
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 128


@pytest.mark.asyncio
async def test_invoke_omits_optional_params_when_none() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)

    await provider.invoke(_sample_request(temperature=None, max_tokens=None))
    kwargs = create.await_args.kwargs
    assert "temperature" not in kwargs
    assert "max_tokens" not in kwargs


@pytest.mark.asyncio
async def test_invoke_parses_response_text_and_usage() -> None:
    create = AsyncMock(return_value=_mock_completion(content="hello", with_usage=True))
    provider = _make_provider(create_mock=create)

    result = await provider.invoke(_sample_request())

    assert result.text == "hello"
    assert result.model == "gpt-4o"
    assert result.usage == LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert result.raw is None


@pytest.mark.asyncio
async def test_invoke_parses_response_without_usage() -> None:
    create = AsyncMock(return_value=_mock_completion(with_usage=False))
    provider = _make_provider(create_mock=create)

    result = await provider.invoke(_sample_request())
    assert result.usage is None


@pytest.mark.asyncio
async def test_invoke_fills_raw_when_return_raw_enabled() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create, return_raw=True)

    result = await provider.invoke(_sample_request())
    assert result.raw == {"id": "chatcmpl-test", "model": "gpt-4o"}


@pytest.mark.asyncio
async def test_invoke_maps_auth_error() -> None:
    create = AsyncMock(side_effect=openai.AuthenticationError("auth failed", response=MagicMock(), body=None))
    provider = _make_provider(create_mock=create)

    with pytest.raises(ProviderAuthError, match="authentication failed"):
        await provider.invoke(_sample_request())
    assert "sk-test" not in str(create.await_args)


@pytest.mark.asyncio
async def test_invoke_maps_permission_denied_to_auth_error() -> None:
    create = AsyncMock(
        side_effect=openai.PermissionDeniedError("denied", response=MagicMock(), body=None)
    )
    provider = _make_provider(create_mock=create)

    with pytest.raises(ProviderAuthError):
        await provider.invoke(_sample_request())


@pytest.mark.asyncio
async def test_invoke_maps_timeout_error() -> None:
    create = AsyncMock(side_effect=openai.APITimeoutError("timeout"))
    provider = _make_provider(create_mock=create)

    with pytest.raises(ProviderTimeout, match="timed out"):
        await provider.invoke(_sample_request())


@pytest.mark.asyncio
async def test_invoke_maps_upstream_status_error() -> None:
    response = MagicMock(status_code=502)
    create = AsyncMock(side_effect=openai.APIStatusError("upstream", response=response, body=None))
    provider = _make_provider(create_mock=create)

    with pytest.raises(ProviderUpstreamError, match="request failed") as exc_info:
        await provider.invoke(_sample_request())
    assert "https://api.openai.com" not in exc_info.value.message
    assert "sk-test" not in exc_info.value.message


@pytest.mark.asyncio
async def test_invoke_maps_status_401_to_auth_error() -> None:
    response = MagicMock(status_code=401)
    create = AsyncMock(side_effect=openai.APIStatusError("unauthorized", response=response, body=None))
    provider = _make_provider(create_mock=create)

    with pytest.raises(ProviderAuthError):
        await provider.invoke(_sample_request())


@pytest.mark.asyncio
async def test_health_check_true_without_calling_create() -> None:
    create = AsyncMock()
    provider = _make_provider(create_mock=create)

    ready = await provider.health_check()

    assert ready is True
    create.assert_not_called()


@pytest.mark.asyncio
async def test_health_check_false_when_key_empty() -> None:
    create = AsyncMock()
    provider = OpenAICompatProvider(
        api_key="",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        timeout_seconds=60,
        client=MagicMock(chat=MagicMock(completions=MagicMock(create=create))),
    )

    ready = await provider.health_check()

    assert ready is False
    create.assert_not_called()


@pytest.mark.asyncio
async def test_invoke_uses_default_model_when_no_override() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)
    await provider.invoke(_sample_request())
    assert create.await_args.kwargs["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_invoke_uses_override_when_present() -> None:
    create = AsyncMock(return_value=_mock_completion(model="gpt-4o-mini"))
    provider = _make_provider(create_mock=create)
    req = _sample_request()
    req.extras = {"model_override": "gpt-4o-mini"}
    result = await provider.invoke(req)
    assert create.await_args.kwargs["model"] == "gpt-4o-mini"
    assert result.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_invoke_ignores_empty_override() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)
    req = _sample_request()
    req.extras = {"model_override": ""}
    result = await provider.invoke(req)
    assert create.await_args.kwargs["model"] == "gpt-4o"
    assert result.model == "gpt-4o"


@pytest.mark.asyncio
async def test_invoke_ignores_none_extras() -> None:
    create = AsyncMock(return_value=_mock_completion())
    provider = _make_provider(create_mock=create)
    req = _sample_request()
    req.extras = None  # type: ignore[assignment]
    result = await provider.invoke(req)
    assert create.await_args.kwargs["model"] == "gpt-4o"
    assert result.model == "gpt-4o"


def test_build_provider_from_config() -> None:
    cfg = Settings(
        openai_api_key="sk-test-not-real",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        llm_timeout_seconds=30,
        llm_return_raw=True,
    )

    provider = build_provider_from_config(cfg)

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.model == "gpt-4o-mini"
    assert provider.api_key == "sk-test-not-real"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.return_raw is True
