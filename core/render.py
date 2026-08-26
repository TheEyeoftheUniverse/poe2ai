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
    <div class="sep"></div>
    <div class="foot">{{ item.name_en }} · 数据 poe2db.tw · 快照 {{ version }}</div>
  </div>
</div>
<style>
  .wrap { width: 460px; padding: 10px; background: transparent;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { background: #0c0c10ee; border: 1px solid #33333c; border-radius: 10px;
          padding: 16px 18px 12px; }
  .head { display: flex; align-items: center; gap: 14px; }
  .icon { width: 64px; height: 64px; object-fit: contain; border-radius: 6px; background: #16161c; }
  .name { font-size: 22px; font-weight: 700; }
  .name.unique { color: #af6025; }
  .name.normal { color: #d0d0d0; }
  .typeline { font-size: 15px; color: #af6025; margin-top: 2px; }
  .sep { height: 1px; background: #33333c; margin: 10px 0; }
  .req { color: #7f7f7f; font-size: 14px; line-height: 1.7; }
  .prop { color: #c8c8c8; font-size: 15px; line-height: 1.7; }
  .mod { color: #8888ff; font-size: 15px; line-height: 1.7; }
  .foot { color: #55555e; font-size: 11px; margin-top: 8px; }
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
  .wrap { width: 460px; padding: 10px; background: transparent;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { background: #0c0c10ee; border: 1px solid #33333c; border-radius: 10px; padding: 16px 18px 12px; }
  .title { font-size: 20px; font-weight: 700; color: #d0b86a; }
  .sub { font-size: 13px; color: #7f7f7f; margin-top: 2px; }
  .sep { height: 1px; background: #33333c; margin: 10px 0; }
  .gname { color: #af6025; font-size: 14px; margin-bottom: 4px; }
  .row { padding: 4px 0; border-bottom: 1px dashed #22222a; }
  .row:last-child { border-bottom: none; }
  .text { color: #8888ff; font-size: 14px; }
  .meta { color: #7f7f7f; font-size: 12px; margin-top: 1px; }
  .foot { color: #55555e; font-size: 11px; margin-top: 8px; }
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
  .wrap { width: 460px; padding: 10px; background: transparent;
          font-family: "PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
  .card { background: #0c0c10ee; border: 1px solid #33333c; border-radius: 10px; padding: 16px 18px 12px; }
  .title { font-size: 20px; font-weight: 700; color: #d0b86a; }
  .sep { height: 1px; background: #33333c; margin: 10px 0; }
  .pt { color: #c8c8c8; font-size: 16px; font-weight: 600; }
  .ps { color: #55555e; font-size: 11px; }
  .pe { color: #9a9aa4; font-size: 13px; line-height: 1.6; margin-top: 4px;
        display: -webkit-box; -webkit-line-clamp: 8; -webkit-box-orient: vertical; overflow: hidden; }
  .foot { color: #55555e; font-size: 11px; margin-top: 8px; }
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
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True})
    except Exception:
        return None


async def render_mods_card(plugin, query, groups, item_class="") -> "str | None":
    try:
        return await plugin.html_render(
            MODS_TMPL, {"query": query, "groups": groups, "item_class": item_class,
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True})
    except Exception:
        return None


async def render_wiki_card(plugin, query, pages) -> "str | None":
    try:
        return await plugin.html_render(
            WIKI_TMPL, {"query": query, "pages": pages,
                        "version": plugin.db.stats()["version"]},
            options={"full_page": True})
    except Exception:
        return None
