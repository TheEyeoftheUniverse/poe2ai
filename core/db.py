"""快照数据库查询层(纯标准库 sqlite3)。"""
import json
import os
import re
import shutil
import sqlite3
import threading


# 常见口语 → 官方术语(查询前展开,提升模糊命中率)
SYNONYMS = {
    "血量": ["生命上限"], "生命值": ["生命上限"], "血条": ["生命上限"],
    "回血": ["生命回复"], "回蓝": ["魔力回复"], "蓝量": ["魔力"],
    "攻速": ["攻击速度"], "施法": ["施法速度"],
    "跑速": ["移动速度"], "移速": ["移动速度"],
    "火抗": ["火焰抗性"], "冰抗": ["冰霜抗性"], "雷抗": ["闪电抗性"],
    "电抗": ["闪电抗性"], "全抗": ["抗性"], "暴伤": ["暴击伤害"],
    "防御": ["护甲"], "蓝耗": ["魔力消耗"], "物抗": ["物理伤害减免"],
}

# PoE2 官方中文术语(长词优先扫描;口语 query 中出现的术语直接作为检索词)
CORE_TERMS = [
    "生命上限", "生命回复", "魔力回复", "魔力保留", "魔力消耗", "能量护盾",
    "攻击速度", "施法速度", "移动速度", "暴击伤害", "暴击率", "暴击",
    "闪避值", "闪避", "护甲", "命中", "物理伤害减免",
    "火焰抗性", "冰霜抗性", "闪电抗性", "混沌抗性", "抗性",
    "物理伤害", "火焰伤害", "冰霜伤害", "闪电伤害", "混沌伤害", "元素伤害",
    "力量", "敏捷", "智慧", "全属性",
    "投射物", "召唤生物", "攻击技能等级", "法术技能等级", "近战技能等级",
    "物品稀有度", "稀有度", "物品数量", "精魂", "咒符", "药剂",
    "晕眩", "异常状态", "点燃", "冰缓", "感电", "中毒", "流血", "破甲",
    "符文结界", "品质", "光环", "诅咒", "持续伤害", "击中", "生命", "魔力",
]

# 口语噪声词(剔除后再检索)
STOPWORDS = [
    "加很多", "加大量", "加不少", "很多", "大量", "不少", "极高", "超高",
    "是什么", "哪个", "哪些", "有没有", "帮我", "查一下", "请问", "我记得",
    "好像", "似乎", "记得", "传奇", "暗金", "金装", "装备", "武器", "首饰",
    "poe2", "流放之路", "是什么", "提高", "增加", "降低", "带有", "具有",
    "属性", "效果", "的吗", "的吗", "吗", "呢", "啊", "的", "了", "一", "是", "有", "个",
]


