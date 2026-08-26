#!/usr/bin/env python3
"""poe2db.tw 全站抓取器（限频、断点续传、本地缓存）。

用法:
  python3 tools/crawl.py                 # 全站抓取(上限 12000 页)
  python3 tools/crawl.py --max-pages 50  # 小规模试跑
  python3 tools/crawl.py --seeds /cn/Bows,/cn/Rings  # 指定种子

缓存: tools/.cache/pages/<slug>.html;已缓存的页面跳过网络请求(断点续传)。
礼貌策略: robots.txt 全站允许;3 并发,每请求前随机延迟 0.3~0.7s。
"""
import argparse
import gzip
import json
import os
import random
import re
import sys
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor

BASE = "https://poe2db.tw"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "pages")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "crawl.log")
UA = "Mozilla/5.0 (Macintosh; poe2ai-snapshot-builder/0.1; +github:TheEyeoftheUniverse/poe2ai)"

DEFAULT_SEEDS = [
    "/cn/", "/cn/Items", "/cn/Modifiers", "/cn/EndGame", "/cn/Gem", "/cn/Crafting",
    "/cn/Quest", "/cn/Keywords", "/cn/Unique_item", "/cn/Essence", "/cn/Flasks",
    "/cn/Waystones", "/cn/Skill_Gems", "/cn/Spirit_Gems", "/cn/Support_Gems",
    "/cn/Desecrated_Modifiers", "/cn/Reforging_Bench", "/cn/Liquid_Emotions",
    "/cn/Lineage_Supports", "/cn/Catalysts", "/cn/Ascendancy_class", "/cn/Act",
    "/cn/Bows", "/cn/Crossbows", "/cn/Quarterstaves", "/cn/Wands", "/cn/Sceptres",
    "/cn/One_Hand_Maces", "/cn/Two_Hand_Maces", "/cn/One_Hand_Axes", "/cn/Two_Hand_Axes",
    "/cn/One_Hand_Swords", "/cn/Two_Hand_Swords", "/cn/Spears",
    "/cn/Helmets", "/cn/Body_Armours", "/cn/Gloves", "/cn/Boots", "/cn/Shields",
    "/cn/Amulets", "/cn/Rings", "/cn/Belts", "/cn/Quivers", "/cn/Jewels", "/cn/Charms",
]
BLACKLIST_RE = re.compile(
    r"(patreon|Supporter_Packs|^Closed_Beta|^Open_Beta|^Commands$|^Achievements$|"
    r"^Core_20\d\d$|^Release_|^Halloween$|^Originators$|^Affliction_Theme$)"
)
LINK_RE = re.compile(r'href="(/cn/[A-Za-z0-9_.\-/]*)"')

_lock = threading.Lock()
_done = 0
_fail = 0
_seen = set()


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _lock:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
        print(line, flush=True)


def slug_to_file(slug):
    return slug[len("/cn/"):].strip("/").replace("/", "__") + ".html"


def file_to_slug(fname):
    return "/cn/" + fname[:-5].replace("__", "/")


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")


def extract_links(html):
    out = set()
    for m in LINK_RE.finditer(html):
        u = m.group(1).split("#")[0].split("?")[0].rstrip("/")
        if u and u != "/cn" and not BLACKLIST_RE.search(u[len("/cn/"):]):
            out.add(u)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=12000)
    ap.add_argument("--seeds", type=str, default="")
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    seeds = args.seeds.split(",") if args.seeds else DEFAULT_SEEDS
    queue = deque()
    seen = set()
    for s in seeds:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            queue.append(s)

    # 断点续传:已缓存页面的链接也要并入枚举(不重新请求)
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".html"):
            slug = file_to_slug(fname)
            if slug not in seen:
                seen.add(slug)
                queue.append(slug)
    cached_count = sum(1 for _ in os.listdir(CACHE_DIR) if _.endswith(".html"))
    log(f"启动: 队列 {len(queue)} (已缓存 {cached_count}), 上限 {args.max_pages}")

    global _done, _fail
    stats = {"pages": cached_count, "fail": 0, "bytes": 0}

    def worker(slug):
        global _done, _fail
        time.sleep(random.uniform(0.3, 0.7))
        path = os.path.join(CACHE_DIR, slug_to_file(slug))
        try:
            html = fetch(BASE + slug)
            with open(path, "w") as f:
                f.write(html)
            with _lock:
                stats["pages"] += 1
                stats["bytes"] += len(html)
            new_links = extract_links(html)
            with _lock:
                for l in new_links:
                    if l not in seen:
                        seen.add(l)
                        queue.append(l)
            return len(new_links)
        except Exception as e:
            with _lock:
                _fail += 1
                stats["fail"] += 1
            log(f"FAIL {slug}: {e}")
            return 0

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        while True:
            # 补充任务
            while queue and len(futures) < 12:
                slug = queue.popleft()
                if os.path.exists(os.path.join(CACHE_DIR, slug_to_file(slug))):
                    # 已缓存:本地提取链接并入队,不发请求
                    try:
                        with open(os.path.join(CACHE_DIR, slug_to_file(slug))) as f:
                            for l in extract_links(f.read()):
                                with _lock:
                                    if l not in seen:
                                        seen.add(l)
                                        queue.append(l)
                    except OSError:
                        pass
                    continue
                if stats["pages"] + len(futures) >= args.max_pages:
                    break
                futures.append(pool.submit(worker, slug))
            if not futures:
                break
            done_f, futures = _wait_some(futures)
        for fu in futures:
            fu.result()
    log(f"完成: 总页面 {stats['pages']}, 失败 {stats['fail']}, "
        f"原始HTML {stats['bytes']/1e6:.1f}MB")


def _wait_some(futures):
    from concurrent.futures import FIRST_COMPLETED, wait
    done, pending = wait(futures, return_when=FIRST_COMPLETED)
    for _ in done:
        pass
    return done, list(pending)


if __name__ == "__main__":
    main()
