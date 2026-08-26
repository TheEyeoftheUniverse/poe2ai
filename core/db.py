"""快照数据库查询层(纯标准库 sqlite3)。"""
import json
import os
import re
import shutil
import sqlite3
import threading


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
        sql = "SELECT * FROM mods WHERE (text LIKE ? OR name_cn LIKE ?)"
        args = [f"%{q}%", f"%{q}%"]
        if item_class:
            sql += " AND item_class = ?"
            args.append(item_class)
        sql += " ORDER BY name_cn, CAST(level AS INTEGER) LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
            return [dict(r) for r in rows]

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
