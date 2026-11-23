# HLTV 与 BO3.gg 选手 Rating 口径（2026-10-20）

当前选手特征使用 HLTV 赛前可用的系列赛 Rating 3.0。选手评分应保留来源、版本和采集时点。现有公开证据主要比较口径与解释，预测效果仍需在同场样本、相同时间切分下检验。 [Stage 1 选手特征](../../../2026_singapore/stage1/model.md#地图克制与选手)

| 来源 | 关键口径 |
| --- | --- |
| HLTV Rating 3.0 | 以赛事尺度的 1.00 为参照，组合击杀、伤害、生存、KAST、多杀和 Round Swing，考虑地图、阵营和经济。 [首发说明](https://www.hltv.org/news/42485/introducing-rating-30) |
| HLTV 修订 | 2025-10-29 调整 Swing、击杀与辅助归因。2026-10-01 更新经济与地图基准，并重算历史结果。比较旧讨论和当前数值时先核对子修订。 [2025-10-29 调权](https://www.hltv.org/news/43047/rating-30-adjustments-go-live) · [2026-10-01 修订](https://www.hltv.org/news/45596/rating-30-receives-small-accuracy-improvements) |
| BO3.gg | 使用 0–10 分和八项不等权指标，参考相同地图、阵营与经济下的职业表现。公开说明列出部分子指标和聚合层次，具体权重未公开。 [BO3.gg 方法说明](https://bo3.gg/articles/top-10-best-cs2-players-in-august-2025) |

社区关于 Swing、残局与角色的讨论记录了应检验的假设。当前 HLTV/BO3 实测还看到 ADR、KAST 与系列聚合口径的差异，因此两站分开保存。重采集时保留原记录的版本与出处，拟合使用选定快照中的观测。 [同场数据对照](hltv_collection_2026-10-20.md)
