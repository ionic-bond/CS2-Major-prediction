# Collection plan

Current design decisions: 2026-10-21. This is a plan and readiness record; it does not start a collection job. Follow the [runbook](runbook.md) for execution and the [contract](contract.md) for field meanings.

## Source selection

| Modeling layer | Default source | Required observations |
|---|---|---|
| Team baseline | HLTV match pages | Opponents, date, event, format, series result, map scores, vetoes, and LAN/online context when available |
| Player map performance | The same HLTV match pages | Historical lineup and stable IDs, per-map K-D, ADR, KAST, Rating, rounds, and source-specific supplementary columns |
| Advanced features | Select fields already present, then fetch additional pages only as needed | HLTV CT/T mapstats, BO3 player aggregates and game/round summaries, or selectively parsed demos |

Reuse results and player records from one HLTV match-page request. There is currently no demonstrated first-layer information requirement that makes a duplicate BO3 crawl mandatory. BO3's structured batch list can be useful if a future team-only historical window is much larger than the player-data window; this is an efficiency option, not evidence of superior prediction data.

BO3 remains an optional supplement, fallback candidate, and source for controlled comparisons. Its existing player-stat response already includes fields such as `first_kills`, `first_death`, `trade_kills`, `trade_death`, `clutches`, `multikills`, and `utility_value`. These are retained in `source_metrics` without an extra request when that response is collected. Their definitions and predictive value still need validation.

The layers describe modeling priorities, not separate passes that throw away other fields. Retain useful fields delivered in an existing response. Do not concatenate cross-site Rating/ADR/KAST observations into one player time series without resolving semantics and identities.

Valve's dated VRS snapshots are a separate external ranking reference, not a second source required to reproduce match results. Their use in the model remains subject to evaluation.

## Readiness

| Component | Current state |
|---|---|
| HLTV result discovery and match pages | Implemented and tested on live bounded samples, including BO1/BO3/BO5 and Default map awards |
| HLTV series and per-map `Both` player tables | Implemented, source-ID based, cached, replayable, and quality-checked |
| HLTV CT/T advanced mapstats | Real page retrieved and cached; production parser/automatic collection not implemented |
| BO3 result/detail/player-stat flow | Implemented; some matches lack parsed demo/player data |
| BO3 raw round/game responses | Optional `--rounds` path works; no complete normalized event stream |
| BO3 lightweight list-only backfill | Possible API strategy, not an implemented CLI mode |
| Valve latest/historical rankings | Implemented with pinned commit references |
| Demo event/tick parsing | Optional future work; no integrated demo parser or guaranteed demo availability |
| Cross-source match/player mapping | Not implemented; same real matches can exist under two sources |
| Historical backfill | Not complete; live tests and result-list scans are not a full detail/player backfill |
| Singapore stage models and registered rosters | Not finalized; no stage prediction has been published |

The [HLTV experiment](../research/hltv_collection_2026-10-20.md) records the small live sample, raw response evidence, source differences, and browser constraints. The [rating research](../research/ratings_comparison_2026-10-20.md) does not establish a predictive winner between HLTV and BO3.

## Before a large collection run

Choose the historical window and meaningful competition scope based on the modeling task. Retain enough opponents to estimate strength rather than restricting every match to a provisional Major roster. Keep missing-data and forfeit flags so the model can select appropriate training rows later.

Use a bounded live sample and cached replay to check current upstream structure, identities, fields, and speed. Existing timing probes are stored under `data/raw/diagnostics/`; they are dated observations, not runtime guarantees. Scale match details, extra mapstats pages, BO3 round requests, and demo parsing separately when estimating cost.

Do not select an annual window or launch multiple full-source crawls just to fill directories. Preserve the shared raw cache and versioned schema across Majors; freeze a distinct manifest for each stage prediction.
