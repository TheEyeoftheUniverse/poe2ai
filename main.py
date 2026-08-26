from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@register("poe2ai", "TheEyeoftheUniverse", "poe2ai AstrBot 插件", "1.0.0")
class Poe2Ai(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("poe2ai")
    async def poe2ai(self, event: AstrMessageEvent):
        """poe2ai 插件入口指令"""
        yield event.plain_result("poe2ai 插件已就绪")
