import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from data.pipeline.bo3 import collect_match, normalize_match, normalize_stats, sync_matches
from data.pipeline.core import (DEFAULT_ROOT, FetchError, HttpCache, Store, digest, export_snapshot,
                                import_legacy, normalize_legacy_match, parse_valve_standings)


def match_fixture(mid=123):
    games = []
    for index, (winner, win_score, loss_score) in enumerate(((1, 13, 11), (2, 13, 4), (1, 13, 10)), 1):
        games.append({"id": index, "number": index, "map_name": ("de_nuke", "de_anubis", "de_ancient")[index - 1],
                      "state": "done", "winner_clan_score": win_score, "loser_clan_score": loss_score,
                      "winner_team_clan": {"team": {"id": winner}},
                      "loser_team_clan": {"team_id": 3 - winner}, "game_version": 2})
    return {"id": mid, "slug": f"a-vs-b-{mid}", "status": "finished", "discipline_id": 1, "game_version": 2,
            "start_date": "2026-10-18T12:00:00+00:00", "end_date": "2026-10-18T14:00:00+00:00",
            "bo_type": 3, "winner_team_id": 1, "team1_score": 2, "team2_score": 1,
            "team1": {"id": 1, "name": "A"}, "team2": {"id": 2, "name": "B"},
            "tournament": {"id": 5, "name": "Event", "event_type": "online"}, "games": list(reversed(games))}


def stats_fixture():
    return [{"kills": 20, "death": 12, "adr": 85, "kast": 0.7, "player_rating": 7.5,
             "team_clan": {"team_id": team},
             "steam_profile": {"id": team * 100 + i, "player_id": team * 100 + i,
                               "nickname": f"p{team}{i}", "player": {"team_id": 3 - team}}}
            for team in (1, 2) for i in range(5)]


class FakeHttp:
    def __init__(self, matches=None, missing=False, fail=False):
        self.matches = matches or [match_fixture()]
        self.missing, self.fail = missing, fail

    def get_json(self, url, **kwargs):
        meta = {"url": url, "fetched_at": "2026-10-20T00:00:00+00:00", "sha256": "fixture"}
        if "/matches?" in url:
            query = parse_qs(urlsplit(url).query)
            offset, limit = int(query["page[offset]"][0]), int(query["page[limit]"][0])
            return {"total": {"count": len(self.matches)}, "results": self.matches[offset:offset + limit]}, meta
        if url.endswith("/players_stats"):
            if self.fail and "/games/" in url:
                raise FetchError("interrupted map statistics request")
            return ([] if self.missing else stats_fixture()), meta
        return copy.deepcopy(self.matches[0]), meta


