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
    pdf_id: str | None = None
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
    conversation_id: str | None = None
    meta: TranslateMeta


class PdfUploadData(BaseModel):
    pdf_id: str
    project_id: str
    name: str
    primary_pdf_filename: str
    primary_pdf_size: int
    created_at: int


class ProjectConflictExisting(BaseModel):
    pdf_id: str
    name: str
    primary_pdf_filename: str
    primary_pdf_size: int
    created_at: int
    last_opened_at: int


class LibraryItem(BaseModel):
    pdf_id: str
    name: str
    primary_pdf_filename: str
    primary_pdf_size: int
    created_at: int
    last_opened_at: int
    thumbnail_url: str | None = None


class LibraryListData(BaseModel):
    items: list[LibraryItem]


class ConversationSummaryItem(BaseModel):
    conversation_id: str
    task_type: str
    selection: dict
    thumbnail_url: str | None = None
    first_assistant_summary: str
    status: str
    created_at: int
    last_used_at: int
    message_count: int


class ConversationListData(BaseModel):
    items: list[ConversationSummaryItem]


class MessageItem(BaseModel):
    message_id: str
    turn_index: int
    role: str
    content: str
    created_at: int
    user_question: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None


class ConversationMessagesData(BaseModel):
    conversation_id: str
    task_type: str
    extracted_text: str
    messages: list[MessageItem]


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


def error_response(
    code: str,
    message: str,
    request_id: str,
    **extra: Any,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    error.update(extra)
    return {
        "ok": False,
        "error": error,
    }
