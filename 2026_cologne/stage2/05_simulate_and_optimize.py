import json, random
from collections import defaultdict
from itertools import combinations

TEAMS = [
    "Spirit", "G2", "Legacy", "FUT", "Astralis", "9z", "Monte", "paiN",
    "GamerLegion", "BetBoom", "B8", "TYLOO", "BIG", "MIBR", "M80", "FlyQuest"
]

R1_MATCHES = [
    ("Spirit", "BetBoom"), ("G2", "M80"), ("Legacy", "MIBR"), ("FUT", "B8"),
    ("Astralis", "GamerLegion"), ("9z", "FlyQuest"), ("Monte", "BIG"), ("paiN", "TYLOO"),
]

MARKET_ADVANCE = {
    "Spirit": 0.94, "G2": 0.73, "Legacy": 0.70, "FUT": 0.64,
    "Astralis": 0.57, "GamerLegion": 0.49, "BetBoom": 0.47,
    "B8": 0.45, "9z": 0.42, "Monte": 0.37, "BIG": 0.36,
    "paiN": 0.34, "MIBR": 0.28, "M80": 0.20, "TYLOO": 0.18, "FlyQuest": 0.10,
}

NUM_SIMS = 200000

def get_buchholz(team, records, history):
    return sum(records[opp][0] - records[opp][1] for opp in history[team])

def pair_pool(pool, records, history, initial_seed):
    pool_sorted = sorted(pool, key=lambda t: (-get_buchholz(t, records, history), initial_seed[t]))
    pairs = []
    used = set()
    for i, t1 in enumerate(pool_sorted):
        if t1 in used: continue
        for j in range(len(pool_sorted) - 1, i, -1):
            t2 = pool_sorted[j]
            if t2 in used or t2 in history[t1]: continue
            pairs.append((t1, t2))
            used.add(t1)
            used.add(t2)
            break
    remaining = [t for t in pool_sorted if t not in used]
    for i in range(0, len(remaining) - 1, 2):
        pairs.append((remaining[i], remaining[i+1]))
    return pairs

