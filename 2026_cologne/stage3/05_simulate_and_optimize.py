import json, random, os
from collections import defaultdict
from itertools import combinations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEAMS = [
    "Vitality", "Natus Vincere", "Falcons", "The MongolZ", "PARIVISION", "Aurora", "FURIA", "MOUZ",
    "Spirit", "FUT", "G2", "BetBoom", "9z", "Monte", "B8", "Legacy",
]

R1_MATCHES = [
    ("The MongolZ", "BetBoom"),
    ("PARIVISION", "9z"),
    ("MOUZ", "Legacy"),
    ("Spirit", "Natus Vincere"),
    ("Falcons", "G2"),
    ("Vitality", "FUT"),
    ("Aurora", "Monte"),
    ("FURIA", "B8"),
]

MARKET_ADVANCE = {
    "Vitality": 0.96,
    "Spirit": 0.90,
    "Natus Vincere": 0.84,
    "FURIA": 0.78,
    "Falcons": 0.76,
    "Aurora": 0.60,
    "MOUZ": 0.55,
    "G2": 0.53,
    "FUT": 0.53,
    "Legacy": 0.43,
    "The MongolZ": 0.37,
    "BetBoom": 0.35,
    "PARIVISION": 0.33,
    "9z": 0.23,
    "Monte": 0.13,
    "B8": 0.07
}

NUM_SIMS = 200000

def get_buchholz(team, records, history):
    return sum(records[opp][0] - records[opp][1] for opp in history[team])

def pair_pool(pool, records, history, initial_seed):
    pool_sorted = sorted(pool, key=lambda t: (-get_buchholz(t, records, history), initial_seed[t]))
    pairs = []
    used = set()
    for i, t1 in enumerate(pool_sorted):
        if t1 in used:
            continue
        for j in range(len(pool_sorted) - 1, i, -1):
            t2 = pool_sorted[j]
            if t2 in used or t2 in history[t1]:
                continue
            pairs.append((t1, t2))
            used.add(t1)
            used.add(t2)
            break
    remaining = [t for t in pool_sorted if t not in used]
    for i in range(0, len(remaining) - 1, 2):
        pairs.append((remaining[i], remaining[i + 1]))
    return pairs

