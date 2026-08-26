#!/usr/bin/env python3
"""poe2ai 快照构建器:把 tools/.cache/pages/*.html 解析进 data/poe2db.sqlite3。

数据源与结构(2026-08-27 实测定稿):
- 装备类型页(如 /cn/Bows):页面内嵌 new ModsView({...}) JSON 为词条真源(各来源组:
  normal/essence/socketable/bonded/...),HTML 卡片 div.col>div.d-flex 为基底真源。
- Unique_item 索引页:同一卡片结构内嵌全部 unique 物品(uniqueName/uniqueTypeLine/icon/固定词条)。
- 其余页面:通用抽取标题+正文文本入 pages 表,全站可搜。

用法: python3 tools/build_snapshot.py [--cache-dir tools/.cache/pages] [--db data/poe2db.sqlite3]
可重复执行(重建数据库)。
"""
import argparse
import html as html_mod
import json
import os
import re
import sqlite3
import sys
import time
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from core.parse import (EQUIP_PAGES, AFFIX_GEN, parse_cards, extract_modsview,
                        html_to_text, page_text, page_title, TITLE_RE)

def slug_of(fname):
    return "/cn/" + fname[:-5].replace("__", "/")


def build(cache_dir, db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
    DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS mods; DROP TABLE IF EXISTS pages; DROP TABLE IF EXISTS meta;
    CREATE TABLE items(
      id INTEGER PRIMARY KEY, kind TEXT, name_cn TEXT, name_en TEXT,
      base_type TEXT, category TEXT, icon_url TEXT, page_slug TEXT,
      props TEXT, text TEXT);
    CREATE INDEX idx_items_name ON items(name_cn);
    CREATE INDEX idx_items_en ON items(name_en);
    CREATE TABLE mods(
      id INTEGER PRIMARY KEY, grp TEXT, name_cn TEXT, name_en TEXT,
      item_class TEXT, affix TEXT, level TEXT, drop_chance TEXT,
      text TEXT, page_slug TEXT);
    CREATE INDEX idx_mods_name ON mods(name_cn);
    CREATE TABLE pages(
      slug TEXT PRIMARY KEY, title TEXT, category TEXT, text TEXT);
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)

    files = sorted(f for f in os.listdir(cache_dir) if f.endswith(".html"))
    stat = {"items": 0, "uniques": 0, "mods": 0, "pages": 0}
    t0 = time.time()
    for fname in files:
        slug = slug_of(fname)
        name = fname[:-5]
        try:
            raw = open(os.path.join(cache_dir, fname), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        mt = TITLE_RE.search(raw)
        title = html_mod.unescape(mt.group(1).split("-")[0].strip()) if mt else name

        if name in EQUIP_PAGES:
            cn, big = EQUIP_PAGES[name]
            # 词条:ModsView JSON
            mv = extract_modsview(raw)
            if mv:
                for grp, lst in mv.items():
                    if not isinstance(lst, list):
                        continue
                    for e in lst:
                        if not isinstance(e, dict):
                            continue
                        c.execute(
                            "INSERT INTO mods(grp,name_cn,name_en,item_class,affix,level,drop_chance,text,page_slug)"
                            " VALUES(?,?,?,?,?,?,?,?,?)",
                            (grp, e.get("Name", ""), "",
                             cn, AFFIX_GEN.get(str(e.get("ModGenerationTypeID", "")), ""),
                             str(e.get("Level", "")), str(e.get("DropChance", "")),
                             html_to_text(e.get("str", "")), slug))
                        stat["mods"] += 1
            # 基底:卡片
            for card in parse_cards(raw):
                nm = (card.get("unique_name") or card.get("text") or "").strip()
                en = card.get("href", "").rstrip("/").split("/")[-1]
                if not nm or not en:
                    continue
                c.execute(
                    "INSERT INTO items(kind,name_cn,name_en,base_type,category,icon_url,page_slug,props,text)"
                    " VALUES('base',?,?,?,?,?,?,?,?)",
                    (nm, en, cn, big, card.get("icon", ""), slug,
                     json.dumps(card.get("lines", []), ensure_ascii=False),
                     " | ".join(card.get("lines", []))))
                stat["items"] += 1
        elif name == "Unique_item":
            for card in parse_cards(raw):
                nm = (card.get("unique_name") or "").strip()
                if not nm:
                    continue
                en = card.get("href", "").rstrip("/").split("/")[-1]
                c.execute(
                    "INSERT INTO items(kind,name_cn,name_en,base_type,category,icon_url,page_slug,props,text)"
                    " VALUES('unique',?,?,?,?,?,?,?,?)",
                    (nm, en, card.get("type_line", ""), "unique", card.get("icon", ""),
                     "/cn/" + en if en else slug,
                     json.dumps(card.get("lines", []), ensure_ascii=False),
                     " | ".join(card.get("lines", []))))
                stat["uniques"] += 1
        # 所有页入通用表
        txt = page_text(raw)
        cat = EQUIP_PAGES.get(name, (None, None))
        c.execute("INSERT OR REPLACE INTO pages(slug,title,category,text) VALUES(?,?,?,?)",
                  (slug, title, cat[0] or "", txt[:200000]))
        stat["pages"] += 1

    c.execute("INSERT INTO meta VALUES('built_at',?)", (time.strftime("%Y-%m-%d %H:%M:%S"),))
    c.execute("INSERT INTO meta VALUES('pages',?)", (str(stat["pages"]),))
    c.execute("INSERT INTO meta VALUES('version',?)", (time.strftime("%Y%m%d"),))
    conn.commit()
    conn.close()
    print(f"构建完成 {time.time()-t0:.0f}s: pages={stat['pages']} items={stat['items']} "
          f"uniques={stat['uniques']} mods={stat['mods']}")
    print(f"DB: {db_path} ({os.path.getsize(db_path)/1e6:.1f}MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=os.path.join(HERE, ".cache", "pages"))
    ap.add_argument("--db", default=os.path.join(HERE, "..", "data", "poe2db.sqlite3"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    build(args.cache_dir, os.path.abspath(args.db))
