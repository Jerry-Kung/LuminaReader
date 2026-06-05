import pytest

from lumina.plugins.base import Plugin, PluginManifest


def test_plugin_abstract_not_instantiable() -> None:
    manifest = PluginManifest.model_validate(
        {
            "id": "x",
            "label": "x",
            "icon": "x",
            "applicable_to": ["image"],
            "prompt_files": {"system": "a.md", "user": "b.md"},
        }
    )
    with pytest.raises(TypeError):
        Plugin(manifest=manifest, prompts={})  # type: ignore[abstract]
