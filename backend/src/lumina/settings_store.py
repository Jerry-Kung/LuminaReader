from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from lumina.config import get_settings
from lumina.projects.paths import settings_json_path

logger = logging.getLogger("lumina.settings")

TASK_TYPES = frozenset({"extract", "translate", "explain", "memory"})
ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {"provider", "task_models", "thinking", "context_expansion"}
)
THINKING_ALLOWED_KEYS = frozenset({"enabled"})
CONTEXT_EXPANSION_ALLOWED_KEYS = frozenset({"enabled"})
MASKED_KEY_PREFIX = "sk-***..."


class InvalidSettingsError(Exception):
    def __init__(self, field_errors: list[dict[str, str]]) -> None:
        self.field_errors = field_errors
        super().__init__("invalid settings")


class SettingsPersistError(Exception):
    """Atomic write failed; message is safe for API responses."""


@dataclass(frozen=True)
class ThinkingSettings:
    enabled: bool = False


@dataclass(frozen=True)
class ContextExpansionSettings:
    """V1.2.1 跨页自动上下文开关（默认开启）。"""

    enabled: bool = True


@dataclass(frozen=True)
class ResolvedSettings:
    provider_kind: Literal["openai_compat"]
    base_url: str
    api_key: str | None
    default_model: str
    timeout_seconds: int
    task_models: dict[str, str | None]
    thinking: ThinkingSettings
    context_expansion: ContextExpansionSettings
    source: Literal["user_data", "env_fallback"]


_current: ResolvedSettings | None = None


def _reset_state() -> None:
    global _current
    _current = None


def get_current() -> ResolvedSettings:
    if _current is None:
        raise RuntimeError("settings_store has not been bootstrapped")
    return _current


def mask_api_key(key: str | None) -> str | None:
    if key is None or not key:
        return None
    if len(key) < 8:
        return "***"
    return f"{MASKED_KEY_PREFIX}{key[-4:]}"


def _is_masked_api_key(key: str) -> bool:
    return key.startswith(MASKED_KEY_PREFIX)


def is_writable() -> bool:
    parent = settings_json_path().parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        test_file = parent / ".write_probe"
        test_file.write_bytes(b"")
        test_file.unlink()
        return True
    except OSError:
        return False


def _normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def _validate_base_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _default_task_models() -> dict[str, str | None]:
    return {"extract": None, "translate": None, "explain": None, "memory": None}


def _validate_thinking(
    data: dict[str, Any],
    errors: list[dict[str, str]],
    *,
    env_fallback_enabled: bool,
) -> ThinkingSettings:
    thinking = data.get("thinking", _MISSING)
    if thinking is _MISSING:
        return ThinkingSettings(enabled=env_fallback_enabled)
    if not isinstance(thinking, dict):
        errors.append({"path": "thinking", "reason": "thinking must be an object"})
        return ThinkingSettings(enabled=False)
    extra_keys = set(thinking.keys()) - THINKING_ALLOWED_KEYS
    if extra_keys:
        for key in sorted(extra_keys):
            errors.append(
                {
                    "path": f"thinking.{key}",
                    "reason": f"unknown field thinking.{key}",
                }
            )
    enabled = thinking.get("enabled", False)
    if not isinstance(enabled, bool):
        errors.append(
            {
                "path": "thinking.enabled",
                "reason": "thinking.enabled must be a boolean",
            }
        )
        return ThinkingSettings(enabled=False)
    return ThinkingSettings(enabled=enabled)


def _validate_context_expansion(
    data: dict[str, Any],
    errors: list[dict[str, str]],
) -> ContextExpansionSettings:
    ce = data.get("context_expansion", _MISSING)
    if ce is _MISSING:
        return ContextExpansionSettings(enabled=True)
    if not isinstance(ce, dict):
        errors.append(
            {
                "path": "context_expansion",
                "reason": "context_expansion must be an object",
            }
        )
        return ContextExpansionSettings(enabled=True)
    extra_keys = set(ce.keys()) - CONTEXT_EXPANSION_ALLOWED_KEYS
    if extra_keys:
        for key in sorted(extra_keys):
            errors.append(
                {
                    "path": f"context_expansion.{key}",
                    "reason": f"unknown field context_expansion.{key}",
                }
            )
    enabled = ce.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(
            {
                "path": "context_expansion.enabled",
                "reason": "context_expansion.enabled must be a boolean",
            }
        )
        return ContextExpansionSettings(enabled=True)
    return ContextExpansionSettings(enabled=enabled)


