import json
import os
from unittest.mock import patch

import pytest

from lumina.config import Settings, get_settings
from lumina.providers import get_provider, init_provider, reset_provider
from lumina import settings_store


def _env_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="sk-envkey123456",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-env",
        llm_timeout_seconds=45,
        **overrides,
    )


def _valid_disk_doc(**overrides: object) -> dict:
    doc = {
        "provider": {
            "kind": "openai_compat",
            "base_url": "https://disk.example.com/v1",
            "api_key": "sk-diskkey1234",
            "default_model": "gpt-disk",
            "timeout_seconds": 90,
        },
        "task_models": {"extract": None, "translate": "gpt-mini", "explain": None},
    }
    doc.update(overrides)
    return doc


def _valid_update_payload(**overrides: object) -> dict:
    payload = {
        "provider": {
            "kind": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-newkey123456",
            "default_model": "gpt-4o-mini",
            "timeout_seconds": 60,
        },
        "task_models": {"extract": None, "translate": None, "explain": None},
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMINA_DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    settings_store._reset_state()
    reset_provider()
    yield
    settings_store._reset_state()
    reset_provider()
    get_settings.cache_clear()


@pytest.fixture
def patched_env(monkeypatch):
    cfg = _env_settings()
    monkeypatch.setattr("lumina.settings_store.get_settings", lambda: cfg)
    return cfg


def test_bootstrap_no_file_uses_env_fallback(patched_env) -> None:
    resolved = settings_store.bootstrap()
    assert resolved.source == "env_fallback"
    assert resolved.base_url == patched_env.openai_base_url
    assert resolved.api_key == patched_env.openai_api_key
    assert resolved.default_model == patched_env.openai_model
    assert resolved.timeout_seconds == 45


def test_bootstrap_valid_file_uses_user_data(patched_env, tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(_valid_disk_doc()), encoding="utf-8")
    resolved = settings_store.bootstrap()
    assert resolved.source == "user_data"
    assert resolved.base_url == "https://disk.example.com/v1"
    assert resolved.default_model == "gpt-disk"
    assert resolved.task_models["translate"] == "gpt-mini"


def test_bootstrap_file_missing_memory_key_backfills_none(patched_env, tmp_path) -> None:
    # V1.2.3 向前兼容：_valid_disk_doc() 未含 task_models.memory 键，模拟旧版 settings.json
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(_valid_disk_doc()), encoding="utf-8")
    resolved = settings_store.bootstrap()
    assert resolved.source == "user_data"
    assert resolved.task_models["memory"] is None


