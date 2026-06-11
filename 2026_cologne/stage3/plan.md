# Stage 3 (全 Bo3 瑞士轮) 预测方案规划

## 赛制概要
- 16 支队伍，瑞士轮 5 轮，**所有比赛均为 Bo3**
- Buchholz 分池 + 种子排序（与 Stage 2 相同）
- 8 支队伍晋级 Playoffs，8 支淘汰
- Pick'Em 规则不变：2x3-0 + 6x3-1/3-2 + 2x0-3，答对 >=5 过关（注意：放在 3-1/3-2 位的队伍如果打出 3-0，不得分）

## 核心改进：引入地图维度

Stage 2 使用单一的 δ 修正因子来捕获 Bo3 战术深度，但这是一个标量压缩，丢失了大量信息（无法区分"全面弱"和"偏科弱"，也无法感知双方地图池的重叠情况）。

Stage 3 全 Bo3 的赛制使得地图 ban/pick 博弈在**每一轮**都会发生，地图池深浅从"偶尔致命"变为"场场致命"。因此我们将 δ 因子升级为**地图级 ban/pick 模拟**。

---

## 计算流水线

### Step 1. 数据抓取（需升级）
- 抓取近半年所有比赛数据（与 Stage 2 相同）
- **新增 1**：通过 `/teams/{teamid}` 接口抓取所有 16 支队伍的**当前大名单 (Current Roster)**
- **新增 2**：通过 `/matches/{matchid}/stats?by_map=true` 接口抓取每场 Bo3 内的**逐图比分**以及**出战选手 ID**
- 将 Stage 2 的实战比赛数据也纳入

### Step 2. 同步推演：H2H 矩阵 + 地图加权胜率表
两套数据系统在**同一个时间循环**中同步构建，共享同一个 Elo 快照：

```
按时间排序所有比赛
for each match in chronological_order:

    # ① 计算换人减权重与历史衰减 (Roster Factor 2.0)
    # 获取当时出战的 5 名选手的个人 Rating，对比现在的队伍名单：
    retained_rating = sum(player.rating for player in (match_players ∩ current_roster[team]))
    total_rating = sum(player.rating for player in match_players)
    
    # 相比简单的人数扣减，使用战力保留比例的平方作为惩罚函数
    # 比如：只少了一个混子 (保留 85% 战力) -> 0.85^2 = 0.72 权重
    # 比如：少了一个超级大腿 (保留 75% 战力) -> 0.75^2 = 0.56 权重
    roster_factor = (retained_rating / total_rating) ^ 2
    
    # 时间衰减：半衰期 60 天的指数衰减，最近一周额外加成
    time_decay = 0.5 ** (days_ago / 60)
    if days_ago <= 6: time_decay *= 1.2

    opp_elo_snapshot = global_elo[opponent]
    weight = opp_elo_snapshot / 1000 × time_decay × roster_factor

    # ② 更新 H2H 矩阵（仅 Bo3，Bo1 不纳入）
    if best_of == 3:
        update_h2h_matrix(team_a, team_b, total_score, weight)

    # ③ 更新地图加权胜率表（Bo1 和 Bo3 均纳入，每张实际打出的图都计入）
    for each map played in this match:
        map_stats[team][map].wins   += result × weight
        map_stats[team][map].losses += (1-result) × weight
        map_stats[team][map].count  += 1       # 记录原始出场次数，用于 Step 4 的 Familiarity 平滑

    # ④ 计算单场震荡值 (Shock Value) 并更新队伍方差指数 (V值)
    # 胜率越悬殊，爆冷产生的 Shock 越大
    expected_p = 1 / (1 + 10 ** ((opp_elo_snapshot - global_elo[team]) / 400))
    shock = ((result - expected_p) ** 2) / (expected_p * (1 - expected_p))
    team_v_value[team] = 0.9 * team_v_value[team] + 0.1 * shock
    # ⑤ (废弃) 动态更新全局 Elo：不再实施
    # 为了保证 V 值的 shock 计算分母始终锚定一个绝对实力参考系，
    # Global Elo 仅作为静态的先验实力快照，不做动态更新。
    # 所有动态胜率博弈 100% 转移至 H2H 增量矩阵和地图胜率中。
# ⑥ 循环结束后：KAST 修正 V 值归一化
# 原始 V 值范围过大 (1.35~5.89)，直接作为 Logit 除数会把强队胜率强行压扁。
# 用 KAST 作为阻尼器：KAST 高的队伍（选手个人稳定），其 V 值应被削弱。
V_norm(T) = V_raw(T) / median(V_raw)           # 归一化到 ~1.0
KAST_factor(T) = (median(KAST) / KAST(T)) ^ α  # α=2，KAST 越高则因子越小
V_adj(T) = V_norm(T) × KAST_factor(T)
> 输出：02_v_values.json (已 KAST 修正)，02_v_values_raw.json (原始值)
```

