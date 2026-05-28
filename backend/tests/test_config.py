from lumina.config import Settings, config_provider_ready


def test_cors_origins_list_splits_and_trims() -> None:
    settings = Settings(cors_allow_origins="http://a.test, http://b.test ,http://c.test")
    assert settings.cors_origins_list == [
        "http://a.test",
        "http://b.test",
        "http://c.test",
    ]


def test_config_provider_ready_false_when_key_empty() -> None:
    settings = Settings(openai_api_key="", openai_base_url="https://api.openai.com/v1")
    assert config_provider_ready(settings) is False


def test_config_provider_ready_true_when_key_and_url_valid() -> None:
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://api.openai.com/v1",
    )
    assert config_provider_ready(settings) is True


def test_config_provider_ready_false_when_url_invalid() -> None:
    settings = Settings(openai_api_key="test-key-not-real", openai_base_url="not-a-url")
    assert config_provider_ready(settings) is False


def test_get_settings_is_singleton() -> None:
    from lumina.config import get_settings

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
    get_settings.cache_clear()