class SnapshotDB:
    """读写运行库。首次运行/快照升级时从插件自带快照复制一份到运行目录。"""

    def __init__(self, runtime_db_path: str, bundled_db_path: str):
        self.path = runtime_db_path
        self.bundled = bundled_db_path
        self._lock = threading.Lock()
        self._ensure_runtime_copy()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def _meta(self, key, conn=None):
        c = conn or self.conn
        try:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if not r:
                return ""
            return r["value"] if not isinstance(r, tuple) else r[0]
        except sqlite3.Error:
            return ""

    def _ensure_runtime_copy(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.bundled):
            raise FileNotFoundError(f"插件快照缺失: {self.bundled}")
        need = not os.path.exists(self.path)
        if not need:
            try:
                src = sqlite3.connect(self.bundled)
                src.row_factory = sqlite3.Row
                src_v = self._meta("version", src)
                src.close()
                dst = sqlite3.connect(self.path)
                dst.row_factory = sqlite3.Row
                dst_v = self._meta("version", dst)
                dst.close()
                need = src_v != dst_v  # 插件升级带来新快照版本
            except sqlite3.Error:
                need = True
        if need:
            for suffix in ("", "-wal", "-shm"):
                p = self.path + suffix
                if os.path.exists(p):
                    os.remove(p)
            shutil.copyfile(self.bundled, self.path)

    def close(self):
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ---------- 查询 ----------

    @staticmethod
    def _en_slug(q: str) -> str:
        """英文查询词转 poe2db slug 形式(Golden Blade -> Golden_Blade)。"""
        q = q.strip().replace(" ", "_").replace("-", "_")
        return re.sub(r"[^A-Za-z0-9_]", "", q)

    def _refine_terms(self, query: str) -> list:
        """口语 query → 有效检索词候选(同义词替换→术语扫描→停用词剔除→滑窗降级)。"""
        q = query.strip()
        if not q:
            return []
        # 1) 口语同义词直接替换成官方术语
        for k, vs in SYNONYMS.items():
            if k in q:
                for v in vs:
                    if v not in q:
                        q = q.replace(k, v)
        # 2) 官方术语扫描(长词优先,去包含冗余)
        hits = [t for t in CORE_TERMS if t in q]
        hits.sort(key=len, reverse=True)
        out, covered = [], ""
        for h in hits:
            if h not in covered:
                out.append(h)
                covered += h
        if out:
            return out
        # 3) 剔除噪声词后的残片
        frag = q
        for w in STOPWORDS:
            frag = frag.replace(w, "")
        if 2 <= len(frag.strip()) <= 8:
            return [frag.strip()]
        # 4) 滑窗降级:长句取 4→3→2 字窗口,取数据库有命中的最长窗口
        for size in (4, 3, 2):
            seen = []
            for i in range(len(q) - size + 1):
                w = q[i:i + size]
                if w not in seen and not any(sw in w for sw in ("的吗", "了", "吗", "呢", " 是", "有 ")):
                    seen.append(w)
            for w in seen[:20]:
                if self._term_hits(w):
                    return [w]
        return [q]

    def _term_hits(self, term: str) -> bool:
        try:
            r = self.conn.execute(
                "SELECT 1 FROM mods WHERE text LIKE ? UNION ALL "
                "SELECT 1 FROM items WHERE text LIKE ? LIMIT 1",
                (f"%{term}%", f"%{term}%")).fetchone()
            return r is not None
        except sqlite3.Error:
            return False

    def search_item(self, query: str, limit: int = 5):
        """按中文名/英文名查装备与 unique 物品。"""
        q = query.strip()
        if not q:
            return []
        en = self._en_slug(q)
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM items WHERE name_cn = ? OR name_en = ?"
                " ORDER BY CASE kind WHEN 'unique' THEN 0 ELSE 1 END LIMIT ?",
                (q, q, limit)).fetchall()
            if not rows:
                rows = self.conn.execute(
                    "SELECT * FROM items WHERE name_cn LIKE ? OR (? != '' AND name_en LIKE ?)"
                    " ORDER BY CASE kind WHEN 'unique' THEN 0 ELSE 1 END,"
                    " LENGTH(name_cn) LIMIT ?",
                    (f"%{q}%", en, f"%{en}%", limit)).fetchall()
            return [dict(r) for r in rows]

    def search_mod(self, query: str, item_class: str = "", limit: int = 20):
        """按词条效果文本/名称查词条(多 tier 聚合)。"""
        q = query.strip()
        if not q:
            return []
        terms = self._refine_terms(q)
        cond = " OR ".join(["text LIKE ?"] * len(terms) + ["name_cn LIKE ?"] * len(terms))
        args = [f"%{t}%" for t in terms] * 2
        sql = f"SELECT * FROM mods WHERE ({cond})"
        if item_class:
            sql += " AND item_class = ?"
            args.append(item_class)
        sql += " ORDER BY name_cn, CAST(level AS INTEGER) LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
            return [dict(r) for r in rows]

    def find_items_by_effect(self, effect: str, kind: str = "unique", limit: int = 20):
        """按效果关键词反查装备(默认暗金),返回含匹配行。"""
        q = effect.strip()
        if not q:
            return []
        terms = self._refine_terms(q)
        cond = " OR ".join(["text LIKE ?"] * len(terms))
        args = [f"%{t}%" for t in terms]
        sql = f"SELECT * FROM items WHERE ({cond})"
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        # 效果行数多的优先(词条更丰富),名称短的优先
        sql += " ORDER BY LENGTH(text) DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            it = dict(r)
            matched = [seg for seg in (it.get("text") or "").split(" | ")
                       if any(t in seg for t in terms)]
            it["matched_lines"] = matched[:2]
            out.append(it)
        return out

    def search_wiki(self, query: str, limit: int = 3):
        """全站页面文本搜索(其余类别兜底)。"""
        q = query.strip()
        if not q:
            return []
        with self._lock:
            rows = self.conn.execute(
                "SELECT slug, title, category, substr(text, 1, 1200) AS excerpt FROM pages"
                " WHERE title LIKE ? OR text LIKE ? ORDER BY (title LIKE ?) DESC, LENGTH(text) LIMIT ?",
                (f"%{q}%", f"%{q}%", f"%{q}%", limit)).fetchall()
            return [dict(r) for r in rows]

    def upsert_page(self, slug, title, category, text):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO pages(slug,title,category,text) VALUES(?,?,?,?)",
                (slug, title, category, text[:200000]))
            self.conn.commit()

    def upsert_items(self, rows):
        with self._lock:
            for r in rows:
                self.conn.execute(
                    "INSERT OR REPLACE INTO items(kind,name_cn,name_en,base_type,category,"
                    "icon_url,page_slug,props,text) VALUES(?,?,?,?,?,?,?,?,?)",
                    (r["kind"], r["name_cn"], r["name_en"], r["base_type"], r["category"],
                     r["icon_url"], r["page_slug"], r["props"], r["text"]))
            self.conn.commit()

    def upsert_mods(self, rows):
        with self._lock:
            self.conn.executemany(
                "INSERT INTO mods(grp,name_cn,name_en,item_class,affix,level,"
                "drop_chance,text,page_slug) VALUES(?,?,?,?,?,?,?,?,?)", rows)
            self.conn.commit()

    def upsert_reforges(self, rows):
        """rows: [(product_cn, product_en, materials_json, materials_text)]"""
        with self._lock:
            self.conn.execute("DELETE FROM reforges")
            self.conn.executemany(
                "INSERT INTO reforges(product_cn,product_en,materials,materials_text)"
                " VALUES(?,?,?,?)", rows)
            self.conn.commit()

    def search_reforge(self, name: str, limit: int = 3):
        """反查重铸配方:该物品作材料能铸出什么/它本身是什么的产物。"""
        q = name.strip()
        if not q:
            return []
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM reforges WHERE materials_text LIKE ? OR product_cn LIKE ?"
                " ORDER BY (materials_text LIKE ?) DESC LIMIT ?",
                (f"%{q}%", f"%{q}%", f"%{q}%", limit)).fetchall()
            return [dict(r) for r in rows]

    def stats(self):
        with self._lock:
            out = {}
            for t in ("items", "mods", "pages"):
                out[t] = self.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            out["uniques"] = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE kind='unique'").fetchone()["c"]
            out["built_at"] = self._meta("built_at")
            out["version"] = self._meta("version")
            return out


def format_item(it) -> str:
    """物品记录 → 人可读紧凑文本(供 LLM 与用户阅读)。"""
    lines = [f"【{it['name_cn']}】{it.get('name_en', '')}"
             + (f" ({it['base_type']})" if it.get("base_type") else "")
             + (f" [{it['category']}]" if it.get("category") else "")]
    try:
        for p in json.loads(it.get("props") or "[]"):
            if p:
                lines.append(f"· {p}")
    except (json.JSONDecodeError, TypeError):
        if it.get("text"):
            lines.append(f"· {it['text']}")
    if it.get("icon_url"):
        lines.append(f"图: {it['icon_url']}")
    return "\n".join(lines)
