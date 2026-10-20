"""HLTV match-page scoreboards: series, maps, historical participants and Rating labels."""

from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urlencode, urljoin, urlsplit

from .core import (FetchError, SCHEMA_VERSION, hltv_id, identity, in_window, match_outcome,
                   number, stats_key, utc_now)


ORIGIN = "https://www.hltv.org"


def soup_html(body):
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise FetchError("HLTV parsing needs: pip install -r data/pipeline/requirements-hltv.txt") from error
    return BeautifulSoup(body, "html.parser")


def text(element):
    return element.get_text(" ", strip=True) if element is not None else ""


def link_id(element, kind):
    match = re.search(r"/" + re.escape(kind) + r"/(\d+)(?:/|$)", element.get("href", "") if element else "")
    if not match:
        raise ValueError("Missing stable HLTV " + kind + " identity")
    return int(match.group(1))


def match_url(value):
    url = urljoin(ORIGIN, value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "www.hltv.org" or parsed.query or parsed.fragment:
        raise ValueError("Expected a canonical public HLTV match URL")
    hltv_id(url)
    return url


def parse_results(body):
    soup = soup_html(body)
    containers = soup.select(".results-all .result-con")
    if not containers:
        if soup.select_one(".results-all") and re.search(r"no results", text(soup), re.I):
            return []
        raise ValueError("HLTV result list missing or changed; refusing an empty success")
    results = []
    seen = set()
    for container in containers:
        url = match_url(container.select_one("a.a-reset[href]")["href"])
        if url in seen:
            continue
        seen.add(url)
        stamp = container.get("data-zonedgrouping-entry-unix")
        instant = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc) if stamp else None
        results.append({"url": url, "format": text(container.select_one(".map-text")).lower(),
                        "results_page_timestamp_utc": instant.isoformat() if instant else None})
    return results


def cell_value(row, name, *, adjusted=False):
    candidates = row.select("td." + name)
    if adjusted:
        cell = next((c for c in candidates if "eco-adjusted-data" in c.get("class", [])), None)
    else:
        cell = next((c for c in candidates if "traditional-data" in c.get("class", [])), None)
        if cell is None:
            cell = next((c for c in candidates if "eco-adjusted-data" not in c.get("class", [])), None)
    return text(cell)


def kd_pair(value):
    if value in ("", "-", "N/A"):
        return None, None
    pair = re.fullmatch(r"\s*(\d+)\s*[-–:]\s*(\d+)\s*", value)
    if pair is None:
        raise ValueError("Unexpected HLTV K-D field: " + value)
    return tuple(map(int, pair.groups()))


def percentage(value):
    result = number(value)
    if result is not None and not 0 <= result <= 100:
        raise ValueError("HLTV percentage outside [0, 100]")
    return result


