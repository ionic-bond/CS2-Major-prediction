"""BO3 public API adapter. Provider identities and ratings stay distinct from HLTV."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from .core import FetchError, SCHEMA_VERSION, identity, in_window, match_outcome, number, stats_key, utc_instant, utc_now


BASE_URL = "https://api.bo3.gg/api/v1"


def team_id(clan):
    clan = clan or {}
    return clan.get("team_id") or (clan.get("team") or {}).get("id")


def provenance(metadata):
    return {key: metadata[key] for key in ("url", "fetched_at", "sha256")}


def normalize_match(raw):
    if raw["status"] != "finished" or raw["discipline_id"] != 1:
        raise ValueError("Expected a finished Counter-Strike match")
    best_of = int(raw["bo_type"])
    teams = {side: {"id": identity("bo3", raw[side]["id"]), "name": raw[side]["name"], "players": []}
             for side in ("team1", "team2")}
    maps = []
    for game in sorted(raw.get("games", []), key=lambda g: (g["number"], g["id"])):
        wid, lid = team_id(game.get("winner_team_clan")), team_id(game.get("loser_team_clan"))
        scores = {identity("bo3", wid): number(game.get("winner_clan_score"), integer=True),
                  identity("bo3", lid): number(game.get("loser_clan_score"), integer=True)}
        a, b = scores.get(teams["team1"]["id"]), scores.get(teams["team2"]["id"])
        finished = game.get("state") == "done" or game.get("status") == "finished"
        played = finished and a is not None and b is not None and a != b
        if finished and not played:
            raise ValueError("Finished game's team identities or scores are missing")
        source_name = game.get("map_name")
        maps.append({"index": game["number"], "source_game_id": int(game["id"]),
                     "name": source_name.removeprefix("de_").capitalize() if source_name else None,
                     "source_map_name": source_name, "map_revision": None, "game_version": game.get("game_version"),
                     "played": played, "demo_parsed": game.get("state") == "done",
                     "team1_rounds": a, "team2_rounds": b,
                     "winner": ("team1" if a > b else "team2") if played else None})
    winner = next((s for s in teams if teams[s]["id"] == identity("bo3", raw.get("winner_team_id"))), None)
    if winner is None:
        raise ValueError("Finished match has no winner matching either participant")
    series, winner, issues = match_outcome(best_of, number(raw.get("team1_score"), integer=True),
                                         number(raw.get("team2_score"), integer=True), maps, winner)
    if any(m["played"] and not m["demo_parsed"] for m in maps):
        issues.append("some_maps_not_demo_parsed")
    if any(m["played"] and m["team1_rounds"] + m["team2_rounds"] <= 1 for m in maps):
        issues.append("map_score_may_be_placeholder_or_forfeit")
    tournament = raw.get("tournament") or {}
    event_type = tournament.get("event_type")
    game_version = raw.get("game_version")
    start = utc_instant(raw["start_date"])
    end = utc_instant(raw["end_date"]).isoformat() if raw.get("end_date") else None
    return {"schema_version": SCHEMA_VERSION, "adapter_version": 1, "match_id": identity("bo3", raw["id"]),
            "source": "bo3", "source_url": "https://bo3.gg/matches/" + raw["slug"], "slug": raw["slug"],
            "date": start.date().isoformat(), "played_at_utc": start.isoformat(),
            "completed_at_utc": end, "ingested_at": utc_now(),
            "game": {1: "csgo", 2: "cs2"}.get(game_version, "unknown"), "game_version": game_version,
            "best_of": best_of, **teams, "series_score": series, "winner": winner, "maps": maps,
            "is_lan": True if event_type in ("lan", "offline") else False if event_type == "online" else None,
            "event": tournament.get("name"), "event_id": identity("bo3", tournament.get("id")),
            "event_tier": tournament.get("tier"), "vetoes": [], "source_match_maps": raw.get("match_maps") or [],
            "parsed_status": raw.get("parsed_status"), "issues": issues}


def normalize_stats(match, raw, map_entry=None):
    if not isinstance(raw, list):
        raise ValueError("Expected BO3 player statistics array")
    output = []
    for player in raw:
        tid = identity("bo3", team_id(player.get("team_clan")))
        side = next((s for s in ("team1", "team2") if match[s]["id"] == tid), None)
        if side is None:
            raise ValueError("Player's match team is missing or does not match participants")
        profile = player["steam_profile"]
        pid = identity("bo3", profile.get("player_id")) or identity("bo3-steam-profile", profile["id"])
        kast = number(player.get("kast"))
        if kast is not None and not 0 <= kast <= 1:
            raise ValueError("BO3 KAST is no longer a fraction in [0, 1]; adapter update required")
        row = {"schema_version": SCHEMA_VERSION, "adapter_version": 1, "match_id": match["match_id"],
               "date": match["date"], "completed_at_utc": match.get("completed_at_utc"),
               "source": "bo3", "team": side, "player_id": pid,
               "player_nick": profile.get("nickname") or (profile.get("player") or {}).get("nickname"),
               "map_name": map_entry["name"] if map_entry else "All maps",
               "source_game_id": map_entry["source_game_id"] if map_entry else None,
               "scope": "map" if map_entry else "series", "side": "Both",
               "kills": number(player.get("kills"), integer=True), "deaths": number(player.get("death"), integer=True),
               "adr": number(player.get("adr")), "kast": kast * 100 if kast is not None else None,
               "bo3_rating": number(player.get("player_rating")), "rating_version": "bo3_algorithm_unspecified",
               "ingested_at": utc_now(),
               "source_metrics": {key: value for key, value in player.items()
                                  if key not in ("steam_profile", "team_clan", "cumulative_round_damages")}}
        if not row["player_nick"]:
            raise ValueError("Player nickname is missing")
        output.append(row)
    if len({stats_key(row) for row in output}) != len(output):
        raise ValueError("Duplicate BO3 player identities in one statistics response")
    return output


def collect_match(store, http, raw, *, refresh=False, rounds=False):
    url = BASE_URL + "/matches/" + raw["slug"] + "?scope=show-match&with=games,teams,tournament_deep,stage"
    details, metadata = http.get_json(url, refresh=refresh)
    match = normalize_match(details)
    match["provenance"] = [provenance(metadata)]
    all_stats = []
    missing = []
    for entry in [None] + [m for m in match["maps"] if m["played"]]:
        endpoint = (BASE_URL + "/games/" + str(entry["source_game_id"]) if entry else BASE_URL + "/matches/" + raw["slug"])
        stats, stats_meta = http.get_json(endpoint + "/players_stats", refresh=refresh)
        rows = normalize_stats(match, stats, entry)
        # Empty responses are not evidence that a team had no players.
        if any(sum(row["team"] == s for row in rows) < 5 for s in ("team1", "team2")):
            missing.append(entry["name"] if entry else "All maps")
        for row in rows:
            row["provenance"] = [provenance(stats_meta)]
        all_stats.extend(rows)
        if entry:
            entry["players"] = {s: [{"id": r["player_id"], "nick": r["player_nick"]}
                                     for r in rows if r["team"] == s] for s in ("team1", "team2")}
            if rounds:
                _, round_meta = http.get_json(endpoint, refresh=refresh)
                entry["rounds_provenance"] = provenance(round_meta)
    for side in ("team1", "team2"):
        unique = {row["player_id"]: {"id": row["player_id"], "nick": row["player_nick"]}
                  for row in all_stats if row["team"] == side}
        match[side]["players"] = list(unique.values())
    if not any(m["played"] for m in match["maps"]):
        missing.append("played_maps")
    match["stats_missing"] = missing
    match["collection_complete"] = not missing
    existing = store.get("matches", match["match_id"])
    if missing and existing and existing.get("collection_complete"):
        raise ValueError("Refreshed statistics are incomplete; previous complete data retained")
    # Save match + all of its statistics as one transaction; a failed map fetch leaves it retryable.
    with store.db:
        store.put("matches", match["match_id"], match["date"], match)
        store.db.execute("DELETE FROM records WHERE kind='player_stats' AND parent_id=?", (match["match_id"],))
        for row in all_stats:
            store.put("player_stats", stats_key(row), row["date"], row)
    return match


def sync_matches(store, http, since, until, *, max_matches=25, max_pages=100, page_size=50, refresh=False, rounds=False):
    report = {"source": "bo3", "attempted": 0, "collected": 0, "already_complete": 0, "pending_unchanged": 0,
              "pages": 0, "errors": [],
              "stats_missing_matches": [], "window_complete": False, "stop_reason": None}
    # Freeze the upper bound so a running collection cannot ingest results completed later.
    upper = datetime.combine(date.fromisoformat(until) + timedelta(days=1), datetime.min.time(), timezone.utc)
    observed_before = min(upper, datetime.now(timezone.utc))
    lower = datetime.combine(date.fromisoformat(since), datetime.min.time(), timezone.utc)
    common = {"scope": "widget-matches", "page[limit]": page_size, "sort": "-start_date,-id",
              "filter[matches.status][in]": "finished", "filter[matches.discipline_id][eq]": 1,
              "filter[matches.start_date][gt]": (lower - timedelta(microseconds=1)).isoformat(),
              "filter[matches.start_date][lt]": upper.isoformat(), "with": "teams,tournament,games"}
    report["request_window_utc"] = {"since_inclusive": lower.isoformat(), "until_exclusive": upper.isoformat()}
    report["observed_before_utc"] = observed_before.isoformat()
    if lower >= observed_before:
        raise ValueError("Collection start date must precede the frozen upper bound")
    seen = set()
    for page in range(max_pages):
        url = BASE_URL + "/matches?" + urlencode({**common, "page[offset]": page * page_size})
        payload, _ = http.get_json(url, refresh=True)
        results = payload["results"]
        if not isinstance(results, list):
            raise ValueError("BO3 match list schema changed")
        report["pages"] += 1
        for raw in results:
            if raw["id"] in seen:
                continue
            seen.add(raw["id"])
            started = utc_instant(raw["start_date"])
            if not in_window(started.date().isoformat(), since, until) or raw["status"] != "finished":
                raise ValueError("BO3 server ignored date/status filters; refusing unbounded ingestion")
            if started >= observed_before:
                continue
            completed = raw.get("end_date")
            if completed and utc_instant(completed) >= observed_before:
                continue
            existing = store.get("matches", identity("bo3", raw["id"]))
            if existing and existing.get("collection_complete") and not refresh:
                report["already_complete"] += 1
                continue
            if (existing and not existing.get("collection_complete") and not refresh
                    and existing.get("parsed_status") == raw.get("parsed_status")):
                report["pending_unchanged"] += 1
                continue
            if report["attempted"] >= max_matches:
                report["stop_reason"] = "max_matches"
                return report
            try:
                report["attempted"] += 1
                match = collect_match(store, http, raw, refresh=refresh or bool(existing), rounds=rounds)
                report["collected"] += 1
                if match["stats_missing"]:
                    report["stats_missing_matches"].append({"match_id": match["match_id"], "missing": match["stats_missing"]})
            except (FetchError, ValueError, TypeError, KeyError) as error:
                report["errors"].append({"match_id": identity("bo3", raw["id"]), "error": str(error)})
                if len(report["errors"]) >= 3:
                    report["stop_reason"] = "repeated_errors"
                    return report
        if len(results) < page_size or (page + 1) * page_size >= payload["total"]["count"]:
            report["window_complete"] = (not report["errors"] and not report["stats_missing_matches"]
                                          and not report["pending_unchanged"])
            report["stop_reason"] = "end_of_results"
            return report
    report["stop_reason"] = "max_pages"
    return report
