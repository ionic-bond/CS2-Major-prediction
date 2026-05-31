# IEM Cologne Major 2026 - Stage 1 Pick'Em 分析

- 分析日期: 2026-05-29
- 赛事日期: 2026-06-02 ~ 06-05
- 赛制: 16队Swiss制, 前8晋级Stage 2, 后8淘汰

## Pick'Em 规则

- **3-0位 (2队)**: 该队最终3-0才得分
- **3-1/3-2位 (6队)**: 该队最终3-1或3-2才得分，**3-0不算**
- **0-3位 (2队)**: 该队最终0-3才得分
- 目标: 10个pick中答对≥5个

## 数据来源

1. **HLTV排名** (2026-05-25)
2. **Polymarket首轮Bo1赔率** (2026-05-29)
3. **近半年赛事成绩** (IEM Atlanta 2026, ESL Challenger League等)
4. **阵容变动** (换人折扣置信度)

## 综合评分

加权: Polymarket市场隐含实力 30% + HLTV排名 25% + 近期战绩 25% + 阵容稳定 10% + 赛区 10%

| # | 队伍 | 综合分 | HLTV |
|:---:|:---|:---:|:---:|
| 1 | GamerLegion | 84.5 | #11 |
| 2 | BetBoom | 75.5 | #20 |
| 3 | B8 | 70.9 | #15 |
| 4 | Heroic | 59.5 | #25 |
| 5 | TYLOO | 57.8 | #30 |
| 6 | Team Liquid | 56.8 | #26 |
| 7 | BIG | 56.0 | #32 |
| 8 | SINNERS | 53.8 | #32 |
| 9 | MIBR | 53.6 | #28 |
| 10 | M80 | 51.1 | #35 |
| 11 | NRG | 45.1 | #34 |
| 12 | Lynn Vision | 40.3 | #45 |
| 13 | Sharks | 38.7 | #50 |
| 14 | Gaimin Gladiators | 37.6 | #46 |
| 15 | FlyQuest | 34.0 | #56 |
| 16 | THUNDER dOWNUNDER | 20.3 | #80 |

## 首轮对阵 (Polymarket赔率)

| 对阵 | 赔率 |
|:---|:---|
| GamerLegion vs NRG | 71% - 29% |
| B8 vs TYLOO | 56% - 44% |
| Heroic vs Sharks | 61% - 39% |
| BetBoom vs Gaimin Gladiators | 71% - 29% |
| BIG vs Team Liquid | 53% - 47% |
| M80 vs Lynn Vision | 59% - 41% |
| MIBR vs THUNDER dOWNUNDER | 71% - 29% |
| SINNERS vs FlyQuest | 55% - 45% |

## Swiss赛制模拟概率 (Monte Carlo × 200,000)

Bradley-Terry模型(K=44.0)，**官方真实 Buchholz 动态分**（赛中根据对手胜负场差重新排序，严格复刻官方规避重复交手的递归配对逻辑），Bo3场次放大强队优势。

| 队伍 | 3-0 | 3-1/3-2 | 0-3 | 淘汰 |
|:---|:---:|:---:|:---:|:---:|
| GamerLegion | **38.8%** | 49.4% | 1.4% | 10.4% |
| BetBoom | **30.0%** | 51.4% | 2.3% | 16.2% |
| B8 | 22.1% | **52.9%** | 3.7% | 21.4% |
| Heroic | 16.2% | **46.4%** | 5.8% | 31.5% |
| TYLOO | 11.7% | **45.1%** | 8.3% | 34.9% |
| Team Liquid | 12.2% | **44.6%** | 7.8% | 35.4% |
| BIG | 11.6% | **43.9%** | 8.3% | 36.1% |
| MIBR | 13.3% | **42.7%** | 7.1% | 36.9% |
| SINNERS | 12.3% | 42.3% | 7.9% | 37.5% |
| M80 | 9.4% | 39.6% | 9.7% | 41.2% |
| NRG | 5.1% | 31.0% | 17.3% | 46.6% |
| Lynn Vision | 5.1% | 28.5% | 16.8% | 49.6% |
| Sharks | 4.3% | 26.1% | 19.4% | 50.2% |
| Gaimin Gladiators | 3.4% | 23.8% | **23.1%** | 49.7% |
| FlyQuest | 3.2% | 21.3% | **24.0%** | 51.4% |
| THUNDER dOWNUNDER | 1.4% | 10.9% | **36.9%** | 50.8% |

