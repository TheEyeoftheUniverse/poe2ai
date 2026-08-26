"""poe2ai — poe2db.tw 全站快照 + 自然语言查询的 AstrBot 插件。

数据形态:仓库自带全站快照(SQLite)为主,本地查不到时按需抓取 poe2db.tw 整页兜底入库;
图片一律走 cdn.poe2db.tw 外链,本地零图片存储。
查询以 llm_tool 注册,用户自然语言提问时由宿主 LLM 自主调用。
"""
import os

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .core.db import SnapshotDB, format_item
from .core.fetcher import Fetcher

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_DB = os.path.join(PLUGIN_DIR, "data", "poe2db.sqlite3")


def _runtime_dir() -> str:
    """优先用 AstrBot 插件数据目录(StarTools),不可用时退回插件目录下 data_runtime/。"""
    try:
        from astrbot.api.star import StarTools
        d = StarTools.get_data_dir("poe2ai")
        return str(d)
    except Exception:
        d = os.path.join(PLUGIN_DIR, "data_runtime")
        os.makedirs(d, exist_ok=True)
        return d


@register("poe2ai", "TheEyeoftheUniverse",
          "poe2db.tw 全站快照本地查询:装备/词条/全站内容,自然语言直问直答", "1.0.0")
class Poe2Ai(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        runtime_db = os.path.join(_runtime_dir(), "poe2db.sqlite3")
        self.db = SnapshotDB(runtime_db, BUNDLED_DB)
        self.fetcher = Fetcher(
            self.db,
            min_interval=self.config.get("fetch_interval", 2.0),
            enabled=self.config.get("enable_fetch", True),
        )
        s = self.db.stats()
        logger.info(f"poe2ai 快照就绪: 物品 {s['items']}(含暗金 {s['uniques']}) / "
                    f"词条 {s['mods']} / 页面 {s['pages']} @ {s['built_at']}")

    async def terminate(self):
        self.db.close()

    @staticmethod
    def _is_admin(event) -> bool:
        """AstrBot 的 RoleType.ADMIN value 为 'admin';兼容枚举与字符串。"""
        role = getattr(event, "role", None)
        if role is None:
            return False
        v = getattr(role, "value", role)
        return "admin" in str(v).lower()

    # ---------- LLM 工具(自然语言主路径) ----------

    @filter.llm_tool(name="poe2_query_item")
    async def query_item(self, event: AstrMessageEvent, query: str):
        '''查询 Path of Exile 2 的装备、物品或暗金(unique)装备,返回其属性、需求与固定效果,并附带装备图片。当用户询问"某装备是什么/什么效果/属性"时调用。传入装备的标准中文名(如"猎首")或英文名(如"Headhunter")。

        Args:
            query(string): 装备/物品的中文名或英文名
        '''
        limit = int(self.config.get("max_items", 5))
        items = self.db.search_item(query, limit=limit)
        fetched = False
        if not items:
            items = await self.fetcher.try_fetch_item(query)
            fetched = bool(items)
        if not items:
            yield event.plain_result(f"本地快照与在线兜底均未找到「{query}」。请确认名称,或提醒用户检查拼写。")
            return
        text = "\n\n".join(format_item(it) for it in items)
        if fetched:
            text = "(在线兜底已抓取并入库)\n" + text
        # FR-3:信息与图片一起发送(icon 为 cdn 外链)
        for it in items[:1]:
            if it.get("icon_url"):
                yield event.image_result(it["icon_url"])
        yield event.plain_result(text)

    @filter.llm_tool(name="poe2_query_mod")
    async def query_mod(self, event: AstrMessageEvent, query: str, item_class: str = ""):
        '''查询 Path of Exile 2 的词条(词缀/mod),返回其各阶级(tier)的数值区间、出现部位与需求等级。当用户询问"某词条/t1攻速/最大生命值是多少"时调用。传入词条的效果描述(如"攻击速度提高"、"最大生命"),可选物品部位。

        Args:
            query(string): 词条的效果文本或名称,如"攻击速度提高"
            item_class(string): 可选,物品部位限定,如"单手剑"、"项链"
        '''
        limit = int(self.config.get("max_mods", 20))
        mods = self.db.search_mod(query, item_class=item_class, limit=limit)
        if not mods:
            yield event.plain_result(f"本地快照未找到词条「{query}」。可尝试换用效果文本关键词,如「生命上限」「攻击速度提高」")
            return
        by_name = {}
        for m in mods:
            by_name.setdefault(m["name_cn"] or query, []).append(m)
        lines = []
        for name, group in list(by_name.items())[:5]:
            parts = []
            for m in group[:8]:
                seg = f"{m['text']}"
                extra = [x for x in (m["item_class"], m["affix"], f"需求{m['level']}级") if x]
                parts.append(seg + f" ({', '.join(extra)})" if extra else seg)
            lines.append(f"【{name}】\n" + "\n".join(parts))
        yield event.plain_result("\n\n".join(lines))

    @filter.llm_tool(name="poe2_search_wiki")
    async def search_wiki(self, event: AstrMessageEvent, query: str):
        '''在 poe2db.tw 全站本地快照(技能宝石、怪物、地图、任务、机制说明等全部内容)中搜索。当问题不属于装备/词条(如技能、天赋、Boss、机制解释)时调用。

        Args:
            query(string): 搜索关键词
        '''
        pages = self.db.search_wiki(query, limit=3)
        if not pages:
            yield event.plain_result(f"全站快照未搜到「{query}」。")
            return
        out = []
        for p in pages:
            out.append(f"【{p['title']}】({p['slug']})\n{p['excerpt']}")
        yield event.plain_result("\n\n".join(out))

    # ---------- 运维指令 ----------

    @filter.command("poe2")
    async def poe2(self, event: AstrMessageEvent, name: str = "", extra: str = ""):
        """poe2db 快照直查: /poe2 <装备名> ;词条/刷新/统计为子功能"""
        if name == "统计":
            s = self.db.stats()
            yield event.plain_result(
                "poe2db 快照 v" + s["version"] + "(构建于 " + s["built_at"] + "):\n"
                "物品 " + str(s["items"]) + "(含暗金 " + str(s["uniques"]) + ") / "
                "词条 " + str(s["mods"]) + " / 页面 " + str(s["pages"]))
        elif name == "刷新":
            if not self._is_admin(event):
                yield event.plain_result("刷新是运维指令,仅管理员可用。")
                return
            page = extra or "Unique_item"
            yield event.plain_result("正在从 poe2db.tw 拉取 /cn/" + page + " …")
            ok = await self.fetcher.fetch_page(page)
            if ok:
                s = self.db.stats()
                yield event.plain_result(
                    "已刷新 /cn/" + page + " 并入库。当前:物品 " + str(s["items"])
                    + "/词条 " + str(s["mods"]) + "/页面 " + str(s["pages"]))
            else:
                yield event.plain_result(
                    "拉取 /cn/" + page + " 失败(页面不存在或网络错误)。"
                    "全量重建请用仓库内 tools/crawl.py + build_snapshot.py。")
        elif name == "词条":
            if not extra:
                yield event.plain_result("用法: /poe2 词条 <效果文本>,如 /poe2 词条 攻击速度提高")
                return
            mods = self.db.search_mod(extra, limit=15)
            if not mods:
                yield event.plain_result("没找到词条「" + extra + "」")
                return
            parts = [m["text"] + " (" + m["item_class"] + "·" + m["affix"]
                     + "·需求" + m["level"] + "级)" for m in mods[:12]]
            yield event.plain_result("\n".join(parts))
        elif name:
            items = self.db.search_item(name, limit=1)
            if not items:
                items = await self.fetcher.try_fetch_item(name)
            if not items:
                yield event.plain_result("没找到「" + name + "」")
                return
            it = items[0]
            if it.get("icon_url"):
                yield event.image_result(it["icon_url"])
            yield event.plain_result(format_item(it))
        else:
            yield event.plain_result(
                "poe2ai 用法:\n/poe2 <装备名> — 直查装备(带图)\n"
                "/poe2 词条 <效果> — 查词条各 tier\n"
                "/poe2 刷新 <页> — 重拉指定页面\n/poe2 统计 — 快照统计\n"
                "日常提问直接用自然语言即可,LLM 会自动调用查询工具。")
