from lumina.providers.base import ProviderError


class StreamUnsupportedError(ProviderError):
    """Provider / Task does not support streaming (invoke_stream path only).

    Maps to HTTP 400 STREAM_UNSUPPORTED before response headers are sent.
    """


class StreamInterruptedError(ProviderError):
    """Marker for upstream interruption during streaming.

    Not raised to invoke_stream callers; invoke_stream emits an error event instead.
    """
