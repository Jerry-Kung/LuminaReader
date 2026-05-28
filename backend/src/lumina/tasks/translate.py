from lumina.providers.base import ImagePart, LLMMessage, LLMRequest, TextPart
from lumina.tasks.base import Task, TaskContext


class TranslateTask(Task):
    task_type = "translate"

    SYSTEM_PROMPT = (
        "You are a professional translator. Produce high-quality translations that read "
        "naturally in the target language. Use context when available, avoid word-for-word "
        "literalism, and preserve technical terms and proper nouns appropriately. "
        "Output only the translated text with no explanations or commentary."
    )
    USER_INSTRUCTION = (
        "Translate the text in the image into {target_lang}. Output only the translation."
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
