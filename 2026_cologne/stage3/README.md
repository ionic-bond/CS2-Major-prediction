# Stage 3: 2026 IEM Cologne Major (Swiss Stage 全 Bo3)

在这个阶段，16 支晋级队伍将进行残酷的瑞士轮对决。与之前最大的不同是：**本阶段的所有比赛均为 Bo3**。

这使得队伍利用单一强势地图爆冷的几率降低，地图池深度和综合硬实力将成为决定因素。

## 🔬 方法论概要 (简述)

针对全 Bo3 赛制，我们的算法进行了全方位的深度定制升级。详细的方法论推演和公式可以参考 [plan.md](./plan.md)。核心升级包括：

1. **地图级 BP 博弈模拟 (Map Veto Minimax)**：不再使用粗略的标量修正，而是抓取逐图数据，通过纳什均衡策略真实模拟双方教练在 ban/pick 时的博弈过程。
2. **人员流动惩罚矩阵 (Roster Factor 2.0)**：用平方级惩罚函数代替简单扣分，精准衡量队伍换人后的战力留存度。
3. **KAST 阻尼器**：用选手个人稳定性（KAST）压制“神经刀”的伪高 V 值，将队伍方差调整到更符合逻辑的区间。
4. **盘口数据逆向工程**：从 Polymarket 取出实时赔率，利用 Bradley-Terry 模型反推 16x16 的市场先验胜率。
5. **H2H 纯净态**：H2H 更新剥离了高随机性的 Bo1 比赛，确保对抗矩阵反映的是纯粹的 Bo3 统治力。

最终，我们将“硬数据轨道”（H2H+地图BP）与“市场轨道”（Polymarket 盘口）以 50:50 融合，交给 20 万次蒙特卡洛引擎进行穷举。

---

## 📈 参考数据展示

### 1. 队伍稳定性指数与基本面画像
*(以 KAST 为核心阻尼器，衡量队伍的发挥稳定性。V 值越低，代表越容易预测，下限越高。)*

| 队伍 | 平均 KAST | 原始方差 (V_raw) | 修正方差 (V_adj) | 稳定性评价 | 首选图 | 必Ban图 | 强图数 | 弱图数 |
|---|---|---|---|---|---|---|---|---|
| **Spirit** | 78.5% | 2.48 | 0.872 | 较高 | Dust2 | Inferno | 4 | 0 |
| **Vitality** | 76.3% | 4.85 | 1.804 | 较低 | Dust2 | Ancient | 5 | 0 |
| **G2** | 75.5% | 3.04 | 1.157 | 一般 | Dust2 | Nuke | 3 | 1 |
| **Legacy** | 74.8% | 5.86 | 2.272 | 极低 | Mirage | Anubis | 4 | 0 |
| **Natus Vincere** | 74.6% | 4.81 | 1.873 | 较低 | Ancient | Overpass | 3 | 0 |
| **9z** | 74.4% | 4.87 | 1.908 | 较低 | Overpass | Anubis | 5 | 1 |
| **FURIA** | 74.2% | 1.77 | 0.695 | 极高 | Overpass | Ancient | 1 | 0 |
| **Falcons** | 73.7% | 4.68 | 1.870 | 较低 | Mirage | Overpass | 3 | 0 |
| **MOUZ** | 73.7% | 2.07 | 0.825 | 较高 | Mirage | Anubis | 2 | 1 |
| **FUT** | 73.3% | 1.58 | 0.638 | 极高 | Mirage | Inferno | 2 | 0 |
| **BetBoom** | 73.3% | 2.17 | 0.875 | 较高 | Nuke | Inferno | 4 | 1 |
| **Aurora** | 71.8% | 5.89 | 2.475 | 极低 | Dust2 | Ancient | 3 | 1 |
| **The MongolZ** | 71.2% | 2.17 | 0.929 | 较高 | Mirage | Anubis | 2 | 1 |
| **PARIVISION** | 71.2% | 2.20 | 0.942 | 较高 | Dust2 | Nuke | 1 | 1 |
| **B8** | 71.2% | 1.35 | 0.579 | 极高 | Mirage | Anubis | 0 | 0 |
| **Monte** | 70.9% | 2.51 | 1.080 | 一般 | Dust2 | Overpass | 1 | 0 |

---

### 2. 各队地图加权胜率表
*(包含了时间衰减 + 对手实力加权。胜率大于 65% 标绿，低于 35% 标红)*