def test_bootstrap_damaged_json_falls_back(patched_env, tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    resolved = settings_store.bootstrap()
    assert resolved.source == "env_fallback"


def test_bootstrap_invalid_schema_falls_back(patched_env, tmp_path) -> None:
    path = tmp_path / "settings.json"
    doc = _valid_disk_doc()
    doc["provider"]["kind"] = "anthropic"
    path.write_text(json.dumps(doc), encoding="utf-8")
    resolved = settings_store.bootstrap()
    assert resolved.source == "env_fallback"


def test_apply_update_valid(patched_env) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    new_state = settings_store.apply_update(_valid_update_payload())
    assert new_state.source == "user_data"
    assert new_state.default_model == "gpt-4o-mini"
    assert settings_store.get_current().default_model == "gpt-4o-mini"


def test_apply_update_persists_to_disk(patched_env, tmp_path) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    settings_store.apply_update(_valid_update_payload())
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["provider"]["default_model"] == "gpt-4o-mini"
    assert saved["provider"]["api_key"] == "sk-newkey123456"


def test_apply_update_atomic_on_failure(patched_env, tmp_path) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    before = settings_store.get_current()
    with patch("lumina.settings_store.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(settings_store.SettingsPersistError):
            settings_store.apply_update(_valid_update_payload())
    assert settings_store.get_current() == before
    assert not (tmp_path / "settings.json").exists()


def test_apply_update_invalid_url(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload()
    payload["provider"]["base_url"] = "not a url"
    with pytest.raises(settings_store.InvalidSettingsError) as exc_info:
        settings_store.apply_update(payload)
    paths = [e["path"] for e in exc_info.value.field_errors]
    assert "provider.base_url" in paths


def test_apply_update_invalid_timeout_range(patched_env) -> None:
    settings_store.bootstrap()
    for value in (0, 1000):
        payload = _valid_update_payload()
        payload["provider"]["timeout_seconds"] = value
        with pytest.raises(settings_store.InvalidSettingsError):
            settings_store.apply_update(payload)


def test_apply_update_unknown_task_key(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload()
    payload["task_models"] = {"summary": "gpt-4o"}
    with pytest.raises(settings_store.InvalidSettingsError):
        settings_store.apply_update(payload)


def test_apply_update_rejects_masked_key(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload()
    payload["provider"]["api_key"] = "sk-***...abcd"
    with pytest.raises(settings_store.InvalidSettingsError):
        settings_store.apply_update(payload)


def test_apply_update_api_key_three_states(patched_env) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    settings_store.apply_update(_valid_update_payload())
    assert settings_store.get_current().api_key == "sk-newkey123456"

    payload = _valid_update_payload()
    del payload["provider"]["api_key"]
    settings_store.apply_update(payload)
    assert settings_store.get_current().api_key == "sk-newkey123456"

    payload = _valid_update_payload()
    payload["provider"]["api_key"] = None
    settings_store.apply_update(payload)
    assert settings_store.get_current().api_key is None

    payload = _valid_update_payload()
    payload["provider"]["api_key"] = "sk-replaced9999"
    settings_store.apply_update(payload)
    assert settings_store.get_current().api_key == "sk-replaced9999"


def test_mask_api_key_short_key() -> None:
    assert settings_store.mask_api_key(None) is None
    assert settings_store.mask_api_key("") is None
    assert settings_store.mask_api_key("short") == "***"


def test_mask_api_key_normal() -> None:
    assert settings_store.mask_api_key("sk-abcd1234") == "sk-***...1234"


@pytest.mark.skipif(os.name != "posix", reason="Unix permission bits")
def test_atomic_write_unix_permission(patched_env, tmp_path) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    settings_store.apply_update(_valid_update_payload())
    mode = os.stat(tmp_path / "settings.json").st_mode & 0o777
    assert mode == 0o600


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL tightening")
def test_atomic_write_windows_no_throw_on_acl_fail(patched_env, caplog) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    with patch(
        "lumina.settings_store.subprocess.run",
        side_effect=__import__("subprocess").CalledProcessError(1, "icacls"),
    ):
        settings_store.apply_update(_valid_update_payload())
    assert settings_store.get_current().source == "user_data"
    assert any("ACL" in r.message for r in caplog.records)


def test_bootstrap_thinking_default_false(patched_env) -> None:
    resolved = settings_store.bootstrap()
    assert resolved.thinking.enabled is False


def test_bootstrap_thinking_env_fallback(patched_env, monkeypatch) -> None:
    cfg = _env_settings(thinking_enabled=True)
    monkeypatch.setattr("lumina.settings_store.get_settings", lambda: cfg)
    resolved = settings_store.bootstrap()
    assert resolved.thinking.enabled is True


def test_bootstrap_file_missing_thinking_uses_env(patched_env, tmp_path, monkeypatch) -> None:
    cfg = _env_settings(thinking_enabled=True)
    monkeypatch.setattr("lumina.settings_store.get_settings", lambda: cfg)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(_valid_disk_doc()), encoding="utf-8")
    resolved = settings_store.bootstrap()
    assert resolved.thinking.enabled is True


def test_apply_update_persists_thinking(patched_env, tmp_path) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    payload = _valid_update_payload(thinking={"enabled": True})
    settings_store.apply_update(payload)
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["thinking"] == {"enabled": True}
    assert settings_store.get_current().thinking.enabled is True


def test_apply_update_without_thinking_preserves(patched_env) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    settings_store.apply_update(_valid_update_payload(thinking={"enabled": True}))
    settings_store.apply_update(_valid_update_payload())
    assert settings_store.get_current().thinking.enabled is True


def test_apply_update_thinking_enabled_type_error(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload(thinking={"enabled": "yes"})
    with pytest.raises(settings_store.InvalidSettingsError) as exc_info:
        settings_store.apply_update(payload)
    paths = [e["path"] for e in exc_info.value.field_errors]
    assert "thinking.enabled" in paths


def test_apply_update_thinking_unknown_field(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload(thinking={"enabled": True, "budget": 1000})
    with pytest.raises(settings_store.InvalidSettingsError) as exc_info:
        settings_store.apply_update(payload)
    paths = [e["path"] for e in exc_info.value.field_errors]
    assert "thinking.budget" in paths


def test_apply_update_unknown_top_level_key(patched_env) -> None:
    settings_store.bootstrap()
    payload = _valid_update_payload()
    payload["extra_section"] = {}
    with pytest.raises(settings_store.InvalidSettingsError) as exc_info:
        settings_store.apply_update(payload)
    paths = [e["path"] for e in exc_info.value.field_errors]
    assert "extra_section" in paths


def test_rebuild_provider_replaces_singleton(patched_env) -> None:
    settings_store.bootstrap()
    init_provider(patched_env)
    assert get_provider().model == patched_env.openai_model
    settings_store.apply_update(_valid_update_payload())
    assert get_provider().model == "gpt-4o-mini"
