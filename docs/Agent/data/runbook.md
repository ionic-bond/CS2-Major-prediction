# Data pipeline runbook

Run commands from the repository root with Python 3.10+. Shared code is `data/pipeline/`; the entry point is `python -m data.pipeline`. Tracked JSONL is in `data/datasets/`; the local collector work database is `data/processed/history.sqlite3`.

The [collection plan](collection-plan.md) owns source selection and readiness. The [contract](contract.md) owns normalized semantics. Examples below are bounded operations, not a request to start every collection job.

## Setup and offline verification

BO3, Valve, and legacy ingestion use the standard library. HLTV additionally needs Chrome/Edge plus `beautifulsoup4` and `websocket-client`. Use a project-local virtual environment if dependencies need installing.

```powershell
python -m pip install -r data/pipeline/requirements-hltv.txt
python -m data.pipeline --help
python -m unittest discover -s data/pipeline/tests -v
```

Canonical JSONL can be verified or read without creating SQLite. `verify-data` checks the JSONL partitions and manifests; `restore-db` rebuilds the local database and legacy archive files from those partitions. A normal restore refuses to replace an existing database. `--replace` first backs up the existing database locally, then replaces it. A clone or analysis machine can use the Python reader directly:

```powershell
python -m data.pipeline verify-data
python -m data.pipeline restore-db
```

```python
from data.pipeline.core import DEFAULT_ROOT
from data.pipeline.dataset import Dataset

dataset = Dataset(root=DEFAULT_ROOT)
matches = dataset.rows("matches", since="2026-01-01", until="2026-10-20", source="hltv")
```

`summary()` reports canonical counts and `verify()` performs exhaustive checks. The reader's `source` argument selects a source family. Collection, import, and rankings commands restore a missing local database automatically. Before writing, they compare its baseline fingerprint with the current canonical dataset so a database left behind after a Git update is rejected as stale; run `restore-db --replace` to refresh it. Their completion exports all committed database records to canonical JSONL, including for `partial` and `paused` outcomes. This updates workspace files only; it does not create a Git commit or fetch data by itself.

In a restricted Windows shell, Python 3.14's owner-only temporary-directory ACL can cause `WinError 5` in fixture setup/cleanup before assertions run. Existing checks have run with an in-process wrapper giving temporary directories inherited workspace permissions (`mkdir` mode `0o777` instead of `0o700`), without changing assertions. Migration test results and local restore timings are in the [migration audit](../../../data/reports/jsonl_migration_2026-10-22.json).

## Primary source: HLTV

```powershell
# Bounded discovery and match-page collection; complete records are skipped.
python -m data.pipeline sync-hltv --since 2026-10-19 --until 2026-10-20 --max-matches 5

# A specific verified sample; date bounds still apply. Repeat --match-url for more URLs.
python -m data.pipeline sync-hltv --since 2026-10-20 --until 2026-10-20 --max-matches 1 --match-url https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier

# Cached replay: no network or browser startup, but normalized records/reports can be written.
python -m data.pipeline --offline sync-hltv --since 2026-10-20 --until 2026-10-20 --max-matches 1 --refresh --match-url https://www.hltv.org/matches/2399776/metizport-vs-ex-rustec-stake-ranked-episode-6-closed-qualifier
```

Use `--until` as an explicit UTC date boundary. Refresh recent matches to incorporate delayed statistics or corrections. `--max-matches` limits attempted matches and `--max-pages` limits list scanning; hitting a bound is not a completed historical backfill.

HLTV uses the collector's own persistent browser profile under `data/raw/browser/hltv/profile/`, an ordinary hidden browser window, direct networking by default, and at least a two-second request interval. It does not import a personal browser profile or account. `--browser` selects the executable; `--browser-proxy direct/system/environment` selects proxy behavior. Windows sandbox IPC errors and upstream HTTP verification failures are distinct; use an environment allowed to launch the browser. The earlier failed headless test also changed proxy settings and does not establish that headless operation is impossible.

Commands close their browser on completion, failure, or interruption. Verification pages are explicit failures and are not successful empty results. The collector prefers actual HTTP response bodies and marks a rendered-DOM fallback in `representation`. Run collection commands sharing one data root sequentially.

### Monthly jobs and safe pause

Keep backfill commands within a single calendar month. A UTF-8 file with one canonical match URL per line can reuse a frozen discovery list; the report records its path and SHA-256. Empty lists fail explicitly. Discovery provenance belongs beside the list, including cached result-page URLs, hashes, and fetch times. Include overlapping boundary candidates and let ingestion check actual UTC starts; explicit-list completion does not prove full-window coverage.

```powershell
# Replace these example paths with the selected job's actual manifest and pause file.
python -m data.pipeline --interval 3 sync-hltv --since 2026-06-10 --until 2026-06-30 --max-matches 2000 --match-urls-file data/reports/runs/JOB/2026-06.urls.txt --stop-file data/reports/runs/JOB/pause.request

# Pause: current page/match finishes, then the browser closes and a paused report is written.
New-Item -ItemType File -Path data/reports/runs/JOB/pause.request
```

The stop file is checked before each list page and match, and at the end of the candidate list. It does not cancel an in-flight network request. Each match commits atomically. On an explicit resume request, remove that job's stop file and repeat its command; complete matches are skipped. Leave a pause file in place until the user asks to resume. `paused` is separate from successful completion or missing upstream statistics.