| Team | Mirage | Inferno | Nuke | Ancient | Anubis | Dust2 | Overpass |
|---|---|---|---|---|---|---|---|
| **Vitality** | **<span style='color:green'>77%</span>** (8.5) | **<span style='color:green'>72%</span>** (6.0) | **<span style='color:green'>73%</span>** (7.2) | - | 54% (3.2) | **<span style='color:green'>93%</span>** (10.5) | **<span style='color:green'>86%</span>** (6.1) |
| **Natus Vincere** | 63% (10.7) | 53% (7.8) | 59% (5.3) | **<span style='color:green'>76%</span>** (8.6) | **<span style='color:green'>67%</span>** (5.1) | 53% (10.5) | - |
| **Falcons** | 51% (8.6) | 49% (4.1) | **<span style='color:green'>80%</span>** (4.8) | **<span style='color:green'>68%</span>** (7.4) | - | 63% (11.6) | - |
| **The MongolZ** | 49% (12.3) | **<span style='color:green'>66%</span>** (6.6) | 65% (6.5) | 49% (6.8) | - | 52% (7.0) | 39% (2.6) |
| **PARIVISION** | 35% (10.4) | 50% (6.8) | - | 57% (8.2) | - | 64% (12.8) | - |
| **Aurora** | 61% (7.0) | 63% (5.2) | **<span style='color:red'>30%</span>** (6.7) | - | **<span style='color:green'>68%</span>** (3.5) | 56% (10.3) | 57% (4.8) |
| **FURIA** | 54% (11.4) | **<span style='color:green'>67%</span>** (7.4) | 54% (7.4) | - | - | 52% (9.2) | 55% (6.2) |
| **MOUZ** | **<span style='color:green'>77%</span>** (6.5) | 60% (5.7) | 58% (6.6) | 58% (4.5) | - | 37% (5.6) | **<span style='color:green'>98%</span>** (4.1) |
| **Spirit** | **<span style='color:green'>75%</span>** (10.3) | - | **<span style='color:green'>68%</span>** (4.2) | **<span style='color:green'>83%</span>** (6.1) | - | **<span style='color:green'>88%</span>** (9.6) | 56% (3.1) |
| **FUT** | **<span style='color:green'>72%</span>** (10.4) | - | 50% (5.0) | **<span style='color:green'>68%</span>** (10.7) | 56% (3.2) | 55% (7.9) | 56% (8.3) |
| **G2** | 62% (11.5) | 56% (7.1) | - | **<span style='color:green'>70%</span>** (9.9) | **<span style='color:red'>22%</span>** (3.6) | 51% (11.8) | **<span style='color:green'>77%</span>** (5.2) |
| **BetBoom** | 38% (7.5) | - | **<span style='color:green'>74%</span>** (9.1) | 60% (4.9) | **<span style='color:green'>77%</span>** (3.2) | **<span style='color:green'>87%</span>** (8.1) | 47% (3.9) |
| **9z** | 39% (6.1) | **<span style='color:green'>68%</span>** (11.9) | 64% (14.3) | 64% (8.5) | - | **<span style='color:green'>69%</span>** (12.1) | **<span style='color:green'>74%</span>** (11.8) |
| **Monte** | 60% (8.4) | 57% (2.5) | 49% (11.0) | 59% (5.9) | - | 61% (13.8) | - |
| **B8** | 53% (15.8) | 54% (6.7) | 50% (6.9) | 58% (14.9) | - | 52% (8.2) | 55% (5.7) |
| **Legacy** | **<span style='color:green'>81%</span>** (11.9) | **<span style='color:green'>72%</span>** (11.7) | 57% (9.8) | 46% (11.1) | - | **<span style='color:green'>68%</span>** (13.4) | **<span style='color:green'>75%</span>** (2.4) |
---

### 3. 终极融合预测矩阵 (P_final)
*(本矩阵由 50% 盘口市场共识与 50% 硬数据融合，已包含 BP 博弈和方差极化缩放。行代表队伍，列代表对手，数值代表**行击败列**的最终概率)*

