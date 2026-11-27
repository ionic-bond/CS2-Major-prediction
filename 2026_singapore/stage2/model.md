# Singapore Major Stage 2 模型与复跑

Stage 2 的赛前截止为 `2026-11-28T04:00:00Z`。八个直邀队按赛前全球 VRS 排种子，八个晋级队按 Stage 1 的最终战绩、对手分和原始种子排序。阶段配置记录了 16 支队伍、五人名单、七图地图池和首轮对阵。 [阶段配置](stage.json) · [Valve 种子规则](https://github.com/ValveSoftware/counter-strike_rules_and_regs/blob/main/major-supplemental-rulebook.md#seeding) · [HLTV 首轮赛程](https://www.hltv.org/news/46076/pgl-major-singapore-stage-2-opening-matches-set)

## 比赛和实力

以全部可用的赛前 HLTV 实打地图拟合。本届 Stage 1 的 33 场、53 张实打地图、完整阵容和 BP 均已入库。训练与状态估计排除本阶段的比赛。 [Stage 1 赛果](https://www.hltv.org/results?event=9303) · [冻结结果](result.json)

近期状态半衰期为 75 天，长期与 LAN/Major 状态为 365 天。三种状态的合并系数为 0.40、0.45、0.15，赛事质量系数为 `1 + 0.15 × I(LAN) + 0.20 × I(Major)`。11 月 2 日之后、参考日之前的比赛通常对长期与 LAN/Major 项乘 0.60。本届 Stage 1 这 53 张图的该因子取 **1.0**，其时间衰减、阵容继承、回合比分、对手修正和系列赛权重按同一公式计算。

全局实力把所有队伍和上场阵容的历史战绩放在同一张对局网络上拟合，单图的基础 logit 为双方全局分之差。同一系列赛的 `m` 张实打地图每张乘 `1/√m`，与同一对手打过 `n` 场则再乘 `1/√n`。回合比分通过相对回合差调节地图的证据权重。旧阵容与当前阵容的继承系数为名单重合比例的 1.5 次方。同队中心化 HLTV Rating 3.0 只在阵容交接时调整旧战绩对当前阵容的影响。

VRS 用 11 月 2 日全球榜积分给当前阵容提供参照。先验精度是 **4.0** 乘阵容继承系数和榜单年龄衰减 `2^(−年龄/75)`。队伍地图和直接交手地图差异，在全局分基础上按三种状态分别拟合并收缩。阶段波动用赛前三个 21 天留出窗的预测残差估计，各窗也使用 VRS 系数 4。每条瑞士轮路径为每队抽一次实力与状态的扰动，贯穿该队的所有轮次。 [Valve 11 月 2 日全球榜](https://github.com/ValveSoftware/counter-strike_regional_standings/blob/f8c55f250fdef796d708aa32814587932154fa04/invitation/2026/standings_global_2026_11_02.md)

## 盘口、模拟和填法

首轮使用 Polymarket 两侧 token 在同一个一小时时间桶内的最后一条价格。以 `p₁/(p₁+p₂)` 归一化后，按 0.25 市场、0.75 数据的系数在 logit 空间融合。统一按阶段截止筛选快照。后续轮次依照队伍按时间和阵容加权的 BP 偏好，从官方禁选图流程抽取地图。晋级和淘汰场为 BO3，其余为 BO1。后续配对使用轮前战绩、Buchholz、初始种子和无重赛规则。 [八场盘口清单](markets.json) · [冻结价格](market_history.json) · [Valve 瑞士轮和 BP 规则](https://github.com/ValveSoftware/counter-strike_rules_and_regs/blob/main/major-supplemental-rulebook.md#swiss-bracket)

每条路径保留完整 16 队战绩。模型搜索同时满足 2 个 3–0、6 个 3–1/3–2、2 个 0–3 的组合，目标为至少命中 5 项的概率。本次运行用 500,000 条主路径，抽 100,000 条搜索每个栏位边际概率最高的 12 队。用全部主路径重测前五个组合，再用 500,000 条不同种子的路径评估固定组合。候选之间的通过率差用同一批验证路径估计抽样区间。 [推荐与战绩概率](README.md) · [逐图矩阵](matrix_3d.md)

## 复跑

从仓库根目录运行。赛前比赛和市场输入以结果中的数据清单和本目录的快照为准。

```powershell
python -B -m 2026_singapore.stage2.run predict-stage `
  --market-file 2026_singapore/stage2/market_history.json --lambda-match 0.25 `
  --simulations 500000 --search-simulations 100000 --candidate-k 12 `
  --validation-simulations 500000 --workers 8 --seed 20261128 --validation-seed 20261129

python -B -m 2026_singapore.stage2.run render-report
```