关键点：对手的 Elo 使用的是**比赛发生时的快照**，而非最终值，避免时间错位。

### Step 3. 市场轨道 (Market Prior)
这是单纯反映外部资金倾向的“外界共识”轨道。
1. 提取 Polymarket "Qualify to Playoffs" 赔率，用 Bradley-Terry 模型反推出 16x16 市场先验矩阵。
2. **首轮盘口 100% 覆写**：抓取首轮确定对阵的单场盘口，对该矩阵对应格子进行 100% 的精确替换。
> 输出：`P_market`

### Step 4. 数据轨道与最终融合 (Data & Fusion)
这是完全基于我们底层计算的“硬数据”轨道。

当模拟器需要判定 A vs B 的 Bo3 胜负时：
```
# 1. 基础数据融合 (H2H 与 地图)
P_h2h_bo3 = 转换为Bo3的H2H胜率(A,B) 
P_map_bo3 = simulate_ban_pick(A, B)  # 地图 BP 博弈胜率
P_data_base = 0.7 × P_h2h_bo3 + 0.3 × P_map_bo3

# 2. V 值方差缩放 (使用 Step 2 输出的 KAST 修正后 V_adj)
V_joint = sqrt(V_adj[A] × V_adj[B])
Logit_base = ln(P_data_base / (1 - P_data_base))
P_data = 1 / (1 + e^(-(Logit_base / V_joint)))

# 3. 终极融合 (50% 市场 + 50% 数据)
P_final = 0.5 × P_market[A][B] + 0.5 × P_data
```

#### 地图 Ban/Pick 模拟 (`simulate_ban_pick`)
```
前置条件：已从历史数据提取各队的地图 BP 画像，拥有 Pref = pick_rate - ban_rate

对于池中的每一张地图，计算相对优势差 (Delta)：
Delta(m) = Pref_A(m) - Pref_B(m)

对 A 队有利的图，Delta 为正；对 B 队有利的图，Delta 为负。
博弈为 Minimax 零和博弈：A 致力于最大化 Delta，B 致力于最小化 Delta。

# 第一轮 Ban/Pick
A ban Delta 最小的图 (对自己最劣，B 最爱)
B ban Delta 最大的图 (对 A 最爽，B 最怕)
A pick 剩余中 Delta 最大的图 → 确定 图1 (计算 P(A 赢图1))
B pick 剩余中 Delta 最小的图 → 确定 图2 (计算 P(A 赢图2))

# 第二轮 Ban & 决胜图
A ban 剩余 3 图中 Delta 最小的图
B ban 剩余 2 图中 Delta 最大的图
决胜图为剩余的最后一张 → 确定 图3 (计算 P(A 赢图3))

模拟三局两胜，输出 Bo3 的理论胜率 P_map_bo3
```

#### 单图加权胜率合成（Odds-Ratio 与平滑体系）
当计算 A vs B 在某张地图的预期胜率时，为防止极端胜率（如 100% 或 0%）导致公式崩溃，并充分考虑熟练度差异，按以下连续公式进行计算：

