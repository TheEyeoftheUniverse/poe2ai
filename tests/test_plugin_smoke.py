"""插件级冒烟测试:stub 掉 astrbot 包,加载 main.py 并驱动 llm_tool handler。

运行: python3 tests/test_plugin_smoke.py
"""
import asyncio
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "astrbot_stub"))  # astrbot stub 优先
sys.path.insert(0, ROOT)


class FakeEvent:
    def __init__(self, role="member"):
        self.role = role
        self.results = []

    def plain_result(self, text):
        r = ("plain", text)
        self.results.append(r)
        return r

    def image_result(self, url):
        r = ("image", url)
        self.results.append(r)
        return r


def _load_plugin():
    """把插件目录作为包加载(模拟 AstrBot 插件管理器),支持 main.py 的相对导入。"""
    spec = importlib.util.spec_from_file_location(
        "poe2ai_plugin", os.path.join(ROOT, "main.py"),
        submodule_search_locations=[ROOT])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["poe2ai_plugin"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPluginSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_plugin()
        cls.plugin = cls.mod.Poe2Ai(_StarStub := __import__("astrbot.api.star", fromlist=["Context"]).Context(),
                                    config={"enable_fetch": False, "max_items": 5, "max_mods": 20})
        # llm_tool 注册验证(取装饰器登记的工具名)
        cls.llm_tools = [getattr(getattr(cls.plugin, n), "_llm_tool_name")
                         for n in dir(cls.plugin)
                         if callable(getattr(cls.plugin, n, None))
                         and hasattr(getattr(cls.plugin, n), "_llm_tool_name")]

    def _run(self, handler, event, **kwargs):
        async def consume():
            out = []
            async for r in handler(event, **kwargs):
                out.append(r)
            return out
        return asyncio.run(consume())

    def test_01_registered(self):
        self.assertIn("poe2_query_item", self.llm_tools)
        self.assertIn("poe2_query_mod", self.llm_tools)
        self.assertIn("poe2_search_wiki", self.llm_tools)

    def test_02_query_item_with_image(self):
        ev = FakeEvent()
        self._run(self.plugin.query_item, ev, query="猎首")
        kinds = [k for k, _ in ev.results]
        self.assertIn("image", kinds)   # FR-3:信息与图片一起发
        text = "".join(t for k, t in ev.results if k == "plain")
        self.assertIn("猎首", text)
        self.assertIn("重革腰带", text)

    def test_03_query_item_miss(self):
        ev = FakeEvent()
        self._run(self.plugin.query_item, ev, query="不存在的装备xyzq")
        self.assertTrue(any("未找到" in t for _, t in ev.results))

    def test_04_query_mod(self):
        ev = FakeEvent()
        self._run(self.plugin.query_mod, ev, query="攻击速度提高", item_class="单手剑")
        text = "".join(t for k, t in ev.results if k == "plain")
        self.assertIn("攻击速度", text)

    def test_05_search_wiki(self):
        ev = FakeEvent()
        self._run(self.plugin.search_wiki, ev, query="升华")
        self.assertTrue(any("升华" in t for _, t in ev.results))

    def test_06_stats_cmd(self):
        ev = FakeEvent()
        self._run(self.plugin.poe2, ev, name="统计")
        self.assertTrue(any("快照" in t for _, t in ev.results))

    def test_07_lookup_direct(self):
        """新指令形态: /poe2 猎首 不带「查」字"""
        ev = FakeEvent()
        self._run(self.plugin.poe2, ev, name="猎首")
        kinds = [k for k, _ in ev.results]
        self.assertIn("image", kinds)
        self.assertTrue(any("猎首" in t for _, t in ev.results))

    def test_08_refresh_denied_for_member(self):
        ev = FakeEvent(role="member")
        self._run(self.plugin.poe2, ev, name="刷新", extra="Amulets")
        self.assertTrue(any("仅管理员" in t for _, t in ev.results))

    def test_09_refresh_admin_passes_gate(self):
        ev = FakeEvent(role="admin")
        self._run(self.plugin.poe2, ev, name="刷新", extra="不存在的页面zzz")
        # 管理员过闸后进入实际拉取(测试环境 fetcher disabled/页面不存在 → 报拉取失败而非无权限)
        self.assertFalse(any("仅管理员" in t for _, t in ev.results))
        self.assertTrue(any("拉取" in t or "正在" in t for _, t in ev.results))

    def test_10_render_item_card_path(self):
        """monkeypatch html_render → 走卡片图路径,直查不再发纯文本"""
        async def fake_html(tmpl, data, options=None):
            return "http://fake/img.png"
        self.plugin.html_render = fake_html
        try:
            ev = FakeEvent()
            self._run(self.plugin.poe2, ev, name="猎首")
            kinds = [k for k, _ in ev.results]
            self.assertEqual(kinds, ["image"])  # 只有图,无纯文本
        finally:
            del self.plugin.html_render  # 回到 stub 无该方法 → fallback

    def test_11_render_fallback_path(self):
        """stub 无 html_render → 渲染失败自动回退 裸icon+纯文本"""
        self.assertFalse(hasattr(self.plugin, "html_render"))
        ev = FakeEvent()
        self._run(self.plugin.poe2, ev, name="猎首")
        kinds = [k for k, _ in ev.results]
        self.assertIn("image", kinds)
        self.assertIn("plain", kinds)

    def test_12_lookup_miss(self):
        ev = FakeEvent()
        self._run(self.plugin.poe2, ev, name="不存在装备xyzq")
        self.assertTrue(any("没找到" in t for _, t in ev.results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
