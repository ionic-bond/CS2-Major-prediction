# Data collection plan

Current decisions: 2026-10-22. Follow the project priorities in [the Agent entry point](../README.md). Use the existing data to build and evaluate a prediction baseline; further collection should answer a concrete modeling need.

## Current dataset

Canonical JSONL lives in `data/datasets/`, grouped by source family and UTC month. Analysis reads it directly. `data/processed/history.sqlite3` is the local collector work database; raw HTTP cache, run reports, and stage snapshots are also local.

| Records | HLTV | BO3 sample | Valve rankings |
|---|---:|---:|---:|
| Matches | 9,928 | 12 | — |
| Player statistics, series and map | 320,225 | 190 | — |
| Dated ranking entries | — | — | 4,792 |

Active observations are from 2026: matches start January 3–October 20, rankings run January 5–October 5. The H1 rebuild replaced the older HLTV imports. All 985 previous match/player observations remain in separate `legacy_replacements.jsonl` archives, with their original Rating semantics. They are not mixed into current training rows. 2025 data remains only in the original Cologne inputs and local rollback material.

January–June used fresh monthly result scans. June 10–October 20 used frozen candidates plus refreshed recent pages and date boundaries. These checks account for the selected candidates; later provider corrections are possible. At this checkpoint no collection job is left running or scheduled.

## Source choices

| Modeling need | Source and scope |
|---|---|
| Team strength, maps and BP | HLTV match pages: dated opponents, series results, map scores, vetoes, actual lineups and event context |
| Player performance and stability | The same pages' series/per-map `Both` tables: K-D, ADR, KAST, Rating and source metrics |
| External ranking baseline | Dated Valve VRS entries with source commits and lineups |
| A specific advanced feature or fallback | BO3 or additional HLTV pages, only when needed for an experiment |

One HLTV match page supplies the first two layers. A second complete BO3 crawl is not part of the current plan. The BO3 sample and its extra fields are available for comparisons; cross-source matches and rating scales must be resolved before combining data. CT/T and demo/round parsers are not implemented and are not prerequisites for the baseline.

## Limits that affect modeling

- 9,762 HLTV matches have complete player tables. Of the 166 incomplete records, 160 have no played maps and six have verified missing map statistics. Exclude Default/forfeit map awards from played-map training.
- Verified gaps: `hltv:2390404` (Nuke), `2390814` (Overpass), `2390818` (Nuke), `2391632` (Mirage), `2391887` (Ancient), and `2392111` (Inferno). The two older full maps for `2390814` and `2390818` remain in their archives; using them requires preserving their distinct observation/Rating context.
- Current historical pages may contain recalculated Rating values. A date-filtered export does not reconstruct exactly what was knowable at the past cutoff.
- Provider IDs are source-specific. The 12 BO3 sample matches may overlap HLTV; no automatic cross-source merge is performed.

See the [data contract](contract.md) for field meanings and the [runbook](runbook.md) for collection, safe pause, verification, and export commands.

## Next work and evidence

Build the time-ordered team baseline described in the [modeling guide](../modeling.md), then measure whether map, roster, and player features improve held-out probabilities. Refresh recent results when preparing an actual stage prediction; freeze the data used for that prediction.

The [collection audit](../../../data/reports/collection_audit_2026-10-22.json) records the pre-JSONL cleanup checkpoint. The [JSONL migration audit](../../../data/reports/jsonl_migration_2026-10-22.json) records lossless export/restoration. Both describe their audited state; the current paths are listed above. Detailed completed work is in the [collection history](../research/collection_history_2026-10-22.md); consult it for a relevant gap, parser issue, or coverage question.
