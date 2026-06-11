import json, math
from collections import defaultdict
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEAMS = [
    "Vitality", "Natus Vincere", "Falcons", "The MongolZ", "PARIVISION", "Aurora", "FURIA", "MOUZ",
    "Spirit", "FUT", "G2", "BetBoom", "9z", "Monte", "B8", "Legacy",
]

HALF_LIFE_DAYS = 60.0
K_FACTOR_H2H = 0.12
K_FACTOR_GLOBAL = 0.03
ACTIVE_MAPS = ["Mirage", "Inferno", "Nuke", "Ancient", "Anubis", "Dust2", "Overpass"]

def main():
    print("Step 2: Building H2H Matrix + Map Stats + V-Values...")
    raw_matches_path = os.path.join(BASE_DIR, "01_raw_matches.json")
    rosters_path = os.path.join(BASE_DIR, "01_rosters.json")
    initial_elo_path = os.path.join(BASE_DIR, "01_initial_elo.json")
    
    with open(raw_matches_path, "r") as f:
        matches = json.load(f)
    with open(rosters_path, "r") as f:
        rosters = json.load(f)
    try:
        with open(initial_elo_path, "r") as f:
            initial_elo = json.load(f)
    except:
        initial_elo = {}

    global_elo = defaultdict(lambda: 1000.0)
    for team, elo in initial_elo.items():
        global_elo[team] = elo

    h2h_matrix = {}
    for a in TEAMS:
        for b in TEAMS:
            if a == b:
                h2h_matrix[f"{a}|{b}"] = 0.5
            else:
                elo_a = global_elo[a]
                elo_b = global_elo[b]
                h2h_matrix[f"{a}|{b}"] = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))

    # map_stats[team][map] = {"wins": float, "losses": float, "count": int}
    map_stats = defaultdict(lambda: defaultdict(lambda: {"wins": 0.0, "losses": 0.0, "count": 0}))

    # BP stats
    bp_matches = defaultdict(float)
    bp_stats = defaultdict(lambda: defaultdict(lambda: {"bans": 0.0, "picks": 0.0}))

    v_values = {t: 1.0 for t in TEAMS}
    team_kast_sums = defaultdict(float)
    team_kast_weights = defaultdict(float)

    for m in matches:
        days_ago = m["days_ago"]
        time_decay = 0.5 ** (days_ago / HALF_LIFE_DAYS)
        if days_ago <= 6:
            time_decay *= 1.2

        t1, t2 = m["t1_name"], m["t2_name"]
        t1_score, t2_score = m["t1_score"], m["t2_score"]

        if t1_score == t2_score:
            t1_score = 1 if m["winner"] == t1 else 0
            t2_score = 1 if m["winner"] == t2 else 0

        mov = math.log1p(abs(t1_score - t2_score))
        if mov == 0:
            mov = 1.0

        in_t1 = t1 in TEAMS
        in_t2 = t2 in TEAMS

        # roster overlap via Firepower (Rating)
        player_stats_data = m.get("player_stats", {})
        t1_stats = player_stats_data.get("t1", {})
        t2_stats = player_stats_data.get("t2", {})

        def get_roster_factor(team_name, p_stats):
            current = set(rosters.get(team_name, []))
            if not current or not p_stats:
                return 1.0
            
            total_rating = 0.0
            retained_rating = 0.0
            
            for str_pid, stats in p_stats.items():
                try:
                    pid = int(str_pid)
                except:
                    continue
                
                r = stats.get("rating", 0.0) if isinstance(stats, dict) else 0.0
                if r <= 0.0: r = 1.0 # fallback default rating
                
                total_rating += r
                if pid in current:
                    retained_rating += r
                    
            if total_rating == 0:
                return 1.0
            
            ratio = retained_rating / total_rating
            return ratio ** 2.0

        rf_t1 = get_roster_factor(t1, t1_stats) if in_t1 else 1.0
        rf_t2 = get_roster_factor(t2, t2_stats) if in_t2 else 1.0

        def get_team_kast(team_name, p_stats):
            current = set(rosters.get(team_name, []))
            kast_sum = 0.0
            count = 0
            for str_pid, stats in p_stats.items():
                try: pid = int(str_pid)
                except: continue
                if pid in current:
                    kast = stats.get("kast", 0.0) if isinstance(stats, dict) else 0.0
                    if kast > 0:
                        kast_sum += kast
                        count += 1
            if count > 0:
                return kast_sum / count
            return 0.0
            
        if in_t1:
            k1 = get_team_kast(t1, t1_stats)
            if k1 > 0:
                team_kast_sums[t1] += k1 * time_decay
                team_kast_weights[t1] += time_decay
                
        if in_t2:
            k2 = get_team_kast(t2, t2_stats)
            if k2 > 0:
                team_kast_sums[t2] += k2 * time_decay
                team_kast_weights[t2] += time_decay

        weight_t1 = time_decay * rf_t1
        weight_t2 = time_decay * rf_t2

        # ③ H2H 矩阵更新（仅 Bo3）
        bo = m.get("best_of", 3)
        if bo == 3:
            if in_t1 and in_t2:
                expected = h2h_matrix[f"{t1}|{t2}"]
                actual = 1.0 if t1_score > t2_score else 0.0
                w = min(weight_t1, weight_t2)
                shift = K_FACTOR_H2H * w * mov * (actual - expected)
                h2h_matrix[f"{t1}|{t2}"] = max(0.01, min(0.99, h2h_matrix[f"{t1}|{t2}"] + shift))
                h2h_matrix[f"{t2}|{t1}"] = 1.0 - h2h_matrix[f"{t1}|{t2}"]
            elif in_t1 and not in_t2:
                actual = 1.0 if t1_score > t2_score else 0.0
                for other in TEAMS:
                    if other != t1:
                        relevance = min(1.0, global_elo[t2] / max(global_elo[other], 1.0))
                        current = h2h_matrix[f"{t1}|{other}"]
                        shift = K_FACTOR_GLOBAL * weight_t1 * mov * relevance * (actual - current)
                        h2h_matrix[f"{t1}|{other}"] = max(0.01, min(0.99, current + shift))
                        h2h_matrix[f"{other}|{t1}"] = 1.0 - h2h_matrix[f"{t1}|{other}"]
            elif in_t2 and not in_t1:
                actual = 1.0 if t2_score > t1_score else 0.0
                for other in TEAMS:
                    if other != t2:
                        relevance = min(1.0, global_elo[t1] / max(global_elo[other], 1.0))
                        current = h2h_matrix[f"{t2}|{other}"]
                        shift = K_FACTOR_GLOBAL * weight_t2 * mov * relevance * (actual - current)
                        h2h_matrix[f"{t2}|{other}"] = max(0.01, min(0.99, current + shift))
                        h2h_matrix[f"{other}|{t2}"] = 1.0 - h2h_matrix[f"{t2}|{other}"]

        # ④ 地图加权胜率表（Bo1 和 Bo3 均纳入）
        maps_in_match = m.get("maps", [])
        for mp in maps_in_match:
            map_name = mp["name"]
            if map_name == "unknown":
                continue
            mt1 = mp["t1_score"]
            mt2 = mp["t2_score"]
            if mt1 == mt2:
                continue
            map_winner_is_t1 = mt1 > mt2

            if in_t1:
                if map_winner_is_t1:
                    map_stats[t1][map_name]["wins"] += weight_t1
                else:
                    map_stats[t1][map_name]["losses"] += weight_t1
                map_stats[t1][map_name]["count"] += 1
            if in_t2:
                if not map_winner_is_t1:
                    map_stats[t2][map_name]["wins"] += weight_t2
                else:
                    map_stats[t2][map_name]["losses"] += weight_t2
                map_stats[t2][map_name]["count"] += 1

        # ⑤ BP 习惯统计
        vetoes = m.get("vetoes", [])
        if vetoes:
            if in_t1: bp_matches[t1] += weight_t1
            if in_t2: bp_matches[t2] += weight_t2
            
            for v in vetoes:
                v_team = v.get("team")
                action = v.get("action")
                v_map = v.get("map")
                
                if v_team == t1 and in_t1:
                    if action == "removed": bp_stats[t1][v_map]["bans"] += weight_t1
                    elif action == "picked": bp_stats[t1][v_map]["picks"] += weight_t1
                elif v_team == t2 and in_t2:
                    if action == "removed": bp_stats[t2][v_map]["bans"] += weight_t2
                    elif action == "picked": bp_stats[t2][v_map]["picks"] += weight_t2

        # ⑥ V 值更新
        for team, is_in in [(t1, in_t1), (t2, in_t2)]:
            if not is_in:
                continue
            my_elo = global_elo[team]
            opp_elo = global_elo[t2 if team == t1 else t1]
            expected_p = 1.0 / (1.0 + 10 ** ((opp_elo - my_elo) / 400.0))
            result = 1.0 if m["winner"] == team else 0.0
            denom = expected_p * (1.0 - expected_p)
            if denom < 0.01:
                denom = 0.01
            shock = ((result - expected_p) ** 2) / denom
            v_values[team] = 0.9 * v_values[team] + 0.1 * shock

    with open(os.path.join(BASE_DIR, "02_h2h_matrix.json"), "w") as f:
        json.dump(h2h_matrix, f, indent=2)
    print(f"Done. Saved 02_h2h_matrix.json")

    map_stats_out = {}
    for team in TEAMS:
        for map_name, stats in map_stats[team].items():
            map_stats_out[f"{team}|{map_name}"] = stats
    with open(os.path.join(BASE_DIR, "02_map_stats.json"), "w") as f:
        json.dump(map_stats_out, f, indent=2)
    print(f"Done. Saved 02_map_stats.json")

    # 先计算 KAST
    final_kast = {}
    for team in TEAMS:
        if team_kast_weights[team] > 0:
            final_kast[team] = team_kast_sums[team] / team_kast_weights[team]
        else:
            final_kast[team] = 70.0

    # KAST 修正 V 值归一化
    KAST_ALPHA = 2.0
    v_raw_vals = [v_values[t] for t in TEAMS]
    kast_vals = [final_kast[t] for t in TEAMS]
    v_median = sorted(v_raw_vals)[len(v_raw_vals) // 2]
    kast_median = sorted(kast_vals)[len(kast_vals) // 2]

    v_adjusted = {}
    print("\n  [KAST-adjusted V-value]")
    for t in TEAMS:
        v_norm = v_values[t] / v_median
        kast_factor = (kast_median / final_kast[t]) ** KAST_ALPHA
        v_adjusted[t] = v_norm * kast_factor
        print(f"    {t:<18} V_raw={v_values[t]:.2f}  KAST={final_kast[t]:.1f}%  V_adj={v_adjusted[t]:.3f}")

    with open(os.path.join(BASE_DIR, "02_v_values.json"), "w") as f:
        json.dump(v_adjusted, f, indent=2)
    print(f"Done. Saved 02_v_values.json (KAST-adjusted)")

    # 计算 BP Profiles
    bp_profiles = defaultdict(dict)
    for team in TEAMS:
        total = bp_matches[team]
        if total < 0.01: total = 0.01
        for map_name in ACTIVE_MAPS:
            bans = bp_stats[team][map_name]["bans"]
            picks = bp_stats[team][map_name]["picks"]
            ban_rate = min(1.0, bans / total)
            pick_rate = min(1.0, picks / total)
            pref = pick_rate - ban_rate
            bp_profiles[team][map_name] = {
                "pref": pref,
                "ban_rate": ban_rate,
                "pick_rate": pick_rate
            }
            
    with open(os.path.join(BASE_DIR, "02_bp_profiles.json"), "w") as f:
        json.dump(bp_profiles, f, indent=2)
    print(f"Done. Saved 02_bp_profiles.json")


    
    with open(os.path.join(BASE_DIR, "02_team_kast.json"), "w") as f:
        json.dump(final_kast, f, indent=2)
    print("Done. Saved 02_team_kast.json")
    

    print()

if __name__ == "__main__":
    main()
