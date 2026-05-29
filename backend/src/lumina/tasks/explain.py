from lumina.providers.base import ImagePart, LLMMessage, LLMRequest, TextPart
from lumina.tasks.base import Task, TaskContext


class ExplainTask(Task):
    task_type = "explain"

    SYSTEM_PROMPT = (
        "You are a knowledgeable reading assistant. Explain the content shown in the image "
        "clearly and structurally — describe what it is about, break it down by points or "
        "paragraphs, preserve and clarify technical terms, and add brief background when "
        "helpful. Write in the language specified by the user. Do not produce a word-for-word "
        "translation; focus on explanation and understanding."
    )
    USER_INSTRUCTION = (
        "Explain the content shown in the image in {target_lang}. "
        "Describe what it is about and clarify key terms."
    )

    def __init__(self, default_temperature: float = 0.2) -> None:
        self.default_temperature = default_temperature

    def build_request(self, ctx: TaskContext) -> LLMRequest:
        target_lang = ctx.options.get("target_lang", "zh-CN")
        temperature = ctx.options.get("temperature", self.default_temperature)
        user_instruction = self.USER_INSTRUCTION.format(target_lang=target_lang)
        return LLMRequest(
            messages=[
                LLMMessage(role="system", content=[TextPart(text=self.SYSTEM_PROMPT)]),
                LLMMessage(
                    role="user",
                    content=[
                        TextPart(text=user_instruction),
                        ImagePart(mime=ctx.image.mime, data_b64=ctx.image.data),
                    ],
                ),
            ],
            temperature=temperature,
        )
