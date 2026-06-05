from string import Template

from lumina.plugins.base import Plugin, PluginContext, PluginPromptSegments, ctx_to_template_vars


class ExplainPlugin(Plugin):
    def build_segments(self, ctx: PluginContext) -> PluginPromptSegments:
        vars_ = ctx_to_template_vars(ctx)
        system = Template(self._prompts["system"]).safe_substitute(vars_)

        use_qa = bool(ctx.user_input) or bool(ctx.history)
        user_template_key = "qa" if use_qa else "full"
        user_template = self._prompts["user"][user_template_key]
        user = Template(user_template).safe_substitute(vars_)

        return PluginPromptSegments(system=system, user=user)


PLUGIN_CLASS = ExplainPlugin
