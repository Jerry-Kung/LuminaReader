from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

from lumina.schemas.selection import ImagePayload, Selection

DataT = TypeVar("DataT")


class TranslateOptions(BaseModel):
    target_lang: str = "zh-CN"
    user_question: str | None = None


class TranslateRequest(BaseModel):
    task_type: str
    session_id: str | None = None
    selection: Selection | None = None
    image: ImagePayload | None = None
    options: TranslateOptions = Field(default_factory=TranslateOptions)


class HealthData(BaseModel):
    service: str
    version: str
    provider_ready: bool


class TranslateUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class TranslateMeta(BaseModel):
    request_id: str
    model: str
    latency_ms: int
    usage: TranslateUsage | None = None
    task_type: str | None = None
    turn_index: int | None = None


class TranslateData(BaseModel):
    text: str
    session_id: str | None = None
    meta: TranslateMeta


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class OkEnvelope(BaseModel):
    ok: Literal[True] = True
    data: Any


class ErrorEnvelope(BaseModel):
    ok: Literal[False] = False
    error: ErrorBody


def ok_response(data: DataT) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        payload = data.model_dump(exclude_none=True)
    else:
        payload = data
    return {"ok": True, "data": payload}


def error_response(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }
