# HLTV 采集联调结果（2026-10-20）

路径说明（2026-10-21）：采集代码已归入 `data/pipeline/`，本文复现命令与链接同步更新；实验数据和结论仍对应原日期。当前运行说明以 [runbook](../data/runbook.md) 为准。

**直接采集 HLTV 已跑通，当前不再只有 BO3 和旧离线 HLTV 文件。** 已实现比赛列表发现、单场/逐图选手统计、稳定 ID 入库、重复执行与离线重放。此次直接采集 11 场、25 张实际地图、360 条选手统计；这是小批联调，不代表历史区间已经补齐。

## 访问方式与实际结果

| 方式 | 本机本轮结果 | 判断范围 |
| --- | --- | --- |
| `requests`、`cloudscraper`，代理及直连 | 结果页/统计页返回 HTTP 403 和 Cloudflare 验证页面 | 这些请求配置未通过，不能推导 HLTV 无法获取 |
| `curl_cffi` 的 Chrome 模拟 | 测试页仍返回 HTTP 403 | 替换 TLS 指纹本轮没有解决问题，不加入正式依赖 |
| 无头 Chrome + 环境代理的初次实验 | 超时后仍是验证页 | 模式与网络同时不同，不能据此归因于无头模式 |
| 普通隐藏 Chrome + 直连 + 本采集器独立配置 | 结果列表、比赛详情、高级逐图统计页均取得 HTTP 200 和真实统计 | 当前正式默认组合；不保证网站以后不会改变验证机制 |

实测浏览器为 Windows Chrome `155.0.8059.84`。采集器通过本机 CDP 读取网页，配置保存在忽略提交的 `data/raw/browser/hltv/profile/`，不使用个人浏览器配置、账号或手工复制的 cookie。后续命令复用采集器自己的会话，每次结束关闭浏览器。依赖仅为 `beautifulsoup4` 和 `websocket-client`，见 [requirements-hltv.txt](../../../data/pipeline/requirements-hltv.txt)。

页面已包含统计且 DOM 到达 `interactive` 时即可解析，不等待无关广告资源全部结束。此前一次有效结果页因等待 `complete` 被误报超时，已修正并加入回归验证。验证页面或不认识的页面会明确报错，失败内容不写入成功页面缓存。

## 已验证的数据与边界

正式采集范围为 `collection_scope=match_page_scoreboards`：比赛详情页内的整场及逐图 Both 表。11 场全部满足这个范围的完整性检查，包含 1 场 BO1、9 场 BO3、1 场 BO5；360 条中整场 110 条、逐图 250 条，页面表头版本全部为 Rating 3.0。

