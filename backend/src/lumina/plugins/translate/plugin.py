from string import Template

from lumina.plugins.base import Plugin, PluginContext, PluginPromptSegments, ctx_to_template_vars


class TranslatePlugin(Plugin):
    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        vars_ = ctx_to_template_vars(ctx)
        system = Template(self._prompts["system"]).safe_substitute(vars_)
        user_template_key = "with_input" if ctx.user_input else "plain"
        user = Template(self._prompts["user"][user_template_key]).safe_substitute(vars_)
        return PluginPromptSegments(system=system, user=user)


PLUGIN_CLASS = TranslatePlugin
