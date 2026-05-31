"""
IEM Cologne Major 2026 - Stage 1 Pick'Em 最优组合搜索 v4
直接暴力搜索所有合理组合，找到P(≥5)最高的picks
"""
import random
import math
import numpy as np
from itertools import combinations

random.seed(42)
SIMULATIONS = 200000

teams_data = {
    "GamerLegion":        {"score": 84.5},
    "BetBoom":            {"score": 76.8},
    "B8":                 {"score": 73.0},
    "Heroic":             {"score": 60.6},
    "TYLOO":              {"score": 57.5},
    "Team Liquid":        {"score": 57.1},
    "BIG":                {"score": 57.1},
    "MIBR":               {"score": 55.9},
    "SINNERS":            {"score": 54.5},
    "M80":                {"score": 51.0},
    "NRG":                {"score": 46.1},
    "Lynn Vision":        {"score": 41.5},
    "Sharks":             {"score": 39.1},
    "Gaimin Gladiators":  {"score": 37.9},
    "FlyQuest":           {"score": 34.6},
    "THUNDER dOWNUNDER":  {"score": 20.3},
}

R1_MATCHES = [
    ("GamerLegion", "NRG"),
    ("B8", "TYLOO"),
    ("Heroic", "Sharks"),
    ("BetBoom", "Gaimin Gladiators"),
    ("BIG", "Team Liquid"),
    ("M80", "Lynn Vision"),
    ("MIBR", "THUNDER dOWNUNDER"),
    ("SINNERS", "FlyQuest"),
]

POLYMARKET_R1 = {
    ("GamerLegion", "NRG"): 0.70,
    ("B8", "TYLOO"): 0.59,
    ("Heroic", "Sharks"): 0.62,
    ("BetBoom", "Gaimin Gladiators"): 0.72,
    ("BIG", "Team Liquid"): 0.54,
    ("M80", "Lynn Vision"): 0.57,
    ("MIBR", "THUNDER dOWNUNDER"): 0.75,
    ("SINNERS", "FlyQuest"): 0.55,
}

team_names = list(teams_data.keys())
team_idx = {name: i for i, name in enumerate(team_names)}


def fit_k():
    best_k, best_err = 40, float('inf')
    for k_try in [x * 0.5 for x in range(20, 200)]:
        err = 0
        for (t1, t2), pm_p in POLYMARKET_R1.items():
            s1 = teams_data[t1]["score"]
            s2 = teams_data[t2]["score"]
            pred_p = 1 / (1 + math.exp(-(s1 - s2) / k_try))
            err += (pred_p - pm_p) ** 2
        if err < best_err:
            best_err = err
            best_k = k_try
    return best_k


K = fit_k()


def win_prob_bo1(team_a, team_b):
    sa = teams_data[team_a]["score"]
    sb = teams_data[team_b]["score"]
    return 1 / (1 + math.exp(-(sa - sb) / K))


def win_prob_bo3(team_a, team_b):
    p = win_prob_bo1(team_a, team_b)
    return p * p * (3 - 2 * p)


def play_match(team_a, team_b, bo3=False):
    p = win_prob_bo3(team_a, team_b) if bo3 else win_prob_bo1(team_a, team_b)
    return team_a if random.random() < p else team_b


