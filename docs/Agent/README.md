# Agent working documentation

This is the technical entry point. Human-facing material lives in the repository [README](../../README.md) and stage prediction pages. Do not require the user to read the documents below to understand a recommendation.

| Task | Read |
|---|---|
| Decide what to collect; identify current readiness and missing work | [Collection plan](data/collection-plan.md) |
| Run ingestion, cached replay, legacy import, rankings, or export | [Data runbook](data/runbook.md) |
| Interpret IDs, schema, timestamps, ratings, snapshots, or compatibility | [Data contract](data/contract.md) |
| Design probability models, evaluation, or Pick'Em optimization | [Modeling guide](modeling.md) |
| Investigate the tested HLTV access path and source discrepancies | [HLTV collection experiment, 2026-10-20](research/hltv_collection_2026-10-20.md) |
| Investigate rating definitions and community evidence | [Rating comparison, 2026-10-20](research/ratings_comparison_2026-10-20.md) |

## Reading and maintenance

- Treat dated research as evidence with a stated scope, not as current operating instructions. The runbook owns current commands; the contract owns field semantics; the collection plan owns source choices.
- Update the relevant canonical document when a decision or interface changes. Add a dated report only when an experiment contributes reusable evidence; avoid duplicate progress logs.
- Keep operational evidence in `data/reports/` and raw diagnostics in `data/raw/diagnostics/`. Large generated data stays out of Git.
- English is fine for Agent documentation. Preserve existing research in its original language. Write a separate Chinese explanation when the user asks to examine a design.

## Historical references

The user has requested that Cologne documents remain unchanged. Read the original [Stage 1](../../2026_cologne/stage1/README.md), [Stage 2](../../2026_cologne/stage2/README.md), [Stage 3](../../2026_cologne/stage3/README.md), and [Stage 3 plan](../../2026_cologne/stage3/plan.md) when needed, without reorganizing or silently correcting them. Their quantitative output is historical; their descriptions are not evidence that the algorithms were calibrated or optimal.

For Singapore, teams and stage snapshots are still empty in [event.json](../../2026_singapore/event.json). Do not invent stage predictions, confirmed rosters, or fixed rules to fill the directory structure.