def main():
    print("Step 5: Running Swiss Monte Carlo Simulation & Optimizer...")
    
    with open("2026_cologne/stage2/04_calibrated_matrix.json", "r") as f:
        data = json.load(f)
    matrix = data["matrix"]
    bo3_delta = data["bo3_delta"]
    initial_seed = {t: i for i, t in enumerate(TEAMS)}

    def get_win_prob(a, b, best_of):
        p = matrix[f"{a}|{b}"]
        if best_of == 3:
            da, db = bo3_delta.get(a, 0), bo3_delta.get(b, 0)
            p_bo3 = p**2 * (3 - 2*p) + da - db
            return max(0.05, min(0.95, p_bo3))
        return p

    def simulate_swiss():
        records = {t: [0, 0] for t in TEAMS}
        history = {t: set() for t in TEAMS}
        advanced, eliminated = [], []

        for t1, t2 in R1_MATCHES:
            winner = t1 if random.random() < get_win_prob(t1, t2, 1) else t2
            loser = t2 if winner == t1 else t1
            records[winner][0] += 1
            records[loser][1] += 1
            history[winner].add(loser)
            history[loser].add(winner)

        for round_num in range(2, 6):
            best_of = 1 if round_num <= 2 else 3
            pools = defaultdict(list)
            for t in TEAMS:
                if t not in advanced and t not in eliminated:
                    w, l = records[t]
                    pools[(w, l)].append(t)

            for (w, l), pool in pools.items():
                if len(pool) < 2: continue
                pairs = pair_pool(pool, records, history, initial_seed)
                for t1, t2 in pairs:
                    winner = t1 if random.random() < get_win_prob(t1, t2, best_of) else t2
                    loser = t2 if winner == t1 else t1
                    records[winner][0] += 1
                    records[loser][1] += 1
                    history[winner].add(loser)
                    history[loser].add(winner)

                    if records[winner][0] == 3: advanced.append(winner)
                    if records[loser][1] == 3: eliminated.append(loser)
        return {t: tuple(records[t]) for t in TEAMS}

    counts_30, counts_312, counts_03, counts_elim = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    all_results = []
    
    print(f"  Simulating {NUM_SIMS:,} times...")
    for _ in range(NUM_SIMS):
        result = simulate_swiss()
        all_results.append(result)
        for t, (w, l) in result.items():
            if w == 3 and l == 0: counts_30[t] += 1
            elif w == 3: counts_312[t] += 1
            elif l == 3 and w == 0: counts_03[t] += 1
            else: counts_elim[t] += 1

    lines = ["=" * 80, "  验证: 模拟 vs 市场 ('Qualify to Stage 3')", "=" * 80]
    lines.append(f"  {'队伍':<14} {'模拟':>7} {'市场':>7} {'差异':>7}")
    lines.append(f"  {'-'*14} {'-'*7} {'-'*7} {'-'*7}")
    
    for t in sorted(TEAMS, key=lambda x: MARKET_ADVANCE[x], reverse=True):
        sim = (counts_30[t] + counts_312[t]) / NUM_SIMS
        mkt = MARKET_ADVANCE[t]
        diff = sim - mkt
        flag = "⚠️" if abs(diff) > 0.08 else ""
        lines.append(f"  {t:<14} {sim:>6.1%} {mkt:>6.1%} {diff:>+6.1%} {flag}")

    sorted_by_30 = sorted(TEAMS, key=lambda t: counts_30[t], reverse=True)
    sorted_by_03 = sorted(TEAMS, key=lambda t: counts_03[t], reverse=True)
    c30 = [t for t in sorted_by_30 if counts_30[t] / NUM_SIMS > 0.05]
    c03 = [t for t in sorted_by_03 if counts_03[t] / NUM_SIMS > 0.05]

    lines.extend(["", "=" * 80, "  暴力搜索最优组合", "=" * 80])
    
    def eval_combo(picks_30, picks_312, picks_03):
        score_dist = defaultdict(int)
        for result in all_results:
            score = 0
            for t in picks_30:
                if result[t] == (3, 0): score += 1
            for t in picks_312:
                w, l = result[t]
                if w == 3 and l > 0: score += 1
            for t in picks_03:
                if result[t] == (0, 3): score += 1
            score_dist[score] += 1
        p5 = sum(v for k, v in score_dist.items() if k >= 5) / NUM_SIMS
        ev = sum(k * v for k, v in score_dist.items()) / NUM_SIMS
        return p5, ev, dict(score_dist)

    best_combos = []
    for p30 in combinations(c30, 2):
        for p03 in combinations(c03, 2):
            if set(p30) & set(p03): continue
            remaining = [t for t in TEAMS if t not in p30 and t not in p03]
            best_312 = sorted(remaining, key=lambda t: counts_312[t], reverse=True)[:6]
            p5, ev, dist = eval_combo(p30, best_312, p03)
            best_combos.append((p5, ev, p30, best_312, p03, dist))
            
    best_combos.sort(key=lambda x: (-x[0], -x[1]))
    
    for i, (p5, ev, p30, p312, p03, _) in enumerate(best_combos[:5]):
        lines.append(f"\n  #{i+1}  P(≥5)={p5:.1%}  期望={ev:.2f}")
        lines.append(f"       3-0:     {', '.join(p30)}")
        lines.append(f"       3-1/3-2: {', '.join(p312)}")
        lines.append(f"       0-3:     {', '.join(p03)}")

    if best_combos:
        _, _, _, _, _, dist = best_combos[0]
        lines.extend(["", "=" * 80, "  最优方案得分分布", "=" * 80])
        for s in range(11):
            pct = dist.get(s, 0) / NUM_SIMS
            bar = "█" * int(pct * 50)
            lines.append(f"    {s:>2}分: {pct:>5.1%} {bar}")

    with open("2026_cologne/stage2/05_simulation_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Done. Saved 05_simulation_results.txt\n")

if __name__ == "__main__":
    main()
