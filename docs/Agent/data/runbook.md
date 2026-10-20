# Data pipeline runbook

Run commands from the repository root with Python 3.10+. Shared code is `data/pipeline/`; the entry point is `python -m data.pipeline`. The code move keeps the existing `data/raw/`, database, reports, and snapshots in place. The old root-level module name is no longer an entry point.

The [collection plan](collection-plan.md) owns source selection and readiness. The [contract](contract.md) owns normalized semantics. Examples below are bounded operations, not a request to start every collection job.

## Setup and offline verification

BO3, Valve, and legacy ingestion use the standard library. HLTV additionally needs Chrome/Edge plus `beautifulsoup4` and `websocket-client`. Use a project-local virtual environment if dependencies need installing.

```powershell
python -m pip install -r data/pipeline/requirements-hltv.txt
python -m data.pipeline --help
python -m unittest discover -s data/pipeline/tests -v
```

In a restricted Windows shell, Python 3.14's owner-only temporary-directory ACL can cause `WinError 5` in fixture setup/cleanup before assertions run. The layout migration was verified with all 25 existing tests using an in-process wrapper that gives fixture directories inherited workspace permissions (`mkdir` mode `0o777` instead of `0o700`); no assertions or production collection behavior were changed. Distinguish this environment issue from a failing parser or a redirected data root.

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

Current production scope is match-page series/map `Both` scoreboards, including traditional and economic-adjusted columns kept separately. The advanced mapstats page was fetched successfully but its CT/T tables are not yet integrated into production collection. See the [dated access experiment](../research/hltv_collection_2026-10-20.md).

## Optional sources

```powershell
# BO3 and Valve connectivity probe; this does not probe HLTV browser access.
python -m data.pipeline probe

# Bounded BO3 sample. Add --rounds only when raw round/game data is needed.
python -m data.pipeline sync --since 2026-10-19 --until 2026-10-20 --max-matches 5

# Valve: latest regional snapshots; --history requests all snapshots in the date range.
python -m data.pipeline rankings --since 2025-01-01 --until 2026-10-20

# Read existing Cologne offline inputs without changing the originals.
python -m data.pipeline import-legacy --since 2025-01-01 --until 2026-10-20
```

The default legacy directory is `2026_cologne/stage3/data/`; `--directory` can override it. An alternate data root is a global option before the subcommand, for example `python -m data.pipeline --data-dir data/processed/hltv-comparison ...`.

BO3 `sync` currently fetches match details plus player statistics. There is no implemented list-only lightweight backfill command. Do not describe an estimate for list-only requests as the runtime of the existing full-sync command.

BO3/Valve HTTP uses normal TLS verification, available environment/system proxies, a default one-second request interval, and bounded retries. No account or API key is required by the current public endpoints. API structure and data availability still need validation when changing the adapters.

## Inspect and freeze

```powershell
python -m data.pipeline status --since 2025-01-01 --until 2026-10-20
python -m data.pipeline export --since 2025-01-01 --until 2026-10-20 --event 2026_singapore
```

`status` writes an operation report; it is not a no-write filesystem command. `export` creates a new snapshot. Review actual source counts, missing player rows, conflicts, and source duplicates before using an export. Reports live in `data/reports/runs/`; `latest.json` excludes status/export so they do not replace the latest collection result.

- `bounded`: this scan hit a limit; the requested window is not yet proven complete.
- `partial`: a request failed, upstream statistics are missing, or pending records remain.
- Complete records skip repeated requests. Incomplete BO3 records whose upstream parsing state has not changed can also skip until the state changes or `--refresh` is used.
- Online errors, unknown shapes, invalid scales, and verification pages must not become successful empty data.
- Cached replay needs the same URLs/parameters as the cached requests. An offline cache miss is explicit.

There is no deployed scheduler or background collector. The existing datasets include legacy quality issues and small live integration samples; no full 2026 backfill has been completed. Stored timing/coverage probes are under `data/raw/diagnostics/bo3/` and `data/raw/diagnostics/hltv/`.
