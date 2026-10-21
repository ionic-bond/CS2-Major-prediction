# Agent working documentation

This is the technical entry point. Human-facing material lives in the repository [README](../../README.md) and stage prediction pages. Do not require the user to read the documents below to understand a recommendation.

## Working priorities

This is a small personal project whose goal is better Pick'Em predictions. Prefer a clear working baseline, useful data, and measured improvements in probability estimates. Spend engineering effort where it helps that goal.

Use the simplest structure that meets today's needs. Add layers, abstractions, dependencies, or defensive machinery only for a concrete observed problem. Future version directories, general compatibility systems, and speculative extensibility can wait until needed; a small later migration is acceptable. Keep the checks that prevent losing collected data or drawing invalid statistical conclusions.

Current decisions belong in the short task documents below. Completed experiments and operational history belong in `research/` or local run reports; consult them when investigating the relevant issue.

## Task routing

| Task | Read |
|---|---|
| Decide what to collect; identify current readiness and missing work | [Collection plan](data/collection-plan.md) |
| Run ingestion, cached replay, legacy import, rankings, dataset verification/restoration, or export | [Data runbook](data/runbook.md) |
| Interpret IDs, schema, timestamps, ratings, snapshots, or compatibility | [Data contract](data/contract.md) |
| Design probability models, evaluation, or Pick'Em optimization | [Modeling guide](modeling.md) |
| Investigate the tested HLTV access path and source discrepancies | [HLTV collection experiment, 2026-10-20](research/hltv_collection_2026-10-20.md) |
| Investigate rating definitions and community evidence | [Rating comparison, 2026-10-20](research/ratings_comparison_2026-10-20.md) |

## Reading and maintenance

- Treat dated research as evidence with a stated scope, not as current operating instructions. The runbook owns current commands; the contract owns field semantics; the collection plan owns source choices.
- Update the relevant canonical document when a decision or interface changes. Add a dated report only when an experiment contributes reusable evidence; avoid duplicate progress logs.
- `data/datasets/` is the tracked canonical dataset. Operational SQLite, raw HTTP cache, stage snapshots, and per-run reports stay local and ignored; stable audit reports are tracked.
- Keep operational evidence in `data/reports/` and raw diagnostics in `data/raw/diagnostics/`. Large disposable generated data stays out of Git.
- English is fine for Agent documentation. Preserve existing research in its original language. Write a separate Chinese explanation when the user asks to examine a design.

## Historical references

The user has requested that Cologne documents remain unchanged. Read the original [Stage 1](../../2026_cologne/stage1/README.md), [Stage 2](../../2026_cologne/stage2/README.md), [Stage 3](../../2026_cologne/stage3/README.md), and [Stage 3 plan](../../2026_cologne/stage3/plan.md) when needed, without reorganizing or silently correcting them. Their quantitative output is historical; their descriptions are not evidence that the algorithms were calibrated or optimal.

For Singapore, teams and stage snapshots are still empty in [event.json](../../2026_singapore/event.json). Do not invent stage predictions, confirmed rosters, or fixed rules to fill the directory structure.
