import json, math
from collections import defaultdict
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEAMS = [
    "Vitality", "Natus Vincere", "Falcons", "The MongolZ", "PARIVISION", "Aurora", "FURIA", "MOUZ",
    "Spirit", "FUT", "G2", "BetBoom", "9z", "Monte", "B8", "Legacy",
]

ACTIVE_MAPS = ["Mirage", "Inferno", "Nuke", "Ancient", "Anubis", "Dust2", "Overpass"]

MARKET_WEIGHT = 0.5
DATA_WEIGHT = 0.5
H2H_WEIGHT = 0.7
MAP_WEIGHT = 0.3
LAPLACE_K = 5
RELIABILITY_C = 10
LAMBDA_PENALTY = 3.0

def load_data():
    with open(os.path.join(BASE_DIR, "02_h2h_matrix.json"), "r") as f:
        h2h_matrix = json.load(f)
    with open(os.path.join(BASE_DIR, "02_map_stats.json"), "r") as f:
        raw_map_stats = json.load(f)
    with open(os.path.join(BASE_DIR, "02_v_values.json"), "r") as f:
        v_values = json.load(f)
    with open(os.path.join(BASE_DIR, "03_market_matrix.json"), "r") as f:
        market_matrix = json.load(f)
    try:
        with open(os.path.join(BASE_DIR, "02_bp_profiles.json"), "r") as f:
            bp_profiles = json.load(f)
    except FileNotFoundError:
        bp_profiles = {}

    map_stats = defaultdict(lambda: defaultdict(lambda: {"wins": 0.0, "losses": 0.0, "count": 0}))
    for key, val in raw_map_stats.items():
        team, map_name = key.split("|", 1)
        map_stats[team][map_name] = val

    return h2h_matrix, map_stats, v_values, market_matrix, bp_profiles

def get_team_global_wr(map_stats, team):
    total_w = sum(s["wins"] for s in map_stats[team].values())
    total_all = total_w + sum(s["losses"] for s in map_stats[team].values())
    if total_all < 0.01:
        return 0.5
    return total_w / total_all

def compute_map_pa(map_stats, h2h_matrix, team_a, team_b, map_name):
    """单图加权胜率合成：Laplace → Odds-Ratio → Reliability → Perma-ban Penalty"""
    sa = map_stats[team_a].get(map_name, {"wins": 0.0, "losses": 0.0, "count": 0})
    sb = map_stats[team_b].get(map_name, {"wins": 0.0, "losses": 0.0, "count": 0})

    prior_a = get_team_global_wr(map_stats, team_a)
    prior_b = get_team_global_wr(map_stats, team_b)
    wr_a = (sa["wins"] + prior_a * LAPLACE_K) / (sa["wins"] + sa["losses"] + LAPLACE_K)
    wr_b = (sb["wins"] + prior_b * LAPLACE_K) / (sb["wins"] + sb["losses"] + LAPLACE_K)

    wr_a = max(0.01, min(0.99, wr_a))
    wr_b = max(0.01, min(0.99, wr_b))

    numerator = wr_a * (1 - wr_b)
    denominator = numerator + wr_b * (1 - wr_a)
    raw_pa = numerator / denominator

    n_a = sa["count"]
    n_b = sb["count"]
    n_total = n_a + n_b
    w = n_total / (n_total + RELIABILITY_C)

    p_h2h = h2h_matrix.get(f"{team_a}|{team_b}", 0.5)
    p_blend = w * raw_pa + (1 - w) * p_h2h

    p_blend = max(0.001, min(0.999, p_blend))
    logit = math.log(p_blend / (1 - p_blend))
    logit += LAMBDA_PENALTY * (2 ** (-n_b) - 2 ** (-n_a))
    pa = 1.0 / (1.0 + math.exp(-logit))

    return pa

def simulate_ban_pick(map_stats, h2h_matrix, team_a, team_b, bp_profiles):
    """Minimax BP 模拟 → 输出 Bo3 胜率"""
    map_pa = {}
    for m in ACTIVE_MAPS:
        map_pa[m] = compute_map_pa(map_stats, h2h_matrix, team_a, team_b, m)

    pool = list(ACTIVE_MAPS)
    
    delta = {}
    for m in ACTIVE_MAPS:
        pref_a = bp_profiles.get(team_a, {}).get(m, {}).get("pref", 0.0)
        pref_b = bp_profiles.get(team_b, {}).get(m, {}).get("pref", 0.0)
        delta[m] = pref_a - pref_b

    a_ban = min(pool, key=lambda m: delta[m])
    pool.remove(a_ban)
    b_ban = max(pool, key=lambda m: delta[m])
    pool.remove(b_ban)

    a_pick = max(pool, key=lambda m: delta[m])
    pool.remove(a_pick)
    p_map1 = map_pa[a_pick]

    b_pick = min(pool, key=lambda m: delta[m])
    pool.remove(b_pick)
    p_map2 = map_pa[b_pick]

    a_ban2 = min(pool, key=lambda m: delta[m])
    pool.remove(a_ban2)
    b_ban2 = max(pool, key=lambda m: delta[m])
    pool.remove(b_ban2)

    p_map3 = map_pa[pool[0]]

    p_bo3 = (
        p_map1 * p_map2 * p_map3
        + p_map1 * p_map2 * (1 - p_map3)
        + p_map1 * (1 - p_map2) * p_map3
        + (1 - p_map1) * p_map2 * p_map3
    )
    return p_bo3

def get_win_prob(h2h_matrix, map_stats, v_adjusted, market_matrix, bp_profiles, team_a, team_b):
    """完整融合：H2H + 地图 BP → KAST修正V值缩放 → 市场融合"""
    p_h2h = h2h_matrix.get(f"{team_a}|{team_b}", 0.5)
    p_h2h_bo3 = p_h2h ** 2 * (3 - 2 * p_h2h)
    p_map_bo3 = simulate_ban_pick(map_stats, h2h_matrix, team_a, team_b, bp_profiles)
    p_data_base = H2H_WEIGHT * p_h2h_bo3 + MAP_WEIGHT * p_map_bo3

    va = v_adjusted.get(team_a, 1.0)
    vb = v_adjusted.get(team_b, 1.0)
    v_joint = math.sqrt(va * vb)
    p_data_base = max(0.001, min(0.999, p_data_base))
    logit_base = math.log(p_data_base / (1 - p_data_base))
    if v_joint < 0.01:
        v_joint = 0.01
    p_data = 1.0 / (1.0 + math.exp(-(logit_base / v_joint)))

    p_market = market_matrix.get(f"{team_a}|{team_b}", 0.5)
    p_final = MARKET_WEIGHT * p_market + DATA_WEIGHT * p_data

    return max(0.01, min(0.99, p_final))

def main():
    print("Step 4: Pre-calculating 16x16 Final Probabilities...")
    h2h_matrix, map_stats, v_values, market_matrix, bp_profiles = load_data()
    
    final_matrix = {}
    for a in TEAMS:
        for b in TEAMS:
            if a == b:
                final_matrix[f"{a}|{b}"] = 0.5
            else:
                final_matrix[f"{a}|{b}"] = get_win_prob(h2h_matrix, map_stats, v_values, market_matrix, bp_profiles, a, b)

    with open(os.path.join(BASE_DIR, "04_final_matrix.json"), "w") as f:
        json.dump(final_matrix, f, indent=2)
    print("Done. Saved 04_final_matrix.json\n")

if __name__ == "__main__":
    main()
