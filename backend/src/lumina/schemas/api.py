from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from lumina.schemas.selection import ImagePayload, Selection

DataT = TypeVar("DataT")


class TranslateOptions(BaseModel):
    target_lang: str = "zh-CN"
    user_question: str | None = None
    stream: bool = False


class TranslateRequest(BaseModel):
    task_type: str
    session_id: str | None = None
    pdf_id: str | None = None
    selection: Selection | None = None
    image: ImagePayload | None = None
    plugins: list[str] = Field(default_factory=list)
    user_input: str | None = None
    options: TranslateOptions = Field(default_factory=TranslateOptions)

    @model_validator(mode="after")
    def _check_image_selection_consistency(self) -> "TranslateRequest":
        if self.selection is None:
            if self.image is not None:
                raise ValueError("Follow-up turn must not include image")
            return self
        if self.selection.type == "text":
            if self.image is not None:
                raise ValueError("Text selection must not include image payload")
        elif self.selection.type == "image":
            if self.image is None:
                raise ValueError("Image selection requires image payload")
        return self


class HealthData(BaseModel):
    service: str
    version: str
    provider_ready: bool


class SettingsProviderOut(BaseModel):
    kind: Literal["openai_compat"]
    base_url: str
    api_key_masked: str | None
    default_model: str
    timeout_seconds: int


class ThinkingSettingsOut(BaseModel):
    enabled: bool = False


class ContextExpansionSettingsOut(BaseModel):
    enabled: bool = True


class SettingsResponse(BaseModel):
    provider: SettingsProviderOut
    task_models: dict[Literal["extract", "translate", "explain"], str | None]
    thinking: ThinkingSettingsOut = Field(default_factory=ThinkingSettingsOut)
    context_expansion: ContextExpansionSettingsOut = Field(
        default_factory=ContextExpansionSettingsOut
    )
    source: Literal["user_data", "env_fallback"]
    writable: bool
    provider_ready: bool


class FieldError(BaseModel):
    path: str
    reason: str


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
    thinking_enabled: bool = False
    plugins: list[str] = Field(default_factory=list)


class TranslateData(BaseModel):
    text: str
    extracted_text: str | None = None
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
    last_read_page: int = 1
    last_read_offset: float = 0.0
    thumbnail_url: str | None = None


class ReadingPositionUpdate(BaseModel):
    last_read_page: int = Field(..., ge=1)
    last_read_offset: float = Field(0.0, ge=0.0, le=1.0)


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
        if isinstance(data, TranslateData):
            payload = data.model_dump()
        else:
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
