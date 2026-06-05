import json
from pathlib import Path

import pytest

from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.plugins.base import Plugin, PluginContext, PluginPromptSegments
from lumina.plugins.errors import PluginLoadError

MINIMAL_PLUGIN_PY = '''
from lumina.plugins.base import Plugin, PluginContext, PluginPromptSegments

class FakePlugin(Plugin):
    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        return PluginPromptSegments(system="s", user="u")

PLUGIN_CLASS = FakePlugin
'''

SIMPLE_MANIFEST = {
    "id": "alpha",
    "label": "Alpha",
    "icon": "ri-test",
    "applicable_to": ["text", "image"],
    "thinking_default": False,
    "prompt_files": {
        "system": "prompts/system.md",
        "user": "prompts/user.md",
    },
}


def _write_plugin(
    root: Path,
    name: str,
    *,
    manifest: dict | None = None,
    plugin_py: str = MINIMAL_PLUGIN_PY,
    write_prompts: bool = True,
    write_manifest: bool = True,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = plugin_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    if write_manifest:
        data = manifest if manifest is not None else {**SIMPLE_MANIFEST, "id": name}
        (plugin_dir / "manifest.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    if write_prompts:
        (prompts_dir / "system.md").write_text("system", encoding="utf-8")
        (prompts_dir / "user.md").write_text("user", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(plugin_py, encoding="utf-8")
    return plugin_dir


def test_r01_load_three_plugins(tmp_path: Path) -> None:
    for name in ("alpha", "beta", "gamma"):
        _write_plugin(tmp_path, name)

    registry = PluginRegistry.load_all(tmp_path)
    assert set(registry.plugins.keys()) == {"alpha", "beta", "gamma"}


def test_r02_invalid_manifest_json(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "bad")
    (tmp_path / "bad" / "manifest.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(PluginLoadError, match="invalid manifest JSON"):
        PluginRegistry.load_all(tmp_path)


def test_r03_manifest_missing_id(tmp_path: Path) -> None:
    manifest = {k: v for k, v in SIMPLE_MANIFEST.items() if k != "id"}
    _write_plugin(tmp_path, "bad", manifest=manifest)

    with pytest.raises(PluginLoadError, match="manifest schema invalid"):
        PluginRegistry.load_all(tmp_path)


def test_r04_prompt_file_missing(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "bad", write_prompts=False)

    with pytest.raises(PluginLoadError, match="prompt file not found"):
        PluginRegistry.load_all(tmp_path)


def test_r05_manifest_id_mismatch(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "wrongdir", manifest={**SIMPLE_MANIFEST, "id": "other"})

    with pytest.raises(PluginLoadError, match="does not match directory name"):
        PluginRegistry.load_all(tmp_path)


def test_r06_skip_dir_without_manifest_or_prompts(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "real")
    (tmp_path / "empty_dir").mkdir()

    registry = PluginRegistry.load_all(tmp_path)
    assert set(registry.plugins.keys()) == {"real"}


def test_r07_prompts_without_manifest_fatal(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "prompts").mkdir()
    (plugin_dir / "prompts" / "system.md").write_text("x", encoding="utf-8")

    with pytest.raises(PluginLoadError, match="manifest.json not found"):
        PluginRegistry.load_all(tmp_path)


def test_r08_missing_plugin_class(tmp_path: Path) -> None:
    _write_plugin(tmp_path, "bad", plugin_py="x = 1\n")

    with pytest.raises(PluginLoadError, match="must export PLUGIN_CLASS"):
        PluginRegistry.load_all(tmp_path)


def test_r09_list_applicable_filters(tmp_path: Path) -> None:
    dict_manifest = {
        **SIMPLE_MANIFEST,
        "id": "dict_only",
        "applicable_when": {"selection_word_count": {"max": 3}},
    }
    _write_plugin(tmp_path, "dict_only", manifest=dict_manifest)
    _write_plugin(tmp_path, "always")

    registry = PluginRegistry.load_all(tmp_path)
    applicable = registry.list_applicable(PluginContext(selection_word_count=4))
    assert [p.manifest.id for p in applicable] == ["always"]

    applicable_short = registry.list_applicable(
        PluginContext(selection_word_count=2)
    )
    assert {p.manifest.id for p in applicable_short} == {"dict_only", "always"}


def test_builtin_plugins_load() -> None:
    registry = PluginRegistry.load_all(get_plugins_root())
    assert set(registry.plugins.keys()) == {"translate", "explain", "dictionary"}
