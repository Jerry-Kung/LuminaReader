from lumina.providers.base import LLMStreamEvent, LLMUsage, ProviderError
from lumina.providers.errors import StreamUnsupportedError


def test_llm_stream_event_text_delta() -> None:
    ev = LLMStreamEvent(type="text_delta", delta="hello")
    assert ev.delta == "hello"


def test_llm_stream_event_usage() -> None:
    usage = LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    ev = LLMStreamEvent(type="usage", usage=usage)
    assert ev.usage == usage


def test_llm_stream_event_done() -> None:
    ev = LLMStreamEvent(type="done", model="gpt-4o", thinking_enabled=False)
    assert ev.model == "gpt-4o"
    assert ev.thinking_enabled is False


def test_llm_stream_event_error() -> None:
    ev = LLMStreamEvent(
        type="error",
        code="PROVIDER_ERROR",
        message="failed",
        retriable=True,
    )
    assert ev.code == "PROVIDER_ERROR"
    assert ev.retriable is True


def test_stream_unsupported_error_inherits_provider_error() -> None:
    assert issubclass(StreamUnsupportedError, ProviderError)