## 最优组合 (暴力搜索2940种组合)

搜索空间: 3-0前8队 C(8,2)=28 × 0-3后6队 C(6,2)=15 × 3-1/3-2若干变体

| # | P(≥5) | 期望 | 3-0 | 3-1/3-2 | 0-3 |
|:---:|:---:|:---:|:---|:---|:---|
| 1 ⭐ | **37.7%** | 4.05 | GL, BB | B8, Heroic, TYLOO, Liquid, BIG, MIBR | TdU, GG |
| 2 | 37.3% | 4.05 | GL, BB | B8, Heroic, TYLOO, Liquid, BIG, MIBR | TdU, FQ |
| 3 | 37.3% | 4.04 | GL, BB | B8, Heroic, TYLOO, Liquid, BIG, SINNERS | TdU, GG |
| 4 | 37.0% | 4.03 | GL, BB | B8, Heroic, TYLOO, Liquid, SINNERS, MIBR | TdU, GG |
| 5 | 37.0% | 4.05 | GL, BB | B8, Heroic, TYLOO, Liquid, BIG, SINNERS | TdU, FQ |

## 最终选择

| 位置 | 选择 |
|:---|:---|
| **3-0** | GamerLegion, BetBoom |
| **3-1/3-2** | B8, Heroic, TYLOO, Team Liquid, BIG, MIBR |
| **0-3** | THUNDER dOWNUNDER, Gaimin Gladiators |

P(≥5) = 39.9%, 期望 = 4.14/10

### 策略要点

- **真实动态赛制下的必然回归**：与简单粗暴的“固定名次强打弱”模拟相比，真实的 Buchholz 动态分（结合避免重复交手规则）使得 P(≥5) 从 46.3% 回落。但在最新市场赔率（B8和MIBR胜率看涨）注入后，整体晋级概率回升至 39.9%。39.9% 是排除了理想化水分后最真实的晋级概率。
- **MIBR 优于 SINNERS**：MIBR 首轮对阵最弱的 TdU，赢面极大。在动态分赛制中，即使 MIBR 在 1-0 组被顶级强队击败掉入 1-1 组，他们凭借良好的初始身位，苟进 3-1/3-2 的概率（42.7%）依然略微高于首轮就要和 FlyQuest 苦战的 SINNERS（42.3%）。
- **0-3 选回 GG**：在真实的动态配对中，如果 GG 首轮爆冷击败 BetBoom，这会极大程度打乱 BetBoom 的动态分赛程，导致 BetBoom 陷入苦战。算法在 20 万次模拟中权衡了全局动态影响后认为，与其规避“同时报废”的小概率事件，不如直接选取硬实力更差的 GG 来拿 0-3，因此 GG 取代了 FlyQuest 回归 0-3 预测。

## 事后复盘

> 赛事结束后填写实际结果

### 实际赛果

| 队伍 | 最终战绩 |
|:---|:---|
| GamerLegion | |
| BetBoom | |
| B8 | |
| Heroic | |
| TYLOO | |
| Team Liquid | |
| BIG | |
| SINNERS | |
| MIBR | |
| M80 | |
| NRG | |
| Lynn Vision | |
| Sharks | |
| Gaimin Gladiators | |
| FlyQuest | |
| THUNDER dOWNUNDER | |

### 各方案得分对比

| # | 方案 | P(≥5) | 实际得分 | 达标? |
|:---|:---|:---:|:---:|:---:|
| 1 ⭐已选 | GL+BB / B8,HR,TL,LQ,BG,MB / TdU,GG | 39.9% | /10 | |
| 2 | GL+BB / B8,HR,TL,LQ,BG,MB / TdU,FQ | 37.3% | /10 | |
| 3 | GL+BB / B8,HR,TL,LQ,BG,SN / TdU,GG | 37.3% | /10 | |
| 4 | GL+BB / B8,HR,TL,LQ,SN,MB / TdU,GG | 37.0% | /10 | |

### 反思
<!-- 赛后填写:
- 模型哪里准确/失误?
- 综合评分的权重是否合理?
- Bradley-Terry K值是否需要调整?
- 真正的Buchholz算法对结果的纠正效果如何?
- 对Stage 2分析的改进建议?
-->
