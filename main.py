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
from .core.render import render_item_card, render_mods_card, render_wiki_card, render_find_card

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
    async def _send(event, result):
        """主动发送消息(llm_tool 中 yield 会直接刷给用户,故用 send)。"""
        try:
            await event.send(result)
        except Exception:
            pass

    @staticmethod
    def _is_admin(event) -> bool:
        """AstrBot 的 RoleType.ADMIN value 为 'admin';兼容枚举与字符串。"""
        role = getattr(event, "role", None)
        if role is None:
            return False
        v = getattr(role, "value", role)
        return "admin" in str(v).lower()

    # ---------- LLM 工具(自然语言主路径) ----------

    @filter.llm_tool(name="poe2_find_items_by_effect")
    async def find_items_by_effect(self, event: AstrMessageEvent, effect: str, kind: str = "unique"):
        '''按效果反查 Path of Exile 2 的装备(默认查暗金/传奇)。当用户描述想要的效果但不知道装备名称时调用,例如"加很多血量的传奇是什么""哪个暗金加攻速"。effect 必须传从用户话里提炼的精炼效果关键词(2~8字,如"生命上限"、"攻击速度提高"、"闪电抗性"),绝不传用户原话整句。常见口语会自动归一:血量→生命上限、攻速→攻击速度、火抗→火焰抗性。

        Args:
            effect(string): 精炼效果关键词,如"生命上限"
            kind(string): 可选,装备类别:unique=暗金(默认),base=普通基底,留空=全部
        '''
        items = self.db.find_items_by_effect(effect, kind=kind, limit=8)
        if not items:
            return ("没有找到固定效果含「" + effect + "」的"
                    + ("暗金装备" if kind == "unique" else "装备")
                    + "。可换更短的关键词(如「生命上限」「抗性」)。")
        if self.config.get("render_image", True):
            url = await render_find_card(self, effect, items, kind)
            if url:
                await self._send(event, event.image_result(url))
        lines = []
        for it in items[:8]:
            ml = "; ".join(it["matched_lines"][:2])
            lines.append("【" + it["name_cn"] + "】(" + (it["base_type"] or "") + ") " + ml)
        return "\n".join(lines)

    @filter.llm_tool(name="poe2_query_item")
    async def query_item(self, event: AstrMessageEvent, query: str):
        '''按名称查询 Path of Exile 2 的装备、物品或暗金(unique)装备,返回其属性、需求与固定效果,并附带装备图片。仅在已知装备名称时调用(如"猎首是什么效果""Headhunter 属性")。用户只描述效果而不知道名称时,应改用 poe2_find_items_by_effect。传入装备的标准中文名(如"猎首")或英文名(如"Headhunter"),不要传描述性语句。

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
            return f"本地快照与在线兜底均未找到「{query}」。请确认名称,或提醒用户检查拼写。"
        texts = []
        for it in items:
            t = format_item(it)
            rfs = self.db.search_reforge(it["name_cn"])
            if rfs:
                t += "\n· 可重铸: " + "; ".join(
                    f"{r['materials_text']} → {r['product_cn']}" for r in rfs[:2])
            texts.append(t)
        text = "\n\n".join(texts)
        if fetched:
            text = "(在线兜底已抓取并入库)\n" + text
        # FR-3:排版卡片图(含 icon),渲染失败回退裸 icon 外链
        rendered = False
        if self.config.get("render_image", True):
            url = await render_item_card(self, items[0])
            if url:
                await self._send(event, event.image_result(url))
                rendered = True
        if not rendered and items[0].get("icon_url"):
            await self._send(event, event.image_result(items[0]["icon_url"]))
        return text

    @filter.llm_tool(name="poe2_query_mod")
    async def query_mod(self, event: AstrMessageEvent, query: str, item_class: str = ""):
        '''查询 Path of Exile 2 的词条(词缀/mod)各阶级数值区间、出现部位与需求等级。当用户问词条/tier 数值时调用(如"t1攻速是多少""生命上限词条上限")。query 必须传官方效果关键词(2~8字,如"生命上限"、"攻击速度提高"),不传用户原话整句;口语自动归一(血量→生命上限、攻速→攻击速度)。想按效果找具体装备时改用 poe2_find_items_by_effect。

        Args:
            query(string): 官方效果关键词,如"攻击速度提高"
            item_class(string): 可选,物品部位限定,如"单手剑"、"项链"
        '''
        limit = int(self.config.get("max_mods", 20))
        mods = self.db.search_mod(query, item_class=item_class, limit=limit)
        if not mods:
            return "本地快照未找到词条「" + query + "」。可尝试换用效果文本关键词,如「生命上限」「攻击速度提高」"
        by_name = {}
        for m in mods:
            by_name.setdefault(m["name_cn"] or query, []).append(m)
        if self.config.get("render_image", True):
            groups = [(name, group[:8]) for name, group in list(by_name.items())[:5]]
            url = await render_mods_card(self, query, groups, item_class)
            if url:
                await self._send(event, event.image_result(url))
        lines = []
        for name, group in list(by_name.items())[:5]:
            parts = []
            for m in group[:8]:
                seg = m["text"]
                extra = [x for x in (m["item_class"], m["affix"], "需求" + m["level"] + "级") if x]
                parts.append(seg + " (" + ", ".join(extra) + ")" if extra else seg)
            lines.append("【" + name + "】\n" + "\n".join(parts))
        return "\n\n".join(lines)

    @filter.llm_tool(name="poe2_search_wiki")
    async def search_wiki(self, event: AstrMessageEvent, query: str):
        '''在 poe2db.tw 全站本地快照中搜索非装备类内容:技能宝石、怪物、Boss、地图/路石、任务、升华、机制说明等。仅在问题不涉及装备/词条/效果找装备时调用(那些用 poe2_query_item / poe2_query_mod / poe2_find_items_by_effect)。query 必须传 2~6 字精炼关键词(如"升华"、"电球"、"断金"),绝不传用户原话整句——本工具是精确子串匹配,长句必然搜不到。

        Args:
            query(string): 2~6 字精炼关键词
        '''
        pages = self.db.search_wiki(query, limit=3)
        if not pages:
            return "全站快照未搜到「" + query + "」。"
        if self.config.get("render_image", True):
            url = await render_wiki_card(self, query, pages)
            if url:
                await self._send(event, event.image_result(url))
        out = []
        for p in pages:
            out.append("【" + p["title"] + "】(" + p["slug"] + ")\n" + p["excerpt"])
        return "\n\n".join(out)

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
            if self.config.get("render_image", True):
                by_name = {}
                for m in mods:
                    by_name.setdefault(m["name_cn"] or extra, []).append(m)
                groups = [(n, g[:8]) for n, g in list(by_name.items())[:5]]
                url = await render_mods_card(self, extra, groups)
                if url:
                    yield event.image_result(url)
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
            if self.config.get("render_image", True):
                url = await render_item_card(self, it)
                if url:
                    yield event.image_result(url)
                    return
            if it.get("icon_url"):
                yield event.image_result(it["icon_url"])
            yield event.plain_result(format_item(it))
        else:
            yield event.plain_result(
                "poe2ai 用法:\n/poe2 <装备名> — 直查装备(带图)\n"
                "/poe2 词条 <效果> — 查词条各 tier\n"
                "/poe2 刷新 <页> — 重拉指定页面\n/poe2 统计 — 快照统计\n"
                "日常提问直接用自然语言即可,LLM 会自动调用查询工具。")
