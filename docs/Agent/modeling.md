# Modeling and evaluation guide

## Objective

Maximize `P(total Pick'Em score >= the event's passing threshold)` under the event's actual scoring and slot rules. Expected score is a secondary quantity. Match prediction accuracy and the marginal advancement probability of each team do not determine the best joint Pick'Em allocation.

These are design constraints, not an implemented or validated Singapore model. The historical Cologne implementations remain untouched.

Start with the smallest working baseline and improve it using held-out evidence. Add model components, data collection, or infrastructure when they answer a specific prediction question; the stages below are experiments to prioritize, not a checklist of systems to build in advance.

## Singapore unified model decision

Singapore will use one joint map-outcome model with three connected strength signals. Parameter fitting and time-ordered checks belong to this same model structure. They do not create separate production model versions.

The match-time score for team `A` on map `m` is represented as:

```text
score(A, m, t) = recent(A, m, t)
               + lambda_long * long(A, m, t)
               + lambda_lan_major * lan_major(A, m, t)
               + style(A, opponent, m, t)
```

- `recent` uses all available historical maps with an initial half-life of 75 days.
- `long` uses all available historical maps with an initial half-life of 365 days. This carries durable team and player strength into the prediction.
- `lan_major` uses LAN and Major evidence with a long memory. It represents performance in high-pressure events and receives continuous event-information weighting.
- `style` contains map-specific and opponent-specific interaction terms. It is part of the same outcome model rather than a post-hoc adjustment.

Every historical observation receives the same roster-continuity factor for temporary and permanent changes:

```text
roster_weight = rho ** replaced_players
```

The factor applies to the observation's contribution to the relevant state. A substitute lowers the relevance of that lineup's result while preserving the normal evidence from the team's other lineups.

The starting temporal mixture is 0.60 recent and 0.40 long-term. The equivalent observation curve is:

```text
time_weight(d) = 0.60 * 2 ** (-d / 75)
               + 0.40 * 2 ** (-d / 365)
```

For the Singapore VRS cutoff, use the 2026-11-02 standings date as `vrs_cutoff` and keep the date in the frozen prediction manifest. Matches after that date and before the Major begins receive a configurable factor `delta_vrs_post_cutoff` in the `long` and `lan_major` states. They remain fully available to `recent`, because they are direct evidence about current form. The initial value is 0.60.

The cutoff factor is an information-timing feature. It does not remove observations and it does not alter the meaning of the match date. A Singapore Major match itself is high-value event evidence and follows the event-state rules for that stage.

Initial values are working priors. Select decay, state weights, event-information scaling, roster retention, and cutoff discount with rolling time-ordered evaluation while preserving this unified structure.

## Implementation plan

The complete implementation record is in [the Singapore model implementation plan](research/singapore_model_implementation_plan_2026-11-19.md). The production path will keep the following decisions together.

- Fit one weighted, regularized map-outcome model over all available teams. Opponent strength is estimated jointly with team strength, so an out-of-stage opponent still contributes through the same parameter system.
- Build match probabilities from map abilities and an empirical veto model. Do not treat a BO3 series probability as another single-map conversion.
- Add lagged player Rating 3.0, the actual five-player lineup, a strongly shrunk five-player residual, team-system continuity, and map-specific opponent style terms. Keep the features continuous and preserve unknown values.
- Estimate a team-stage latent state from residual volatility. Draw it once per team in each complete Swiss simulation so repeated matches share the same stage condition.
- Use a global `lambda_match` learned from time-ordered historical Major match markets. Apply it only where a valid market snapshot exists. A Stage 1 prediction uses one frozen stage-lock cutoff for all opening matches.
- If a Stage 2 advancement market appears, calibrate the simulated advancement margins with a separate `lambda_stage2`. It does not replace individual match probabilities.
- Generate complete Swiss outcomes with the official pairing and format rules, retain the full simulation rows, and optimize the actual Pick'Em passing probability rather than independent team rankings.
- Select parameters with rolling event-level evaluation using log loss, Brier score, calibration, and Pick'Em passing probability. A model component enters the final path only after it improves time-ordered evidence.

## Continuous numerical modeling

- Preserve continuous information and available precision in feature construction, fitting, calibration, prediction, and Pick'Em optimization. Do not discretize numerical values into bins, tiers, threshold flags, or descriptive labels. Display-only grouping or rounding must not feed back into calculations or model selection.
- Use justified continuous transformations, smooth time weighting, and continuous shrinkage. Small samples should produce gradually stronger shrinkage or greater uncertainty, not an arbitrary sample-count switch. Do not add step bonuses for a chosen recent-period cutoff. Free weights, decay rates, and shrinkage strengths need a stated statistical rationale or time-ordered held-out evidence.
- Keep genuinely categorical facts, such as map identity, BO1/BO3 format, and observed wins/losses, and official competition rules as defined. Time cutoffs for information availability and temporal evaluation are information boundaries, not substitutes for continuous recency features.
- Reliability diagrams may group predictions for display. Fit and assess probability models using the underlying numerical predictions; do not use display bins as calibration inputs or selection criteria.

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
