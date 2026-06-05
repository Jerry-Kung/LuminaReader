from __future__ import annotations

import re
from collections.abc import AsyncIterator
from enum import Enum

from lumina.plugins.base import PluginParseResult, StructuredStreamEvent
from lumina.providers.base import LLMStreamEvent

_TAG_OCR_OPEN = "<ocr>"
_TAG_OCR_CLOSE = "</ocr>"
_TAG_ANSWER_OPEN = "<answer>"
_TAG_ANSWER_CLOSE = "</answer>"

_WAIT_OCR_OPEN_BUFFER_LIMIT = 256
_TAIL_BUFFER_SIZE = max(
    len(_TAG_OCR_OPEN),
    len(_TAG_OCR_CLOSE),
    len(_TAG_ANSWER_OPEN),
    len(_TAG_ANSWER_CLOSE),
)

_OCR_RE = re.compile(r"<ocr>(.*?)</ocr>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)
_RESIDUAL_TAG_RE = re.compile(r"</?(?:ocr|answer)>")


class _State(Enum):
    WAIT_OCR_OPEN = "wait_ocr_open"
    IN_OCR = "in_ocr"
    WAIT_ANSWER_OPEN = "wait_answer_open"
    IN_ANSWER = "in_answer"
    FALLBACK_ALL_ANSWER = "fallback_all_answer"
    DONE = "done"


def _strip_residual_tags(text: str) -> str:
    return _RESIDUAL_TAG_RE.sub("", text)


def parse_full_response(text: str) -> tuple[PluginParseResult, str | None]:
    ocr_match = _OCR_RE.search(text)
    answer_match = _ANSWER_RE.search(text)
    if ocr_match and answer_match:
        return (
            PluginParseResult(
                answer=answer_match.group(1).strip(),
                extracted_text=ocr_match.group(1).strip(),
            ),
            None,
        )
    cleaned = _strip_residual_tags(text).strip()
    return (
        PluginParseResult(answer=cleaned, extracted_text=None),
        "non_stream_regex_failed",
    )


class StreamingTagParser:
    def __init__(self) -> None:
        self._state = _State.WAIT_OCR_OPEN
        self._buffer = ""
        self._wait_ocr_open_accum = 0
        self._ocr_full = ""
        self.failure_reason: str | None = None

    async def feed_stream(
        self,
        events: AsyncIterator[LLMStreamEvent],
    ) -> AsyncIterator[StructuredStreamEvent]:
        async for ev in events:
            if ev.type == "text_delta":
                if ev.delta:
                    for out in self._process_delta(ev.delta):
                        yield out
            elif ev.type == "usage":
                yield StructuredStreamEvent.passthrough(ev)
            elif ev.type == "done":
                for out in self._finalize():
                    yield out
                yield StructuredStreamEvent(
                    type="done",
                    section=None,
                    model=ev.model,
                    thinking_enabled=ev.thinking_enabled,
                )
            elif ev.type == "error":
                yield StructuredStreamEvent.passthrough(ev)
                return

    def _emit_text_delta(
        self,
        text: str,
        section: str,
        *,
        allow_empty: bool = False,
    ) -> StructuredStreamEvent | None:
        if not text and not allow_empty:
            return None
        if section == "ocr":
            self._ocr_full += text
        return StructuredStreamEvent(
            type="text_delta",
            section=section,  # type: ignore[arg-type]
            delta=text,
        )

    def _process_delta(self, delta: str) -> list[StructuredStreamEvent]:
        if self._state == _State.DONE:
            return []

        if self._state == _State.FALLBACK_ALL_ANSWER:
            cleaned = _strip_residual_tags(delta)
            ev = self._emit_text_delta(cleaned, "answer")
            return [ev] if ev else []

        self._buffer += delta
        out: list[StructuredStreamEvent] = []

        while True:
            if self._state == _State.WAIT_OCR_OPEN:
                self._wait_ocr_open_accum += len(delta)
                idx = self._buffer.find(_TAG_OCR_OPEN)
                if idx >= 0:
                    self._buffer = self._buffer[idx + len(_TAG_OCR_OPEN) :]
                    self._state = _State.IN_OCR
                    continue
                if self._wait_ocr_open_accum > _WAIT_OCR_OPEN_BUFFER_LIMIT:
                    self.failure_reason = "ocr_open_not_found"
                    self._state = _State.FALLBACK_ALL_ANSWER
                    cleaned = _strip_residual_tags(self._buffer)
                    self._buffer = ""
                    ev = self._emit_text_delta(cleaned, "answer")
                    if ev:
                        out.append(ev)
                break

            if self._state == _State.IN_OCR:
                idx = self._buffer.find(_TAG_OCR_CLOSE)
                if idx >= 0:
                    ocr_text = self._buffer[:idx]
                    ev = self._emit_text_delta(ocr_text, "ocr", allow_empty=True)
                    if ev:
                        out.append(ev)
                    out.append(
                        StructuredStreamEvent(
                            type="extracted_text",
                            section=None,
                            text=self._ocr_full,
                        )
                    )
                    self._buffer = self._buffer[idx + len(_TAG_OCR_CLOSE) :]
                    self._state = _State.WAIT_ANSWER_OPEN
                    continue
                if len(self._buffer) > _TAIL_BUFFER_SIZE:
                    emit_len = len(self._buffer) - _TAIL_BUFFER_SIZE
                    ocr_text = self._buffer[:emit_len]
                    self._buffer = self._buffer[emit_len:]
                    ev = self._emit_text_delta(ocr_text, "ocr")
                    if ev:
                        out.append(ev)
                break

            if self._state == _State.WAIT_ANSWER_OPEN:
                idx = self._buffer.find(_TAG_ANSWER_OPEN)
                if idx >= 0:
                    self._buffer = self._buffer[idx + len(_TAG_ANSWER_OPEN) :]
                    self._state = _State.IN_ANSWER
                    continue
                break

            if self._state == _State.IN_ANSWER:
                idx = self._buffer.find(_TAG_ANSWER_CLOSE)
                if idx >= 0:
                    answer_text = self._buffer[:idx]
                    ev = self._emit_text_delta(answer_text, "answer", allow_empty=True)
                    if ev:
                        out.append(ev)
                    self._buffer = ""
                    self._state = _State.DONE
                    break
                if len(self._buffer) > _TAIL_BUFFER_SIZE:
                    emit_len = len(self._buffer) - _TAIL_BUFFER_SIZE
                    answer_text = self._buffer[:emit_len]
                    self._buffer = self._buffer[emit_len:]
                    ev = self._emit_text_delta(answer_text, "answer")
                    if ev:
                        out.append(ev)
                break

            break

        return out

    def _finalize(self) -> list[StructuredStreamEvent]:
        out: list[StructuredStreamEvent] = []

        if self._state == _State.WAIT_OCR_OPEN:
            self.failure_reason = "ocr_open_not_found"
            cleaned = _strip_residual_tags(self._buffer)
            ev = self._emit_text_delta(cleaned, "answer")
            if ev:
                out.append(ev)
            self._buffer = ""
            self._state = _State.DONE

        elif self._state == _State.IN_OCR:
            self.failure_reason = "ocr_close_not_found"
            ev = self._emit_text_delta(self._buffer, "ocr")
            if ev:
                out.append(ev)
            if self._ocr_full or self._buffer:
                out.append(
                    StructuredStreamEvent(
                        type="extracted_text",
                        section=None,
                        text=self._ocr_full,
                    )
                )
            self._buffer = ""
            self._state = _State.DONE

        elif self._state == _State.WAIT_ANSWER_OPEN:
            self.failure_reason = "answer_open_not_found"
            cleaned = _strip_residual_tags(self._buffer)
            ev = self._emit_text_delta(cleaned, "answer")
            if ev:
                out.append(ev)
            self._buffer = ""
            self._state = _State.DONE

        elif self._state == _State.IN_ANSWER:
            ev = self._emit_text_delta(self._buffer, "answer")
            if ev:
                out.append(ev)
            self._buffer = ""
            self._state = _State.DONE

        return out
