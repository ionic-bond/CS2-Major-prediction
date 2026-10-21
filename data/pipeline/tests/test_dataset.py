from contextlib import closing, redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from data.pipeline.__main__ import main
from data.pipeline.core import DEFAULT_ROOT, Store, atomic_write, digest, json_bytes, stats_key
from data.pipeline.dataset import (Dataset, database_path, dataset_directory, export_dataset,
                                   prepare_working_database, restore_database)


def match_row(mid="hltv:1", day="2026-01-03"):
    return {"schema_version": 1, "adapter_version": 3, "source": mid.split(":")[0],
            "match_id": mid, "date": day, "completed_at_utc": day + "T14:00:00+00:00",
            "team1": {"name": "甲", "players": []}, "team2": {"name": "B", "players": []},
            "maps": [{"name": "Nuke", "played": True}], "vetoes": [], "issues": [],
            "map_revision": None, "provenance": [{"sha256": "original", "fetched_at": "2026-10-20"}]}


def player_row(match):
    return {"schema_version": 1, "adapter_version": 3, "source": match["source"],
            "match_id": match["match_id"], "date": match["date"],
            "completed_at_utc": match["completed_at_utc"], "team": "team1", "player_id": None,
            "player_nick": "无名", "scope": "map", "map_name": "Nuke", "side": "Both",
            "hltv_rating": 1.2 if match["source"] == "hltv" else None,
            "bo3_rating": 7.3 if match["source"] == "bo3" else None,
            "rating_version": "3.0" if match["source"] == "hltv" else "unknown",
            "kast": None, "adr": 80.0, "source_metrics": {"eco_kast": 104.7}}


def put_match(store, match):
    store.put("matches", match["match_id"], match["date"], match)
    player = player_row(match)
    store.put("player_stats", stats_key(player), player["date"], player)


def seed(root):
    first = match_row()
    # Deliberately preserve original insertion order and whitespace in this historical file.
    body = json_bytes({"schema_version": 1, "archived_at": "2026-10-21",
                       "match": copy.deepcopy(first), "player_stats": [player_row(first)]})
    path = "raw/legacy-replacements/1/" + digest(body) + ".json"
    atomic_write(root / path, body)
    first["legacy_archive"] = {"path": path, "sha256": digest(body), "player_rows": 1}
    with Store(root) as store:
        for match in (first, match_row("hltv:2", "2026-02-03"), match_row("bo3:3", "2026-02-04")):
            put_match(store, match)
        for source, day in (("legacy_valve", "2026-01-05"), ("valve_official", "2026-02-02")):
            row = {"schema_version": 1, "adapter_version": 1, "source": source,
                   "date": day, "region": "Europe", "rank": 1, "points": 1000.5, "lineup": [None]}
            store.put("rankings", json.dumps([day, "Europe", 1]), day, row)
    return path, body


def all_records(root):
    with closing(sqlite3.connect(database_path(root))) as db:
        return [(kind, rid, day, parent, json.loads(payload)) for kind, rid, day, parent, payload in
                db.execute("SELECT kind,record_id,record_date,parent_id,payload FROM records ORDER BY kind,record_id")]


