# Shared data contract

Read the [runbook](runbook.md) for commands and the [collection plan](collection-plan.md) for source choices. This document describes the data currently used for prediction.

## Storage

All paths below are relative to the repository's `data/` directory.

| Path | Purpose |
|---|---|
| `pipeline/` | Python collection, normalization, validation, export, and tests |
| `datasets/<family>/<YYYY-MM>/` | Tracked canonical JSONL record partitions |
| `datasets/manifest.json` | Deterministic version, partition counts, sizes, date ranges, and checksums |
| `datasets/hltv/<YYYY-MM>/legacy_replacements.jsonl` | Archived HLTV records and player rows replaced by current source data |
| `raw/` | Local content-hashed HTTP responses, request metadata, browser profile, and diagnostics |
| `processed/history.sqlite3` | Local SQLite collector/work database for matches, player statistics, and dated rankings |
| `snapshots/<timestamp>/` | Local date-filtered stage JSONL exports with a checksum manifest |
| `reports/latest.json` | Local, Git-ignored report of the most recent collection/import/rankings/probe operation |
| `reports/runs/` | Local individual operation reports |
| `reports/collection_audit_<date>.json` | Tracked, dated collection/cleanup checkpoint and integrity evidence; no dataset payload |
| `reports/jsonl_migration_2026-10-22.json` | Tracked evidence for the canonical JSONL migration |

The canonical dataset is partitioned by source family and UTC month. `hltv` contains records whose payload source is `hltv` or `legacy_hltv`; `bo3` contains `bo3`; `valve` contains `legacy_valve` or `valve_official`. Nonempty partitions contain the applicable `matches.jsonl`, `player_stats.jsonl`, and/or `rankings.jsonl`; a single `datasets/manifest.json` describes all partitions. The payloads retain their existing source, provenance, rating, unknown-value, and series/map-scope fields; partitioning does not merge cross-source identities.

JSONL records have a fixed deterministic order, UTF-8 encoding, LF line endings, and reject non-finite numbers. The manifest records checksums, row counts, format and schema versions without a volatile generation timestamp; adapter versions remain in their original payloads. `.gitattributes` preserves LF on checkout. The `hltv` partition also contains `legacy_replacements.jsonl`, which preserves all 985 legacy replacement archives. Each line wraps `date`, `match_id`, `path`, `sha256`, and `content`; `content` is the exact UTF-8 JSON text of the archived object. This sidecar is archival provenance, not part of the main player training rows; readers can decode its `content` with `json.loads`.

`data/datasets/` is the tracked canonical record set. SQLite remains a local collector work database; analysis can read JSONL directly without building SQLite. The local pre-H1 backup is rollback material, not canonical data. `raw/`, `processed/`, `snapshots/`, and operational reports are ignored; canonical datasets and stable audit reports are tracked. Git restoration does not require the old raw HTTP cache, which remains a bounded optional replay set. Existing Cologne inputs stay in `2026_cologne/stage3/data/`; import reads those files without moving or modifying them. Event configuration refers to the shared data root, not a copied event dataset.

The checked-in [October 22 collection audit](../../../data/reports/collection_audit_2026-10-22.json) is a pre-migration cleanup checkpoint; its storage-format and clone-restoration statements describe that point in time. The [JSONL migration audit](../../../data/reports/jsonl_migration_2026-10-22.json) records the current migration result.

Bulk HTTP bodies are disposable after normalization and validation. Retain a bounded replay set covering parser regressions, verified source gaps, format samples, and discovery/source-comparison evidence. A provenance hash remains an observation identifier when its body has been pruned; it does not guarantee offline replay or byte-identical redownload. Online collection can refill absent cache entries. The two October 20 sample exports were retired during cleanup; a retained manifest is a historical receipt, not an available stage dataset. No Singapore stage has selected either export.

## Provenance and identities

- `schema_version=1` describes normalized semantics; `adapter_version` identifies the parser. Preserve source URL, fetch time, SHA-256, and response metadata. Online records have `provenance` references.
- Match, team, and player IDs are source-specific (`hltv:`, `bo3:`, or the documented BO3 Steam-profile fallback). Missing legacy identities remain unknown.
- Stable IDs deduplicate repeated collection within a source. The same real match from two sites can still be two records. No automatic cross-source identity resolution is implemented; select a source or establish verified mappings before training.
- Determine historical teams from match statistics/lineups, not a player's current team profile. Preserve per-map lineups to expose stand-ins.
- A match and its statistics commit together. Failed refreshes or empty upstream statistics must not replace an existing complete record with empty data.

## Fields used in prediction

