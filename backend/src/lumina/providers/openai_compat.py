import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import openai
from openai import AsyncOpenAI

from lumina.providers.base import (
    ImagePart,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderTimeout,
    ProviderUpstreamError,
    TextPart,
)

logger = logging.getLogger("lumina.providers.openai_compat")

OPENAI_AUTH_ERRORS = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
)
OPENAI_TIMEOUT_ERRORS = (openai.APITimeoutError,)
OPENAI_UPSTREAM_ERRORS = (openai.APIStatusError, openai.APIError)


def _is_qwen_base_url(base_url: str) -> bool:
    low = base_url.lower()
    return "dashscope" in low or "aliyuncs" in low


def _base_url_host(base_url: str) -> str:
    parsed = urlparse(base_url.strip())
    return parsed.netloc or base_url


def _is_retriable_upstream(exc: Exception) -> bool:
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 429:
            return True
        if exc.status_code is not None and exc.status_code >= 500:
            return True
        return False
    return False


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        return_raw: bool = False,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.return_raw = return_raw
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            _enforce_credentials=False,
        )

    def _build_sdk_kwargs(
        self, req: LLMRequest, *, stream: bool
    ) -> tuple[dict[str, Any], bool, str]:
        override = None
        if req.extras:
            override = req.extras.get("model_override")
        effective_model = override if override else self.model

        kwargs: dict[str, Any] = {
            "model": effective_model,
            "messages": _to_openai_messages(req.messages),
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.max_tokens is not None:
            kwargs["max_tokens"] = req.max_tokens

        thinking_active = False
        if req.thinking:
            if _is_qwen_base_url(self.base_url):
                extra_body = dict(kwargs.get("extra_body") or {})
                extra_body["enable_thinking"] = True
                kwargs["extra_body"] = extra_body
                thinking_active = True
            else:
                logger.info(
                    "thinking_not_supported_by_base_url",
                    extra={
                        "base_url_host": _base_url_host(self.base_url),
                        "fallback": True,
                    },
                )

        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}

        return kwargs, thinking_active, effective_model

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        if req.stream:
            raise ProviderConfigError(
                "invoke() called with req.stream=True; use invoke_stream()"
            )

        kwargs, thinking_active, effective_model = self._build_sdk_kwargs(
            req, stream=False
        )

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderTimeout("Upstream LLM request timed out.") from exc
        except OPENAI_AUTH_ERRORS as exc:
            raise ProviderAuthError("Upstream LLM authentication failed.") from exc
        except openai.APIStatusError as exc:
            if exc.status_code in (401, 403):
                raise ProviderAuthError("Upstream LLM authentication failed.") from exc
            raise ProviderUpstreamError("Upstream LLM request failed.") from exc
        except openai.APIError as exc:
            raise ProviderUpstreamError("Upstream LLM request failed.") from exc

        text = response.choices[0].message.content or ""
        usage = None
        if response.usage is not None:
            usage = LLMUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        raw = response.model_dump() if self.return_raw else None
        return LLMResponse(
            text=text,
            model=effective_model,
            usage=usage,
            raw=raw,
            thinking_enabled=thinking_active,
        )

    async def invoke_stream(
        self, req: LLMRequest
    ) -> AsyncIterator[LLMStreamEvent]:
        if not req.stream:
            raise ProviderConfigError(
                "invoke_stream() called with req.stream=False; use invoke()"
            )

        kwargs, thinking_active, effective_model = self._build_sdk_kwargs(
            req, stream=True
        )

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta is not None and delta.content:
                        yield LLMStreamEvent(type="text_delta", delta=delta.content)

                usage_obj = getattr(chunk, "usage", None)
                if usage_obj is not None:
                    usage = LLMUsage(
                        prompt_tokens=usage_obj.prompt_tokens,
                        completion_tokens=usage_obj.completion_tokens,
                        total_tokens=usage_obj.total_tokens,
                    )
                    yield LLMStreamEvent(type="usage", usage=usage)

            yield LLMStreamEvent(
                type="done",
                model=effective_model,
                thinking_enabled=thinking_active,
            )

        except asyncio.CancelledError:
            raise

        except OPENAI_AUTH_ERRORS as exc:
            yield LLMStreamEvent(
                type="error",
                code="PROVIDER_ERROR",
                message=str(exc)[:200],
                retriable=False,
            )

        except OPENAI_TIMEOUT_ERRORS:
            yield LLMStreamEvent(
                type="error",
                code="PROVIDER_TIMEOUT",
                message="upstream timeout",
                retriable=True,
            )

        except OPENAI_UPSTREAM_ERRORS as exc:
            yield LLMStreamEvent(
                type="error",
                code="PROVIDER_ERROR",
                message=str(exc)[:200],
                retriable=_is_retriable_upstream(exc),
            )

        except (ConnectionError, OSError) as exc:
            yield LLMStreamEvent(
                type="error",
                code="STREAM_INTERRUPTED",
                message=f"connection lost: {type(exc).__name__}",
                retriable=True,
            )

        except Exception as exc:
            yield LLMStreamEvent(
                type="error",
                code="STREAM_INTERRUPTED",
                message=f"unexpected: {type(exc).__name__}",
                retriable=False,
            )

    async def health_check(self) -> bool:
        if not self.api_key.strip():
            return False
        parsed = urlparse(self.base_url.strip())
        return bool(parsed.scheme and parsed.netloc)


def _to_openai_messages(messages: list[LLMMessage]) -> list[dict]:
    converted: list[dict] = []
    for message in messages:
        content: list[dict] = []
        for part in message.content:
            if isinstance(part, TextPart) or part.type == "text":
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart) or part.type == "image":
                url = f"data:{part.mime};base64,{part.data_b64}"
                content.append({"type": "image_url", "image_url": {"url": url}})
        converted.append({"role": message.role, "content": content})
    return converted