def _validate_payload(
    data: dict[str, Any],
    *,
    env_fallback_enabled: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    unknown_top = set(data.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if unknown_top:
        for key in sorted(unknown_top):
            errors.append(
                {"path": key, "reason": f"unknown top-level field {key}"}
            )

    provider = data.get("provider")
    if not isinstance(provider, dict):
        errors.append({"path": "provider", "reason": "provider must be an object"})
        provider = {}

    kind = provider.get("kind")
    if kind != "openai_compat":
        errors.append(
            {
                "path": "provider.kind",
                "reason": 'provider.kind must be "openai_compat"',
            }
        )

    base_url = provider.get("base_url")
    if not isinstance(base_url, str) or not _validate_base_url(base_url):
        errors.append(
            {
                "path": "provider.base_url",
                "reason": "provider.base_url must be a valid http or https URL",
            }
        )

    api_key = provider.get("api_key", _MISSING)
    if api_key is not _MISSING:
        if api_key is not None:
            if not isinstance(api_key, str) or not api_key.strip():
                errors.append(
                    {
                        "path": "provider.api_key",
                        "reason": "provider.api_key must be a non-empty string or null",
                    }
                )
            elif _is_masked_api_key(api_key):
                errors.append(
                    {
                        "path": "provider.api_key",
                        "reason": "masked api_key cannot be written back",
                    }
                )

    default_model = provider.get("default_model")
    if not isinstance(default_model, str) or not default_model.strip():
        errors.append(
            {
                "path": "provider.default_model",
                "reason": "provider.default_model must be a non-empty string",
            }
        )

    timeout_seconds = provider.get("timeout_seconds", 60)
    if not isinstance(timeout_seconds, int) or timeout_seconds < 5 or timeout_seconds > 300:
        errors.append(
            {
                "path": "provider.timeout_seconds",
                "reason": "provider.timeout_seconds must be an integer between 5 and 300",
            }
        )

    task_models = data.get("task_models")
    if not isinstance(task_models, dict):
        errors.append({"path": "task_models", "reason": "task_models must be an object"})
        task_models = {}
    else:
        extra_keys = set(task_models.keys()) - TASK_TYPES
        missing_keys = TASK_TYPES - set(task_models.keys())
        if extra_keys or missing_keys:
            errors.append(
                {
                    "path": "task_models",
                    "reason": "task_models keys must be exactly extract, translate, explain, memory",
                }
            )
        for task in sorted(TASK_TYPES):
            value = task_models.get(task, _MISSING)
            if value is _MISSING:
                errors.append(
                    {
                        "path": f"task_models.{task}",
                        "reason": f"task_models.{task} is required",
                    }
                )
            elif value is not None and (not isinstance(value, str) or not value.strip()):
                errors.append(
                    {
                        "path": f"task_models.{task}",
                        "reason": f"task_models.{task} must be null or a non-empty string",
                    }
                )

    thinking_settings = _validate_thinking(
        data, errors, env_fallback_enabled=env_fallback_enabled
    )
    context_expansion_settings = _validate_context_expansion(data, errors)

    if errors:
        raise InvalidSettingsError(errors)

    normalized_task_models: dict[str, str | None] = {}
    for task in TASK_TYPES:
        raw = task_models[task]
        if isinstance(raw, str):
            normalized_task_models[task] = raw.strip()
        else:
            normalized_task_models[task] = None

    normalized_provider: dict[str, Any] = {
        "kind": "openai_compat",
        "base_url": _normalize_base_url(str(base_url)),
        "default_model": str(default_model).strip(),
        "timeout_seconds": int(timeout_seconds),
    }
    if api_key is not _MISSING:
        normalized_provider["api_key"] = None if api_key is None else str(api_key).strip()

    return {
        "provider": normalized_provider,
        "task_models": normalized_task_models,
        "thinking": thinking_settings,
        "context_expansion": context_expansion_settings,
    }


_MISSING = object()


def _resolved_from_validated(
    validated: dict[str, Any],
    *,
    api_key: str | None,
    source: Literal["user_data", "env_fallback"],
) -> ResolvedSettings:
    provider = validated["provider"]
    task_models = validated["task_models"]
    return ResolvedSettings(
        provider_kind="openai_compat",
        base_url=provider["base_url"],
        api_key=api_key,
        default_model=provider["default_model"],
        timeout_seconds=provider["timeout_seconds"],
        task_models={
            "extract": task_models["extract"],
            "translate": task_models["translate"],
            "explain": task_models["explain"],
            "memory": task_models["memory"],
        },
        thinking=validated["thinking"],
        context_expansion=validated["context_expansion"],
        source=source,
    )


def _to_disk_document(resolved: ResolvedSettings) -> dict[str, Any]:
    return {
        "provider": {
            "kind": resolved.provider_kind,
            "base_url": resolved.base_url,
            "api_key": resolved.api_key,
            "default_model": resolved.default_model,
            "timeout_seconds": resolved.timeout_seconds,
        },
        "task_models": dict(resolved.task_models),
        "thinking": {"enabled": resolved.thinking.enabled},
        "context_expansion": {"enabled": resolved.context_expansion.enabled},
    }


def _restrict_permissions(path: Path) -> None:
    if os.name == "posix":
        os.chmod(path, 0o600)
    elif os.name == "nt":
        try:
            username = os.environ["USERNAME"]
            subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{username}:F",
                ],
                check=True,
                capture_output=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, KeyError) as exc:
            logger.warning("failed to tighten settings.json ACL on Windows: %s", exc)


