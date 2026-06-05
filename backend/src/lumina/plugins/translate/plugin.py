from string import Template

from lumina.plugins.base import Plugin, PluginContext, PluginPromptSegments, ctx_to_template_vars


class TranslatePlugin(Plugin):
    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        vars_ = ctx_to_template_vars(ctx)
        system = Template(self._prompts["system"]).safe_substitute(vars_)
        user = Template(self._prompts["user"]).safe_substitute(vars_)
        return PluginPromptSegments(system=system, user=user)


PLUGIN_CLASS = TranslatePlugin
