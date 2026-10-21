"""Read and export shared JSONL; SQLite is an optional collector work file."""

from collections import Counter
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from uuid import uuid4

from .core import (DEFAULT_ROOT, SCHEMA_VERSION, Store, atomic_write, digest,
                   json_bytes, stats_key, valid_date)


KINDS = ("matches", "player_stats", "rankings")
ARCHIVES = "legacy_replacements"
SOURCE_FAMILIES = {"hltv": "hltv", "legacy_hltv": "hltv", "bo3": "bo3",
                   "legacy_valve": "valve", "valve_official": "valve"}
FILE_PATTERN = re.compile(r"(hltv|bo3|valve)/(\d{4}-(?:0[1-9]|1[0-2]))/"
                          r"(matches|player_stats|rankings|legacy_replacements)\.jsonl")
ARCHIVE_PATTERN = re.compile(r"raw/legacy-replacements/(\d+)/([0-9a-f]{64})\.json")


def dataset_directory(root):
    return Path(root) / "datasets"


def database_path(root):
    return Path(root) / "processed" / "history.sqlite3"


def _state_path(root):
    return database_path(root).with_name("dataset-state.json")


def _line(row):
    return (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _reject_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


def _record_key(kind, row):
    if kind == "matches":
        return row["match_id"]
    if kind == "player_stats":
        return stats_key(row)
    if kind == "rankings":
        return json.dumps([row["date"], row["region"], row["rank"]])
    if kind == ARCHIVES:
        return row["path"]
    raise ValueError("Unknown record kind: " + str(kind))


def _family(kind, row):
    if kind == ARCHIVES:
        return "hltv"
    try:
        return SOURCE_FAMILIES[row["source"]]
    except KeyError as error:
        raise ValueError("Unsupported source: " + str(row.get("source"))) from error


def _archive_body(row):
    match = ARCHIVE_PATTERN.fullmatch(row["path"])
    if not match or match[2] != row["sha256"] or row["match_id"] != "hltv:" + match[1]:
        raise ValueError("Invalid legacy archive reference: " + str(row.get("path")))
    body = row["content"].encode("utf-8")
    if digest(body) != row["sha256"]:
        raise ValueError("Legacy archive checksum mismatch: " + row["path"])
    archive = json.loads(body)
    if (archive["schema_version"] != SCHEMA_VERSION or
            archive["match"]["match_id"] != row["match_id"] or
            archive["match"]["date"] != row["date"]):
        raise ValueError("Legacy archive identity/date mismatch: " + row["path"])
    return body


class Dataset:
    """Read canonical JSONL directly, without creating a database or using network."""

    def __init__(self, root=DEFAULT_ROOT, *, directory=None):
        self.root = Path(root)
        self.directory = Path(directory) if directory is not None else dataset_directory(root)
        manifest_body = (self.directory / "manifest.json").read_bytes()
        self.manifest_sha256 = digest(manifest_body)
        self.manifest = json.loads(manifest_body)
        if (self.manifest.get("format") != "cs2-jsonl" or
                self.manifest.get("format_version") != 1 or
                self.manifest.get("schema_version") != SCHEMA_VERSION):
            raise ValueError("Unsupported JSONL format/schema version")
        self._verified = {}
        for name, info in self.manifest["files"].items():
            match = FILE_PATTERN.fullmatch(name)
            if not match or (info["source"], info["month"], info["kind"]) != match.groups():
                raise ValueError("Invalid dataset partition: " + name)
            valid_date(info["month"] + "-01")
            path = self.directory / name
            if not path.resolve().is_relative_to(self.directory.resolve()):
                raise ValueError("Dataset partition outside data directory: " + name)

    def _file_rows(self, name, info):
        path = self.directory / name
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if self._verified.get(name) != signature:
            actual = _file_digest(path)
            if stat.st_size != info["bytes"] or actual != info["sha256"]:
                raise ValueError("Dataset checksum mismatch: " + name)
            self._verified[name] = signature
        count = 0
        previous = None
        first = last = None
        with path.open("rb") as handle:
            for line in handle:
                if not line.endswith(b"\n") or line.endswith(b"\r\n"):
                    raise ValueError("Dataset requires UTF-8 JSONL with LF: " + name)
                row = json.loads(line, parse_constant=_reject_constant)
                day = row["date"]
                if (valid_date(day) != day or day[:7] != info["month"] or
                        _family(info["kind"], row) != info["source"]):
                    raise ValueError("Record source/date disagrees with partition: " + name)
                if info["kind"] == ARCHIVES:
                    _archive_body(row)
                elif row.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError("Unsupported record schema: " + name)
                key = (day, _record_key(info["kind"], row))
                if previous is not None and key <= previous:
                    raise ValueError("Duplicate or unsorted records: " + name)
                previous = key
                first, last = first or day, day
                count += 1
                yield row
        if (count, first, last) != (info["rows"], info["first_date"], info["last_date"]):
            raise ValueError("Partition row count/date range mismatch: " + name)

    def rows(self, kind, since="0001-01-01", until="9999-12-31", source=None):
        """Source is a family (hltv/bo3/valve); original row.source is unchanged."""
        if kind not in (*KINDS, ARCHIVES):
            raise ValueError("Unknown record kind: " + str(kind))
        if valid_date(since) > valid_date(until):
            raise ValueError("since must not be after until")
        if source is not None and source not in set(SOURCE_FAMILIES.values()):
            raise ValueError("Unknown source family: " + str(source))
        for name, info in sorted(self.manifest["files"].items()):
            if (info["kind"] != kind or (source is not None and info["source"] != source) or
                    info["last_date"] < since or info["first_date"] > until):
                continue
            for row in self._file_rows(name, info):
                completed = row.get("completed_at_utc")
                if since <= row["date"] <= until and (not completed or completed[:10] <= until):
                    yield row

    def summary(self):
        result = {}
        for kind in KINDS:
            files = [x for x in self.manifest["files"].values() if x["kind"] == kind]
            if files:
                result[kind] = {"count": sum(x["rows"] for x in files),
                                "earliest": min(x["first_date"] for x in files),
                                "latest": max(x["last_date"] for x in files)}
        return result

    def verify(self):
        expected = set(self.manifest["files"])
        actual = {p.relative_to(self.directory).as_posix() for p in self.directory.rglob("*.jsonl")}
        if actual != expected:
            raise ValueError("Dataset has missing or unlisted JSONL files")
        keys = {kind: set() for kind in (*KINDS, ARCHIVES)}
        matches, parents, references, archives = {}, [], {}, {}
        counts = Counter()
        for name, info in sorted(self.manifest["files"].items()):
            kind = info["kind"]
            for row in self._file_rows(name, info):
                key = _record_key(kind, row)
                if key in keys[kind]:
                    raise ValueError("Duplicate dataset record: " + key)
                keys[kind].add(key)
                counts[kind] += 1
                if kind == "matches":
                    matches[key] = (row["date"], row["source"])
                    if row.get("legacy_archive"):
                        ref = row["legacy_archive"]
                        path = ARCHIVE_PATTERN.fullmatch(ref["path"])
                        if not path or key != "hltv:" + path[1] or ref["sha256"] != path[2]:
                            raise ValueError("Invalid match archive reference: " + key)
                        references[ref["path"]] = (ref["sha256"], key, row["date"])
                elif kind == "player_stats":
                    parents.append((row["match_id"], row["date"], row["source"]))
                elif kind == ARCHIVES:
                    archives[key] = (row["sha256"], row["match_id"], row["date"])
        if any(matches.get(mid) != (day, source) for mid, day, source in parents):
            raise ValueError("Player record has missing or mismatched parent match")
        if references != archives:
            raise ValueError("Legacy archive references do not match exported archives")
        if {k: counts[k] for k in KINDS} != self.manifest["record_counts"]:
            raise ValueError("Dataset record counts disagree with manifest")
        if counts[ARCHIVES] != self.manifest["archive_count"]:
            raise ValueError("Dataset archive count disagrees with manifest")
        return {"manifest_sha256": self.manifest_sha256, "files": len(expected),
                "records": {k: counts[k] for k in KINDS}, "archives": counts[ARCHIVES]}


def _save_state(root, manifest_sha256):
    atomic_write(_state_path(root), json_bytes({"manifest_sha256": manifest_sha256}))


def _check_baseline(root):
    manifest = dataset_directory(root) / "manifest.json"
    if manifest.exists():
        state_path = _state_path(root)
        state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
        if state.get("manifest_sha256") != digest(manifest.read_bytes()):
            raise ValueError("JSONL version differs from the SQLite baseline. Run restore-db --replace "
                             "to back up the existing work database and restore this data version.")


def _staging(root, label):
    path = Path(root) / "processed" / ("." + label + "-" + uuid4().hex)
    path.mkdir(parents=True)
    return path


def _remove_staging(path, root):
    if not path.resolve().is_relative_to((Path(root) / "processed").resolve()):
        raise ValueError("Refusing staging cleanup outside processed data")
    shutil.rmtree(path)


def export_dataset(store):
    """Publish all committed records, independently of stage/date-cutoff exports."""
    root = store.root
    _check_baseline(root)
    if store.db.in_transaction:
        raise ValueError("Commit the work database before exporting JSONL")
    stage = _staging(root, "jsonl-export")
    destination = dataset_directory(root)
    old_manifest = destination / "manifest.json"
    files, counts, references = {}, Counter(), {}
    try:
        old_files = Dataset(root).manifest["files"] if old_manifest.exists() else {}
        with ExitStack() as stack:
            handles = {}

            def append(kind, row):
                name = f"{_family(kind, row)}/{row['date'][:7]}/{kind}.jsonl"
                if not FILE_PATTERN.fullmatch(name):
                    raise ValueError("Invalid partition: " + name)
                if name not in handles:
                    path = stage / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handles[name] = stack.enter_context(path.open("wb"))
                    files[name] = {"kind": kind, "source": _family(kind, row), "month": row["date"][:7],
                                   "rows": 0, "bytes": 0, "first_date": row["date"], "last_date": row["date"]}
                body = _line(row)
                handles[name].write(body)
                info = files[name]
                info["rows"] += 1
                info["bytes"] += len(body)
                info["last_date"] = row["date"]
                counts[kind] += 1

            for kind, rid, day, parent, payload in store.db.execute(
                    "SELECT kind,record_id,record_date,parent_id,payload FROM records ORDER BY kind,record_date,record_id"):
                row = json.loads(payload)
                if (kind not in KINDS or _record_key(kind, row) != rid or
                        row["date"] != day or row.get("match_id") != parent):
                    raise ValueError("Work database record identity mismatch: " + rid)
                append(kind, row)
                if kind == "matches" and row.get("legacy_archive"):
                    reference = row["legacy_archive"]
                    references[reference["path"]] = (day, rid, reference)
            for path, (day, mid, ref) in sorted(references.items(), key=lambda x: (x[1][0], x[0])):
                if not ARCHIVE_PATTERN.fullmatch(path):
                    raise ValueError("Invalid legacy archive path: " + path)
                content = (root / path).read_bytes().decode("utf-8")
                row = {"date": day, "match_id": mid, "path": path, "sha256": ref["sha256"], "content": content}
                _archive_body(row)
                append(ARCHIVES, row)
        for name, info in files.items():
            info["sha256"] = _file_digest(stage / name)
            if info["bytes"] >= 100 * 1024 * 1024:
                raise ValueError("Partition exceeds ordinary GitHub file limit: " + name)
        manifest = {"format": "cs2-jsonl", "format_version": 1, "schema_version": SCHEMA_VERSION,
                    "files": dict(sorted(files.items())), "record_counts": {k: counts[k] for k in KINDS},
                    "archive_count": counts[ARCHIVES]}
        manifest_body = json_bytes(manifest)
        atomic_write(stage / "manifest.json", manifest_body)
        Dataset(root, directory=stage).verify()
        # Publish the manifest last. Readers reject mixed/unfinished versions by checksum.
        destination.mkdir(parents=True, exist_ok=True)
        changed = 0
        for name, info in sorted(files.items()):
            target = destination / name
            if target.exists():
                if _file_digest(target) == info["sha256"]:
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            (stage / name).replace(target)
            changed += 1
        for name in old_files.keys() - files.keys():
            (destination / name).unlink(missing_ok=True)
        if not old_manifest.exists() or old_manifest.read_bytes() != manifest_body:
            atomic_write(old_manifest, manifest_body)
        _save_state(root, digest(manifest_body))
        return {"manifest": str(old_manifest), "manifest_sha256": digest(manifest_body),
                "files": len(files), "changed_files": changed, "records": manifest["record_counts"],
                "archives": counts[ARCHIVES], "bytes": sum(x["bytes"] for x in files.values())}
    finally:
        _remove_staging(stage, root)


def restore_database(root=DEFAULT_ROOT, *, replace=False):
    root = Path(root)
    target = database_path(root)
    if target.exists() and not replace:
        raise ValueError("Work database already exists; --replace saves a backup before replacement")
    dataset = Dataset(root)
    verification = dataset.verify()
    stage = _staging(root, "jsonl-restore")
    backup = None
    try:
        with Store(stage) as store:
            for kind in KINDS:
                for row in dataset.rows(kind):
                    store.put(kind, _record_key(kind, row), row["date"], row)
            store.db.commit()
            if store.db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Restored SQLite failed integrity check")
        for row in dataset.rows(ARCHIVES):
            path = root / row["path"]
            body = _archive_body(row)
            if path.exists() and path.read_bytes() != body:
                raise ValueError("Existing legacy archive differs: " + row["path"])
            if not path.exists():
                atomic_write(path, body)
        if digest((dataset.directory / "manifest.json").read_bytes()) != dataset.manifest_sha256:
            raise ValueError("JSONL version changed during restore; retry")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = target.parent / "backups" / (uuid4().hex + ".sqlite3")
            backup.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(backup)) as copy:
                    original.backup(copy)
        database_path(stage).replace(target)
        _save_state(root, dataset.manifest_sha256)
        return {"database": str(target), "backup": str(backup) if backup else None,
                "verification": verification}
    finally:
        _remove_staging(stage, root)


def prepare_working_database(root):
    """Collector entry: restore a missing cache; reject a cache from another Git version."""
    if (dataset_directory(root) / "manifest.json").exists():
        if not database_path(root).exists():
            restore_database(root)
        _check_baseline(root)