def _atomic_write(path: Path, data: bytes) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=parent,
        delete=False,
        prefix=".settings.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp.name)
    try:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp_path, path)
        _restrict_permissions(path)
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise SettingsPersistError(
            f"failed to write settings.json: {type(exc).__name__}"
        ) from exc
    finally:
        if not tmp.closed:
            tmp.close()


def bootstrap() -> ResolvedSettings:
    global _current
    sj_path = settings_json_path()
    env_cfg = get_settings()
    if sj_path.exists():
        try:
            raw = json.loads(sj_path.read_text(encoding="utf-8"))
            # V1.2.3 向前兼容：旧版本写盘的 settings.json 无 task_models.memory 键，
            # 读取时补默认 None，避免整体回退 .env
            tm = raw.get("task_models")
            if isinstance(tm, dict) and "memory" not in tm:
                tm["memory"] = None
            validated = _validate_payload(
                raw,
                env_fallback_enabled=env_cfg.thinking_enabled,
            )
            provider = validated["provider"]
            file_api_key = provider.get("api_key", env_cfg.openai_api_key or None)
            _current = _resolved_from_validated(
                validated,
                api_key=file_api_key,
                source="user_data",
            )
            logger.info(
                "settings source=user_data default_model=%s api_key_present=%s",
                _current.default_model,
                _current.api_key is not None,
            )
            return _current
        except (json.JSONDecodeError, InvalidSettingsError, OSError) as exc:
            logger.warning(
                "settings.json damaged or invalid (%s); falling back to .env",
                type(exc).__name__,
            )

    _current = ResolvedSettings(
        provider_kind="openai_compat",
        base_url=env_cfg.openai_base_url,
        api_key=env_cfg.openai_api_key or None,
        default_model=env_cfg.openai_model,
        timeout_seconds=int(env_cfg.llm_timeout_seconds),
        task_models=_default_task_models(),  # type: ignore[assignment]
        thinking=ThinkingSettings(enabled=env_cfg.thinking_enabled),
        context_expansion=ContextExpansionSettings(
            enabled=env_cfg.context_expansion_enabled
        ),
        source="env_fallback",
    )
    logger.info(
        "settings source=env_fallback default_model=%s api_key_present=%s",
        _current.default_model,
        _current.api_key is not None,
    )
    return _current


