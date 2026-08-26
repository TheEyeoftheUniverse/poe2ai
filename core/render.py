"""查询结果 → poe2db 风格 HTML 卡片图(经 AstrBot html_render 截图)。

三种卡片:物品 tooltip 卡(装备/暗金)、词条 tier 表、全站搜索卡。
渲染失败统一返回 None,调用方回退纯文本。
"""
import json

ITEM_TMPL = """
<div class="wrap">
  <div class="card">
    <div class="head">
      {% if item.icon_url %}<img class="icon" src="{{ item.icon_url }}" onerror="this.style.display='none'">{% endif %}
      <div class="titles">
        <div class="name {{ 'unique' if item.kind == 'unique' else 'normal' }}">{{ item.name_cn }}</div>
        {% if item.base_type %}<div class="typeline">{{ item.base_type }}</div>{% endif %}
      </div>
    </div>
    <div class="sep"></div>
    {% for p in lines %}
      {% if p.startswith('需求') %}
        <div class="req">{{ p }}</div>
      {% elif '—' in p %}
        <div class="mod">{{ p }}</div>
      {% else %}
        <div class="prop">{{ p }}</div>
      {% endif %}
    {% endfor %}
    {% if reforges %}
      <div class="sep"></div>
      <div class="rtitle">⚙ 重铸</div>
      {% for rf in reforges %}
        <div class="rforge">{{ rf.materials_text }} → <b>{{ rf.product_cn }}</b></div>
      {% endfor %}
    {% endif %}
    <div class="sep"></div>
    <div class="foot">{{ item.name_en }} · 数据 poe2db.tw · 快照 {{ version }}</div>
  </div>
</div>
<style>
  html, body { margin: 0; padding: 0; background: #121218; }
  .wrap { width: 100%; box-sizing: border-box; padding: 14px; background: #121218;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { width: 100%; box-sizing: border-box; background: #0c0c10; border: 1px solid #33333c;
          border-radius: 14px; padding: 24px 28px 16px; }
  .head { display: flex; align-items: center; gap: 18px; }
  .icon { width: 92px; height: 92px; object-fit: contain; border-radius: 8px; background: #16161c; }
  .name { font-size: 34px; font-weight: 700; }
  .name { font-size: 22px; font-weight: 700; }
  .name.unique { color: #af6025; }
  .name.normal { color: #d0d0d0; }
  .typeline { font-size: 22px; color: #af6025; margin-top: 4px; }
  .sep { height: 2px; background: #33333c; margin: 14px 0; }
  .req { color: #7f7f7f; font-size: 20px; line-height: 1.8; }
  .prop { color: #c8c8c8; font-size: 21px; line-height: 1.8; }
  .mod { color: #8888ff; font-size: 21px; line-height: 1.8; }
  .foot { color: #55555e; font-size: 15px; margin-top: 10px; }
  .rtitle { color: #d0b86a; font-size: 20px; font-weight: 700; }
  .rforge { color: #c8c8c8; font-size: 19px; line-height: 1.8; }
</style>
"""

MODS_TMPL = """
<div class="wrap">
  <div class="card">
    <div class="title">{{ query }}</div>
    {% if item_class %}<div class="sub">限定部位:{{ item_class }}</div>{% endif %}
    {% for name, group in groups %}
      <div class="sep"></div>
      <div class="gname">{{ name }}</div>
      {% for m in group %}
        <div class="row">
          <div class="text">{{ m.text }}</div>
          <div class="meta">{{ m.affix }} · 需求{{ m.level }}级</div>
        </div>
      {% endfor %}
    {% endfor %}
    <div class="sep"></div>
    <div class="foot">词条数据 poe2db.tw · 快照 {{ version }}</div>
  </div>
</div>
<style>
  html, body { margin: 0; padding: 0; background: #121218; }
  .wrap { width: 100%; box-sizing: border-box; padding: 14px; background: #121218;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { width: 100%; box-sizing: border-box; background: #0c0c10; border: 1px solid #33333c;
          border-radius: 14px; padding: 24px 28px 16px; }
  .title { font-size: 30px; font-weight: 700; color: #d0b86a; }
  .sub { font-size: 18px; color: #7f7f7f; margin-top: 4px; }
  .sep { height: 2px; background: #33333c; margin: 14px 0; }
  .gname { color: #af6025; font-size: 20px; margin-bottom: 6px; }
  .row { padding: 4px 0; border-bottom: 1px dashed #22222a; }
  .row:last-child { border-bottom: none; }
  .text { color: #8888ff; font-size: 20px; }
  .meta { color: #7f7f7f; font-size: 16px; margin-top: 2px; }
  .foot { color: #55555e; font-size: 15px; margin-top: 10px; }
  .rtitle { color: #d0b86a; font-size: 20px; font-weight: 700; }
  .rforge { color: #c8c8c8; font-size: 19px; line-height: 1.8; }
</style>
"""

