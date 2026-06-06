import json, math
from collections import defaultdict

TEAMS = [
    "Spirit", "G2", "Legacy", "FUT", "Astralis", "9z", "Monte", "paiN",
    "GamerLegion", "BetBoom", "B8", "TYLOO", "BIG", "MIBR", "M80", "FlyQuest"
]

HALF_LIFE_DAYS = 60.0
K_FACTOR_H2H = 0.04
K_FACTOR_GLOBAL = 0.01

def main():
    print("Step 3: Building Pure Data Matrix with Match-by-Match Elo...")
    with open("2026_cologne/stage2/02_raw_matches.json", "r") as f:
        matches = json.load(f)

    # Initialize data matrix at 0.5
    data_matrix = {}
    for a in TEAMS:
        for b in TEAMS:
            data_matrix[f"{a}|{b}"] = 0.5

    team_bo1 = defaultdict(lambda: [0.0, 0.0])
    team_bo3 = defaultdict(lambda: [0.0, 0.0])
    
    # 动态跟踪所有出现过的队伍的相对战力（基准为 1000）
    global_elo = defaultdict(lambda: 1000.0)

    for m in matches:
        days_ago = m["days_ago"]
        weight = 0.5 ** (days_ago / HALF_LIFE_DAYS)
        if days_ago <= 6: weight *= 1.2
        
        t1, t2 = m["t1_name"], m["t2_name"]
        t1_score, t2_score = m["t1_score"], m["t2_score"]
        
        if t1_score == t2_score:
            t1_score = 1 if m["winner"] == t1 else 0
            t2_score = 1 if m["winner"] == t2 else 0

        mov = math.log1p(abs(t1_score - t2_score))
        if mov == 0: mov = 1.0  # fallback

        in_t1 = t1 in TEAMS
        in_t2 = t2 in TEAMS
        
        # Bo1 / Bo3 records for delta calculation
        bo = m["best_of"]
        for t, is_in, is_win in [(t1, in_t1, t1_score > t2_score), (t2, in_t2, t2_score > t1_score)]:
            if is_in:
                if bo == 1:
                    if is_win: team_bo1[t][0] += weight
                    else: team_bo1[t][1] += weight
                elif bo >= 3:
                    if is_win: team_bo3[t][0] += weight
                    else: team_bo3[t][1] += weight
                    
        # 更新动态底层 Elo，用于评估任意队伍（特别是外部队伍）的实时战力
        elo1, elo2 = global_elo[t1], global_elo[t2]
        expected_t1 = 1 / (1 + 10 ** ((elo2 - elo1) / 400.0))
        actual_t1 = 1.0 if t1_score > t2_score else 0.0
        global_elo[t1] += 32 * weight * mov * (actual_t1 - expected_t1)
        global_elo[t2] += 32 * weight * mov * ((1 - actual_t1) - (1 - expected_t1))

        # Matrix updates
        if in_t1 and in_t2:
            # H2H Update
            expected = data_matrix[f"{t1}|{t2}"]
            actual = 1.0 if t1_score > t2_score else 0.0
            shift = K_FACTOR_H2H * weight * mov * (actual - expected)
            
            data_matrix[f"{t1}|{t2}"] = max(0.01, min(0.99, data_matrix[f"{t1}|{t2}"] + shift))
            data_matrix[f"{t2}|{t1}"] = 1.0 - data_matrix[f"{t1}|{t2}"]
            
        elif in_t1 and not in_t2:
            # Global form boost for t1
            actual = 1.0 if t1_score > t2_score else 0.0
            # 使用外部队伍 t2 的实时动态战力来放大/缩小权重
            opponent_strength = max(0.5, min(2.0, global_elo[t2] / 1000.0))
            shift = K_FACTOR_GLOBAL * opponent_strength * weight * mov * (actual - 0.5)
            for other in TEAMS:
                if other != t1:
                    data_matrix[f"{t1}|{other}"] = max(0.01, min(0.99, data_matrix[f"{t1}|{other}"] + shift))
                    data_matrix[f"{other}|{t1}"] = 1.0 - data_matrix[f"{t1}|{other}"]
                    
        elif in_t2 and not in_t1:
            # Global form boost for t2
            actual = 1.0 if t2_score > t1_score else 0.0
            # 使用外部队伍 t1 的实时动态战力来放大/缩小权重
            opponent_strength = max(0.5, min(2.0, global_elo[t1] / 1000.0))
            shift = K_FACTOR_GLOBAL * opponent_strength * weight * mov * (actual - 0.5)
            for other in TEAMS:
                if other != t2:
                    data_matrix[f"{t2}|{other}"] = max(0.01, min(0.99, data_matrix[f"{t2}|{other}"] + shift))
                    data_matrix[f"{other}|{t2}"] = 1.0 - data_matrix[f"{t2}|{other}"]

    bo3_delta = {}
    for name in TEAMS:
        w1, l1 = team_bo1[name]
        w3, l3 = team_bo3[name]
        t1, t3 = w1 + l1, w3 + l3
        if t1 >= 2.0 and t3 >= 2.0:
            p1 = w1 / t1
            p3 = w3 / t3
            delta = p3 - (p1**2 * (3 - 2*p1))
            bo3_delta[name] = max(-0.15, min(0.15, delta))
        else:
            bo3_delta[name] = 0.0

    out = {
        "matrix": data_matrix,
        "bo3_delta": bo3_delta
    }
    with open("2026_cologne/stage2/03_data_matrix.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Done. Saved 03_data_matrix.json\n")

if __name__ == "__main__":
    main()
