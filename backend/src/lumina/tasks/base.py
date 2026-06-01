from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from lumina.providers.base import LLMMessage, LLMRequest, LLMResponse, Provider
from lumina.schemas.selection import ImagePayload, Selection


class TaskContext(BaseModel):
    selection: Selection | None = None
    image: ImagePayload | None = None
    options: dict = Field(default_factory=dict)
    history: list[LLMMessage] = Field(default_factory=list)
    user_question: str | None = None
    extracted_text: str | None = None
    project_id: str | None = None
    pdf_id: str | None = None


class TaskResult(BaseModel):
    text: str


class UnsupportedTaskError(Exception):
    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__(f"Unsupported task type: {task_type}")


class Task(ABC):
    task_type: str

    @abstractmethod
    def build_request(self, ctx: TaskContext) -> LLMRequest: ...

    def parse_response(self, resp: LLMResponse) -> TaskResult:
        return TaskResult(text=resp.text)

    async def run(self, ctx: TaskContext, provider: Provider) -> TaskResult:
        req = self.build_request(ctx)
        resp = await provider.invoke(req)
        return self.parse_response(resp)
