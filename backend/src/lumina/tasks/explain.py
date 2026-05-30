from lumina.providers.base import ContentPart, ImagePart, LLMMessage, LLMRequest, TextPart
from lumina.tasks.base import Task, TaskContext


class ExplainTask(Task):
    task_type = "explain"

    # Full-content explanation when the user has no focused question.
    SYSTEM_PROMPT = (
        "You are a knowledgeable reading assistant. Explain the content shown in the image "
        "clearly and structurally — describe what it is about, break it down by points or "
        "paragraphs, preserve and clarify technical terms, and add brief background when "
        "helpful. Write in the language specified by the user. Do not produce a word-for-word "
        "translation; focus on explanation and understanding. "
        "When the user provides a focused question, prioritize answering that question; "
        "otherwise explain the full content."
    )
    USER_INSTRUCTION = (
        "Explain the content shown in the image in {target_lang}. "
        "Describe what it is about and clarify key terms."
    )
    # QA branch: first turn with user_question, or any follow-up turn.
    USER_INSTRUCTION_QA = (
        "Answer the user's question directly and concisely in {target_lang}. "
        "The screenshot content below is provided only as context — do NOT proactively "
        "re-explain the whole content or enumerate key points unless the user explicitly "
        "asks for it. Stay focused on the user's question."
    )

    def __init__(self, default_temperature: float = 0.2) -> None:
        self.default_temperature = default_temperature

    def _format_extracted_context(self, extracted_text: str) -> str:
        return (
            "Source content (extracted from the user's screenshot):\n\n"
            f"{extracted_text}"
        )

    def _uses_qa_instruction(self, ctx: TaskContext) -> bool:
        return bool(ctx.history) or bool(ctx.user_question)

    def build_request(self, ctx: TaskContext) -> LLMRequest:
        target_lang = ctx.options.get("target_lang", "zh-CN")
        temperature = ctx.options.get("temperature", self.default_temperature)

        if ctx.history and ctx.user_question is None:
            raise ValueError("Follow-up turn requires ctx.user_question")

        if self._uses_qa_instruction(ctx):
            user_instruction = self.USER_INSTRUCTION_QA.format(target_lang=target_lang)
        else:
            user_instruction = self.USER_INSTRUCTION.format(target_lang=target_lang)

        user_parts: list[ContentPart] = [TextPart(text=user_instruction)]
        if ctx.user_question:
            user_parts.append(TextPart(text=f"The user's question: {ctx.user_question}"))

        if ctx.extracted_text is not None:
            user_parts.append(TextPart(text=self._format_extracted_context(ctx.extracted_text)))
        elif ctx.image is not None:
            user_parts.append(ImagePart(mime=ctx.image.mime, data_b64=ctx.image.data))
        else:
            raise ValueError("ExplainTask requires either ctx.extracted_text or ctx.image")

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=[TextPart(text=self.SYSTEM_PROMPT)]),
        ]

        if ctx.history:
            messages.extend(ctx.history)
            messages.append(LLMMessage(role="user", content=user_parts))
        else:
            messages.append(LLMMessage(role="user", content=user_parts))

        return LLMRequest(messages=messages, temperature=temperature)