WIKI_TMPL = """
<div class="wrap">
  <div class="card">
    <div class="title">全站搜索:{{ query }}</div>
    {% for p in pages %}
      <div class="sep"></div>
      <div class="pt">{{ p.title }}</div>
      <div class="ps">{{ p.slug }}</div>
      <div class="pe">{{ p.excerpt }}</div>
    {% endfor %}
    <div class="sep"></div>
    <div class="foot">数据 poe2db.tw · 快照 {{ version }}</div>
  </div>
</div>
<style>
  html, body { margin: 0; padding: 0; background: #121218; }
  .wrap { width: 100%; box-sizing: border-box; padding: 14px; background: #121218;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { width: 100%; box-sizing: border-box; background: #0c0c10; border: 1px solid #33333c;
          border-radius: 14px; padding: 24px 28px 16px; }
  .title { font-size: 30px; font-weight: 700; color: #d0b86a; }
  .sep { height: 2px; background: #33333c; margin: 14px 0; }
  .pt { color: #c8c8c8; font-size: 24px; font-weight: 600; }
  .ps { color: #55555e; font-size: 15px; }
  .pe { color: #9a9aa4; font-size: 18px; line-height: 1.7; margin-top: 6px;
        display: -webkit-box; -webkit-line-clamp: 8; -webkit-box-orient: vertical; overflow: hidden; }
  .foot { color: #55555e; font-size: 15px; margin-top: 10px; }
  .rtitle { color: #d0b86a; font-size: 20px; font-weight: 700; }
  .rforge { color: #c8c8c8; font-size: 19px; line-height: 1.8; }
</style>
"""


def item_lines(item) -> list:
    """物品 props JSON → 行列表(去空)。"""
    try:
        return [p for p in json.loads(item.get("props") or "[]") if p]
    except (json.JSONDecodeError, TypeError):
        return [t for t in (item.get("text") or "").split(" | ") if t]


async def render_item_card(plugin, item) -> "str | None":
    try:
        return await plugin.html_render(
            ITEM_TMPL, {"item": item, "lines": item_lines(item),
                        "reforges": plugin.db.search_reforge(item["name_cn"]),
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True, "type": "png"})
    except Exception:
        return None


async def render_mods_card(plugin, query, groups, item_class="") -> "str | None":
    try:
        return await plugin.html_render(
            MODS_TMPL, {"query": query, "groups": groups, "item_class": item_class,
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True, "type": "png"})
    except Exception:
        return None


async def render_wiki_card(plugin, query, pages) -> "str | None":
    try:
        return await plugin.html_render(
            WIKI_TMPL, {"query": query, "pages": pages,
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True, "type": "png"})
    except Exception:
        return None


FIND_TMPL = """
<div class="wrap">
  <div class="card">
    <div class="title">效果匹配:{{ effect }}</div>
    <div class="sub">按固定效果反查{{ '暗金装备' if kind == 'unique' else '装备基底' }} · 共 {{ items|length }} 件</div>
    <div class="grid">
      {% for c in cells %}
        <div class="cell">
          <div class="head">
            {% if c.item.icon_url %}<img class="icon" src="{{ c.item.icon_url }}" onerror="this.style.display='none'">{% endif %}
            <div>
              <div class="name">{{ c.item.name_cn }}</div>
              {% if c.item.base_type %}<div class="bt">{{ c.item.base_type }}</div>{% endif %}
            </div>
          </div>
          {% for line, hit in c.lines %}
            <div class="{{ 'ml' if hit else 'pl' }}">{{ line }}</div>
          {% endfor %}
        </div>
      {% endfor %}
    </div>
    <div class="foot">数据 poe2db.tw · 快照 {{ version }}</div>
  </div>
</div>
<style>
  html, body { margin: 0; padding: 0; background: #121218; }
  .wrap { width: 100%; box-sizing: border-box; padding: 14px;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { width: 100%; box-sizing: border-box; background: #0c0c10; border: 1px solid #33333c;
          border-radius: 14px; padding: 24px 28px 16px; }
  .title { font-size: 30px; font-weight: 700; color: #d0b86a; }
  .sub { font-size: 18px; color: #7f7f7f; margin: 4px 0 14px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .cell { background: #16161c; border: 1px solid #2a2a33; border-radius: 10px; padding: 12px 14px; }
  .head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .icon { width: 44px; height: 44px; object-fit: contain; border-radius: 6px; background: #0c0c10; flex-shrink: 0; }
  .name { font-size: 18px; font-weight: 700; color: #af6025; line-height: 1.3; }
  .bt { font-size: 12px; color: #7f7f7f; }
  .ml { color: #8888ff; font-size: 13px; line-height: 1.6; font-weight: 600; }
  .pl { color: #b9b9c2; font-size: 13px; line-height: 1.6; }
  .foot { color: #55555e; font-size: 15px; margin-top: 12px; }
</style>
"""


async def render_find_card(plugin, effect, items, kind="unique") -> "str | None":
    """列表卡:每件装备一张完整迷你卡(全部效果行,匹配行高亮),自适应 3~4 列网格。"""
    cells = []
    for it in items:
        lines = []
        for line in item_lines(it):
            hit = line in (it.get("matched_lines") or [])
            lines.append((line, hit))
        cells.append({"item": it, "lines": lines})
    try:
        return await plugin.html_render(
            FIND_TMPL, {"effect": effect, "cells": cells, "kind": kind,
                        "items": items, "version": plugin.db.stats()["version"]},
            options={"full_page": True, "type": "png"})
    except Exception:
        return None