1. **胜率基底平滑 (Laplace Smoothing)**：
   先对双方的原始胜率进行贝叶斯收缩：
   $WR_A = (加权胜场_A + prior_A \times 5) / (加权总场_A + 5)$
   *(其中 $prior_A$ = A 队所有地图的加权胜场总和 / 加权总场总和)*
   $WR_B$ 同理。
2. **理论对局概率 (Odds-Ratio)**：
   $原始\_P\_A = WR_A \times (1-WR_B) / [WR_A \times (1-WR_B) + WR_B \times (1-WR_A)]$
3. **可靠性收缩 (Reliability Blend)**：
   设双方在该图的总场数 $N_{total} = N_A + N_B$。
   权重 $W = N_{total} / (N_{total} + 10)$。
   $P_{blend} = W \times 原始\_P\_A + (1 - W) \times P_{h2h}$
   *(如果双方都没打过该图，$W=0$，平滑退化为纯拼枪硬实力 $P_{h2h}$)*
4. **单边盲区惩罚 (Perma-ban Penalty)**：
   如果一方场数属于正常范围（如 10 场 vs 20 场），这不属于逃避，不应有惩罚。
   因此我们引入一个连续的指数“回避度”函数：$Avoidance(N) = 2^{-N}$
   （当 $N=0$ 时为 1；$N=1$ 时为 0.5；$N \ge 5$ 时趋近于 0）
   在对数几率上进行不对称惩罚：
   $Logit_{map} = \ln(P_{blend} / (1 - P_{blend})) + \lambda \times (2^{-N_B} - 2^{-N_A})$
   *(其中 $\lambda$ 为惩罚烈度，暂定为 3.0)*
   最后将 $Logit_{map}$ 还原为最终的单图实战胜率 $P_A$ 供 BP 模拟器使用。

### Step 5. 暴力搜索最优 Pick'Em 组合
与 Stage 2 完全一致：穷举所有 3-0 / 3-1/3-2 / 0-3 组合，找 P(>=5) 最大的方案。

### 📊 面向普通用户的 README 数据展示方案
底层代码我们用乘法 V 值（比如 0.8 或 1.25）来保证数学上的几何对称性，但在最终写入 README 向普通用户展示时，我们会将其转换为易读的**“队伍稳定性指数 (Stability Rating)”**：
- 例如 $V = 1.0$，展示为 `0% (标准方差)`
- 例如 $V = 1.25$，展示为 `+25% (神经刀/高爆冷率)`
- 例如 $V = 0.8$，展示为 `-20% (铁头功/极低爆冷率)`
这样既保全了核心代码的严密性，又极大降低了用户的阅读门槛。

---

## 与 Stage 2 的差异对照

| 维度 | Stage 2 | Stage 3 |
|---|---|---|
| 赛制 | R1-R2 Bo1，R3-R5 Bo3 | **全部 Bo3** |
| Bo3 建模 | δ 修正因子（单标量/队） | **地图级 ban/pick 模拟** |
| 数据粒度 | 比赛级（总比分） | **地图级（逐图比分）** |
| 单场胜负判定 | 查表 + δ 公式 | **独立双轨并行 → 终极 4:6 融合** |
| 地图加权胜率 | 不涉及 | **Elo加权 + 时间衰减 + Odds-Ratio + Familiarity 平滑** |
| Elo 同步 | H2H 单轨推演 | **H2H + 地图双轨同步推演** |

---

## 可调参数汇总
| 参数 | 含义 | 当前值 | 备注 |
|---|---|---|---|
| `k` | 胜率基底平滑的贝叶斯先验强度 | 5 | 虚拟先验比赛场数 |
| Reliability 常数 | 可靠性收缩的半饱和场数 | 10 | $W = N/(N+10)$ |
| $\lambda$ | 单边盲区惩罚烈度 | 3.0 | Logit 空间下的偏移系数 |
| 半衰期 | 时间衰减的半衰期天数 | 60 天 | $0.5^{days/60}$ |
| 近一周加成 | 最近 6 天内比赛的额外权重 | ×1.2 | |
| H2H vs 地图 权重 | 数据轨道内部融合 | 7:3 | |
| 市场 vs 数据 权重 | 终极融合比例 | 5:5 | |
