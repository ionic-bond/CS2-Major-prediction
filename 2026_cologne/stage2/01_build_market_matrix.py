import json

TEAMS = [
    "Spirit", "G2", "Legacy", "FUT", "Astralis", "9z", "Monte", "paiN",
    "GamerLegion", "BetBoom", "B8", "TYLOO", "BIG", "MIBR", "M80", "FlyQuest"
]

MARKET_ADVANCE = {
    "Spirit": 0.94, "G2": 0.73, "Legacy": 0.70, "FUT": 0.64,
    "Astralis": 0.57, "GamerLegion": 0.49, "BetBoom": 0.47,
    "B8": 0.45, "9z": 0.42, "Monte": 0.37, "BIG": 0.36,
    "paiN": 0.34, "MIBR": 0.28, "M80": 0.20, "TYLOO": 0.18, "FlyQuest": 0.10,
}

def main():
    print("Step 1: Building Market Matrix from Polymarket Qualify Odds...")
    matrix = {}
    for a in TEAMS:
        for b in TEAMS:
            if a == b:
                matrix[f"{a}|{b}"] = 0.5
            else:
                sa = MARKET_ADVANCE[a]
                sb = MARKET_ADVANCE[b]
                matrix[f"{a}|{b}"] = sa / (sa + sb)

    with open("2026_cologne/stage2/01_market_matrix.json", "w") as f:
        json.dump(matrix, f, indent=2)
    print("Done. Saved 01_market_matrix.json\n")

if __name__ == "__main__":
    main()
