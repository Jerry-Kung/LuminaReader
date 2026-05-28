from abc import ABC, abstractmethod
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    mime: str
    data_b64: str


ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: list[ContentPart]


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    extras: dict = Field(default_factory=dict)


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(BaseModel):
    text: str
    model: str
    usage: LLMUsage | None = None
    raw: dict | None = None


class ProviderError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ProviderConfigError(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderUpstreamError(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class Provider(ABC):
    name: str

    @abstractmethod
    async def invoke(self, req: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Lightweight config validation without calling the LLM."""
