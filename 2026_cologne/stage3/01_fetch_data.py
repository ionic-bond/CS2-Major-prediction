import os, json, csv
from datetime import datetime
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "data", "match_details_lite.json")
PLAYER_STATS_PATH = os.path.join(BASE_DIR, "data", "player_stats.csv")

TEAMS = [
    "Vitality", "Natus Vincere", "Falcons", "The MongolZ", "PARIVISION", "Aurora", "FURIA", "MOUZ",
    "Spirit", "FUT", "G2", "BetBoom", "9z", "Monte", "B8", "Legacy",
]

TODAY = datetime(2026, 6, 11)
MAX_DAYS_AGO = 365

def main():
    print("Step 1 (Offline Mode): Parsing match history + rosters + map stats from local DB...")
    
    if not os.path.exists(LOCAL_DB_PATH):
        print(f"Error: {LOCAL_DB_PATH} not found!")
        return
        
    with open(LOCAL_DB_PATH, "r", encoding="utf-8") as f:
        local_db = json.load(f)
    print(f"  => Loaded {len(local_db)} offline matches!")

    print("  => Loading player stats from CSV...")
    stats_by_url = defaultdict(lambda: defaultdict(dict))
    if os.path.exists(PLAYER_STATS_PATH):
        with open(PLAYER_STATS_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("match_url", "")
                nick = row.get("player_id", "") # csv header says player_id but it's the nick
                m_name = row.get("map_name", "All maps")
                if not url or not nick: continue
                
                try:
                    stats_by_url[url][nick.lower()][m_name] = {
                        "rating": float(row["rating"]) if row["rating"] else 0.0,
                        "adr": float(row["adr"]) if row["adr"] else 0.0,
                        "kast": float(row["kast"]) if row["kast"] else 0.0
                    }
                except:
                    pass

    all_matches = []
    
    for url, md in local_db.items():
        try:
            m_date = datetime.strptime(md["date"], "%Y-%m-%d")
        except:
            continue
        
        days_ago = (TODAY - m_date).days
        if days_ago < 0 or days_ago > MAX_DAYS_AGO:
            continue
            
        try:
            mid = int(url.split("/")[4])
        except:
            mid = md.get("index", hash(url))
            
        t1_name = md.get("team1", "Unknown")
        t2_name = md.get("team2", "Unknown")
        
        try:
            t1_score = int(md.get("team1_score", 0))
            t2_score = int(md.get("team2_score", 0))
        except:
            continue
            
        if t1_score > t2_score:
            winner = t1_name
        elif t2_score > t1_score:
            winner = t2_name
        else:
            winner = "draw"
            
        b_type = md.get("type", "BO3")
        if b_type == "BO1": best_of = 1
        elif b_type == "BO3": best_of = 3
        elif b_type == "BO5": best_of = 5
        else: best_of = 1 # fallback
        
        maps_out = []
        p_t1 = []
        p_t2 = []
        
        if "details" in md:
            for m in md["details"].get("maps", []):
                s = m.get("score", "")
                if s == "- - -" or s == "unknown":
                    continue
                try:
                    s1, s2 = s.split(" - ")
                    maps_out.append({
                        "name": m.get("map_name", "unknown"),
                        "t1_score": int(s1.strip()),
                        "t2_score": int(s2.strip())
                    })
                except:
                    pass
                    
            p_t1 = [int(p["id"]) for p in md["details"].get("team1_lineup", []) if isinstance(p, dict) and p.get("id")]
            p_t2 = [int(p["id"]) for p in md["details"].get("team2_lineup", []) if isinstance(p, dict) and p.get("id")]
            
        vetoes = md.get("details", {}).get("veto_steps", [])
        vrs_data = md.get("details", {}).get("vrs_data", {})
        
        match_obj = {
            "id": mid,
            "date": md["date"],
            "days_ago": days_ago,
            "best_of": best_of,
            "t1_name": t1_name,
            "t2_name": t2_name,
            "t1_score": t1_score,
            "t2_score": t2_score,
            "winner": winner,
            "maps": maps_out,
            "vetoes": vetoes,
            "vrs_data": vrs_data
        }
        
        if p_t1 and p_t2:
            match_obj["player_ids"] = {
                "t1": p_t1,
                "t2": p_t2
            }
            
            # Populate detailed stats if available
            p_stats = {"t1": {}, "t2": {}}
            for p in md["details"].get("team1_lineup", []):
                if not isinstance(p, dict) or not p.get("id"): continue
                nick = p.get("nick", "").lower()
                pid = int(p["id"])
                p_stats["t1"][pid] = stats_by_url.get(url, {}).get(nick, {}).get("All maps", {})
                
            for p in md["details"].get("team2_lineup", []):
                if not isinstance(p, dict) or not p.get("id"): continue
                nick = p.get("nick", "").lower()
                pid = int(p["id"])
                p_stats["t2"][pid] = stats_by_url.get(url, {}).get(nick, {}).get("All maps", {})
                
            match_obj["player_stats"] = p_stats
            
        all_matches.append(match_obj)
        
    # Sort matches chronologically (oldest first)
    sorted_matches = sorted(all_matches, key=lambda x: -x["days_ago"])
    
    # Extract latest rosters for TEAMS
    rosters = {}
    for team in TEAMS:
        # Find the most recent match for this team
        latest_roster = []
        for m in reversed(sorted_matches):
            if "player_ids" not in m: continue
            if m["t1_name"].lower() == team.lower():
                latest_roster = m["player_ids"]["t1"]
                break
            elif m["t2_name"].lower() == team.lower():
                latest_roster = m["player_ids"]["t2"]
                break
                
        if latest_roster:
            rosters[team] = latest_roster
        else:
            rosters[team] = []
            print(f"    ⚠️ Could not find recent match for {team}.")
            
    with open(os.path.join(BASE_DIR, "01_raw_matches.json"), "w") as f:
        json.dump(sorted_matches, f, indent=2)
    print(f"Done. Saved {len(sorted_matches)} valid matches to 01_raw_matches.json")
    
    with open(os.path.join(BASE_DIR, "01_rosters.json"), "w") as f:
        json.dump(rosters, f, indent=2)
    print("Done. Saved latest rosters to 01_rosters.json")

    # Extract initial VRS points as Baseline Elo from official valve rankings
    initial_elo = {}
    try:
        with open(os.path.join(BASE_DIR, "data", "valve_rankings.csv"), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["region"] == "global":
                    team = row["team_name"]
                    # 放弃一年前的种子，改回使用最新的 V社积分作为静态基准
                    raw_vrs = float(row["points"])
                    # 我们让老数据覆盖，最终得到的是 2026 科隆最近一期的官方积分！
                    initial_elo[team] = 1000.0 + (raw_vrs - 800.0) / 1.5
    except Exception as e:
        print(f"Could not load initial elo from valve_rankings.csv: {e}")

    # Fallback to match vrs_data if any team is missing
    for m in sorted_matches:
        vrs = m.get("vrs_data", {})
        t1, t2 = m["t1_name"], m["t2_name"]
        if t1 not in initial_elo and vrs.get("team1_vrs_points"):
            initial_elo[t1] = float(vrs["team1_vrs_points"])
        if t2 not in initial_elo and vrs.get("team2_vrs_points"):
            initial_elo[t2] = float(vrs["team2_vrs_points"])
            
    with open(os.path.join(BASE_DIR, "01_initial_elo.json"), "w") as f:
        json.dump(initial_elo, f, indent=2)
    print(f"Done. Saved {len(initial_elo)} teams' baseline VRS points to 01_initial_elo.json\n")

if __name__ == "__main__":
    main()
