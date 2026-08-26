"""AstrBot API stub:仅用于插件冒烟测试。"""


class _Filter:
    def command(self, *a, **k):
        def deco(f):
            f._is_command = True
            return f
        return deco

    def command_group(self, *a, **k):
        def deco(f):
            f._is_group = True
            f.command = self.command  # 指令组的子指令注册
            return f
        return deco

    def llm_tool(self, name=None):
        def deco(f):
            f._llm_tool_name = name
            return f
        return deco

    def on_agent_done(self, *a, **k):
        def deco(f):
            f._is_agent_done_hook = True
            return f
        return deco

    class EventMessageType:
        ALL = "all"

    class PermissionType:
        ADMIN = "admin"


filter = _Filter()


class AstrMessageEvent:
    pass


class MessageEventResult:
    pass
