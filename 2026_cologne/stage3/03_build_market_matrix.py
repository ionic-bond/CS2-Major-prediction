import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEAMS = [
    "Vitality", "Natus Vincere", "Falcons", "The MongolZ", "PARIVISION", "Aurora", "FURIA", "MOUZ",
    "Spirit", "FUT", "G2", "BetBoom", "9z", "Monte", "B8", "Legacy",
]

MARKET_ADVANCE = {
    "Vitality": 0.96,
    "Spirit": 0.92,
    "Natus Vincere": 0.80,
    "Falcons": 0.75,
    "FURIA": 0.69,
    "Aurora": 0.58,
    "G2": 0.47,
    "MOUZ": 0.45,
    "The MongolZ": 0.44,
    "FUT": 0.43,
    "BetBoom": 0.38,
    "Legacy": 0.38,
    "PARIVISION": 0.34,
    "9z": 0.24,
    "B8": 0.18,
    "Monte": 0.17
}

POLYMARKET_R1 = {
    ("The MongolZ", "BetBoom"): 0.52,
    ("PARIVISION", "9z"): 0.56,
    ("MOUZ", "Legacy"): 0.56,
    ("Spirit", "Natus Vincere"): 0.65,
    ("Falcons", "G2"): 0.63,
    ("Vitality", "FUT"): 0.83,
    ("Aurora", "Monte"): 0.65,
    ("FURIA", "B8"): 0.74,
}

def prob_advance(p):
    return (p**3) + 3*(p**3)*(1-p) + 6*(p**3)*((1-p)**2)

def find_p_win(target_adv):
    if target_adv >= 0.99: return 0.95
    if target_adv <= 0.01: return 0.05
    low, high = 0.01, 0.99
    for _ in range(20):
        mid = (low + high) / 2
        if prob_advance(mid) > target_adv:
            high = mid
        else:
            low = mid
    return (low + high) / 2

def main():
    print("Step 3: Building Market Matrix from Polymarket Odds...")

    S_values = {}
    for team, adv in MARKET_ADVANCE.items():
        p_win = find_p_win(adv)
        S_values[team] = p_win / (1 - p_win)

    matrix = {}
    for a in TEAMS:
        for b in TEAMS:
            if a == b:
                matrix[f"{a}|{b}"] = 0.5
            else:
                sa = S_values[a]
                sb = S_values[b]
                matrix[f"{a}|{b}"] = sa / (sa + sb)

    for (a, b), p_a in POLYMARKET_R1.items():
        base_p = matrix[f"{a}|{b}"]
        print(f"  [Override] {a} vs {b}: BT Inferred={base_p:.1%}, Polymarket={p_a:.1%}")
        matrix[f"{a}|{b}"] = p_a
        matrix[f"{b}|{a}"] = 1.0 - p_a

    with open(os.path.join(BASE_DIR, "03_market_matrix.json"), "w") as f:
        json.dump(matrix, f, indent=2)
    print(f"\nDone. Saved 03_market_matrix.json\n")

if __name__ == "__main__":
    main()
