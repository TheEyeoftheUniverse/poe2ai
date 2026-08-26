"""poe2db.tw 页面解析(构建与运行时兜底共用)。

页面数据形态(2026-08-27 实测定稿):
- 装备类型页:词条在内嵌 new ModsView({...}) JSON;基底与 unique 物品在 div.col>div.d-flex 卡片。
- 其余页面:服务端渲染,做通用文本抽取。
"""
import html as html_mod
import json
import re

BASE = "https://poe2db.tw"

EQUIP_PAGES = {  # 装备类型 slug -> (中文名, 大类)
    "Bows": ("弓", "武器"), "Crossbows": ("战弩", "武器"), "Quarterstaves": ("长杖", "武器"),
    "Wands": ("魔杖", "武器"), "Sceptres": ("权杖", "武器"),
    "One_Hand_Maces": ("单手锤", "武器"), "Two_Hand_Maces": ("双手锤", "武器"),
    "One_Hand_Axes": ("单手斧", "武器"), "Two_Hand_Axes": ("双手斧", "武器"),
    "One_Hand_Swords": ("单手剑", "武器"), "Two_Hand_Swords": ("双手剑", "武器"),
    "Spears": ("战矛", "武器"), "Traps": ("陷阱", "武器"),
    "Helmets": ("头盔", "护甲"), "Body_Armours": ("护甲", "护甲"), "Gloves": ("手套", "护甲"),
    "Boots": ("鞋子", "护甲"), "Shields": ("盾牌", "护甲"),
    "Amulets": ("项链", "饰品"), "Rings": ("戒指", "饰品"), "Belts": ("腰带", "饰品"),
    "Quivers": ("箭袋", "副手"), "Jewels": ("珠宝", "珠宝"), "Charms": ("咒符", "咒符"),
    "Flasks": ("药剂", "药剂"),
}
AFFIX_GEN = {"1": "前缀", "2": "后缀", "5": "腐化", "3": "附魔", "4": "重铸"}

CARD_SPLIT = re.compile(r'<div class="col"><div class="d-flex')
PROP_RE = re.compile(r'<div class="(property|explicitMod|implicitMod|requirements)"[^>]*>(.*?)</div>', re.S)
UNIQUE_NAME_RE = re.compile(r'<span class="uniqueName">(.*?)</span>', re.S)
TYPE_LINE_RE = re.compile(r'<span class="uniqueTypeLine">(.*?)</span>', re.S)
IMG_RE = re.compile(r'<img[^>]+src="(https?://[^"]+)"')
A_RE = re.compile(r'<a[^>]+href="([^"#][^"]*)"[^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r'<[^>]+>')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
NAV_MARK = "简体中文 US"


def _clean(s):
    return re.sub(r"\s+", " ", html_mod.unescape(TAG_RE.sub("", s))).strip()


def parse_cards(html):
    """解析 div.col>div.d-flex 卡片(装备基底/unique 物品),字段级正则提取。"""
    cards = []
    for blk in CARD_SPLIT.split(html)[1:]:
        blk = blk.split('<div class="col"><div class="d-flex')[0]
        img = IMG_RE.search(blk)
        un = UNIQUE_NAME_RE.search(blk)
        tl = TYPE_LINE_RE.search(blk)
        href, text = "", ""
        for m in A_RE.finditer(blk):   # 第一个有非空文本的链接 = 主条目
            if _clean(m.group(2)):
                href, text = m.group(1), _clean(m.group(2))
                break
        props = [_clean(p[1]) for p in PROP_RE.findall(blk) if _clean(p[1])]
        if img or un:
            cards.append({"icon": img.group(1) if img else "",
                          "unique_name": _clean(un.group(1)) if un else "",
                          "type_line": _clean(tl.group(1)) if tl else "",
                          "href": href, "text": text, "lines": props})
    return cards


def extract_modsview(html):
    """提取页面内嵌 new ModsView({...}) JSON,失败返回 None。"""
    m = re.search(r"new\s+ModsView\s*\(", html)
    if not m:
        return None
    i = html.find("{", m.end() - 1)
    depth, j, in_str, esc = 0, i, None, False
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_str:
                in_str = None
        else:
            if c in "\"'":
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
        j += 1
    try:
        return json.loads(html[i:j + 1])
    except json.JSONDecodeError:
        return None


def html_to_text(s):
    """词条 str 字段的 HTML 转纯文本(保留数值区间与 —)。"""
    if not s:
        return ""
    return _clean(s)


def page_text(html):
    """整页可见正文文本(去 script/style/标签,截掉导航头)。"""
    h = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    h = re.sub(r"<style[^>]*>.*?</style>", "", h, flags=re.S)
    h = re.sub(r"<!--.*?-->", "", h, flags=re.S)
    t = _clean(h)
    i = t.find(NAV_MARK)
    if i > 0:
        t = t[i + len(NAV_MARK):].strip()
    return t


def page_title(html, fallback=""):
    mt = TITLE_RE.search(html)
    return html_mod.unescape(mt.group(1).split("-")[0].strip()) if mt else fallback
