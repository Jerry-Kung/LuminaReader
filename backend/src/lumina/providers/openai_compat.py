from urllib.parse import urlparse

import openai
from openai import AsyncOpenAI

from lumina.providers.base import (
    ImagePart,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderTimeout,
    ProviderUpstreamError,
    TextPart,
)


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

    async def invoke(self, req: LLMRequest) -> LLMResponse:
        override = None
        if req.extras:
            override = req.extras.get("model_override")
        effective_model = override if override else self.model

        kwargs: dict = {
            "model": effective_model,
            "messages": _to_openai_messages(req.messages),
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.max_tokens is not None:
            kwargs["max_tokens"] = req.max_tokens

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderTimeout("Upstream LLM request timed out.") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
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
        return LLMResponse(text=text, model=effective_model, usage=usage, raw=raw)

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
