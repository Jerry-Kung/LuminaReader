from lumina.providers.base import ContentPart, ImagePart, LLMMessage, LLMRequest, TextPart
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

    def _format_extracted_context(self, extracted_text: str) -> str:
        return (
            "Source content (extracted from the user's screenshot):\n\n"
            f"{extracted_text}"
        )

    def _format_user_question_inline(self, question: str) -> str:
        return f"Additional question from the user: {question}"

    def build_request(self, ctx: TaskContext) -> LLMRequest:
        target_lang = ctx.options.get("target_lang", "zh-CN")
        temperature = ctx.options.get("temperature", self.default_temperature)
        user_instruction = self.USER_INSTRUCTION.format(target_lang=target_lang)

        user_parts: list[ContentPart] = [TextPart(text=user_instruction)]
        if ctx.extracted_text is not None:
            user_parts.append(TextPart(text=self._format_extracted_context(ctx.extracted_text)))
        elif ctx.image is not None:
            user_parts.append(ImagePart(mime=ctx.image.mime, data_b64=ctx.image.data))
        else:
            raise ValueError("TranslateTask requires either ctx.extracted_text or ctx.image")

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=[TextPart(text=self.SYSTEM_PROMPT)]),
        ]

        if ctx.history:
            if ctx.user_question is None:
                raise ValueError("Follow-up turn requires ctx.user_question")
            messages.extend(ctx.history)
            messages.append(
                LLMMessage(
                    role="user",
                    content=user_parts
                    + [TextPart(text=self._format_user_question_inline(ctx.user_question))],
                )
            )
        else:
            if ctx.user_question:
                user_parts.append(
                    TextPart(text=self._format_user_question_inline(ctx.user_question))
                )
            messages.append(LLMMessage(role="user", content=user_parts))

        return LLMRequest(messages=messages, temperature=temperature)
