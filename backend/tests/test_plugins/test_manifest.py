import pytest
from pydantic import ValidationError

from lumina.plugins.base import PluginManifest


VALID_MANIFEST = {
    "id": "translate",
    "label": "翻译",
    "icon": "ri-translate-2",
    "applicable_to": ["text", "image"],
    "thinking_default": False,
    "prompt_files": {
        "system": "prompts/system.md",
        "user": "prompts/user.md",
    },
}


def test_m01_valid_manifest_all_fields() -> None:
    manifest = PluginManifest.model_validate(VALID_MANIFEST)
    assert manifest.id == "translate"
    assert manifest.thinking_default is False


def test_m02_missing_id() -> None:
    data = {k: v for k, v in VALID_MANIFEST.items() if k != "id"}
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(data)


def test_m03_missing_prompt_files() -> None:
    data = {k: v for k, v in VALID_MANIFEST.items() if k != "prompt_files"}
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(data)


def test_m04_unknown_field_forbidden() -> None:
    data = {**VALID_MANIFEST, "foo": "bar"}
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(data)


def test_m05_invalid_applicable_to_literal() -> None:
    data = {**VALID_MANIFEST, "applicable_to": ["video"]}
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(data)
