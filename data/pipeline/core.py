"""Shared, model-independent data ingestion. Python standard library only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = 1
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def atomic_write(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(body)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def valid_date(value):
    return date.fromisoformat(str(value)).isoformat()


def utc_instant(value):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return instant.astimezone(timezone.utc)


def in_window(value, since, until):
    return since <= valid_date(value) <= until


class FetchError(RuntimeError):
    pass


class HttpCache:
    """Immutable response bodies plus a small URL index; never disables TLS checks."""

    def __init__(self, root=DEFAULT_ROOT, *, offline=False, interval=1.0, timeout=20, retries=2):
        self.root = Path(root)
        self.offline = offline
        self.interval = interval
        self.timeout = timeout
        self.retries = retries
        self.last_request = 0.0
        self.requests = []

    def get(self, url, *, refresh=False):
        if urlsplit(url).scheme != "https":
            raise FetchError("Only HTTPS sources are supported")
        folder = self.root / "raw" / "http" / digest(url.encode("utf-8"))
        index_path = folder / "latest.json"
        if index_path.exists() and (self.offline or not refresh):
            metadata = json.loads(index_path.read_text(encoding="utf-8"))
            body = (folder / metadata["body_file"]).read_bytes()
            if digest(body) != metadata["sha256"]:
                raise FetchError(f"Cache checksum mismatch: {url}")
            self.requests.append({**metadata, "cache_hit": True})
            return body, metadata
        if self.offline:
            raise FetchError(f"No cached response: {url}")
        for attempt in range(self.retries + 1):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                headers = {"User-Agent": "CS2-Major-prediction/1.0 (public esports research)",
                           "Accept": "application/json,text/plain,text/html;q=0.8"}
                if urlsplit(url).hostname == "api.bo3.gg":
                    headers.update({"User-Agent": "Mozilla/5.0", "Origin": "https://bo3.gg", "Referer": "https://bo3.gg/"})
                request = Request(url, headers=headers)
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    metadata = {"url": url, "fetched_at": utc_now(), "status": response.status,
                                "sha256": digest(body), "content_type": response.headers.get("Content-Type"),
                                "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
                metadata["body_file"] = metadata["sha256"] + ".body"
                atomic_write(folder / metadata["body_file"], body)
                atomic_write(index_path, json_bytes(metadata))
                self.requests.append({**metadata, "cache_hit": False})
                return body, metadata
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise FetchError(f"HTTP {error.code}: {url}") from error
                delay = error.headers.get("Retry-After", "")
                time.sleep(min(30, float(delay)) if delay.isdigit() else min(8, 2 ** attempt))
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self.retries:
                    raise FetchError(f"{type(error).__name__}: {error}: {url}") from error
                time.sleep(min(8, 2 ** attempt))
        raise AssertionError("unreachable")

    def get_json(self, url, *, refresh=False):
        body, metadata = self.get(url, refresh=refresh)
        try:
            return json.loads(body), metadata
        except (ValueError, UnicodeError) as error:
            raise FetchError(f"Expected JSON response: {url}") from error


class Store:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.path = self.root / "processed" / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, record_id TEXT NOT NULL, "
                        "record_date TEXT NOT NULL, payload TEXT NOT NULL, parent_id TEXT, PRIMARY KEY (kind, record_id))")
        self.db.execute("CREATE INDEX IF NOT EXISTS records_date ON records (kind, record_date)")
        self.db.execute("CREATE INDEX IF NOT EXISTS records_parent ON records (kind, parent_id)")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.db.rollback()
        else:
            self.db.commit()
        self.db.close()

    def put(self, kind, record_id, record_date, payload):
        valid_date(record_date)
        self.db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, record_id) "
                        "DO UPDATE SET record_date=excluded.record_date, payload=excluded.payload, parent_id=excluded.parent_id",
                        (kind, str(record_id), record_date,
                         json.dumps(payload, ensure_ascii=False, allow_nan=False), payload.get("match_id")))

    def get(self, kind, record_id):
        row = self.db.execute("SELECT payload FROM records WHERE kind=? AND record_id=?",
                              (kind, str(record_id))).fetchone()
        return json.loads(row[0]) if row else None

    def rows(self, kind, since="0001-01-01", until="9999-12-31"):
        for (payload,) in self.db.execute("SELECT payload FROM records WHERE kind=? AND record_date BETWEEN ? AND ? "
                                          "ORDER BY record_date, record_id", (kind, since, until)):
            row = json.loads(payload)
            completed = row.get("completed_at_utc")
            if completed and completed[:10] > until:
                continue
            yield row

    def summary(self):
        return {kind: {"count": count, "earliest": first, "latest": last}
                for kind, count, first, last in self.db.execute(
                    "SELECT kind,COUNT(*),MIN(record_date),MAX(record_date) FROM records GROUP BY kind")}


def number(value, *, integer=False):
    if value is None or str(value).strip() in ("", "-", "N/A", "unknown"):
        return None
    result = float(str(value).strip().rstrip("%"))
    if not math.isfinite(result) or (integer and not result.is_integer()):
        raise ValueError(f"Invalid numeric value: {value!r}")
    return int(result) if integer else result


def identity(namespace, value):
    return f"{namespace}:{int(value)}" if value is not None and str(value) != "" else None


def hltv_id(url):
    match = re.search(r"/matches/(\d+)(?:/|$)", url)
    if not match:
        raise ValueError(f"Missing stable HLTV match ID: {url}")
    return int(match.group(1))


def match_outcome(best_of, score1, score2, maps, winner=None):
    """Series winner never depends on the sum of rounds across maps."""
    issues = []
    if best_of not in (None, 1, 3, 5):
        raise ValueError(f"Unknown best_of: {best_of!r}")
    if winner not in (None, "team1", "team2"):
        raise ValueError(f"Invalid winner: {winner!r}")
    played = [m for m in maps if m["played"]]
    if best_of is None:
        issues.append("best_of_unknown")
        series = {side: sum(m["winner"] == side for m in played) for side in ("team1", "team2")} if played else None
        inferred = None
        if series and series["team1"] != series["team2"]:
            inferred = max(series, key=series.get)
        elif score1 is not None and score2 is not None and score1 != score2:
            inferred = "team1" if score1 > score2 else "team2"
    elif best_of == 1:
        series = {"team1": 0, "team2": 0} if played or score1 is not None else None
        inferred = None
        if played:
            inferred = played[0]["winner"]
        elif score1 is not None and score2 is not None and score1 != score2:
            inferred = "team1" if score1 > score2 else "team2"
        if series and inferred:
            series[inferred] = 1
    else:
        series = {"team1": score1, "team2": score2} if score1 is not None and score2 is not None else None
        inferred = None
        if series:
            if any(v < 0 or v > best_of for v in series.values()):
                raise ValueError("Series scores are not map counts")
            if score1 != score2:
                inferred = "team1" if score1 > score2 else "team2"
        if played:
            counted = {side: sum(m["winner"] == side for m in played) for side in ("team1", "team2")}
            if series and counted != series:
                issues.append("reported_series_score_differs_from_played_maps")
            if series is None:
                series = counted
                if counted["team1"] != counted["team2"]:
                    inferred = max(counted, key=counted.get)
    if winner and inferred and winner != inferred:
        issues.append("reported_winner_conflicts_with_score")
    winner = winner or inferred
    if not winner:
        issues.append("winner_unknown")
    elif best_of is not None and (not series or series[winner] < best_of // 2 + 1):
        issues.append("series_incomplete_or_forfeit")
    return series, winner, issues


def normalize_legacy_match(url, raw):
    mid = hltv_id(url)
    details = raw.get("details") or {}
    source_format = str(raw.get("type", "unknown")).upper()
    best_of = int(source_format.removeprefix("BO")) if re.fullmatch(r"BO[135]", source_format) else None
    maps = []
    for index, entry in enumerate(details.get("maps", []), 1):
        score = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", entry.get("score", ""))
        a, b = map(int, score.groups()) if score else (None, None)
        played = a is not None and a != b
        maps.append({"index": index, "name": entry.get("map_name"), "played": played,
                     "source_map_name": entry.get("map_name"), "map_revision": None,
                     "team1_rounds": a, "team2_rounds": b,
                     "winner": ("team1" if a > b else "team2") if played else None,
                     "picker": entry.get("picker"), "half_score": entry.get("half_score"),
                     "team1_start_side": entry.get("team1_half1_side")})
    series, winner, issues = match_outcome(best_of, number(raw.get("team1_score"), integer=True),
                                         number(raw.get("team2_score"), integer=True), maps)
    played_at = raw.get("match_datetime")
    match_date = valid_date(raw["date"])
    if played_at:
        played_at = utc_instant(played_at).isoformat()
        match_date = played_at[:10]
    record = {"schema_version": SCHEMA_VERSION, "match_id": f"hltv:{mid}", "hltv_id": mid,
              "source": "legacy_hltv", "adapter_version": 1, "game": "unknown", "game_version": None,
              "source_url": url, "ingested_at": utc_now(),
              "date": match_date, "source_date": raw["date"], "played_at_utc": played_at,
              "best_of": best_of, "source_format": source_format,
              "series_score": series, "winner": winner, "maps": maps,
              "is_lan": details.get("is_lan"), "event": details.get("event_name"),
              "event_id": details.get("event_id"), "stage": details.get("stage"),
              "vetoes": details.get("veto_steps", []), "vrs": details.get("vrs_data", {}), "issues": issues}
    for side in ("team1", "team2"):
        record[side] = {"id": None, "name": raw[side], "players": [
            {"id": identity("hltv", p.get("id")), "nick": p.get("nick")}
            for p in details.get(side + "_lineup", []) if isinstance(p, dict)]}
    return record


def stats_key(row):
    player = row["player_id"] if row["player_id"] is not None else "nick:" + row["player_nick"].casefold()
    return json.dumps([row["match_id"], row["team"], player, row["map_name"], row["side"]], ensure_ascii=False)


def import_legacy(store, directory, since, until):
    directory = Path(directory)
    report = {"source": "legacy_hltv", "matches": 0, "player_stats": 0, "rankings": 0,
              "rejected": 0, "rejection_examples": [], "input_files": []}
    index = {}
    path = directory / "match_details_lite.json"
    body = path.read_bytes()
    report["input_files"].append({"path": str(path.resolve()), "sha256": digest(body)})
    for url, raw in json.loads(body).items():
        try:
            match = normalize_legacy_match(url, raw)
            if not in_window(match["date"], since, until):
                continue
        except (ValueError, TypeError, KeyError) as error:
            report["rejected"] += 1
            if len(report["rejection_examples"]) < 10:
                report["rejection_examples"].append({"record": url, "error": str(error)})
            continue
        index[match["hltv_id"]] = match
        # An offline import must not replace richer, subsequently collected live records.
        existing = store.get("matches", match["match_id"])
        if not existing or existing["source"] == "legacy_hltv":
            store.put("matches", match["match_id"], match["date"], match)
        report["matches"] += 1
    path = directory / "player_stats.csv"
    if path.exists():
        report["input_files"].append({"path": str(path.resolve()), "sha256": digest(path.read_bytes())})
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                try:
                    mid = hltv_id(raw["match_url"])
                    match = index.get(mid)
                    if match is None:
                        continue
                    nick = raw["player_id"]  # Historical CSV uses nicknames in this column.
                    candidates = [(side, p) for side in ("team1", "team2") for p in match[side]["players"]
                                  if (p.get("nick") or "").casefold() == nick.casefold()]
                    if len(candidates) == 1:
                        side, player = candidates[0]
                        pid = player["id"]
                    else:
                        side = next((s for s in ("team1", "team2")
                                     if match[s]["name"].casefold() == raw["team"].casefold()), None)
                        if side is None:
                            raise ValueError("Could not associate player with either team")
                        pid = None
                    row = {"schema_version": SCHEMA_VERSION, "adapter_version": 1,
                           "match_id": match["match_id"], "date": match["date"],
                           "source": "legacy_hltv", "team": side, "player_id": pid, "player_nick": nick,
                           "map_name": raw["map_name"], "scope": "series" if raw["map_name"] == "All maps" else "map",
                           "side": raw.get("side") or "Both", "rating_version": "unknown", "ingested_at": utc_now(),
                           "kills": number(raw.get("kills"), integer=True), "deaths": number(raw.get("deaths"), integer=True),
                           **{key: number(raw.get(key)) for key in ("adr", "kast")},
                           "hltv_rating": number(raw.get("rating")),
                           "source_metrics": {"plus_minus": raw.get("plus_minus")}}
                    key = stats_key(row)
                    existing = store.get("player_stats", key)
                    if not existing or existing["source"] == "legacy_hltv":
                        store.put("player_stats", key, row["date"], row)
                    report["player_stats"] += 1
                except (ValueError, TypeError, KeyError) as error:
                    report["rejected"] += 1
                    if len(report["rejection_examples"]) < 10:
                        report["rejection_examples"].append({"record": raw.get("match_url"), "error": str(error)})
    path = directory / "valve_rankings.csv"
    if path.exists():
        report["input_files"].append({"path": str(path.resolve()), "sha256": digest(path.read_bytes())})
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                if not in_window(raw["snapshot_date"], since, until):
                    continue
                row = {"schema_version": SCHEMA_VERSION, "adapter_version": 1,
                       "source": "legacy_valve", "date": raw["snapshot_date"],
                       "region": raw["region"], "rank": int(raw["standing"]), "points": float(raw["points"]),
                       "team_name": raw["team_name"], "roster": [p.strip() for p in raw["roster"].split(",")],
                       "ingested_at": utc_now()}
                key = json.dumps([row["date"], row["region"], row["rank"]])
                existing = store.get("rankings", key)
                if not existing or existing["source"] == "legacy_valve":
                    store.put("rankings", key, row["date"], row)
                report["rankings"] += 1
    return report


def parse_valve_standings(text, snapshot_date, region, source_url):
    title_date = re.search(r"Standings as of (\d{4})_(\d{2})_(\d{2})", text, re.I)
    if title_date and "-".join(title_date.groups()) != snapshot_date:
        raise ValueError("Ranking title date does not match its filename")
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6 or not cells[1].isdigit():
            continue
        rows.append({"schema_version": SCHEMA_VERSION, "adapter_version": 1,
                     "source": "valve_official", "source_url": source_url,
                     "date": valid_date(snapshot_date), "region": region, "rank": int(cells[1]),
                     "points": float(cells[2]), "team_name": cells[3],
                     "roster": [p.strip() for p in cells[4].split(",") if p.strip()], "ingested_at": utc_now()})
    if not rows or len({r["rank"] for r in rows}) != len(rows):
        raise ValueError("Empty or duplicate ranking table")
    return rows


def sync_rankings(store, http, since, until, *, history=False):
    repo = "https://api.github.com/repos/ValveSoftware/counter-strike_regional_standings"
    ref, _ = http.get_json(repo + "/git/ref/heads/main", refresh=True)
    commit = ref["object"]["sha"]
    tree_url = repo + "/git/trees/" + commit + "?recursive=1"
    tree, _ = http.get_json(tree_url, refresh=True)
    if tree.get("truncated"):
        raise ValueError("GitHub file tree is truncated; ranking discovery would be incomplete")
    selected = {}
    for item in tree["tree"]:
        match = re.fullmatch(r"(live|invitation)/\d{4}/standings_(global|europe|americas|asia)_(\d{4})_(\d{2})_(\d{2})\.md", item["path"])
        if not match:
            continue
        group, region, year, month, day = match.groups()
        snapshot_date = f"{year}-{month}-{day}"
        if in_window(snapshot_date, since, until):
            # The same date/region can appear in both directories; prefer invitation snapshots.
            key = (snapshot_date, region)
            if key not in selected or group == "invitation":
                selected[key] = item["path"]
    if not selected:
        raise ValueError("No official ranking snapshots in the requested date window")
    if not history:
        selected = {key: path for key, path in selected.items()
                    if key[0] == max(k[0] for k in selected if k[1] == key[1])}
    count = 0
    for (snapshot_date, region), path in sorted(selected.items()):
        url = "https://raw.githubusercontent.com/ValveSoftware/counter-strike_regional_standings/" + commit + "/" + path
        body, _ = http.get(url)
        rows = parse_valve_standings(body.decode("utf-8-sig"), snapshot_date, region, url)
        for row in rows:
            store.put("rankings", json.dumps([row["date"], region, row["rank"]]), snapshot_date, row)
        count += len(rows)
        store.db.commit()
    return {"source": "valve_official", "git_commit": commit, "snapshots": len(selected), "rankings": count,
            "latest_snapshot": max(k[0] for k in selected)}


def quality_report(store, since, until):
    counts = {"matches": 0, "maps_played": 0, "matches_with_vetoes": 0, "matches_with_ten_players": 0,
              "series_player_rows": 0, "map_player_rows": 0, "player_id_missing": 0,
              "matches_with_series_player_stats": 0, "matches_with_map_player_stats": 0,
              "matches_with_issues": 0, "hltv_rating_rows": 0, "bo3_rating_rows": 0,
              "metric_missing": {k: 0 for k in ("kast", "adr")}}
    days = []
    issues = []
    stats_scopes = {"series": set(), "map": set()}
    for row in store.rows("player_stats", since, until):
        counts[row["scope"] + "_player_rows"] += 1
        stats_scopes[row["scope"]].add(row["match_id"])
        counts["player_id_missing"] += row["player_id"] is None
        counts["hltv_rating_rows"] += row.get("hltv_rating") is not None
        counts["bo3_rating_rows"] += row.get("bo3_rating") is not None
        for metric in counts["metric_missing"]:
            counts["metric_missing"][metric] += row.get(metric) is None
    for row in store.rows("matches", since, until):
        counts["matches"] += 1
        days.append(row["date"])
        counts["maps_played"] += sum(m["played"] for m in row["maps"])
        counts["matches_with_vetoes"] += bool(row.get("vetoes"))
        counts["matches_with_ten_players"] += all(len(row[s]["players"]) == 5 for s in ("team1", "team2"))
        counts["matches_with_issues"] += bool(row.get("issues"))
        if row.get("issues") and len(issues) < 10:
            issues.append({"match_id": row["match_id"], "issues": row["issues"]})
    for scope, mids in stats_scopes.items():
        counts["matches_with_" + scope + "_player_stats"] = len(mids)
    return {"window": {"since": since, "until": until, "timezone": "UTC; legacy date may have day precision"},
            "coverage": counts, "earliest_match": min(days) if days else None,
            "latest_match": max(days) if days else None, "issue_examples": issues}


def export_snapshot(store, since, until):
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = store.root / "snapshots" / label
    files = {}
    for kind in ("matches", "player_stats", "rankings"):
        body = b"".join((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
                        for row in store.rows(kind, since, until))
        atomic_write(folder / (kind + ".jsonl"), body)
        files[kind + ".jsonl"] = {"sha256": digest(body), "rows": body.count(b"\n"), "bytes": len(body)}
    manifest = {"schema_version": SCHEMA_VERSION, "created_at": utc_now(), "files": files,
                "quality": quality_report(store, since, until),
                "note": "Date-filtered export of current records; ingested_at is not historical availability."}
    atomic_write(folder / "manifest.json", json_bytes(manifest))
    return {"snapshot": str(folder.resolve()), "files": files, "quality": manifest["quality"]}
