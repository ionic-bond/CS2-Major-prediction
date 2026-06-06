import json

TEAMS = [
    "Spirit", "G2", "Legacy", "FUT", "Astralis", "9z", "Monte", "paiN",
    "GamerLegion", "BetBoom", "B8", "TYLOO", "BIG", "MIBR", "M80", "FlyQuest"
]

POLYMARKET_R1 = {
    ("Spirit", "BetBoom"): 0.73, ("G2", "M80"): 0.68,
    ("Legacy", "MIBR"): 0.64, ("FUT", "B8"): 0.61,
    ("Astralis", "GamerLegion"): 0.54, ("9z", "FlyQuest"): 0.55,
    ("Monte", "BIG"): 0.45, ("paiN", "TYLOO"): 0.53,
}

MARKET_WEIGHT = 0.70
DATA_WEIGHT = 0.30

def main():
    print("Step 4: Blending Market and Data Matrices...")
    
    with open("2026_cologne/stage2/01_market_matrix.json", "r") as f:
        mkt_matrix = json.load(f)
        
    with open("2026_cologne/stage2/03_data_matrix.json", "r") as f:
        data_json = json.load(f)
        data_matrix = data_json["matrix"]
        bo3_delta = data_json["bo3_delta"]

    final_matrix = {}
    
    # 1. Blend
    for a in TEAMS:
        for b in TEAMS:
            if a == b:
                final_matrix[f"{a}|{b}"] = 0.5
            else:
                p_mkt = mkt_matrix[f"{a}|{b}"]
                p_data = data_matrix[f"{a}|{b}"]
                final_matrix[f"{a}|{b}"] = p_mkt * MARKET_WEIGHT + p_data * DATA_WEIGHT

    # 2. Overwrite with Polymarket R1 Odds (50% confidence for current match form)
    for (a, b), p_a in POLYMARKET_R1.items():
        base_p = final_matrix[f"{a}|{b}"]
        if abs(base_p - p_a) > 0.10:
            print(f"  ⚠️ ALERT: {a} vs {b} - 基础矩阵概率为 {base_p:.1%}，但首轮盘口开出了 {p_a:.1%}，偏差达 {abs(base_p - p_a):.1%}！")
            
        w_r1 = 0.5
        final_matrix[f"{a}|{b}"] = (1 - w_r1) * final_matrix[f"{a}|{b}"] + w_r1 * p_a
        final_matrix[f"{b}|{a}"] = 1.0 - final_matrix[f"{a}|{b}"]

    out = {
        "matrix": final_matrix,
        "bo3_delta": bo3_delta
    }
    with open("2026_cologne/stage2/04_calibrated_matrix.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Done. Saved 04_calibrated_matrix.json\n")

if __name__ == "__main__":
    main()