Legacy imports remain protected by default, including with `--refresh`. When the user has authorized rebuilding them, first save and verify a SQLite backup, then add `--replace-legacy` to the bounded monthly command. Each successful replacement archives the old match and all player rows in `raw/legacy-replacements/<hltv_id>/<sha256>.json`, records that path/hash on the new match, and replaces the match and player rows in one transaction. By default, incomplete new statistics cannot replace nonempty legacy statistics; failed saves retain the old database rows. Future direct refreshes retain the archive reference. Review `legacy_replaced`, remaining legacy IDs and archive hashes before declaring reconciliation complete. The January–June job plan records the current backup and manifests.

Reconciliation respects the normal HTTP cache unless `--refresh` is explicit. An existing legacy database row is not itself a reason to repeat a successful cached request. This matters on resume: otherwise old out-of-window boundary IDs can be fetched on every attempt before reaching the actual collection cursor. Source metadata retains the original cache observation time/hash; request an explicit refresh when an observation must be newer.

For individually verified upstream gaps, add repeated `--allow-partial-legacy hltv:<ID>` values with `--replace-legacy` and a bounded explicit URL list. Prefer offline replay of the freshly verified body so the evidence hash and stored record agree. All old rows remain in the archive; current rows remain incomplete. Review `partial_legacy_replaced` and the exact permitted IDs, and retain the verification report/hash. This does not permit a partial refresh over complete direct-source data.

When the user requests active monitoring, keep the command in a tracked tool session and wait in 30–60 second intervals. Read the database for committed progress and inspect the final report on exit, including browser cleanup. An independently launched OS process can outlive a conversation turn; its exit does not by itself wake the assistant. Do not imply that a returned final answer leaves ongoing assistant supervision in place.

For this rebuild the user subsequently requested ten-minute progress inspections/summaries. Short tool waits may be grouped into that cadence without polling the database each minute. Still handle process exit/errors and user pauses early; retain the active native session handle. This is active-turn monitoring, not a deployed scheduler.

Current production scope is match-page series/map `Both` scoreboards, including traditional and economic-adjusted columns kept separately. The advanced mapstats page was fetched successfully but its CT/T tables are not yet integrated into production collection. See the [dated access experiment](../research/hltv_collection_2026-10-20.md).

## Optional sources

```powershell
# BO3 and Valve connectivity probe; this does not probe HLTV browser access.
python -m data.pipeline probe

# Bounded BO3 sample. Add --rounds only when raw round/game data is needed.
python -m data.pipeline sync --since 2026-10-19 --until 2026-10-20 --max-matches 5

# Valve: latest regional snapshots; --history requests all snapshots in the date range.
python -m data.pipeline rankings --since 2026-01-01 --until 2026-10-20

# Read existing Cologne offline inputs without changing the originals.
python -m data.pipeline import-legacy --since 2026-01-01 --until 2026-10-20
```

The default legacy directory is `2026_cologne/stage3/data/`; `--directory` can override it. An alternate data root is a global option before the subcommand, for example `python -m data.pipeline --data-dir data/processed/hltv-comparison ...`.

BO3 `sync` currently fetches match details plus player statistics. There is no implemented list-only lightweight backfill command. Do not describe an estimate for list-only requests as the runtime of the existing full-sync command.

BO3/Valve HTTP uses normal TLS verification, available environment/system proxies, a default one-second request interval, and bounded retries. No account or API key is required by the current public endpoints. API structure and data availability still need validation when changing the adapters.

## Inspect and freeze

```powershell
python -m data.pipeline status --since 2026-01-01 --until 2026-10-20
python -m data.pipeline export --since 2026-01-01 --until 2026-10-20 --event 2026_singapore
python -m data.pipeline export-data
```

`status` and the existing `export` read canonical JSONL when available; `status` writes an operation report, and `export` creates a new dated stage snapshot with its cutoff and manifest. `export-data` requires an existing work database and refreshes canonical JSONL from all committed SQLite rows, without applying a stage date cutoff. Review actual source counts, missing player rows, conflicts, and source duplicates before using an export. Reports live in `data/reports/runs/`; only collection/import/rankings/probe commands update Git-ignored `latest.json`.

Canonical exports validate a staged version before publishing each changed file atomically and its manifest last. A hard process kill during publication can leave checksum mismatches; readers reject that mixed version. Rerun `export-data` from the same work database to finish publication. Do not run collection, publication, or `restore-db --replace` concurrently with another writer; a normal safe pause finishes export.

- `bounded`: this scan hit a limit; the requested window is not yet proven complete.
- `partial`: a request failed, upstream statistics are missing, or pending records remain.
- Complete records skip repeated requests. Incomplete BO3 records whose upstream parsing state has not changed can also skip until the state changes or `--refresh` is used.
- Online errors, unknown shapes, invalid scales, and verification pages must not become successful empty data.
- Cached replay needs the same URLs/parameters as the cached requests. Bulk HTTP bodies were pruned on October 22; a bounded replay/discovery/comparison set remains. An offline cache miss for a pruned page is expected; online mode can fetch it again.

There is no deployed scheduler. Bounded backfill job plans, process metadata, logs, and reports belong under `data/reports/runs/`; inspect them and the actual process/database before claiming a collector is running. Current HLTV jobs reconciled fresh monthly result scans for January–June and processed selected candidates through October 20, 2026. This is bounded coverage with documented source gaps and correction limits; consult the collection plan for exact windows and audits. The active database now contains only 2026 observations; 2025 legacy data remains in the original Cologne files and local rollback backup. Do not reimport it without a new need. Stored timing/coverage probes are under `data/raw/diagnostics/bo3/` and `data/raw/diagnostics/hltv/`.
