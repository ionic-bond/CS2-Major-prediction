# IEM Cologne Major 2026 - Stage 1 Pick'Em 分析

- 分析日期: 2026-05-29
- 赛事日期: 2026-06-02 ~ 06-05
- 赛制: 16队Swiss制, 前8晋级Stage 2, 后8淘汰

## 数据来源

1. **HLTV排名** (2026-05-25更新)
2. **Polymarket首轮Bo1赔率** (2026-05-29截取)
3. **近半年赛事成绩** (重点: IEM Atlanta 2026, ESL Challenger League, CS Asia Championships等)
4. **阵容变动** (考虑换人带来的置信度折扣)

## 16队综合实力排名

| # | 队伍 | 综合分 | HLTV | 层级 |
|:---:|:---|:---:|:---:|:---:|
| 1 | GamerLegion | 84.5 | #11 | 🟢T1 |
| 2 | BetBoom | 75.5 | #20 | 🟢T1 |
| 3 | B8 | 70.9 | #15 | 🟢T1 |
| 4 | Heroic | 59.5 | #25 | 🟡T2 |
| 5 | TYLOO | 57.8 | #30 | 🟡T2 |
| 6 | Team Liquid | 56.8 | #26 | 🟡T2 |
| 7 | BIG | 56.0 | #32 | 🟡T2 |
| 8 | SINNERS | 53.8 | #32 | 🟡T2 |
| 9 | MIBR | 53.6 | #28 | 🟠T3 |
| 10 | M80 | 51.1 | #35 | 🟠T3 |
| 11 | NRG | 45.1 | #34 | 🔴T4 |
| 12 | Lynn Vision | 40.3 | #45 | 🔴T4 |
| 13 | Sharks | 38.7 | #50 | 🔴T4 |
| 14 | Gaimin Gladiators | 37.6 | #46 | 🔴T4 |
| 15 | FlyQuest | 34.0 | #56 | 🔴T4 |
| 16 | THUNDER dOWNUNDER | 20.3 | #80 | 🔴T4 |

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

## 策略模拟结果 (Monte Carlo × 200,000)

| 策略 | 期望分 | P(≥5) | P(≥6) | P(≥7) |
|:---|:---:|:---:|:---:|:---:|
| A: 铁壁 (最保守) | 5.59 | **81.3%** | 54.1% | 23.4% |
| B: 稳健 | 5.44 | 75.5% | 48.7% | 22.0% |
| C: 平衡 | 5.20 | 68.4% | 42.2% | 18.9% |
| D: 冒险 | 5.18 | 67.9% | 41.7% | 18.6% |
| E: 赌狗 | 5.13 | 66.9% | 40.1% | 17.0% |

## 各策略详细picks

### 策略A: 铁壁 (最保守) — P(≥5) = 81.3%, 期望5.59分

| 位置 | 选择 |
|:---|:---|
| 3-0 | MIBR, M80 |
| 晋级 | GamerLegion, BetBoom, B8, Heroic, TYLOO, Team Liquid |
| 0-3 | THUNDER dOWNUNDER, Gaimin Gladiators |

### 策略B: 稳健 (保守) — P(≥5) = 75.5%, 期望5.44分

| 位置 | 选择 |
|:---|:---|
| 3-0 | GamerLegion, MIBR |
| 晋级 | BetBoom, B8, Heroic, TYLOO, Team Liquid, BIG |
| 0-3 | THUNDER dOWNUNDER, Gaimin Gladiators |

### 策略C: 平衡 (中等风险) — P(≥5) = 68.4%, 期望5.20分

| 位置 | 选择 |
|:---|:---|
| 3-0 | GamerLegion, BetBoom |
| 晋级 | B8, Heroic, TYLOO, Team Liquid, BIG, SINNERS |
| 0-3 | THUNDER dOWNUNDER, Gaimin Gladiators |

### 策略D: 冒险 (激进) — P(≥5) = 67.9%, 期望5.18分

| 位置 | 选择 |
|:---|:---|
| 3-0 | GamerLegion, BetBoom |
| 晋级 | B8, Heroic, TYLOO, Team Liquid, BIG, MIBR |
| 0-3 | THUNDER dOWNUNDER, FlyQuest |

### 策略E: 赌狗 (极端激进) — P(≥5) = 66.9%, 期望5.13分

| 位置 | 选择 |
|:---|:---|
| 3-0 | GamerLegion, B8 |
| 晋级 | BetBoom, Heroic, TYLOO, Team Liquid, BIG, SINNERS |
| 0-3 | THUNDER dOWNUNDER, Sharks |

## 最终选择: 策略A (铁壁)

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

### 各策略得分对比

| 策略 | 预测P(≥5) | 实际得分 | 达标? |
|:---|:---:|:---:|:---:|
| A: 铁壁 ⭐已选 | 81.3% | /10 | |
| B: 稳健 | 75.5% | /10 | |
| C: 平衡 | 68.4% | /10 | |
| D: 冒险 | 67.9% | /10 | |
| E: 赌狗 | 66.9% | /10 | |

### 反思
<!-- 赛后填写:
- 模型哪里准确/失误?
- 哪些因素被低估/高估?
- 策略选择是否最优? 如果选了其他策略结果会怎样?
- 对Stage 2分析的改进建议?
-->
