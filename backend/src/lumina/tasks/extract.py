from lumina.providers.base import ImagePart, LLMMessage, LLMRequest, TextPart
from lumina.tasks.base import Task, TaskContext


class ExtractTask(Task):
    task_type = "extract"

    SYSTEM_PROMPT = (
        "You are a document extraction assistant. Extract all textual content from the "
        "provided image as structured Markdown. Preserve the layout order: output headings, "
        "paragraphs, lists, and tables as appropriate Markdown. "
        "For inline math use $...$ and for display math use $$...$$. "
        "For figures and charts, mark textual labels with prefixes like "
        "Figure: ... or Table: ... as needed. "
        "Output only the extracted text content. Do not translate, do not explain, "
        "and do not add commentary."
    )
    USER_INSTRUCTION = "Extract all textual content from the image as structured Markdown."

    def __init__(self, default_temperature: float = 0.2) -> None:
        self.default_temperature = default_temperature

    def build_request(self, ctx: TaskContext) -> LLMRequest:
        if ctx.image is None:
            raise ValueError("ExtractTask requires ctx.image")

        temperature = ctx.options.get("temperature", self.default_temperature)
        return LLMRequest(
            messages=[
                LLMMessage(role="system", content=[TextPart(text=self.SYSTEM_PROMPT)]),
                LLMMessage(
                    role="user",
                    content=[
                        TextPart(text=self.USER_INSTRUCTION),
                        ImagePart(mime=ctx.image.mime, data_b64=ctx.image.data),
                    ],
                ),
            ],
            temperature=temperature,
        )


EXTRACT_TASK = ExtractTask()