def simulate_swiss():
    records = {t: [0, 0] for t in teams_data}
    history = {t: set() for t in teams_data}
    initial_seed = {t: i for i, t in enumerate(sorted(teams_data, key=lambda x: teams_data[x]["score"], reverse=True))}

    def get_valid_matching(pool_sorted):
        if not pool_sorted:
            return []
        t1 = pool_sorted[0]
        for i in range(len(pool_sorted) - 1, 0, -1):
            t2 = pool_sorted[i]
            if t2 not in history[t1]:
                remaining = pool_sorted[1:i] + pool_sorted[i+1:]
                sub = get_valid_matching(remaining)
                if sub is not None:
                    return [(t1, t2)] + sub
        return None

    def pair_and_play(pool, round_num, bo3=False):
        if round_num <= 2:
            pool_sorted = sorted(pool, key=lambda t: initial_seed[t])
        else:
            def buchholz(t):
                return sum(records[opp][0] - records[opp][1] for opp in history[t])
            pool_sorted = sorted(pool, key=lambda t: (-buchholz(t), initial_seed[t]))

        matchings = get_valid_matching(pool_sorted)
        if matchings is None:
            matchings = [(pool_sorted[i], pool_sorted[len(pool_sorted)-1-i]) for i in range(len(pool_sorted)//2)]

        winners, losers = [], []
        for t1, t2 in matchings:
            winner = play_match(t1, t2, bo3)
            loser = t2 if winner == t1 else t1
            records[winner][0] += 1
            records[loser][1] += 1
            history[t1].add(t2)
            history[t2].add(t1)
            winners.append(winner)
            losers.append(loser)
        return winners, losers

    r1_winners, r1_losers = [], []
    for t1, t2 in R1_MATCHES:
        winner = play_match(t1, t2)
        loser = t2 if winner == t1 else t1
        records[winner][0] += 1
        records[loser][1] += 1
        history[t1].add(t2)
        history[t2].add(t1)
        r1_winners.append(winner)
        r1_losers.append(loser)

    r2_high_w, r2_high_l = pair_and_play(r1_winners, 2)
    r2_low_w, r2_low_l = pair_and_play(r1_losers, 2)

    advanced, eliminated = [], []
    pool_2_0 = r2_high_w
    pool_0_2 = r2_low_l
    pool_1_1 = r2_high_l + r2_low_w

    r3_20_w, r3_20_l = pair_and_play(pool_2_0, 3, bo3=True)
    advanced.extend(r3_20_w)
    r3_02_w, r3_02_l = pair_and_play(pool_0_2, 3, bo3=True)
    eliminated.extend(r3_02_l)
    r3_11_w, r3_11_l = pair_and_play(pool_1_1, 3)

    pool_2_1 = r3_20_l + r3_11_w
    pool_1_2 = r3_02_w + r3_11_l

    r4_21_w, r4_21_l = pair_and_play(pool_2_1, 4, bo3=True)
    advanced.extend(r4_21_w)
    r4_12_w, r4_12_l = pair_and_play(pool_1_2, 4, bo3=True)
    eliminated.extend(r4_12_l)

    pool_2_2 = r4_21_l + r4_12_w
    r5_w, r5_l = pair_and_play(pool_2_2, 5, bo3=True)
    advanced.extend(r5_w)
    eliminated.extend(r5_l)

    results = {}
    for t in teams_data:
        w, l = records[t]
        if w == 3 and l == 0:
            results[t] = 0  # 3-0
        elif w == 0 and l == 3:
            results[t] = 2  # 0-3
        elif w == 3:
            results[t] = 1  # 3-1/3-2
        else:
            results[t] = 3  # eliminated (non 0-3)
    return results


# ==================== 模拟 ====================
print("模拟Swiss赛制中...")

# outcome_matrix[sim][team] = 0(3-0), 1(3-1/3-2), 2(0-3), 3(eliminated)
outcome_matrix = np.zeros((SIMULATIONS, len(team_names)), dtype=np.int8)

for sim_i in range(SIMULATIONS):
    result = simulate_swiss()
    for t, outcome in result.items():
        outcome_matrix[sim_i, team_idx[t]] = outcome

# 预计算布尔矩阵
is_30 = (outcome_matrix == 0)    # shape: (SIMS, 16)
is_312 = (outcome_matrix == 1)
is_03 = (outcome_matrix == 2)

# 各队概率
print()
print("=" * 80)
print("  各队概率")
print("=" * 80)
print()
print(f"  {'队伍':<22} {'3-0':>6} {'3-1/3-2':>8} {'0-3':>6} {'淘汰':>6}")
print(f"  {'-'*50}")

p30_by_team = {}
p312_by_team = {}
p03_by_team = {}
for i, name in enumerate(team_names):
    p30 = is_30[:, i].mean() * 100
    p312 = is_312[:, i].mean() * 100
    p03 = is_03[:, i].mean() * 100
    elim = 100 - p30 - p312 - p03
    p30_by_team[name] = p30
    p312_by_team[name] = p312
    p03_by_team[name] = p03
    print(f"  {name:<22} {p30:>5.1f}% {p312:>7.1f}% {p03:>5.1f}% {elim:>5.1f}%")

# ==================== 暴力搜索 ====================
print()
print("=" * 80)
print("  暴力搜索最优组合")
print("=" * 80)
print()

# 3-0候选: 取3-0概率前8的队伍
top30_candidates = sorted(range(len(team_names)), key=lambda i: is_30[:, i].sum(), reverse=True)[:8]
# 0-3候选: 取0-3概率前6的队伍
top03_candidates = sorted(range(len(team_names)), key=lambda i: is_03[:, i].sum(), reverse=True)[:6]

print(f"  3-0候选 ({len(top30_candidates)}): {[team_names[i] for i in top30_candidates]}")
print(f"  0-3候选 ({len(top03_candidates)}): {[team_names[i] for i in top03_candidates]}")
print()

best_p5 = 0
best_combo = None
best_avg = 0
total_combos = 0
top_results = []

for combo_30 in combinations(top30_candidates, 2):
    for combo_03 in combinations(top03_candidates, 2):
        # 检查3-0和0-3没有重叠
        if set(combo_30) & set(combo_03):
            continue

        used = set(combo_30) | set(combo_03)
        remaining = [i for i in range(len(team_names)) if i not in used]

        # 对remaining按3-1/3-2概率排序，取前6
        remaining_sorted = sorted(remaining, key=lambda i: is_312[:, i].sum(), reverse=True)

        # 尝试top6和几种替换
        candidates_312 = [remaining_sorted[:6]]
        # 也尝试把第7名换入
        if len(remaining_sorted) > 6:
            for swap_pos in range(6):
                alt = list(remaining_sorted[:6])
                alt[swap_pos] = remaining_sorted[6]
                candidates_312.append(alt)

        for combo_312 in candidates_312:
            # 计算得分
            score = np.zeros(SIMULATIONS, dtype=np.int8)
            for t in combo_30:
                score += is_30[:, t]
            for t in combo_312:
                score += is_312[:, t]
            for t in combo_03:
                score += is_03[:, t]

            p5 = (score >= 5).mean() * 100
            avg = score.mean()
            total_combos += 1

            if p5 > best_p5 or (p5 == best_p5 and avg > best_avg):
                best_p5 = p5
                best_avg = avg
                best_combo = (combo_30, tuple(combo_312), combo_03)

            if p5 >= best_p5 - 2:  # 记录接近最优的
                top_results.append((p5, avg, combo_30, tuple(combo_312), combo_03))

print(f"  搜索了 {total_combos:,} 种组合")
print()

# 去重排序
top_results.sort(key=lambda x: (-x[0], -x[1]))
seen = set()
unique_top = []
for r in top_results:
    key = (r[2], r[3], r[4])
    if key not in seen:
        seen.add(key)
        unique_top.append(r)

print("=" * 80)
print("  TOP 10 最优组合")
print("=" * 80)
print()

for rank, (p5, avg, c30, c312, c03) in enumerate(unique_top[:10], 1):
    names_30 = [team_names[i] for i in c30]
    names_312 = [team_names[i] for i in c312]
    names_03 = [team_names[i] for i in c03]
    marker = " ⭐" if rank == 1 else ""
    print(f"  #{rank}{marker}  P(≥5)={p5:.1f}%  期望={avg:.2f}")
    print(f"       3-0:     {', '.join(names_30)}")
    print(f"       3-1/3-2: {', '.join(names_312)}")
    print(f"       0-3:     {', '.join(names_03)}")
    print()

# 最优方案详细分布
print("=" * 80)
print("  最优方案得分分布")
print("=" * 80)
print()

c30, c312, c03 = best_combo
score = np.zeros(SIMULATIONS, dtype=np.int8)
for t in c30:
    score += is_30[:, t]
for t in c312:
    score += is_312[:, t]
for t in c03:
    score += is_03[:, t]

for s in range(11):
    pct = (score == s).mean() * 100
    bar = "█" * int(pct * 2)
    marker = " ← 目标" if s == 5 else ""
    print(f"    {s:>2}分: {pct:5.1f}% {bar}{marker}")

print()
p5 = (score >= 5).mean() * 100
p6 = (score >= 6).mean() * 100
p7 = (score >= 7).mean() * 100
print(f"  P(≥5) = {p5:.1f}%  |  P(≥6) = {p6:.1f}%  |  P(≥7) = {p7:.1f}%")