| Team | Vitality | Spirit | Natus Vincere | FURIA | Falcons | Aurora | MOUZ | G2 | FUT | Legacy | The MongolZ | BetBoom | PARIVISION | 9z | Monte | B8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Vitality** | - | 57.2% | <span style='color:green'>65.4%</span> | <span style='color:green'>78.2%</span> | 64.1% | <span style='color:green'>71.9%</span> | <span style='color:green'>77.6%</span> | <span style='color:green'>75.1%</span> | <span style='color:green'>80.4%</span> | <span style='color:green'>71.6%</span> | <span style='color:green'>78.3%</span> | <span style='color:green'>83.1%</span> | <span style='color:green'>84.2%</span> | <span style='color:green'>76.5%</span> | <span style='color:green'>84.3%</span> | <span style='color:green'>87.0%</span> |
| **Spirit** | 42.8% | - | 64.0% | <span style='color:green'>77.8%</span> | 61.7% | <span style='color:green'>72.3%</span> | <span style='color:green'>78.1%</span> | <span style='color:green'>74.2%</span> | <span style='color:green'>82.0%</span> | <span style='color:green'>70.9%</span> | <span style='color:green'>81.5%</span> | <span style='color:green'>83.0%</span> | <span style='color:green'>84.2%</span> | <span style='color:green'>80.3%</span> | <span style='color:green'>86.5%</span> | <span style='color:green'>87.0%</span> |
| **Natus Vincere** | <span style='color:red'>34.6%</span> | 36.0% | - | 59.7% | 50.0% | 58.2% | 61.8% | 64.3% | <span style='color:green'>65.9%</span> | 60.5% | 63.6% | <span style='color:green'>68.3%</span> | <span style='color:green'>68.9%</span> | <span style='color:green'>67.6%</span> | <span style='color:green'>73.5%</span> | <span style='color:green'>72.4%</span> |
| **FURIA** | <span style='color:red'>21.8%</span> | <span style='color:red'>22.2%</span> | 40.3% | - | 39.2% | 54.6% | 48.7% | 54.9% | 55.5% | 51.0% | 54.7% | 62.7% | 62.5% | 61.4% | <span style='color:green'>66.5%</span> | 64.5% |
| **Falcons** | 35.9% | 38.3% | 50.0% | 60.8% | - | 59.5% | 60.0% | 64.3% | <span style='color:green'>69.1%</span> | 59.0% | 64.5% | <span style='color:green'>70.9%</span> | <span style='color:green'>71.1%</span> | <span style='color:green'>67.4%</span> | <span style='color:green'>69.6%</span> | <span style='color:green'>75.7%</span> |
| **Aurora** | <span style='color:red'>28.1%</span> | <span style='color:red'>27.7%</span> | 41.8% | 45.4% | 40.5% | - | 53.1% | 54.9% | 54.1% | 51.8% | 54.9% | 55.6% | 61.1% | 58.9% | 60.7% | 65.0% |
| **MOUZ** | <span style='color:red'>22.4%</span> | <span style='color:red'>21.9%</span> | 38.2% | 51.3% | 40.0% | 46.9% | - | 54.3% | 56.7% | 49.1% | 54.3% | 61.4% | 62.3% | 58.2% | <span style='color:green'>65.4%</span> | <span style='color:green'>66.9%</span> |
| **G2** | <span style='color:red'>24.9%</span> | <span style='color:red'>25.8%</span> | 35.7% | 45.1% | 35.7% | 45.1% | 45.7% | - | 47.5% | 46.7% | 54.3% | 55.0% | 58.0% | 56.3% | <span style='color:green'>65.5%</span> | 61.6% |
| **FUT** | <span style='color:red'>19.6%</span> | <span style='color:red'>18.0%</span> | <span style='color:red'>34.1%</span> | 44.5% | <span style='color:red'>30.9%</span> | 45.9% | 43.3% | 52.5% | - | 44.6% | 46.5% | 58.3% | 59.0% | 54.9% | 64.9% | 61.0% |
| **Legacy** | <span style='color:red'>28.4%</span> | <span style='color:red'>29.1%</span> | 39.5% | 49.0% | 41.0% | 48.2% | 50.9% | 53.3% | 55.4% | - | 51.5% | 55.3% | 59.4% | 58.3% | 63.3% | <span style='color:green'>66.0%</span> |
| **The MongolZ** | <span style='color:red'>21.7%</span> | <span style='color:red'>18.5%</span> | 36.4% | 45.3% | 35.5% | 45.1% | 45.7% | 45.7% | 53.5% | 48.5% | - | 55.2% | 52.2% | 56.5% | 65.0% | 60.6% |
| **BetBoom** | <span style='color:red'>16.9%</span> | <span style='color:red'>17.0%</span> | <span style='color:red'>31.7%</span> | 37.3% | <span style='color:red'>29.1%</span> | 44.4% | 38.6% | 45.0% | 41.7% | 44.7% | 44.8% | - | 52.0% | 50.9% | 59.4% | 57.7% |
| **PARIVISION** | <span style='color:red'>15.8%</span> | <span style='color:red'>15.8%</span> | <span style='color:red'>31.1%</span> | 37.5% | <span style='color:red'>28.9%</span> | 38.9% | 37.7% | 42.0% | 41.0% | 40.6% | 47.8% | 48.0% | - | 49.5% | 57.6% | 54.6% |
| **9z** | <span style='color:red'>23.5%</span> | <span style='color:red'>19.7%</span> | <span style='color:red'>32.4%</span> | 38.6% | <span style='color:red'>32.6%</span> | 41.1% | 41.8% | 43.7% | 45.1% | 41.7% | 43.5% | 49.1% | 50.5% | - | 56.4% | 54.8% |
| **Monte** | <span style='color:red'>15.7%</span> | <span style='color:red'>13.5%</span> | <span style='color:red'>26.5%</span> | <span style='color:red'>33.5%</span> | <span style='color:red'>30.4%</span> | 39.3% | <span style='color:red'>34.6%</span> | <span style='color:red'>34.5%</span> | 35.1% | 36.7% | 35.0% | 40.6% | 42.4% | 43.6% | - | 45.1% |
| **B8** | <span style='color:red'>13.0%</span> | <span style='color:red'>13.0%</span> | <span style='color:red'>27.6%</span> | 35.5% | <span style='color:red'>24.3%</span> | 35.0% | <span style='color:red'>33.1%</span> | 38.4% | 39.0% | <span style='color:red'>34.0%</span> | 39.4% | 42.3% | 45.4% | 45.2% | 54.9% | - |