class DatasetTests(unittest.TestCase):
    def setUp(self):
        parent = DEFAULT_ROOT / "processed" / "test-temp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        self.archive_path, self.archive_body = seed(self.root)
        with Store(self.root) as store:
            self.export = export_dataset(store)

    def tearDown(self):
        self.temp.cleanup()

    def clone(self, name="clone"):
        root = self.root / name
        shutil.copytree(dataset_directory(self.root), dataset_directory(root))
        return root

    def cli(self, root, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--data-dir", str(root), "--offline", *args])
        report = json.JSONDecoder().raw_decode(output.getvalue())[0]
        return code, report

    def test_portable_read_and_restore_preserve_records_and_exact_archive_bytes(self):
        clone = self.clone()
        data = Dataset(clone)
        self.assertEqual(data.verify()["records"], {"matches": 3, "player_stats": 3, "rankings": 2})
        self.assertEqual({x["source"] for x in data.rows("rankings", source="valve")},
                         {"legacy_valve", "valve_official"})
        self.assertEqual([x["match_id"] for x in data.rows("matches", "2026-01-03", "2026-01-03")], ["hltv:1"])
        self.assertFalse(database_path(clone).exists())
        prepare_working_database(clone)
        self.assertEqual(all_records(clone), all_records(self.root))
        self.assertEqual((clone / self.archive_path).read_bytes(), self.archive_body)
        with Store(clone) as store:
            result = export_dataset(store)
        self.assertEqual(result["changed_files"], 0)
        self.assertEqual(result["manifest_sha256"], self.export["manifest_sha256"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            restore_database(clone)

    def test_repeated_export_is_identical_and_changes_only_affected_partitions(self):
        files = Dataset(self.root).manifest["files"]
        before = {name: (dataset_directory(self.root) / name).stat().st_mtime_ns for name in files}
        with Store(self.root) as store:
            self.assertEqual(export_dataset(store)["changed_files"], 0)
        self.assertEqual(before, {name: (dataset_directory(self.root) / name).stat().st_mtime_ns for name in files})
        with Store(self.root) as store:
            moved = store.get("matches", "hltv:2")
            moved.update(date="2026-03-01", completed_at_utc="2026-03-01T14:00:00+00:00")
            put_match(store, moved)
        with Store(self.root) as store:
            result = export_dataset(store)
        self.assertEqual(result["changed_files"], 2)
        self.assertFalse((dataset_directory(self.root) / "hltv/2026-02/matches.jsonl").exists())
        self.assertEqual(Dataset(self.root).verify()["records"], self.export["records"])
        for name in files:
            if not name.startswith("hltv/2026-02/"):
                self.assertEqual(before[name], (dataset_directory(self.root) / name).stat().st_mtime_ns)

    def test_stage_commands_read_canonical_without_database_and_honor_finish_cutoff(self):
        clone = self.clone()
        for command in ("verify-data", "status", "export"):
            extra = [] if command == "verify-data" else ["--since", "2026-01-01", "--until", "2026-02-28"]
            code, report = self.cli(clone, command, *extra)
            self.assertEqual(code, 0, report)
            self.assertFalse(database_path(clone).exists())
            if command != "verify-data":
                self.assertEqual(report["data_backend"], "jsonl")
        self.assertFalse((clone / "reports/latest.json").exists())
        with Store(self.root) as store:
            match = store.get("matches", "hltv:2")
            match["completed_at_utc"] = "2026-02-04T01:00:00+00:00"
            put_match(store, match)
        with Store(self.root) as store:
            export_dataset(store)
        data = Dataset(self.root)
        self.assertEqual(list(data.rows("matches", "2026-02-03", "2026-02-03")), [])
        self.assertEqual(list(data.rows("player_stats", "2026-02-03", "2026-02-03")), [])
        # The canonical export retains all committed observations, including late finishes.
        self.assertEqual(data.summary()["matches"]["count"], 3)

    def test_stale_work_database_is_blocked_and_explicit_restore_backs_it_up(self):
        clone = self.clone()
        prepare_working_database(clone)
        original = all_records(clone)
        with Store(self.root) as store:
            put_match(store, match_row("hltv:4", "2026-03-04"))
        with Store(self.root) as store:
            export_dataset(store)
        shutil.copytree(dataset_directory(self.root), dataset_directory(clone), dirs_exist_ok=True)
        with self.assertRaisesRegex(ValueError, "baseline"):
            prepare_working_database(clone)
        with Store(clone) as store, self.assertRaisesRegex(ValueError, "baseline"):
            export_dataset(store)
        with patch("data.pipeline.__main__.sync_hltv") as collector:
            code, report = self.cli(clone, "sync-hltv")
        self.assertEqual(code, 1, report)
        collector.assert_not_called()
        self.assertNotIn("dataset_export", report)
        result = restore_database(clone, replace=True)
        with closing(sqlite3.connect(result["backup"])) as db:
            backup = [(k, rid, day, parent, json.loads(payload)) for k, rid, day, parent, payload in
                      db.execute("SELECT kind,record_id,record_date,parent_id,payload FROM records ORDER BY kind,record_id")]
        self.assertEqual(backup, original)
        self.assertEqual(all_records(clone), all_records(self.root))
        prepare_working_database(clone)

    def test_failed_export_keeps_previous_canonical_version(self):
        original = (dataset_directory(self.root) / "manifest.json").read_bytes()
        with Store(self.root) as store:
            row = player_row(match_row("hltv:999", "2026-02-08"))
            store.put("player_stats", stats_key(row), row["date"], row)
        with Store(self.root) as store, self.assertRaisesRegex(ValueError, "parent"):
            export_dataset(store)
        self.assertEqual((dataset_directory(self.root) / "manifest.json").read_bytes(), original)
        self.assertEqual(Dataset(self.root).verify()["records"], self.export["records"])

    def test_verification_rejects_corruption_even_if_partition_checksum_is_resealed(self):
        for case in ("checksum", "month", "parent", "duplicate", "nonfinite", "crlf", "archive"):
            with self.subTest(case=case):
                clone = self.clone(case)
                folder = dataset_directory(clone)
                manifest = json.loads((folder / "manifest.json").read_bytes())
                kind = "legacy_replacements" if case == "archive" else "player_stats"
                name = "hltv/2026-01/" + kind + ".jsonl"
                body = (folder / name).read_bytes()
                row = json.loads(body)
                if case == "checksum":
                    body += b" "
                elif case == "duplicate":
                    body += body
                    manifest["files"][name]["rows"] += 1
                elif case == "crlf":
                    body = body.replace(b"\n", b"\r\n")
                else:
                    if case == "month":
                        row["date"] = "2026-02-01"
                    elif case == "parent":
                        row["match_id"] = "hltv:999"
                    elif case == "nonfinite":
                        row["adr"] = float("nan")
                    else:
                        row["content"] += " "
                    body = (json.dumps(row, ensure_ascii=False) + "\n").encode()
                atomic_write(folder / name, body)
                if case != "checksum":
                    manifest["files"][name].update(sha256=digest(body), bytes=len(body))
                    atomic_write(folder / "manifest.json", json_bytes(manifest))
                with self.assertRaises(ValueError):
                    Dataset(clone).verify()
                with self.assertRaises(ValueError):
                    restore_database(clone)
                self.assertFalse(database_path(clone).exists())

    def test_unknown_format_unsafe_path_and_unlisted_files_are_rejected(self):
        for case in ("version", "path", "unlisted"):
            with self.subTest(case=case):
                clone = self.clone(case)
                folder = dataset_directory(clone)
                manifest = json.loads((folder / "manifest.json").read_bytes())
                if case == "version":
                    manifest["format_version"] = 2
                elif case == "path":
                    manifest["files"]["../../outside.jsonl"] = next(iter(manifest["files"].values()))
                else:
                    atomic_write(folder / "unlisted.jsonl", b"{}\n")
                atomic_write(folder / "manifest.json", json_bytes(manifest))
                with self.assertRaises(ValueError):
                    Dataset(clone).verify()

    def test_collector_publishes_committed_records_on_pause_partial_error_and_interrupt(self):
        for outcome in ("paused", "partial", "error", "interrupt"):
            with self.subTest(outcome=outcome):
                root = self.root / outcome

                def collect(store, http, since, until, **kwargs):
                    put_match(store, match_row())
                    store.db.commit()
                    if outcome in ("error", "interrupt"):
                        put_match(store, match_row("hltv:2"))
                        if outcome == "interrupt":
                            raise KeyboardInterrupt()
                        raise ValueError("failed after first committed match")
                    return {"errors": ["gap"] if outcome == "partial" else [],
                            "stats_missing_matches": 0, "pending_unchanged": 0, "window_complete": False,
                            "stop_reason": "stop_requested" if outcome == "paused" else "max_matches"}

                with patch("data.pipeline.__main__.sync_hltv", side_effect=collect):
                    code, report = self.cli(root, "sync-hltv", "--since", "2026-01-01", "--until", "2026-01-31")
                expected = {"paused": (0, "paused"), "partial": (1, "partial"),
                            "error": (1, "failed"), "interrupt": (130, "interrupted")}[outcome]
                self.assertEqual((code, report["status"]), expected, report)
                self.assertEqual(report["dataset_export"]["records"]["matches"], 1)
                self.assertEqual(Dataset(root).verify()["records"]["player_stats"], 1)

    def test_export_command_refuses_missing_database_instead_of_publishing_empty_data(self):
        clone = self.clone()
        code, report = self.cli(clone, "export-data")
        self.assertEqual(code, 1, report)
        self.assertFalse(database_path(clone).exists())
        self.assertEqual(Dataset(clone).verify()["records"], self.export["records"])


if __name__ == "__main__":
    unittest.main()
