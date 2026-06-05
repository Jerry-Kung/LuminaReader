from pathlib import Path

from fastapi import Request

from lumina.plugins.base import (
    ApplicableWhen,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginParseResult,
    PluginPromptSegments,
    StructuredStreamEvent,
    evaluate_applicable_when,
)
from lumina.plugins.errors import PluginLoadError, PluginNotFoundError
from lumina.plugins.pipeline import PluginPipeline
from lumina.plugins.registry import PluginRegistry

__all__ = [
    "ApplicableWhen",
    "Plugin",
    "PluginContext",
    "PluginLoadError",
    "PluginManifest",
    "PluginNotFoundError",
    "PluginParseResult",
    "PluginPromptSegments",
    "PluginPipeline",
    "PluginRegistry",
    "StructuredStreamEvent",
    "evaluate_applicable_when",
    "get_plugin_registry",
    "get_plugins_root",
]


def get_plugins_root() -> Path:
    return Path(__file__).parent


def get_plugin_registry(request: Request) -> PluginRegistry:
    return request.app.state.plugin_registry