def _merge_update(payload: dict[str, Any], current: ResolvedSettings) -> dict[str, Any]:
    provider_in = payload.get("provider")
    if not isinstance(provider_in, dict):
        raise InvalidSettingsError([{"path": "provider", "reason": "provider must be an object"}])

    merged_provider: dict[str, Any] = {
        "kind": provider_in.get("kind", current.provider_kind),
        "base_url": provider_in.get("base_url", current.base_url),
        "default_model": provider_in.get("default_model", current.default_model),
        "timeout_seconds": provider_in.get("timeout_seconds", current.timeout_seconds),
    }
    if "api_key" in provider_in:
        merged_provider["api_key"] = provider_in["api_key"]
    else:
        merged_provider["api_key"] = current.api_key

    task_models_in = payload.get("task_models")
    if task_models_in is None:
        merged_task_models = dict(current.task_models)
    elif isinstance(task_models_in, dict):
        merged_task_models = dict(current.task_models)
        merged_task_models.update(task_models_in)
    else:
        raise InvalidSettingsError(
            [{"path": "task_models", "reason": "task_models must be an object"}]
        )

    thinking_in = payload.get("thinking")
    if thinking_in is None:
        merged_thinking: dict[str, Any] = {"enabled": current.thinking.enabled}
    elif isinstance(thinking_in, dict):
        merged_thinking = dict(thinking_in)
        if "enabled" not in merged_thinking:
            merged_thinking["enabled"] = current.thinking.enabled
    else:
        raise InvalidSettingsError(
            [{"path": "thinking", "reason": "thinking must be an object"}]
        )

    ce_in = payload.get("context_expansion")
    if ce_in is None:
        merged_ce: dict[str, Any] = {"enabled": current.context_expansion.enabled}
    elif isinstance(ce_in, dict):
        merged_ce = dict(ce_in)
        if "enabled" not in merged_ce:
            merged_ce["enabled"] = current.context_expansion.enabled
    else:
        raise InvalidSettingsError(
            [
                {
                    "path": "context_expansion",
                    "reason": "context_expansion must be an object",
                }
            ]
        )

    return {
        "provider": merged_provider,
        "task_models": merged_task_models,
        "thinking": merged_thinking,
        "context_expansion": merged_ce,
    }


def apply_update(payload: dict[str, Any]) -> ResolvedSettings:
    global _current
    if _current is None:
        raise RuntimeError("settings_store has not been bootstrapped")

    unknown_top = set(payload.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if unknown_top:
        raise InvalidSettingsError(
            [
                {"path": key, "reason": f"unknown top-level field {key}"}
                for key in sorted(unknown_top)
            ]
        )

    merged = _merge_update(payload, _current)
    env_cfg = get_settings()
    validated = _validate_payload(
        merged,
        env_fallback_enabled=env_cfg.thinking_enabled,
    )
    provider = validated["provider"]
    api_key = provider.get("api_key", _current.api_key)

    new_settings = _resolved_from_validated(
        validated,
        api_key=api_key,
        source="user_data",
    )

    disk_doc = _to_disk_document(new_settings)
    encoded = json.dumps(disk_doc, indent=2, ensure_ascii=False).encode("utf-8")
    path = settings_json_path()

    try:
        _atomic_write(path, encoded)
    except SettingsPersistError:
        raise

    from lumina.providers import rebuild_provider

    rebuild_provider(
        api_key=new_settings.api_key,
        base_url=new_settings.base_url,
        default_model=new_settings.default_model,
        timeout_seconds=new_settings.timeout_seconds,
    )
    _current = new_settings

    task_summary = ",".join(
        f"{task}:{new_settings.task_models[task] or 'default'}"
        for task in sorted(TASK_TYPES)
    )
    logger.info(
        "PUT /api/v1/settings source=user_data default_model=%s api_key_present=%s task_models=[%s]",
        new_settings.default_model,
        new_settings.api_key is not None,
        task_summary,
    )
    return new_settings
