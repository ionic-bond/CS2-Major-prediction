# Modeling and evaluation guide

## Objective

Maximize `P(total Pick'Em score >= the event's passing threshold)` under the event's actual scoring and slot rules. Expected score is a secondary quantity. Match prediction accuracy and the marginal advancement probability of each team do not determine the best joint Pick'Em allocation.

These are design constraints, not an implemented or validated Singapore model. The historical Cologne implementations remain untouched.

Start with the smallest working baseline and improve it using held-out evidence. Add model components, data collection, or infrastructure when they answer a specific prediction question; the stages below are experiments to prioritize, not a checklist of systems to build in advance.

## Build evidence in stages

1. Establish a team-level baseline using dated results, opposition strength, format, maps, and LAN/online context when known.
2. Test the incremental value of actual lineups, roster continuity, player mean performance, and recent form. Team results already encode some player strength; roster changes and limited team samples can still make player data useful.
3. Test residual player/team variance and persistent form only after controlling for opposition, map, role when available, environment, and sample size. Shrink uncertain variance estimates. KAST measures round contribution/survival, not consistency across matches.
4. Add veto behavior and advanced statistics when they answer a concrete modeling question and improve time-ordered held-out performance. Availability alone does not justify a feature.

Use rolling temporal splits, log loss, Brier score, and calibration. Avoid selecting a model or data source from a few successful predictions. Keep source definitions consistent within a player time series; current HLTV/BO3 comparison samples contain ADR/KAST differences as well as incompatible rating scales.

## Probability and simulation semantics

- State whether every probability is for a map, a series, or a tournament outcome. A Bo3 series probability must not receive a second single-map-to-Bo3 conversion.
- For a fixed match win probability, independently adding outcome noise does not automatically improve tournament modeling. Shared day/event form can create correlations; estimate and validate such persistence before introducing it.
- Construct all pairings in a round from the same pre-round state. Apply official ordering constraints and use a matching/backtracking method where necessary to avoid avoidable rematches.
- A historical preference-based veto heuristic is a behavior model, not a Nash or minimax solution. Claims of optimal BP require an explicit game, payoffs, and solution method.
- Preserve complete tournament simulation rows so candidate Pick'Em scores retain correlations. Evaluate shortlisted allocations on fresh simulations to reduce selection bias.
- Label restricted candidate searches accurately. Do not call a truncated search globally optimal without a proof or a complete search.

## Data timing

Freeze a dataset manifest for each prediction. Distinguish when a match occurred from when the data became available. Today's recalculated historical Rating may incorporate a later rating revision; the current date-filtered export is not a reconstruction of exactly what was knowable at a past cutoff.

Unknown patch/map revision and missing statistics remain explicit. Do not train on Default/forfeit map awards as played maps. Do not resolve conflicting series outcomes by summing rounds across maps.

## Legacy reuse checklist

The earlier read-only Cologne audit identified paths to recheck before reusing code: Stage 2 series winners inferred from summed rounds, greedy Swiss pairings, within-round state updates, restricted Pick'Em searches, Stage 3 H2H series/map probability confusion, and preference-based BP described as game-theoretic optimization. These are reasons to inspect the relevant code, not instructions to modify the historical record during unrelated work.