| 真实样本 | 已验证内容 |
| --- | --- |
| [Metizport–ex-RUSTEC](https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier)，BO3 2:0 | 10 条整场 + 20 条逐图，队伍/选手 HLTV ID、BP、传统与经济修正统计分开 |
| [Iberian Soul–Sashi](https://www.hltv.org/matches/2399600/iberian-soul-vs-sashi-digital-crusade-draculan-season-7)，BO1 | 10 条整场 + 10 条地图；系列比分为 1:0，单图比分仍单独保留 |
| [FURIA–BetBoom](https://www.hltv.org/matches/2399417/furia-vs-betboom-thunderpick-world-championship-2026)，BO5 3:2 | 10 条整场 + 50 条逐图，五张实际地图全部解析 |
| [FORZE Reload–Azuolas](https://www.hltv.org/matches/2399485/forze-reload-vs-azuolas-cct-2026-europe-series-12) | 双方各弃一图；Default 0:1 / 1:0 保存为判胜信息，`played=false`、回合数为空，不索要不存在的选手统计；实际 Ancient 13:5 正常保存 |

标准化表包括 K-D、ADR、KAST、Rating、Swing、经济修正 K-D/ADR/KAST、当场和逐图名单。传统数据不被隐藏的经济修正列覆盖，手机/桌面重复展示不重复入库。Default 地图及系列比分与实际地图的差异保留质量标记，供训练筛选。

**高级统计页也能取得，尚未全部标准化。** 对 [Anubis 统计页](https://www.hltv.org/stats/matches/mapstatsid/242269/metizport-vs-ex-rustec) 的单页实验成功返回原始 HTTP 200：两队各 Both/CT/T，共六张表、30 个选手行，含首杀首死、多杀回合、残局、爆头、助攻/闪光助攻等列。原始响应 SHA-256 为 `51cebea051d210e5a2a12105221280130d4bca2e8be978c8953630d4981c80de`；诊断记录在 `data/raw/diagnostics/hltv/advanced-page-probe.json`。这些行暂不计入上述 360 条，不宣称当前 CLI 已自动抓取全部高级页或逐回合数据。

比赛日期从页面 Unix 时间转 UTC，不依赖网页显示时区。准确结束时刻、游戏补丁、地图修订和 Rating 3.0 的具体子修订拿不到时保留未知；不能把今天重算的旧 Rating 当作历史当时可得的数值。旧导入的 HLTV 记录保持原样，刷新不会自动替换旧导入资料。

## 可复现的命令与验证

在仓库根目录运行，命令顺序执行：

```powershell
python -m pip install -r data/pipeline/requirements-hltv.txt

# 列表发现并采集最多 5 场新比赛；重复运行跳过已完成记录
python -m data.pipeline sync-hltv --since 2026-10-19 --until 2026-10-20 --max-matches 5

# 指定比赛，仍检查日期；--refresh 可刷新已经采集的统计
python -m data.pipeline sync-hltv --since 2026-10-20 --until 2026-10-20 --max-matches 1 --match-url https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier

# 使用相同缓存重新解析，无需启动 Chrome
python -m data.pipeline --offline sync-hltv --since 2026-10-20 --until 2026-10-20 --max-matches 1 --refresh --match-url https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier

python -m unittest discover -s data/pipeline/tests -v
```

本机沙箱内 Chrome 的 IPC 启动被 Windows 拒绝；在已允许启动浏览器的环境执行后成功。这与 HLTV 的 HTTP 403 是不同问题。默认浏览器直连，也提供 `--browser-proxy system/environment`；没有通过关闭 TLS 验证来解决连接问题。

实际证据保存在 `data/reports/runs/`：

- `20261020T123152477947Z-sync-hltv.json`：正式单场命令成功，30 条统计。
- `20261020T124039138334Z-sync-hltv.json`：列表流程新增 5 场，`bounded` 如实表示还有候选未扫描完。
- `20261020T124442198840Z-sync-hltv.json`：新浏览器进程跳过 6 场已有完整记录，继续 3 场；发现 Default 地图问题，原报告保留。
- `20261020T124840028041Z-sync-hltv.json`：修正 Default 后，9 场全部从原始缓存重放成功，数量不增长，浏览器 `started=false`。
- `20261020T124926821105Z-sync-hltv.json`：BO1 与 BO5 指定样本在线采集成功，浏览器正常退出。

最终测试为 **25/25 通过**，覆盖字段口径、UTC 日期、主键去重、事务刷新、保留旧导入记录、Default、验证页拒绝、离线重放及未加载完广告资源时的正常解析。线上成功与失败的浏览器均已关闭，不部署常驻任务。

冻结快照：`data/snapshots/20261020T125123701791Z/manifest.json`，事件标签 `2026_singapore`。包含 3,299 条来源比赛记录、104,904 条选手记录、13,895 条排名记录；包括旧资料、BO3 与此次 HLTV 联调，**同场跨站记录仍分别存在，并非 3,299 场已消重的独立比赛**。JSONL 的行数和 SHA-256 已核验，历史缺口和旧比分问题仍需在建模前处理。

清理注记（2026-10-22）：该联调快照未被任何 stage 使用，旧 JSONL 载荷已清理；保留的 manifest 仅记录当时的行数和校验值，不能作为现存数据集加载。当前数据状态见 [采集计划](../data/collection-plan.md)。

## 同场 BO3 与 HLTV 数值核对

[样本对照 JSON](../../../data/reports/hltv_bo3_sample_comparison.json) 保存了 Metizport–ex-RUSTEC 的逐项差异及原始响应引用。两站各 30 行，在同一场、同队名、同地图范围内按大小写无关的昵称对上 8 名选手、24 行；两名选手有前缀或不同别名，未仅凭相同 K-D 强行匹配。

24 行 K-D 全部一致；ADR 有 24 行超过一位小数的舍入容差，KAST 有 11 行不同。例如 Brilliance 的 Anubis，HLTV 为 ADR 72.6 / KAST 50%，BO3 原始 API 为 72.85 / 55%。这些值直接来自原始响应，不是单位转换造成。部分系列汇总差异还涉及聚合：本样本 BO3 整场 ADR 62.7886 等于两张地图 ADR 的简单平均，按 20/22 回合加权则为 62.3095。此观察不外推成整个网站的固定算法，也未解释所有逐图差异。

因此暂不把两站 ADR/KAST 直接互补，更不把不同尺度的 Rating 拼成一个字段。后续应在已核验的同场交集上比较赛前特征的增量预测效果；本次样本不能判定哪站更准确。社区和官方算法证据另见 [Rating 调研](ratings_comparison_2026-10-20.md)。

## 社区数据备选

同时检查了公开 HLTV 衍生数据，用于直采失效时的备选；本轮未把这些 CSV/JSON 自动混入标准化库：

- [StrandedPond/hltv_scraper，固定提交](https://github.com/StrandedPond/hltv_scraper/tree/1db381a4e9a1e688f9d6be80111eb85231395f10)：实际 CSV 覆盖 2025-12-08 至 2026-10-19，2,566 个地图行、25,661 个选手行。选手表缺稳定 ID 和比赛 URL，且不是恰好每图十行，需先验证连接、重复和异常，不直接依赖仓库“每日更新”的声明。
- [smallmeji/hltv-cs2-data-public，固定提交](https://github.com/smallmeji/hltv-cs2-data-public/tree/f9143e44f3eb5dc1870c903f2707b3c131c9a047)：2026-10-16 导出有战队近期地图和选手窗口汇总，但检查到 `matches/index.json` 是空数组，不能当作完整逐场选手数据替代品。
- [ppxdpp17/CS2-Predictor](https://github.com/ppxdpp17/CS2-Predictor)：当日仓库有更新，检查的数据末日却为 2026-08-27，部分比赛 ID 是重建编号。仓库更新时间不能代表比赛覆盖日期。

下载内容按固定提交和 SHA-256 缓存，检查记录在 `data/raw/diagnostics/hltv/public-datasets.json`。没有运行这些仓库的采集代码或读取其中的私密配置。
