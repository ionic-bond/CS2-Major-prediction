# Shared data contract

Read the [runbook](runbook.md) for commands and the [collection plan](collection-plan.md) for source choices. This document describes the current v1 representation; it does not assert that the historical dataset is complete or ready for training.

## Storage

All paths below are relative to the repository's `data/` directory.

| Path | Purpose |
|---|---|
| `pipeline/` | Python collection, normalization, validation, export, and tests |
| `raw/` | Content-hashed HTTP responses, request metadata, browser profile, and diagnostics |
| `processed/v1/history.sqlite3` | Matches, player statistics, and dated ranking records |
| `snapshots/<timestamp>/` | Date-filtered JSONL exports with a checksum manifest |
| `reports/latest.json` | Most recent non-status/non-export operation |
| `reports/runs/` | Individual operation reports |

Raw data, databases, snapshots, and run reports are generated and ignored by Git. Existing Cologne inputs stay in `2026_cologne/stage3/data/`; import reads those files without moving or modifying them. Event configuration refers to the shared data root, not a copied event dataset.

## Provenance and identities

- `schema_version=1` describes normalized semantics; `adapter_version` identifies the parser. Preserve source URL, fetch time, SHA-256, and response metadata. Online records have `provenance` references.
- Match, team, and player IDs are source-specific (`hltv:`, `bo3:`, or the documented BO3 Steam-profile fallback). Missing legacy identities remain unknown.
- Stable IDs deduplicate repeated collection within a source. The same real match from two sites can still be two records. No automatic cross-source identity resolution is implemented; select a source or establish verified mappings before training.
- Determine historical teams from match statistics/lineups, not a player's current team profile. Preserve per-map lineups to expose stand-ins.
- A match and its statistics commit together. Failed refreshes or empty upstream statistics must not replace an existing complete record with empty data.

## Fields and compatibility

- `series_score` counts maps won; `maps[].team1_rounds/team2_rounds` count rounds on a map. A series winner is not inferred from total rounds across maps.
- HLTV Default maps have `default_map=true`, `played=false`, unknown rounds, and separate `awarded_winner` / `source_default_score`. Unknown BoX stays `best_of=null`. Conflicts and placeholder scores are recorded in `issues`, not silently repaired.
- Player rows use `scope=series/map` and `side=Both/CT/T` as actually collected. Do not treat a series row as another map. Current production HLTV collection covers `Both` only.
- Preserve unknown values as `null`/`unknown`, never zero. KAST is normalized to 0–100 exactly once; BO3's original fraction is 0–1.
- `bo3_rating` and `hltv_rating` remain separate scales. Unspecified Rating versions remain unspecified. New HLTV records read the table's Rating label, but the precise subrevision is unknown; legacy records are not relabeled 3.0.
- New HLTV K-D/ADR/KAST use traditional columns. Economic adjustments remain in `source_metrics.eco_*`; Swing is `round_swing_pct`. BO3 additional raw statistics remain in `source_metrics`. Similar column names do not establish equivalent definitions across sites.
- `game`, source `game_version`, date, source map name, and `map_revision` support compatibility filtering. A source's game-version code is not automatically an exact game patch. Unknown patches and map revisions remain unknown. Collection does not discard old maps based on today's pool.
- A changed field meaning requires a new schema/database version, with old snapshots still readable. Additive optional fields can remain v1. Parser fixes should replay cached responses where possible.

## Time and snapshots

- `date` is the UTC start date when the timestamp is known. Legacy date-only records do not gain invented time precision. Match time and fetch time are distinct.
- `--since` and `--until` include both dates. Exports exclude matches known to finish after the cutoff. Missing end times are not inferred.
- Current exports filter today's records by match date. They are not historical availability replays: fetch times may be later, and a provider may have recalculated old ratings using later information.
- `matches.jsonl` contains matches, maps, and actual lineups; `player_stats.jsonl` contains series/map player rows; `rankings.jsonl` contains ranking entries. The manifest records date bounds, quality, row counts, and SHA-256 for each file.
- Stage predictions reference fixed manifests. Later collection does not update an existing snapshot. The event tag labels the snapshot's intended use; it does not infer participants or crop the dataset to current rosters.

## Source-specific boundaries

- HLTV's `collection_scope=match_page_scoreboards` means the match page's series and played-map `Both` tables. Complete within that scope does not mean advanced CT/T or round-level data was collected.
- HLTV imports and direct collection share `hltv:<match ID>`. Direct collection preserves legacy-imported records by default; refresh updates records owned by the direct adapter. Use an isolated `--data-dir` for comparisons rather than silently replacing legacy data.
- BO3 may have scores before a demo is parsed; missing player data remains missing and is reported. Optional `--rounds` retains raw game/round responses, not a fully standardized event stream.
- Valve rankings preserve dated lineups, original points, and pinned Git commits. VRS points are not Elo ratings.

The [HLTV experiment](../research/hltv_collection_2026-10-20.md) records live samples and source discrepancies; the [rating comparison](../research/ratings_comparison_2026-10-20.md) records definitions and revision evidence.
