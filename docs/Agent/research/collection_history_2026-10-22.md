# HLTV collection and migration audit, October 20–22, 2026

Coverage counts refer to the audited UTC windows. Current source choices and commands are in the collection plan and runbook. [Collection plan](../data/collection-plan.md) · [Runbook](../data/runbook.md)

## Coverage

- June 10–October 20. The monthly manifests, refreshed result pages and boundary checks accounted for 4,245 candidate IDs, yielding 4,226 in-window matches, 18 starts outside the window and one drawn exhibition excluded from competitive data. There were 4,167 complete player tables. The other 59 had zero played maps and Default awards. Local evidence lives in `data/reports/runs/20261020T172359Z-hltv-monthly-backfill/`, including `completion-audit.json`.
- January–June rebuild. Fresh monthly scans and UTC date overlaps resolved 6,100 distinct candidate IDs to 6,083 in-window starts and 17 outside H1. The set includes 381 already collected June 10–30 matches. There were 5,969 complete player tables, 108 zero-played-map Default records, and six played-map source gaps. All 985 January 1–June 9 legacy observations were replaced and archived. The per-month manifests and source-gap proofs live in `data/reports/runs/20261021T075707Z-hltv-2026-h1-rebuild/`.
- The audit covers the selected candidates and checked boundaries. Later provider corrections and results unfinished at observation time can affect coverage. Keep the UTC start date and result-list date distinct.

## Corrections retained in collection

- The legacy audit found missing stable IDs, unknown Rating versions and 489 series/map score conflicts flagged as reversals. Live samples included both reversed and correctly stored results. Recollection restored source facts and separate Default awards. In a 100-row sample matched to current HLTV, K-D, ADR and KAST agreed while 80 Rating values differed. The archives preserve the prior values and their provenance. Local evidence is in `data/reports/runs/20261021-upper-half-audit/`.
- Economic-adjusted KAST can exceed 100. The adapter permits verified economic values while keeping traditional KAST bounded. Named optional slots and unplayed TBA/Default placeholders are handled separately from scored maps.
- Kept played-map results and marked missing stats for the six verified gaps. Two fuller legacy observations remain accessible in `legacy_replacements.jsonl` with their original Rating semantics. [Known gaps](../data/collection-plan.md#limits-that-affect-modeling)
- Browser navigation failures exposed a CDP receive timeout shorter than the protocol loop and legacy refreshes that ignored cached job responses. The collector aligned timeouts, improved diagnostics and reuses cached responses on retries. Direct collection and bounded replay are recorded in the H1 job reports.

## Migration and recovery

The October 22 cleanup removed 2025 from the working set. It verified all 335,147 retained 2026 database rows and preserved the 2025 original inputs and local pre-H1 SQLite backup at `data/snapshots/20261021T075707Z-before-2026-h1-rebuild/`. The backup and migration evidence also verify all 985 legacy match archives and 31,552 archived player rows.

The migration publishes deterministic source/month JSONL in `data/datasets/`. Analysts read JSONL directly, and collectors can restore their work database from it. The pre-migration and migration audits retain row counts, integrity checks and backup provenance. [Collection audit](../../../data/reports/collection_audit_2026-10-22.json) · [JSONL migration audit](../../../data/reports/jsonl_migration_2026-10-22.json)