class PipelineTests(unittest.TestCase):
    def setUp(self):
        parent = DEFAULT_ROOT / "processed" / "test-temp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_series_winner_is_not_total_round_winner_and_map_order_is_restored(self):
        match = normalize_match(match_fixture())
        self.assertEqual(match["winner"], "team1")
        self.assertEqual(sum(m["team1_rounds"] for m in match["maps"]), 30)
        self.assertEqual(sum(m["team2_rounds"] for m in match["maps"]), 34)
        self.assertEqual([m["index"] for m in match["maps"]], [1, 2, 3])
        self.assertEqual(match["issues"], [])

    def test_stats_use_match_team_and_preserve_distinct_rating_scales(self):
        rows = normalize_stats(normalize_match(match_fixture()), stats_fixture())
        self.assertEqual(rows[0]["team"], "team1")
        self.assertEqual(rows[0]["player_id"], "bo3:100")
        self.assertEqual(rows[0]["kast"], 70)
        self.assertEqual(rows[0]["bo3_rating"], 7.5)
        self.assertNotIn("hltv_rating", rows[0])

    def test_finished_unparsed_maps_are_kept_with_quality_flags(self):
        raw = match_fixture()
        raw["games"][0].pop("state")
        raw["games"][0].update(status="finished", winner_clan_score=1, loser_clan_score=0)
        row = normalize_match(raw)
        self.assertEqual(len(row["maps"]), 3)
        self.assertIn("some_maps_not_demo_parsed", row["issues"])
        self.assertIn("map_score_may_be_placeholder_or_forfeit", row["issues"])

    def test_source_timezone_is_converted_before_date_filtering(self):
        raw = match_fixture()
        raw["start_date"] = "2026-10-19T00:30:00+08:00"
        raw["end_date"] = "2026-10-19T02:30:00+08:00"
        row = normalize_match(raw)
        self.assertEqual(row["date"], "2026-10-18")
        self.assertEqual(row["completed_at_utc"], "2026-10-18T18:30:00+00:00")

    def test_kast_schema_drift_stops_ingestion(self):
        raw = stats_fixture()
        raw[0]["kast"] = 70
        with self.assertRaisesRegex(ValueError, "adapter update"):
            normalize_stats(normalize_match(match_fixture()), raw)

    def test_interrupted_match_does_not_commit_half_the_statistics(self):
        with Store(self.root) as store:
            with self.assertRaises(FetchError):
                collect_match(store, FakeHttp(fail=True), match_fixture())
            self.assertIsNone(store.get("matches", "bo3:123"))
            self.assertEqual(list(store.rows("player_stats")), [])

    def test_refresh_is_idempotent_and_keeps_good_data_when_new_response_is_empty(self):
        with Store(self.root) as store:
            collect_match(store, FakeHttp(), match_fixture())
            collect_match(store, FakeHttp(), match_fixture(), refresh=True)
            self.assertEqual(store.summary()["player_stats"]["count"], 40)
            with self.assertRaisesRegex(ValueError, "previous complete data retained"):
                collect_match(store, FakeHttp(missing=True), match_fixture(), refresh=True)
            self.assertTrue(store.get("matches", "bo3:123")["collection_complete"])
            self.assertEqual(store.summary()["player_stats"]["count"], 40)

    def test_empty_stats_remain_retryable(self):
        with Store(self.root) as store:
            result = collect_match(store, FakeHttp(missing=True), match_fixture())
            self.assertFalse(result["collection_complete"])
            self.assertIn("Nuke", result["stats_missing"])

    def test_pending_statistics_do_not_block_backfill_on_repeated_runs(self):
        first, second = match_fixture(123), match_fixture(124)
        first["parsed_status"] = "waiting"
        second["parsed_status"] = "done"
        http = FakeHttp(matches=[first, second])
        with Store(self.root) as store:
            pending = normalize_match(first)
            pending["collection_complete"] = False
            store.put("matches", pending["match_id"], pending["date"], pending)
            # No need to model HTTP details here; check which match reaches the collector.
            with patch("data.pipeline.bo3.collect_match", return_value={"stats_missing": []}) as collector:
                report = sync_matches(store, http, "2026-10-18", "2026-10-19", max_matches=1)
            self.assertEqual(collector.call_count, 1)
            self.assertEqual(collector.call_args.args[2]["id"], 124)
            self.assertEqual(report["pending_unchanged"], 1)
            self.assertFalse(report["window_complete"])

    def test_pagination_and_repeated_bounded_runs_eventually_finish(self):
        http = FakeHttp(matches=[match_fixture(i) for i in (123, 124, 125)])
        collected = []

        def collect(store, http, raw, **kwargs):
            row = normalize_match(raw)
            row.update(collection_complete=True, stats_missing=[])
            store.put("matches", row["match_id"], row["date"], row)
            store.db.commit()
            collected.append(row["match_id"])
            return row

        with Store(self.root) as store, patch("data.pipeline.bo3.collect_match", side_effect=collect):
            first = sync_matches(store, http, "2026-10-18", "2026-10-19", max_matches=1, page_size=2)
            second = sync_matches(store, http, "2026-10-18", "2026-10-19", max_matches=1, page_size=2)
            third = sync_matches(store, http, "2026-10-18", "2026-10-19", max_matches=1, page_size=2)
        self.assertFalse(first["window_complete"])
        self.assertEqual(second["already_complete"], 1)
        self.assertTrue(third["window_complete"])
        self.assertEqual(collected, ["bo3:123", "bo3:124", "bo3:125"])

    def test_unknown_historical_format_is_retained_without_guessing_bo1(self):
        raw = {"date": "2026-06-07", "type": "unknown", "team1": "A", "team2": "B",
               "team1_score": "6", "team2_score": "13", "details": {"maps": [
                   {"map_name": "Nuke", "score": "6 - 13"}]}}
        row = normalize_legacy_match("https://www.hltv.org/matches/2394882/example", raw)
        self.assertIsNone(row["best_of"])
        self.assertIn("best_of_unknown", row["issues"])
        self.assertEqual(row["winner"], "team2")

    def test_legacy_import_repeats_without_duplicates_and_flags_score_conflicts(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        url = "https://www.hltv.org/matches/123/example"
        raw = {"date": "2026-06-01", "type": "BO3", "team1": "A", "team2": "B",
               "team1_score": "2", "team2_score": "0", "details": {"maps": [
                   {"map_name": "Nuke", "score": "4 - 13"}],
                   "team1_lineup": [{"id": "100", "nick": "alice"}]}}
        (legacy / "match_details_lite.json").write_text(json.dumps({url: raw}), encoding="utf-8")
        with (legacy / "player_stats.csv").open("w", encoding="utf-8", newline="") as handle:
            row = {"match_url": url, "player_id": "alice", "team": "A", "map_name": "All maps", "side": "Both",
                   "kills": "20", "deaths": "12", "adr": "80", "kast": "70", "rating": "1.2", "plus_minus": "-3.19"}
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        with Store(self.root) as store:
            for _ in range(2):
                import_legacy(store, legacy, "2026-01-01", "2026-10-20")
            match = store.get("matches", "hltv:123")
            player = next(store.rows("player_stats"))
            self.assertEqual(store.summary()["matches"]["count"], 1)
            self.assertEqual(store.summary()["player_stats"]["count"], 1)
            self.assertIn("reported_series_score_differs_from_played_maps", match["issues"])
            self.assertEqual(player["player_id"], "hltv:100")
            self.assertEqual(player["source_metrics"]["plus_minus"], "-3.19")
            self.assertEqual(player["hltv_rating"], 1.2)

    def test_export_omits_results_that_finished_after_cutoff(self):
        with Store(self.root) as store:
            row = normalize_match(match_fixture())
            row["completed_at_utc"] = "2026-10-19T01:00:00+00:00"
            store.put("matches", row["match_id"], row["date"], row)
            for stat in normalize_stats(row, stats_fixture()):
                store.put("player_stats", stat["player_id"], stat["date"], stat)
            exported = export_snapshot(store, "2026-10-18", "2026-10-18")
        self.assertEqual(exported["files"]["matches.jsonl"]["rows"], 0)
        self.assertEqual(exported["files"]["player_stats.jsonl"]["rows"], 0)
        for name, info in exported["files"].items():
            self.assertEqual(digest((Path(exported["snapshot"]) / name).read_bytes()), info["sha256"])

    def test_cache_verifies_checksum_and_offline_miss_is_explicit(self):
        http = HttpCache(self.root, offline=True)
        url = "https://example.com/matches"
        with self.assertRaisesRegex(FetchError, "No cached response"):
            http.get(url)
        folder = self.root / "raw/http" / digest(url.encode())
        folder.mkdir(parents=True)
        (folder / "test.body").write_bytes(b"changed")
        (folder / "latest.json").write_text(json.dumps({"body_file": "test.body", "sha256": digest(b"original")}))
        with self.assertRaisesRegex(FetchError, "checksum mismatch"):
            http.get(url)

    def test_ranking_date_and_roster_are_preserved(self):
        text = "### Standings as of 2026_10_05<br />\n| 1 | 2046 | Spirit | a, b, c, d, e | [details](x) |"
        rows = parse_valve_standings(text, "2026-10-05", "global", "https://example.com/commit/file.md")
        self.assertEqual(rows[0]["roster"], ["a", "b", "c", "d", "e"])
        with self.assertRaisesRegex(ValueError, "date"):
            parse_valve_standings(text, "2026-09-07", "global", "https://example.com/commit/file.md")


if __name__ == "__main__":
    unittest.main()
