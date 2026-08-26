"""core 模块单测(不依赖 AstrBot 运行时)。

运行: python3 tests/test_core.py
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.db import SnapshotDB, format_item          # noqa: E402
from core.fetcher import Fetcher                     # noqa: E402

BUNDLED = os.path.join(ROOT, "data", "poe2db.sqlite3")
CACHE = os.path.join(ROOT, "tools", ".cache", "pages")


class TestDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = SnapshotDB(os.path.join(cls.tmp, "poe2db.sqlite3"), BUNDLED)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_stats(self):
        s = self.db.stats()
        self.assertGreater(s["items"], 100)
        self.assertGreater(s["mods"], 1000)
        self.assertGreater(s["uniques"], 100)
        self.assertTrue(s["version"])

    def test_01b_second_instantiation(self):
        """第二次实例化(运行库已存在,走版本比较分支)不再报
        tuple indices must be integers or slices"""
        db2 = SnapshotDB(os.path.join(self.tmp, "poe2db.sqlite3"), BUNDLED)
        try:
            self.assertTrue(db2.stats()["items"] > 100)
        finally:
            db2.close()

    def test_02_search_item_cn_unique(self):
        items = self.db.search_item("猎首")
        self.assertTrue(items and items[0]["kind"] == "unique")
        self.assertIn("Headhunter", items[0]["name_en"])
        self.assertIn("webp", items[0]["icon_url"])

    def test_03_search_item_en(self):
        items = self.db.search_item("Headhunter")
        self.assertTrue(items)
        items = self.db.search_item("Golden Blade")
        self.assertTrue(any(it["name_cn"] == "金色之刃" for it in items))

    def test_04_search_mod_tiers(self):
        mods = self.db.search_mod("攻击速度提高", item_class="单手剑")
        self.assertGreaterEqual(len(mods), 4)  # 多 tier
        self.assertTrue(all("攻击速度" in m["text"] for m in mods))

    def test_05_search_mod_no_class(self):
        mods = self.db.search_mod("生命上限")
        self.assertTrue(mods)

    def test_06_search_wiki(self):
        pages = self.db.search_wiki("升华")
        self.assertTrue(pages)

    def test_07_format_item(self):
        items = self.db.search_item("猎首")
        text = format_item(items[0])
        self.assertIn("猎首", text)
        self.assertIn("重革腰带", text)


class TestFetcherIngest(unittest.TestCase):
    """用抓取缓存的真实页面验证 _ingest 解析入库(不发网络请求)。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = SnapshotDB(os.path.join(cls.tmp, "poe2db.sqlite3"), BUNDLED)
        cls.fetcher = Fetcher(cls.db, enabled=False)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ingest_unique_page(self):
        f = os.path.join(CACHE, "Headhunter.html")
        if not os.path.exists(f):
            self.skipTest("缓存页未抓到")
        html = open(f, encoding="utf-8", errors="replace").read()
        self.fetcher._ingest("Headhunter", html)
        items = self.db.search_item("Headhunter")
        self.assertTrue(any(it["name_cn"] == "猎首" for it in items))

    def test_ingest_equip_page(self):
        f = os.path.join(CACHE, "Rings.html")
        if not os.path.exists(f):
            self.skipTest("缓存页未抓到")
        before = self.db.stats()["mods"]
        html = open(f, encoding="utf-8", errors="replace").read()
        self.fetcher._ingest("Rings", html)
        after = self.db.stats()["mods"]
        self.assertGreaterEqual(after, before)  # 戒指页词条入库


if __name__ == "__main__":
    unittest.main(verbosity=2)