def parse_match(body, url, metadata):
    url = match_url(url)
    soup = soup_html(body)
    root = soup.select_one(".match-page")
    if root is None or text(root.select_one(".countdown")).lower() != "match over":
        raise ValueError("HLTV page is not a recognized finished match")
    stamp = root.select_one(".timeAndEvent [data-unix]")
    if stamp is None:
        raise ValueError("HLTV match start timestamp missing")
    start = datetime.fromtimestamp(int(stamp["data-unix"]) / 1000, timezone.utc)
    provenance = [{key: metadata[key] for key in ("url", "fetched_at", "sha256", "transport", "representation")
                   if key in metadata}]
    teams = {}
    scores = {}
    for side in ("team1", "team2"):
        box = root.select_one("." + side + "-gradient")
        if box is None:
            raise ValueError("HLTV match participant box missing")
        teams[side] = {"id": identity("hltv", link_id(box.select_one('a[href^="/team/"]'), "team")),
                       "name": text(box.select_one(".teamName")), "players": []}
        scores[side] = number(text(box.select_one(".won,.lost")), integer=True)
        if not teams[side]["name"] or scores[side] is None:
            raise ValueError("HLTV finished match participant name or score missing")
    veto_boxes = root.select(".veto-box")
    description = text(veto_boxes[0]) if veto_boxes else ""
    best = re.search(r"Best of ([135])\b", description, re.I)
    best_of = int(best.group(1)) if best else None
    if re.search(r"Best of \d+", description, re.I) and best is None:
        raise ValueError("Unsupported HLTV best-of format")
    maps = []
    for index, holder in enumerate(root.select(".mapholder"), 1):
        name = text(holder.select_one(".mapname"))
        if not name:
            raise ValueError("HLTV map name missing")
        round_scores = {}
        picks = []
        for position in ("left", "right"):
            block = holder.select_one(".results-" + position)
            if block is None:
                raise ValueError("HLTV map participant block missing")
            name_at_map = text(block.select_one(".results-teamname"))
            side = next((s for s in teams if teams[s]["name"].casefold() == name_at_map.casefold()), None)
            if side is None:
                raise ValueError("HLTV map participants disagree with series participants")
            round_scores[side] = number(text(block.select_one(".results-team-score")), integer=True)
            if "pick" in block.get("class", []):
                picks.append(side)
        a, b = round_scores.get("team1"), round_scores.get("team2")
        default = name.casefold() == "default"
        played = not default and bool(holder.select_one(".results.played")) and a is not None and b is not None and a != b
        stats = holder.select_one('a.results-stats[href*="/mapstatsid/"]')
        stats_id = re.search(r"/mapstatsid/(\d+)/", stats["href"]) if stats else None
        half = holder.select_one(".results-center-half-score")
        first_side = half.select_one(".ct,.t") if half else None
        maps.append({"index": index, "name": name, "source_map_name": name, "map_revision": None,
                     "played": played, "team1_rounds": None if default else a, "team2_rounds": None if default else b,
                     "winner": ("team1" if a > b else "team2") if played else None,
                     "default_map": default,
                     "awarded_winner": ("team1" if a > b else "team2") if default and a is not None and b is not None and a != b else None,
                     "source_default_score": {"team1": a, "team2": b} if default else None,
                     "source_map_stats_id": int(stats_id.group(1)) if stats_id else None,
                     "stats_url": urljoin(ORIGIN, stats["href"]) if stats else None,
                     "picker": picks[0] if len(picks) == 1 else None, "half_score": text(half) or None,
                     "team1_start_side": "CT" if first_side and "ct" in first_side.get("class", []) else "T" if first_side else None})
    winner = "team1" if scores["team1"] > scores["team2"] else "team2" if scores["team2"] > scores["team1"] else None
    series, winner, issues = match_outcome(best_of, scores["team1"], scores["team2"], maps, winner)
    if not maps:
        issues.append("map_scoreboards_missing_or_forfeit")
    if any(m["default_map"] for m in maps):
        issues.append("default_maps_present")
    event = root.select_one('.timeAndEvent .event a[href^="/events/"]')
    event_id = identity("hltv", link_id(event, "events")) if event else None
    record = {"schema_version": SCHEMA_VERSION, "adapter_version": 1, "source": "hltv",
              "match_id": identity("hltv", hltv_id(url)), "hltv_id": hltv_id(url), "source_url": url,
              "date": start.date().isoformat(), "played_at_utc": start.isoformat(), "completed_at_utc": None,
              "ingested_at": utc_now(), "game": "unknown",
              "game_version": None, "best_of": best_of, "series_score": series, "winner": winner,
              **teams, "maps": maps, "event": text(event) or None, "event_id": event_id,
              "is_lan": False if "(Online)" in description else True if "(LAN)" in description else None,
              "source_description": description,
              "vetoes": [{"order": index, "source_text": line.strip()} for index, line in
                          enumerate(veto_boxes[-1].get_text("\n", strip=True).splitlines(), 1)
                          if re.match(r"\d+\.\s", line.strip())] if len(veto_boxes) > 1 else [],
              "issues": issues, "provenance": provenance, "collection_scope": "match_page_scoreboards"}
    rows = []
    missing = []
    for entry in [None] + [m for m in maps if m["played"]]:
        content_id = "all-content" if entry is None else str(entry["source_map_stats_id"]) + "-content"
        content = root.find("div", id=content_id)
        scope_rows = []
        for table in content.select("table.totalstats") if content else []:
            header_team = table.select_one('.header-row a[href^="/team/"]')
            team = identity("hltv", link_id(header_team, "team"))
            side = next((s for s in teams if teams[s]["id"] == team), None)
            if side is None:
                raise ValueError("HLTV statistics team differs from match participants")
            version_label = text(table.select_one(".header-row .ratingDesc"))
            version = version_label if re.fullmatch(r"\d+\.\d+", version_label) else "unknown"
            for player in table.select("tr"):
                link = player.select_one('td.players a[href^="/player/"]')
                if link is None:
                    continue
                pid = identity("hltv", link_id(link, "player"))
                nick = text(link.select_one(".player-nick")) or text(link.select_one(".smartphone-only"))
                if not nick:
                    raise ValueError("HLTV player nickname missing")
                kills, deaths = kd_pair(cell_value(player, "kd"))
                eco_kills, eco_deaths = kd_pair(cell_value(player, "kd", adjusted=True))
                row = {"schema_version": SCHEMA_VERSION, "adapter_version": 1, "source": "hltv",
                       "match_id": record["match_id"], "date": record["date"], "team": side,
                       "player_id": pid, "player_nick": nick, "scope": "map" if entry else "series",
                       "map_name": entry["name"] if entry else "All maps", "side": "Both",
                       "source_map_stats_id": entry["source_map_stats_id"] if entry else None,
                       "kills": kills, "deaths": deaths, "adr": number(cell_value(player, "adr")),
                       "kast": percentage(cell_value(player, "kast")),
                       "hltv_rating": number(cell_value(player, "rating")), "rating_version": version,
                       "rating_revision": "unknown", "ingested_at": utc_now(), "provenance": provenance,
                       "source_metrics": {"round_swing_pct": number(cell_value(player, "roundSwing")),
                                          "eco_kills": eco_kills, "eco_deaths": eco_deaths,
                                          "eco_adr": number(cell_value(player, "adr", adjusted=True)),
                                          "eco_kast": percentage(cell_value(player, "kast", adjusted=True))}}
                scope_rows.append(row)
        if (any(sum(r["team"] == side for r in scope_rows) < 5 for side in teams)
                or any(r[k] is None for r in scope_rows for k in ("kills", "deaths", "adr", "kast", "hltv_rating"))):
            missing.append(entry["name"] if entry else "All maps")
        if entry:
            entry["players"] = {s: [{"id": r["player_id"], "nick": r["player_nick"]}
                                     for r in scope_rows if r["team"] == s] for s in teams}
        rows.extend(scope_rows)
    if len({stats_key(row) for row in rows}) != len(rows):
        raise ValueError("Duplicate HLTV player/scope identities")
    for side in teams:
        unique = {r["player_id"]: {"id": r["player_id"], "nick": r["player_nick"]} for r in rows if r["team"] == side}
        record[side]["players"] = list(unique.values())
    if not any(m["played"] for m in maps):
        missing.append("played_maps")
    record["stats_missing"] = missing
    record["collection_complete"] = not missing
    return record, rows


