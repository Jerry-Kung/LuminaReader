from lumina.config import Settings
from lumina.providers.base import Provider
from lumina.providers.openai_compat import OpenAICompatProvider

__all__ = [
    "Provider",
    "OpenAICompatProvider",
    "build_provider_from_config",
    "get_provider",
    "init_provider",
    "init_provider_from_resolved",
    "rebuild_provider",
    "reset_provider",
]

_provider: Provider | None = None


def build_provider_from_config(cfg: Settings) -> Provider:
    # V0: single provider kind; future: branch on cfg.provider_kind
    return OpenAICompatProvider(
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url,
        model=cfg.openai_model,
        timeout_seconds=cfg.llm_timeout_seconds,
        return_raw=cfg.llm_return_raw,
    )


def init_provider(cfg: Settings) -> Provider:
    global _provider
    _provider = build_provider_from_config(cfg)
    return _provider


def rebuild_provider(
    *,
    api_key: str | None,
    base_url: str,
    default_model: str,
    timeout_seconds: int,
) -> Provider:
    global _provider
    _provider = OpenAICompatProvider(
        api_key=api_key or "",
        base_url=base_url,
        model=default_model,
        timeout_seconds=timeout_seconds,
        return_raw=False,
    )
    return _provider


def init_provider_from_resolved(
    *,
    api_key: str | None,
    base_url: str,
    default_model: str,
    timeout_seconds: int,
) -> Provider:
    return rebuild_provider(
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
        timeout_seconds=timeout_seconds,
    )


def get_provider() -> Provider:
    if _provider is None:
        raise RuntimeError("Provider has not been initialized")
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
