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

用Bradley-Terry模型(K=44.0)计算任意两队胜率，模拟完整Swiss赛制(R1固定对阵→R2按战绩配对→...→R5)，Bo3场次放大强队优势。

| 队伍 | 3-0 | 3-1/3-2 | 0-3 | 淘汰 |
|:---|:---:|:---:|:---:|:---:|
| GamerLegion | **34.2%** | 52.6% | 1.9% | 11.3% |
| BetBoom | **27.9%** | 52.4% | 2.9% | 16.8% |
| B8 | 20.7% | **52.5%** | 4.6% | 22.2% |
| Heroic | 15.8% | **46.3%** | 6.7% | 31.3% |
| TYLOO | 11.0% | **43.6%** | 9.7% | 35.7% |
| Team Liquid | 12.2% | **43.4%** | 8.9% | 35.6% |
| BIG | 11.9% | **42.8%** | 9.3% | 36.1% |
| MIBR | 14.6% | **42.8%** | 7.1% | 35.6% |
| SINNERS | 13.3% | 42.1% | 8.2% | 36.4% |
| M80 | 11.2% | 39.3% | 9.9% | 39.6% |
| NRG | 5.5% | 30.0% | 18.1% | 46.4% |
| Lynn Vision | 6.1% | 28.4% | 16.7% | 48.8% |
| Sharks | 5.2% | 25.9% | 19.2% | 49.8% |
| Gaimin Gladiators | 4.2% | 23.5% | **22.3%** | 50.0% |
| FlyQuest | 4.3% | 22.3% | **21.8%** | 51.6% |
| THUNDER dOWNUNDER | 2.0% | 12.1% | **32.8%** | 53.1% |

## 最优组合 (暴力搜索2940种组合)

搜索空间: 3-0前8队 C(8,2)=28 × 0-3后6队 C(6,2)=15 × 3-1/3-2若干变体

| # | P(≥5) | 期望 | 3-0 | 3-1/3-2 | 0-3 |
|:---:|:---:|:---:|:---|:---|:---|
| 1 ⭐ | **33.0%** | 3.88 | GL, BB | B8, Heroic, TYLOO, Liquid, MIBR, BIG | TdU, GG |
| 2 | 32.9% | 3.88 | GL, BB | B8, Heroic, TYLOO, Liquid, MIBR, SINNERS | TdU, GG |
| 3 | 32.8% | 3.88 | GL, BB | B8, Heroic, TYLOO, SINNERS, MIBR, BIG | TdU, GG |
| 4 | 32.8% | 3.88 | GL, BB | B8, Heroic, TYLOO, Liquid, SINNERS, BIG | TdU, GG |
| 5 | 32.7% | 3.88 | GL, BB | B8, Heroic, TYLOO, Liquid, MIBR, BIG | TdU, FQ |

## 最终选择

| 位置 | 选择 |
|:---|:---|
| **3-0** | GamerLegion, BetBoom |
| **3-1/3-2** | B8, Heroic, TYLOO, Team Liquid, MIBR, BIG |
| **0-3** | THUNDER dOWNUNDER, Gaimin Gladiators |

P(≥5) = 33.0%, 期望 = 3.88/10

### 策略要点

- **强队放3-0而非3-1/3-2**: GL放3-1/3-2位只有52.6%命中(34.2%的时间GL打出3-0会浪费这个pick)，放3-0位有34.2%命中且释放3-1/3-2位给其他队
- **0-3选GG而非FQ**: 虽然FQ的0-3概率(21.8%)接近GG(22.3%)，但若将FQ选入0-3且SINNERS选入3-0，两者首轮直接对阵(SINNERS vs FlyQuest)，45%概率SINNERS输导致两个pick同时废掉(关联性风险)
- **MIBR优于SINNERS作为第6个3-1/3-2位**: MIBR的3-1/3-2概率(42.8%)略高于SINNERS(42.1%)

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
| 1 ⭐已选 | GL+BB / B8,HR,TL,LQ,MB,BG / TdU,GG | 33.0% | /10 | |
| 2 | GL+BB / B8,HR,TL,LQ,MB,SN / TdU,GG | 32.9% | /10 | |
| 3 | GL+BB / B8,HR,TL,SN,MB,BG / TdU,GG | 32.8% | /10 | |
| 4 | GL+BB / B8,HR,TL,LQ,SN,BG / TdU,GG | 32.8% | /10 | |

### 反思
<!-- 赛后填写:
- 模型哪里准确/失误?
- 综合评分的权重是否合理?
- Bradley-Terry K值是否需要调整?
- 对Stage 2分析的改进建议?
-->
