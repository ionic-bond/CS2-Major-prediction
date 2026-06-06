import urllib.request, json, time, ssl
from datetime import datetime

TEAMS = [
    "Spirit", "G2", "Legacy", "FUT", "Astralis", "9z", "Monte", "paiN",
    "GamerLegion", "BetBoom", "B8", "TYLOO", "BIG", "MIBR", "M80", "FlyQuest"
]

CSAPI_IDS = {
    "Spirit": 7020, "G2": 5995, "Legacy": 12468, "FUT": 13286,
    "Astralis": 6665, "9z": 9996, "Monte": 11811, "paiN": 4773,
    "GamerLegion": 9928, "BetBoom": 12394, "B8": 11241, "TYLOO": 4863,
    "BIG": 7532, "MIBR": 9215, "M80": 12376, "FlyQuest": 12774,
}

TEAM_NAME_MAP = {"Liquid": "Team Liquid", "HEROIC": "Heroic"}
TODAY = datetime(2026, 6, 6)
MAX_DAYS_AGO = 180

ctx = ssl._create_unverified_context()

def fetch(url):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return json.loads(urllib.request.urlopen(req, timeout=20, context=ctx).read().decode('utf-8'))
        except:
            time.sleep(2)
    return None

def main():
    print("Step 2: Fetching Raw CS API Data...")
    all_matches = {}
    
    for name in TEAMS:
        print(f"  Fetching {name}...")
        data = fetch(f"https://api.csapi.de/teams/{CSAPI_IDS[name]}/matchhistory?limit=100")
        time.sleep(0.5)
        if not data: continue

        for m in data:
            try: m_date = datetime.strptime(m["date"], "%Y-%m-%d")
            except: continue
            
            days_ago = max(0, (TODAY - m_date).days)
            if days_ago > MAX_DAYS_AGO: continue

            mid = m["id"]
            if mid not in all_matches:
                t1_name = TEAM_NAME_MAP.get(m["team1"]["name"], m["team1"]["name"])
                t2_name = TEAM_NAME_MAP.get(m["team2"]["name"], m["team2"]["name"])
                
                # Reverse lookup if the name differs but ID matches our known ID
                for known_name, known_id in CSAPI_IDS.items():
                    if m["team1"]["id"] == known_id: t1_name = known_name
                    if m["team2"]["id"] == known_id: t2_name = known_name

                # Extract score from maps
                t1_score = 0
                t2_score = 0
                if "maps" in m:
                    for mp in m["maps"]:
                        t1_score += mp.get("team1_score", 0)
                        t2_score += mp.get("team2_score", 0)
                else:
                    t1_score = m["team1"].get("score", 0)
                    t2_score = m["team2"].get("score", 0)

                all_matches[mid] = {
                    "id": mid,
                    "date": m["date"],
                    "days_ago": days_ago,
                    "best_of": m["best_of"],
                    "t1_name": t1_name,
                    "t2_name": t2_name,
                    "t1_score": t1_score,
                    "t2_score": t2_score,
                    "winner": TEAM_NAME_MAP.get(m["winner"]["name"], m["winner"]["name"])
                }
                
                for known_name, known_id in CSAPI_IDS.items():
                    if m["winner"]["id"] == known_id:
                        all_matches[mid]["winner"] = known_name

    # Sort matches chronologically (oldest first)
    sorted_matches = sorted(list(all_matches.values()), key=lambda x: -x["days_ago"])
    
    with open("2026_cologne/stage2/02_raw_matches.json", "w") as f:
        json.dump(sorted_matches, f, indent=2)
    print(f"Done. Saved {len(sorted_matches)} valid matches to 02_raw_matches.json\n")

if __name__ == "__main__":
    main()