---

## 🎲 最终推演结果与推荐

### 晋级概率与市场盘口验证 (含赛后复盘区)
这里将我们模拟器跑出的硬数据与外部市场（Polymarket）的热度进行了直接对比。当市场严重高估或低估某支队伍时（差异>±10%），我们会标记 ⚠️ 警示符号。

| 队伍 | 算法模拟晋级率 | 市场隐含概率 | 偏差分析 | 最终实际结果 |
|---|---|---|---|---|
| **Vitality** | 91.8% | 96.0% | -4.2% | *(待更新)* |
| **Spirit** | 89.3% | 90.0% | -0.7% | *(待更新)* |
| **Falcons** | 73.2% | 76.0% | -2.8% | *(待更新)* |
| **Natus Vincere** | 66.2% | 84.0% | **-17.8% ⚠️** (被高估) | *(待更新)* |
| **FURIA** | 56.2% | 78.0% | **-21.8% ⚠️** (被高估) | *(待更新)* |
| **Aurora** | 54.4% | 60.0% | -5.6% | *(待更新)* |
| **MOUZ** | 50.7% | 55.0% | -4.3% | *(待更新)* |
| **The MongolZ** | 47.0% | 37.0% | **+10.0% ⚠️** (被低估) | *(待更新)* |
| **Legacy** | 46.8% | 43.0% | +3.8% | *(待更新)* |
| **G2** | 42.0% | 53.0% | **-11.0% ⚠️** (低于市场预期) | *(待更新)* |
| **FUT** | 35.5% | 53.0% | **-17.5% ⚠️** (低于市场预期) | *(待更新)* |
| **9z** | 35.2% | 23.0% | **+12.2% ⚠️** (被低估) | *(待更新)* |
| **BetBoom** | 34.2% | 35.0% | -0.8% | *(待更新)* |
| **PARIVISION** | 34.2% | 33.0% | +1.2% | *(待更新)* |
| **Monte** | 22.0% | 13.0% | **+9.0% ⚠️** | *(待更新)* |
| **B8** | 21.4% | 7.0% | **+14.4% ⚠️** | *(待更新)* |

**本阶段模型有效性总结**：
*(赛后补充，分析地图 BP 模型、Roster Factor 以及市场融合这套混合双轨制的实际表现与改进空间。)*

### 🎯 推荐 Pick'Em 组合 (Top 5)

通过对上述矩阵的穷举搜索，以下是达成条件（获得 5 个以上正确预测）概率最高的 5 个阵容方案：

**方案 #1 (P(≥5) = 36.4% | 期望得分 = 4.01)**
*   **3-0**: Vitality, Spirit
*   **3-1/3-2**: Natus Vincere, Falcons, FURIA, Aurora, MOUZ, Legacy
*   **0-3**: B8, Monte

**方案 #2 (P(≥5) = 36.0% | 期望得分 = 4.00)**
*   **3-0**: Vitality, Spirit
*   **3-1/3-2**: Natus Vincere, Falcons, FURIA, Aurora, MOUZ, The MongolZ
*   **0-3**: B8, Monte

**方案 #3 (P(≥5) = 35.4% | 期望得分 = 3.98)**
*   **3-0**: Vitality, Spirit
*   **3-1/3-2**: Natus Vincere, Falcons, FURIA, Aurora, MOUZ, G2
*   **0-3**: B8, Monte

**方案 #4 (P(≥5) = 35.4% | 期望得分 = 3.97)**
*   **3-0**: Vitality, Spirit
*   **3-1/3-2**: Natus Vincere, Falcons, FURIA, MOUZ, Legacy, The MongolZ
*   **0-3**: B8, Monte

**方案 #5 (P(≥5) = 35.3% | 期望得分 = 3.97)**
*   **3-0**: Vitality, Spirit
*   **3-1/3-2**: Natus Vincere, Falcons, FURIA, Aurora, Legacy, The MongolZ
*   **0-3**: B8, Monte

> **💡 组合总结**：
> 在概率最高的预测方案中，3-0 位置主要由 **Vitality** 和 **Spirit** 占据；0-3 位置主要由 **B8** 和 **Monte** 占据。
> 3-1/3-2 位置在 Legacy、G2、The MongolZ 之间存在微调空间。

