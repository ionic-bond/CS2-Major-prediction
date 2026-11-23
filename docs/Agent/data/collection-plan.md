# Data collection plan

The counts below describe the data frozen for Singapore Stage 1. Refresh coverage when preparing another prediction or investigating a verified source gap. [Stage 1 inputs and settings](../../../2026_singapore/stage1/model.md#冻结输入)

## Current dataset

Canonical JSONL lives in `data/datasets/`, grouped by source family and UTC month. Analysis reads it directly. `data/processed/history.sqlite3` is the local collector work database; raw HTTP cache, run reports, and stage snapshots are also local.

| Records | HLTV | BO3 sample | Valve rankings |
|---|---:|---:|---:|
| Matches | 10,849 | 12 | — |
| Player statistics, series and map | 350,839 | 190 | — |
| Dated ranking entries | — | — | 5,544 |

The Stage 1 manifest covers HLTV match starts from January 3 through November 23 and Valve rankings from January 5 through November 2, 2026. Training used 24,388 scored maps. The H1 rebuild replaced the older HLTV imports, with 985 original match/player observations and their Rating semantics retained in `legacy_replacements.jsonl` archives. The original Cologne inputs and local rollback material retain the 2025 records.

January–June used fresh monthly result scans. June 10–October 20 used frozen candidates plus refreshed recent pages and date boundaries. The audit accounts for those candidates. [Collection coverage](../research/collection_history_2026-10-22.md)

Before the final Singapore run, the 2026-11-01 through 2026-11-23 results pages were scanned again. Ten cached November 2 match pages were collected explicitly, including the five Beijing matches that had fallen outside the earlier boundary scan, then the full recent window was reconciled. The remaining 13 incomplete rows are unplayed or default-map records and do not enter map training.

## Source choices

| Modeling need | Source and scope |
|---|---|
| Team strength, maps and BP | HLTV match pages: dated opponents, series results, map scores, vetoes, actual lineups and event context |
| Player performance and stability | The same pages' series/per-map `Both` tables: K-D, ADR, KAST, Rating and source metrics |
| External ranking baseline | Dated Valve VRS entries with source commits and lineups |
| A specific advanced feature or fallback | BO3 or additional HLTV pages, only when needed for an experiment |

Polymarket binary match prices use `data/pipeline/polymarket.py`. The collector resolves Gamma metadata, fetches both CLOB outcome tokens and preserves paired time-bucket snapshots. The frozen Stage 1 input has 2,560 hourly pairs across eight opening markets, ending at `2026-11-23T16:00:00Z`. Historical order-book depth remains an unknown field in price-history observations. [Frozen market history](../../../2026_singapore/stage1/market_history.json)

One HLTV match page supplies the first two layers. A second complete BO3 crawl is not part of the current plan. The BO3 sample and its extra fields are available for comparisons; cross-source matches and rating scales must be resolved before combining data. CT/T and demo/round parsers are not implemented and are not prerequisites for the baseline.

## Limits that affect modeling

- The October 22 audit found 9,762 HLTV matches with complete player tables. Of the 166 incomplete records at that checkpoint, 160 had no played maps and six had verified missing map statistics. Exclude Default/forfeit map awards from played-map training.
- Verified gaps: `hltv:2390404` (Nuke), `2390814` (Overpass), `2390818` (Nuke), `2391632` (Mirage), `2391887` (Ancient), and `2392111` (Inferno). The two older full maps for `2390814` and `2390818` remain in their archives; using them requires preserving their distinct observation/Rating context.
- Current historical pages may contain recalculated Rating values. A date-filtered export does not reconstruct exactly what was knowable at the past cutoff.
- Provider IDs are source-specific. The 12 BO3 sample matches may overlap HLTV; no automatic cross-source merge is performed.

See the [data contract](contract.md) for field meanings and the [runbook](runbook.md) for collection, safe pause, verification, and export commands.

## Forecast inputs and evidence

Preserve the match and availability timestamps, LAN and event context, and actual lineups used by the three model states. Freeze the exact dataset manifest, stage configuration, and market snapshots used for each forecast. [Modeling guide](../modeling.md)

Stage 1 used the 2026 canonical data window. The historical replay covers Cologne 2026. [Stage 1 findings](../research/singapore_stage1_findings_2026-11-24.md)

The [collection audit](../../../data/reports/collection_audit_2026-10-22.json) records the pre-JSONL cleanup checkpoint. The [JSONL migration audit](../../../data/reports/jsonl_migration_2026-10-22.json) records lossless export/restoration. Both describe their audited state; the current paths are listed above. Detailed completed work is in the [collection history](../research/collection_history_2026-10-22.md); consult it for a relevant gap, parser issue, or coverage question.