- `series_score` counts maps won; `maps[].team1_rounds/team2_rounds` count rounds on a map. A series winner is not inferred from total rounds across maps.
- HLTV Default maps have `default_map=true`, `played=false`, unknown rounds, and separate `awarded_winner` / `source_default_score`. Unknown BoX stays `best_of=null`. Conflicts and placeholder scores are recorded in `issues`, not silently repaired.
- Player rows use `scope=series/map` and `side=Both/CT/T` as actually collected. Do not treat a series row as another map. Current production HLTV collection covers `Both` only.
- A played map can have a score but no source player table or mapstats link. Preserve `stats_missing` and `collection_complete=false`; retain the available maps without imputing the missing players. A series `All maps` table does not prove coverage of every played map when one table is missing (observed `hltv:2390404`).
- Preserve unknown values as `null`/`unknown`, never zero. KAST is normalized to 0–100 exactly once; BO3's original fraction is 0–1.
- `bo3_rating` and `hltv_rating` remain separate scales. Unspecified Rating versions remain unspecified. New HLTV records read the table's Rating label, but the precise subrevision is unknown; legacy records are not relabeled 3.0.
- New HLTV K-D/ADR/KAST use traditional columns. Economic adjustments remain in `source_metrics.eco_*`; Swing is `round_swing_pct`. BO3 additional raw statistics remain in `source_metrics`. Similar column names do not establish equivalent definitions across sites.
- HLTV adapter v2 preserves finite `source_metrics.eco_kast` values above 100 as reported (observed examples: 104.7%, 101.2%, 102.8%, 103.5%). These are economic-adjusted source values, not bounded probabilities; do not clamp, rescale, or substitute them for traditional KAST. Traditional `kast` still requires 0–100. The old shared percentage validator incorrectly rejected whole matches for these adjusted values; cached replay repairs the rejected imports without new requests.
- Adapter v3 also accepts `TBA` map placeholders with no result/participant/statistics blocks, observed on three January forfeits, and named slots explicitly marked `.optional` with no result blocks (observed Dust2/Ancient on `hltv:2393546`). Preserve their name, unplayed state and unknown rounds. A missing participant block on a scored map still fails validation, even with optional markup. These placeholders do not create played maps or complete player tables; archived legacy Default awards can be replaced while remaining explicitly incomplete for training purposes.
- `game`, source `game_version`, date, source map name, and `map_revision` support compatibility filtering. A source's game-version code is not automatically an exact game patch. Unknown patches and map revisions remain unknown. Collection does not discard old maps based on today's pool.
- Keep field meanings explicit and update affected readers when they change. Decide on a migration only when an actual change needs it. Existing `schema_version` metadata does not create a directory hierarchy or a requirement to maintain multiple formats. Parser fixes should replay available cached samples.

## Time, readers, and snapshots

- `date` is the UTC start date when the timestamp is known. Legacy date-only records do not gain invented time precision. Match time and fetch time are distinct.
- `--since` and `--until` include both dates. Exports exclude matches known to finish after the cutoff. Missing end times are not inferred.
- `export-data` writes all committed SQLite records to the canonical partitions in deterministic order; it does not apply a stage date cutoff. The existing `export` command creates a date-filtered stage snapshot from canonical data when available, with its own frozen manifest. These exports are not historical availability replays: fetch times may be later, and a provider may have recalculated old ratings using later information.
- `matches.jsonl` contains matches, maps, and actual lineups; `player_stats.jsonl` contains series/map player rows; `rankings.jsonl` contains ranking entries. The dataset manifest records format/schema versions, counts, and SHA-256 for each file.
- `Dataset` in `data.pipeline.dataset` reads canonical JSONL without creating SQLite. `rows(kind, since='0001-01-01', until='9999-12-31', source=None)` returns payload dictionaries; `source` filters by family. Date bounds are inclusive, and rows completed after `until` are excluded. `summary()` reports dataset counts and `verify()` exhaustively checks hashes, schema, identity, date, source, parent, and archive consistency.
- Iteration is deterministic by partition filename, then date and record identity within each file; multiple source families are not globally interleaved by date. Sort explicitly for chronological modeling. Call `verify()` to check all partitions, including data outside a reader's selected dates.
- Stage predictions reference fixed manifests. Later collection does not update an existing snapshot. The event tag labels the snapshot's intended use; it does not infer participants or crop the dataset to current rosters.

## Source-specific boundaries

- HLTV's `collection_scope=match_page_scoreboards` means the match page's series and played-map `Both` tables. Complete within that scope does not mean advanced CT/T or round-level data was collected.
- HLTV imports and direct collection share `hltv:<match ID>`. Direct collection preserves legacy-imported records by default; refresh updates records owned by the direct adapter. Use an isolated `--data-dir` for comparisons rather than silently replacing legacy data.
- An explicitly authorized rebuild may use `--replace-legacy`. Before each replacement, the collector saves the old match and all its player rows as a content-addressed JSON archive. The new match's `legacy_archive` stores its relative path, SHA-256 and player-row count, retained across subsequent direct refreshes. By default, if nonempty legacy player statistics exist, incomplete new tables reject the replacement. Match and player-row replacement is atomic; an archive can remain after a rolled-back save. A verified whole-database backup is an additional operational prerequisite for a bulk rebuild. Cologne input files remain unchanged.
- If a fresh bounded check confirms missing source tables, `--allow-partial-legacy hltv:<ID>` can explicitly permit that ID's partial replacement alongside `--replace-legacy`. This exception is per ID, never a global relaxation. Archive all older statistics before replacement, set `legacy_archive.replacement_incomplete`, and keep the new record's missing scopes/false completeness. The archive retains older full maps for separate use with their original Rating semantics; do not silently blend them into current tables. This exception cannot downgrade an already complete direct-HLTV record. Record source hashes and verification evidence in the job's known-gap registry.
- BO3 may have scores before a demo is parsed; missing player data remains missing and is reported. Optional `--rounds` retains raw game/round responses, not a fully standardized event stream.
- Valve rankings preserve dated lineups, original points, and pinned Git commits. VRS points are not Elo ratings.

The [HLTV experiment](../research/hltv_collection_2026-10-20.md) records live samples and source discrepancies; the [rating comparison](../research/ratings_comparison_2026-10-20.md) records definitions and revision evidence.
