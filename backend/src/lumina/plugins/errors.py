class PluginError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PluginLoadError(PluginError):
    pass


class PluginNotFoundError(PluginError):
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        super().__init__(f"Plugin not found: {plugin_id}")