def main():
    print("Step 5: Running Swiss Monte Carlo Simulation & Optimizer...")
    with open(os.path.join(BASE_DIR, "04_final_matrix.json"), "r") as f:
        final_matrix = json.load(f)

    initial_seed = {t: i for i, t in enumerate(TEAMS)}

    def get_win_prob(a, b):
        return final_matrix[f"{a}|{b}"]

    def simulate_swiss():
        records = {t: [0, 0] for t in TEAMS}
        history = {t: set() for t in TEAMS}
        advanced, eliminated = [], []

        # R1 matches (if defined)
        for t1, t2 in R1_MATCHES:
            winner = t1 if random.random() < get_win_prob(t1, t2) else t2
            loser = t2 if winner == t1 else t1
            records[winner][0] += 1
            records[loser][1] += 1
            history[winner].add(loser)
            history[loser].add(winner)

        # Ensure we simulate 5 rounds total. If R1 is missing, start from round 1.
        start_round = 2 if R1_MATCHES else 1

        for round_num in range(start_round, 6):
            pools = defaultdict(list)
            for t in TEAMS:
                if t not in advanced and t not in eliminated:
                    w, l = records[t]
                    pools[(w, l)].append(t)

            for (w, l), pool in pools.items():
                if len(pool) < 2:
                    continue
                pairs = pair_pool(pool, records, history, initial_seed)
                for t1, t2 in pairs:
                    winner = t1 if random.random() < get_win_prob(t1, t2) else t2
                    loser = t2 if winner == t1 else t1
                    records[winner][0] += 1
                    records[loser][1] += 1
                    history[winner].add(loser)
                    history[loser].add(winner)

                    if records[winner][0] == 3:
                        advanced.append(winner)
                    if records[loser][1] == 3:
                        eliminated.append(loser)

        return {t: tuple(records[t]) for t in TEAMS}

    counts_30 = defaultdict(int)
    counts_312 = defaultdict(int)
    counts_03 = defaultdict(int)
    all_results = []

    import numpy as np
    import time

    print(f"  Simulating {NUM_SIMS:,} times...")
    # 为了使用 Numpy 加速几万种组合的暴力搜索，我们把结果存为矩阵
    # 形状 (NUM_SIMS, 16)
    is_30_mat = np.zeros((NUM_SIMS, 16), dtype=np.bool_)
    is_312_mat = np.zeros((NUM_SIMS, 16), dtype=np.bool_)
    is_03_mat = np.zeros((NUM_SIMS, 16), dtype=np.bool_)

    counts_30 = defaultdict(int)
    counts_312 = defaultdict(int)
    counts_03 = defaultdict(int)

    start_sim_time = time.time()
    for i in range(NUM_SIMS):
        if i > 0 and i % 25000 == 0:
            elapsed = time.time() - start_sim_time
            eta = (elapsed / i) * (NUM_SIMS - i)
            print(f"    [{i:,} / {NUM_SIMS:,}] ETA: {eta:.1f}s...")
            
        result = simulate_swiss()
        for t_idx, t_name in enumerate(TEAMS):
            w, l = result[t_name]
            if w == 3 and l == 0:
                is_30_mat[i, t_idx] = True
                counts_30[t_name] += 1
            elif w == 3:
                is_312_mat[i, t_idx] = True
                counts_312[t_name] += 1
            elif l == 3 and w == 0:
                is_03_mat[i, t_idx] = True
                counts_03[t_name] += 1

    lines = ["=" * 80, "  验证: 模拟晋级率 vs 市场赔率", "=" * 80]
    lines.append(f"  {'队伍':<18} {'模拟':>7} {'市场':>7} {'差异':>7}")
    lines.append(f"  {'-'*18} {'-'*7} {'-'*7} {'-'*7}")

    for t in sorted(TEAMS, key=lambda x: MARKET_ADVANCE.get(x, 0.5), reverse=True):
        sim = (counts_30[t] + counts_312[t]) / NUM_SIMS
        mkt = MARKET_ADVANCE.get(t, 0.5)
        diff = sim - mkt
        flag = "⚠️" if abs(diff) > 0.08 else ""
        lines.append(f"  {t:<18} {sim:>6.1%} {mkt:>6.1%} {diff:>+6.1%} {flag}")

    # Pick'Em 暴力搜索
    sorted_by_30 = sorted(TEAMS, key=lambda t: counts_30[t], reverse=True)
    sorted_by_03 = sorted(TEAMS, key=lambda t: counts_03[t], reverse=True)
    # 选出 3-0 和 0-3 出现次数最高的前 10 支队伍作为候选（C(10,2) = 45 种可能）
    c30 = sorted_by_30[:10]
    c03 = sorted_by_03[:10]

    lines.extend(["", "=" * 80, "  暴力搜索最优 Pick'Em 组合", "=" * 80])

    def eval_combo_vectorized(p30_idx, p312_idx, p03_idx):
        scores = (
            is_30_mat[:, p30_idx].sum(axis=1) + 
            is_312_mat[:, p312_idx].sum(axis=1) + 
            is_03_mat[:, p03_idx].sum(axis=1)
        )
        p5 = (scores >= 5).mean()
        ev = scores.mean()
        # count occurrences of each score 0-10
        dist = {s: int((scores == s).sum()) for s in range(11)}
        return float(p5), float(ev), dist

    best_combos = []
    
    # 将名字转换为索引
    team_to_idx = {t: i for i, t in enumerate(TEAMS)}

    # 计算一下总共有多少个合法的 30/03 对，用来显示进度
    valid_pairs = sum(1 for p30 in combinations(c30, 2) for p03 in combinations(c03, 2) if not (set(p30) & set(p03)))
    print(f"  Total valid 3-0/0-3 pairs to evaluate: {valid_pairs}")
    
    pair_count = 0
    start_opt_time = time.time()
    
    # 开始扩大搜索范围
    is_312_mat_int8 = is_312_mat.astype(np.int8)
    for p30 in combinations(c30, 2):
        for p03 in combinations(c03, 2):
            if set(p30) & set(p03):
                continue
            
            pair_count += 1
            if pair_count % 50 == 0:
                elapsed = time.time() - start_opt_time
                eta = (elapsed / pair_count) * (valid_pairs - pair_count)
                print(f"    Evaluating pair {pair_count} / {valid_pairs} (ETA: {eta:.1f}s)...")

            
            remaining = [t for t in TEAMS if t not in p30 and t not in p03]
            # 对剩下的队伍按晋级概率排序
            remaining_sorted = sorted(remaining, key=lambda t: counts_312[t], reverse=True)
            top_10_remaining = remaining_sorted[:10]
            
            # 提前构造好 210 种组合的 mask (形状: 16 x 210)
            combos_312 = list(combinations(top_10_remaining, 6))
            num_combos = len(combos_312)
            mask_312 = np.zeros((16, num_combos), dtype=np.int8)
            for j, combo in enumerate(combos_312):
                for team in combo:
                    mask_312[team_to_idx[team], j] = 1
            
            p30_idx = [team_to_idx[t] for t in p30]
            p03_idx = [team_to_idx[t] for t in p03]
            
            # 提取 05_simulate_and_optimize.py 中的优化部分
            # 计算固定的 3-0 和 0-3 得分 (形状: 200000, 1)
            base_scores = (is_30_mat[:, p30_idx].sum(axis=1) + is_03_mat[:, p03_idx].sum(axis=1)).astype(np.int8)
            
            # 矩阵相乘： (200000, 16) @ (16, 210) -> (200000, 210)
            p312_scores = np.dot(is_312_mat_int8, mask_312)
            
            # 总得分
            total_scores = base_scores[:, None] + p312_scores
            
            # 计算指标
            p5_arr = (total_scores >= 5).mean(axis=0)
            ev_arr = total_scores.mean(axis=0)
            
            for j in range(num_combos):
                # 只有在前十名左右的组合，我们才保存，避免内存爆炸
                if p5_arr[j] > 0.1:  # 稍微过滤一下极低概率的组合
                    dist = None  # 先不存 dist，最后提取最佳结果时再算
                    best_combos.append((float(p5_arr[j]), float(ev_arr[j]), list(p30), list(combos_312[j]), list(p03), dist))

    best_combos.sort(key=lambda x: (-x[0], -x[1]))

    lines.extend(["", "=" * 80, "  暴力搜索最优 Pick'Em 组合 (Top 100)", "=" * 80])
    for i, (p5, ev, p30, p312, p03, _) in enumerate(best_combos[:100]):
        lines.append(f"\n  #{i+1}  P(≥5)={p5:.1%}  期望={ev:.2f}")
        lines.append(f"       3-0:     {', '.join(p30)}")
        lines.append(f"       3-1/3-2: {', '.join(p312)}")
        lines.append(f"       0-3:     {', '.join(p03)}")
        
    if len(best_combos) > 500:
        lines.extend(["", "=" * 80, "  低概率组合采样 (反面教材展示)", "=" * 80])
        total_c = len(best_combos)
        # 挑选 50%, 75%, 90%, 99%, 100% 顺位的组合
        sample_indices = [
            total_c // 2, 
            total_c * 3 // 4, 
            total_c * 9 // 10, 
            total_c - (total_c // 100) - 1, 
            total_c - 1
        ]
        for idx in sample_indices:
            p5, ev, p30, p312, p03, _ = best_combos[idx]
            lines.append(f"\n  #{idx+1} (排位)  P(≥5)={p5:.1%}  期望={ev:.2f}")
            lines.append(f"       3-0:     {', '.join(p30)}")
            lines.append(f"       3-1/3-2: {', '.join(p312)}")
            lines.append(f"       0-3:     {', '.join(p03)}")

    if best_combos:
        # 重算排名第一的 dist
        p5, ev, p30, p312, p03, _ = best_combos[0]
        p30_idx = [team_to_idx[t] for t in p30]
        p312_idx = [team_to_idx[t] for t in p312]
        p03_idx = [team_to_idx[t] for t in p03]
        scores = (is_30_mat[:, p30_idx].sum(axis=1) + 
                  is_312_mat[:, p312_idx].sum(axis=1) + 
                  is_03_mat[:, p03_idx].sum(axis=1))
        dist = {s: int((scores == s).sum()) for s in range(11)}
        
        lines.extend(["", "=" * 80, "  最优方案得分分布", "=" * 80])
        for s in range(11):
            pct = dist.get(s, 0) / NUM_SIMS
            bar = "█" * int(pct * 50)
            lines.append(f"    {s:>2}分: {pct:>5.1%} {bar}")

    output = "\n".join(lines)
    print(output)

    with open(os.path.join(BASE_DIR, "05_simulation_results.txt"), "w", encoding="utf-8") as f:
        f.write(output)
    print("\nDone. Saved 05_simulation_results.txt\n")

if __name__ == "__main__":
    main()
