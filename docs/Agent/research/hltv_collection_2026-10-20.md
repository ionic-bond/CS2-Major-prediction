# HLTV 采集联调结论（2026-10-20）

当时的正式采集通过独立配置的普通隐藏 Chrome 直连，读取结果列表与比赛详情的整场、逐图 Both 表。HTTP 直接请求与 TLS 指纹模拟在该批样本遇到验证页。受限 Windows 环境中的浏览器 IPC 启动失败属于本机权限。日常运行命令和当前字段口径见采集手册。 [采集手册](../data/runbook.md) · [数据契约](../data/contract.md)

- 11 场联调共取到 25 张实打地图和 360 条 Rating 3.0 选手行。BO1、BO3、BO5 和弃赛样本都验证了系列赛比分、地图比分、稳定 ID、实际阵容与 BP 的保存。经济调整列单独保留。Default 图按判胜记录，回合数为空。 [BO3 样本](https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier) · [Default 样本](https://www.hltv.org/matches/2399485/forze-reload-vs-azuolas-cct-2026-europe-series-12)
- 页面到 `interactive` 且出现统计后可解析。离线重放读取相同响应，无需启动浏览器。详细运行证据位于 `data/reports/runs/` 的 2026-10-20 `sync-hltv` 报告。
- 单个高级 mapstats 样本返回 Both/CT/T 六张表、30 个选手行，另含首杀首死、多杀、残局、爆头和助攻。这些数据保留为高级采集的可行性证据。正式范围是比赛详情的 Both 表。 [高级页样本](https://www.hltv.org/stats/matches/mapstatsid/242269/metizport-vs-ex-rustec) · [采集范围](../data/runbook.md)
- 同一场 HLTV 与 BO3 对齐了 8 名选手、24 条统计。K-D 逐条一致，24 条 ADR 超过舍入误差且 11 条 KAST 不同。系列 ADR 聚合方式在样本中也有差异。用经核验的交集比较两站特征，保留各自口径。 [样本对照](../../../data/reports/hltv_bo3_sample_comparison.json) · [Rating 口径](ratings_comparison_2026-10-20.md)
- 公开衍生数据备选分别遇到稳定 ID 不齐、逐场索引为空或覆盖日期旧于仓库更新日期的问题。检查快照与响应散列保留于 `data/raw/diagnostics/hltv/public-datasets.json`。正式数据来自已验证的采集路径。 [数据来源与覆盖](../data/collection-plan.md)

10 月 20 日联调快照的清单保留了当时的计数和校验值，原载荷已经清理。较完整的历史窗口和迁移证据见后续审计。 [覆盖审计](collection_history_2026-10-22.md)
