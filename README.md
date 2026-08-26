# poe2ai

AstrBot 插件:让机器人帮你翻 [poe2db.tw](https://poe2db.tw/)(Path of Exile 2 社区数据库)。
自然语言问「猎首是什么效果」「t1 攻速多少」,LLM 自动调用本地快照查询作答,装备信息与图片一起发送。

## 特性

- **全站快照** — 插件自带 poe2db.tw 全站中文数据的 SQLite 快照(装备基底、暗金、全部词条、技能/地图/任务等页面),装好即用、零冷启动、默认不发任何网络请求
- **自然语言查询** — 3 个 LLM 工具(`poe2_query_item` / `poe2_query_mod` / `poe2_search_wiki`),LLM 在对话中自主调用
- **装备带图** — 图片走 `cdn.poe2db.tw` 外链,本地零图片存储
- **排版卡片图** — 点名查询装备(`/poe2 猎首`或对话中明确问到某装备)时渲染 poe2db 风格深色 tooltip 卡片图(含装备图标);效果反查/词条等多结果查询只把数据交给 LLM 出结论、不发图刷屏;依赖 AstrBot 文转图环境,关闭 `render_image` 或渲染失败自动回退纯文本
- **按需兜底** — 快照查不到时(仅英文 slug 可定位),限频抓取 poe2db 对应整页解析入库,下次直接命中
- **中英别名** — 中文名、英文 slug(含空格写法)均可命中

## 安装

将本仓库克隆到 AstrBot 的 `data/plugins/poe2ai` 目录,重启 AstrBot 或在管理面板重载插件:

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/TheEyeoftheUniverse/poe2ai
```

首次启动会把快照复制到插件数据目录,运行期增量数据写在副本上;插件升级带来新快照版本时自动重新复制。

## 使用

直接和机器人对话即可:

> 猎首是什么效果?
> t1 攻速的数值区间是多少?单手剑上的
> 电球这个技能怎么运作?

运维指令:

| 指令 | 说明 |
|---|---|
| `/poe2 猎首` | 直查装备(带图) |
| `/poe2 词条 攻击速度提高` | 直查词条各 tier |
| `/poe2 刷新 Amulets` | 重拉指定页面入库(仅管理员) |
| `/poe2 统计` | 快照统计 |

## 快照构建(维护者)

全量重建快照(限频慢跑,预计 30~60 分钟):

```bash
python3 tools/crawl.py            # 1. 全站抓取(断点续传,缓存于 tools/.cache/)
python3 tools/build_snapshot.py   # 2. 解析入 data/poe2db.sqlite3
python3 tests/test_core.py        # 3. 数据层单测
```

构建后提交仓库并 bump `metadata.yaml` 版本号,用户端会自动感知新快照。

## 许可

数据来源于 [poe2db.tw](https://poe2db.tw/)(CC BY-NC-SA),本插件仅供学习交流。
