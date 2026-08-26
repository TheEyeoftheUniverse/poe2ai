"""按需拉取兜底:快照查不到时,把查询词当 poe2db 页面 slug 直查整页并入库。

礼貌策略:aiohttp 异步、全局锁限频(默认 2s/请求)、失败静默返回 None。
"""
import asyncio
import json
import re
import time

from .parse import BASE, EQUIP_PAGES, AFFIX_GEN, parse_cards, extract_modsview, \
    html_to_text, page_text, page_title, parse_reforge_recipes

UA = "Mozilla/5.0 (Macintosh) poe2ai-fetcher/1.0 (+github:TheEyeoftheUniverse/poe2ai)"


class Fetcher:
    def __init__(self, db, min_interval: float = 2.0, enabled: bool = True):
        self.db = db
        self.min_interval = max(0.5, float(min_interval))
        self.enabled = enabled
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def _throttled_get(self, url: str, timeout: float = 20.0):
        """限频 GET,返回 HTML 文本;非 200/网络错误返回 None。"""
        import aiohttp
        async with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers={"User-Agent": UA},
                                 timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    if r.status != 200:
                        return None
                    return await r.text(errors="replace")
        except Exception:
            return None

    @staticmethod
    def _slugify(q: str) -> str:
        q = q.strip().replace(" ", "_")
        return re.sub(r"[^A-Za-z0-9_\-一-鿿]", "", q)

    async def fetch_page(self, slug: str):
        """抓取 /cn/<slug> 整页并解析入库,返回是否成功。"""
        if not self.enabled:
            return False
        html = await self._throttled_get(f"{BASE}/cn/{slug}")
        if not html:
            return False
        self._ingest(slug, html)
        return True

    async def try_fetch_item(self, query: str):
        """兜底:把查询词视作页面英文名(slug)直查,命中则入库并返回物品列表。"""
        if not self.enabled:
            return None
        slug = self._slugify(query)
        if not slug or not re.match(r"[A-Za-z]", slug):
            return None  # 只有中文时无法构造英文 slug
        html = await self._throttled_get(f"{BASE}/cn/{slug}")
        if not html:
            return None
        self._ingest(slug, html)
        return self.db.search_item(query, limit=3)

    def _ingest(self, slug: str, html: str):
        """解析整页并入运行库(卡片物品 + ModsView 词条 + 页面文本)。"""
        title = page_title(html, slug)
        name = slug.split("/")[-1]
        self.db.upsert_page("/cn/" + slug, title, "", page_text(html))
        if name == "Reforging_Bench":
            rows = [(p, ph, json.dumps(mats, ensure_ascii=False), " + ".join(n for n, _ in mats))
                    for p, ph, mats in parse_reforge_recipes(html)]
            if rows:
                self.db.upsert_reforges(rows)
        cards = parse_cards(html)
        item_rows = []
        for c in cards:
            nm = (c["unique_name"] or c["text"] or "").strip()
            en = c["href"].rstrip("/").split("/")[-1]
            if not nm or not en:
                continue
            is_unique = bool(c["unique_name"])
            item_rows.append({
                "kind": "unique" if is_unique else "base",
                "name_cn": nm, "name_en": en,
                "base_type": c["type_line"] or EQUIP_PAGES.get(name, ("", ""))[0],
                "category": "unique" if is_unique else EQUIP_PAGES.get(name, ("", ""))[0],
                "icon_url": c["icon"], "page_slug": "/cn/" + slug,
                "props": json.dumps(c["lines"], ensure_ascii=False),
                "text": " | ".join(c["lines"]),
            })
        if item_rows:
            self.db.upsert_items(item_rows)
        mv = extract_modsview(html)
        if mv and name in EQUIP_PAGES:
            cn = EQUIP_PAGES[name][0]
            rows = []
            for grp, lst in mv.items():
                if not isinstance(lst, list):
                    continue
                for e in lst:
                    if not isinstance(e, dict):
                        continue
                    rows.append((
                        grp, e.get("Name", ""), "", cn,
                        AFFIX_GEN.get(str(e.get("ModGenerationTypeID", "")), ""),
                        str(e.get("Level", "")), str(e.get("DropChance", "")),
                        html_to_text(e.get("str", "")), "/cn/" + slug))
            if rows:
                self.db.upsert_mods(rows)