def collect_match(store, http, url, *, refresh=False, since=None, until=None, before=None):
    body, metadata = http.get(url, refresh=refresh)
    match, rows = parse_match(body, url, metadata)
    if since and until and not in_window(match["date"], since, until):
        return match, False
    if before and datetime.fromisoformat(match["played_at_utc"]) >= before:
        return match, False
    existing = store.get("matches", match["match_id"])
    if existing and existing["source"] != "hltv":
        raise ValueError("Existing imported HLTV record retained; use a separate --data-dir for source comparison")
    if existing and existing.get("collection_complete") and not match["collection_complete"]:
        raise ValueError("Incomplete HLTV refresh; previous complete data retained")
    with store.db:
        store.put("matches", match["match_id"], match["date"], match)
        store.db.execute("DELETE FROM records WHERE kind='player_stats' AND parent_id=?", (match["match_id"],))
        for row in rows:
            store.put("player_stats", stats_key(row), row["date"], row)
    return match, True


def sync_matches(store, http, since, until, *, max_matches=5, max_pages=100, refresh=False, urls=None):
    report = {"source": "hltv", "attempted": 0, "collected": 0, "already_complete": 0,
              "pending_unchanged": 0, "existing_import_retained": 0, "forfeits_skipped": 0,
              "outside_window": 0, "pages": 0, "errors": [], "stats_missing_matches": [],
              "window_complete": False, "requested_urls_complete": False, "stop_reason": None,
              "selection": "explicit_urls" if urls else "results_pages", "collection_scope": "match_page_scoreboards"}
    seen = set()
    observed_before = min(datetime.now(timezone.utc), datetime.combine(date.fromisoformat(until) + timedelta(days=1),
                                                                 datetime.min.time(), timezone.utc))
    report["observed_before_utc"] = observed_before.isoformat()
    # Result pages group by result date. Extend edges and verify UTC start dates locally.
    query = {"startDate": (date.fromisoformat(since) - timedelta(days=1)).isoformat(),
             "endDate": (date.fromisoformat(until) + timedelta(days=1)).isoformat()}
    report["results_date_filters"] = query
    report["coverage_note"] = "Scanned provider result pages; UTC starts checked locally; exact completion times unavailable."
    for page in range(1 if urls else max_pages):
        if urls:
            candidates = [{"url": match_url(url)} for url in urls]
        else:
            params = {**query, "offset": page * 100} if page else query
            body, _ = http.get(ORIGIN + "/results?" + urlencode(params), refresh=True)
            candidates = parse_results(body)
            report["pages"] += 1
        for candidate in candidates:
            url = candidate["url"]
            if url in seen:
                continue
            seen.add(url)
            if candidate.get("format") == "def":
                report["forfeits_skipped"] += 1
                continue
            stamp = candidate.get("results_page_timestamp_utc")
            if stamp and datetime.fromisoformat(stamp) >= observed_before:
                report["outside_window"] += 1
                continue
            existing = store.get("matches", identity("hltv", hltv_id(url)))
            if existing and existing["source"] != "hltv":
                report["existing_import_retained"] += 1
                continue
            if existing and not refresh:
                key = "already_complete" if existing.get("collection_complete") else "pending_unchanged"
                report[key] += 1
                continue
            if report["attempted"] >= max_matches:
                report["stop_reason"] = "max_matches"
                return report
            report["attempted"] += 1
            try:
                match, saved = collect_match(store, http, url, refresh=refresh or bool(existing), since=since, until=until,
                                             before=observed_before)
                if not saved:
                    report["outside_window"] += 1
                    continue
                report["collected"] += 1
                if match["stats_missing"]:
                    report["stats_missing_matches"].append({"match_id": match["match_id"], "missing": match["stats_missing"]})
            except (FetchError, ValueError, TypeError, KeyError) as error:
                report["errors"].append({"url": url, "error": str(error)})
                if isinstance(error, FetchError) or len(report["errors"]) >= 3:
                    report["stop_reason"] = "access_error" if isinstance(error, FetchError) else "repeated_errors"
                    return report
        if urls or len(candidates) < 100:
            complete = not (report["errors"] or report["stats_missing_matches"] or report["pending_unchanged"])
            report["requested_urls_complete" if urls else "window_complete"] = complete
            report["stop_reason"] = "requested_urls_complete" if urls else "end_of_results"
            return report
    report["stop_reason"] = "max_pages"
    return report
