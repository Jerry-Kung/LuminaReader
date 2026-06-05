from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pydantic import ValidationError

from lumina.plugins.base import Plugin, PluginContext, PluginManifest
from lumina.plugins.errors import PluginLoadError, PluginNotFoundError


class PluginRegistry:
    def __init__(self, plugins: dict[str, Plugin]) -> None:
        self.plugins = plugins

    def get(self, plugin_id: str) -> Plugin:
        if plugin_id not in self.plugins:
            raise PluginNotFoundError(plugin_id)
        return self.plugins[plugin_id]

    def list_all(self) -> list[Plugin]:
        return list(self.plugins.values())

    def list_applicable(self, ctx: PluginContext) -> list[Plugin]:
        return [p for p in self.plugins.values() if p.is_applicable(ctx)]

    @classmethod
    def load_all(cls, plugins_root: Path) -> PluginRegistry:
        if not plugins_root.is_dir():
            raise PluginLoadError(f"plugins root not found: {plugins_root}")

        plugins: dict[str, Plugin] = {}
        subdirs = sorted(
            [
                p
                for p in plugins_root.iterdir()
                if p.is_dir()
                and not p.name.startswith("_")
                and p.name != "__pycache__"
            ]
        )

        for plugin_dir in subdirs:
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.is_file():
                if (plugin_dir / "prompts").is_dir():
                    raise PluginLoadError(
                        f"plugin {plugin_dir.name}: manifest.json not found"
                    )
                continue

            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise PluginLoadError(
                    f"plugin {plugin_dir.name}: invalid manifest JSON: {e}"
                ) from e

            try:
                manifest = PluginManifest.model_validate(manifest_data)
            except ValidationError as e:
                raise PluginLoadError(
                    f"plugin {plugin_dir.name}: manifest schema invalid: {e}"
                ) from e

            if manifest.id != plugin_dir.name:
                raise PluginLoadError(
                    f"plugin {plugin_dir.name}: manifest.id={manifest.id} "
                    f"does not match directory name"
                )

            prompts = _load_prompt_files(plugin_dir, manifest.prompt_files)
            plugin_cls = _load_plugin_class(plugin_dir)
            plugins[manifest.id] = plugin_cls(manifest=manifest, prompts=prompts)

        return cls(plugins=plugins)


def _load_prompt_files(
    plugin_dir: Path,
    prompt_files: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    result: dict[str, str | dict[str, str]] = {}
    for key, value in prompt_files.items():
        if isinstance(value, str):
            file_path = plugin_dir / value
            if not file_path.is_file():
                raise PluginLoadError(
                    f"plugin {plugin_dir.name}: prompt file not found: {value}"
                )
            result[key] = file_path.read_text(encoding="utf-8")
        elif isinstance(value, dict):
            sub: dict[str, str] = {}
            for sub_key, sub_path in value.items():
                file_path = plugin_dir / sub_path
                if not file_path.is_file():
                    raise PluginLoadError(
                        f"plugin {plugin_dir.name}: prompt file not found: {sub_path}"
                    )
                sub[sub_key] = file_path.read_text(encoding="utf-8")
            result[key] = sub
        else:
            raise PluginLoadError(
                f"plugin {plugin_dir.name}: prompt_files.{key} must be str or dict"
            )
    return result


def _load_plugin_class(plugin_dir: Path) -> type[Plugin]:
    plugin_path = plugin_dir / "plugin.py"
    if not plugin_path.is_file():
        raise PluginLoadError(f"plugin {plugin_dir.name}: plugin.py not found")

    module_name = f"lumina.plugins._dynamic_{plugin_dir.name}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"plugin {plugin_dir.name}: failed to load plugin.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_cls = getattr(module, "PLUGIN_CLASS", None)
    if plugin_cls is None or not issubclass(plugin_cls, Plugin):
        raise PluginLoadError(
            f"plugin {plugin_dir.name}: plugin.py must export PLUGIN_CLASS "
            f"subclass of Plugin"
        )
    return plugin_cls
