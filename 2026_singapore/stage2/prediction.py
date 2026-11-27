"""Fit Stage 2 and reuse the Singapore match and Swiss simulation models."""

from collections import defaultdict
from datetime import timedelta
from itertools import combinations
from math import prod, sqrt
from time import perf_counter

from ..stage1 import prediction as swiss
from ..stage1.market import load_match_markets


def _fit(dataset, stage, reference_day, vrs_date, *, registered=None, cutoff=None):
    reference_text = reference_day.isoformat()
    until = reference_text if cutoff is not None else (reference_day - timedelta(days=1)).isoformat()
    matches = [
        row for row in dataset.rows("matches", until=until, source="hltv")
        if row.get("event_id") != stage["event_id"]
        and (cutoff is None or swiss._available_before(row, cutoff))
    ]
    match_ids = {row["match_id"] for row in matches}
    stats = (row for row in dataset.rows("player_stats", until=until, source="hltv")
             if row["match_id"] in match_ids)
    data = swiss.build_training_data(matches, stats, reference_date=reference_day,
                                     vrs_cutoff=vrs_date, registered=registered)

    previous_stage = {row["match_id"] for row in matches
                      if row.get("event_id") == stage["previous_stage_event_id"]}
    previous_maps = [example for example in data.examples if example.match_id in previous_stage]
    restored = 0
    for example in previous_maps:
        if vrs_date < example.date < reference_text:
            # Undo the historical long/LAN discount for this Major's Stage 1.
            example.weights["long"] /= 0.60
            example.weights["lan_major"] /= 0.60
            restored += 1
    strength = swiss._fit_global_strength(
        data, dataset, vrs_date, "global", vrs_prior_strength=stage["vrs_prior_strength"])
    model = swiss.UnifiedMapModel(data, global_strength=strength).fit()
    return model, {
        "event_id": stage["previous_stage_event_id"],
        "series": len(previous_stage),
        "maps": len(previous_maps),
        "maps_exempted_from_post_vrs_discount": restored,
    }


def _estimate_stage_form(model, dataset, stage, cutoff):
    """Fit the three Stage 2 form windows with the same VRS prior as the forecast."""
    reference = model.data.reference_date
    teams_moments = defaultdict(lambda: [0.0, 0.0])
    population_moment = population_mass = 0.0
    pair_count = 0
    windows = []
    for days_back in (63, 42, 21):
        start = reference - timedelta(days=days_back)
        end = start + timedelta(days=21)
        dates, _ = swiss._vrs_snapshot_index(dataset, (start - timedelta(days=1)).isoformat())
        if not dates:
            continue
        forecast, _ = _fit(dataset, stage, start, dates[-1])
        lineups = forecast.data.reference_lineups
        windows.append(start.isoformat())
        events = defaultdict(list)
        for match in dataset.rows("matches", start.isoformat(), end.isoformat(), source="hltv"):
            day = swiss._parse_day(match["date"])
            if day == end and (end != reference or not swiss._available_before(match, cutoff)):
                continue
            event = match.get("event_id")
            if not event or event == stage["event_id"]:
                continue
            raw_teams = (match["team1"], match["team2"])
            ids = tuple(swiss._team_id(team) for team in raw_teams)
            if any(not lineups.get(team_id) for team_id in ids):
                continue
            teams = [swiss.StageTeam(team_id, swiss._team_name(team), seed, lineups[team_id])
                     for seed, (team_id, team) in enumerate(zip(ids, raw_teams), 1)]
            exponent = model.data.roster_overlap_exponent
            error = info = 0.0
            carry_to_stage = [0.0, 0.0]
            for row in match.get("maps", []):
                if (not row.get("played") or row.get("default_map") or not row.get("name")
                        or row.get("winner") not in ("team1", "team2")):
                    continue
                actual = [swiss._lineup_for_map(team, row, side)
                          for team, side in zip(raw_teams, ("team1", "team2"))]
                weight = prod(swiss._roster_overlap(lineup, team.players)[0] ** exponent
                              for lineup, team in zip(actual, teams))
                p = forecast.map_probability(*teams, row["name"], match.get("best_of") or 1)
                change = weight * p * (1.0 - p)
                error += weight * (float(row["winner"] == "team1") - p)
                info += change
                for index, team_id in enumerate(ids):
                    target = model.data.reference_lineups.get(team_id, ())
                    carry_to_stage[index] += change * swiss._roster_overlap(actual[index], target)[0] ** exponent
            if info:
                for index, team_id in enumerate(ids):
                    events[event, team_id].append((ids[1 - index], day, (-1) ** index * error / info,
                                                   info, carry_to_stage[index] / info))
        for (_, team_id), series in events.items():
            for left, right in combinations(series, 2):
                opponent, day, error, info, carry = left
                other, other_day, other_error, other_info, other_carry = right
                if opponent == other:
                    continue
                weight = info * other_info * 2.0 ** (-abs((day - other_day).days) / 7.0
                                                     - (reference - max(day, other_day)).days / 75.0)
                moment = error * other_error
                population_moment += weight * moment
                population_mass += weight
                inherited = weight * carry * other_carry
                teams_moments[team_id][0] += inherited * moment
                teams_moments[team_id][1] += inherited
                pair_count += 1
    variance = max(0.0, population_moment / population_mass) if population_mass else 0.0
    model.population_sigma = min(0.75, max(0.10, 0.22 * sqrt(variance)))
    model.team_sigma = {
        team_id: min(0.75, max(0.10, 0.22 * sqrt(max(0.0, (moment + 20.0 * variance) / (mass + 20.0)))))
        for team_id, (moment, mass) in teams_moments.items() if mass > 0.0
    }
    model.stability_summary = {
        "window_starts": windows, "window_days": 21, "series_pairs": pair_count,
        "population_form_variance": variance, "population_sigma": model.population_sigma,
    }


def _search(outcomes, names, search_simulations, candidate_k):
    count = len(outcomes)
    search_count = min(search_simulations, count)
    if search_count == count:
        result = swiss.PickemOptimizer(outcomes, names).optimize(candidate_k)
    else:
        subset = [outcomes[index * count // search_count] for index in range(search_count)]
        shortlist = swiss.PickemOptimizer(subset, names).optimize(candidate_k)
        optimizer = swiss.PickemOptimizer(outcomes, names)
        recommendations = [
            optimizer.evaluate_selection((row["team_id"], row["slot"]) for row in candidate["selection"])
            for candidate in shortlist["recommendations"]
        ]
        recommendations.sort(key=lambda item: (-item["pass_probability"], -item["expected_correct"]))
        result = {**recommendations[0], "recommendations": recommendations,
                  "marginals": optimizer.marginals(), "simulations": count,
                  "search": {**shortlist["search"], "global_optimum_proven": False}}
    result["search"].update(search_simulations=search_count, evaluation_simulations=count)
    return result


def _opening_predictions(first_round, matrix, markets):
    predictions = []
    for row in first_round:
        team_id, opponent_id = row["teams"]
        p = matrix[team_id]["opponents"][opponent_id]["bo1"]
        market = markets.get(frozenset((team_id, opponent_id)))
        market_p = None
        if market is not None:
            market_p = (market.market_probability if team_id == market.team1_id
                        else 1.0 - market.market_probability)
        predictions.append({
            "team1_id": team_id, "team2_id": opponent_id, "start": row["start"],
            "model_probability": p, "market_probability": market_p,
            "blended_probability": market.probability_for(team_id, opponent_id, p) if market else p,
            "lambda_match": market.lambda_match if market else None,
            "market_id": market.market_id if market else None,
            "snapshot_at": market.snapshot_at if market else None,
        })
    return predictions


def run_stage_prediction(dataset, stage_file, *, simulations, seed, market_file, lambda_match,
                         candidate_k, search_simulations, validation_simulations,
                         validation_seed, workers, market_lock_at=None):
    started_at = perf_counter()
    stage, teams, map_pool, cutoff_text = swiss.load_stage_file(stage_file)
    cutoff = swiss._parse_instant(cutoff_text)
    ordered = sorted(teams, key=lambda team: team.seed)
    seed_pairs = {frozenset((left.team_id, right.team_id)) for left, right in zip(ordered[:8], ordered[8:])}
    scheduled_pairs = {frozenset(row["teams"]) for row in stage["first_round"]}
    if seed_pairs != scheduled_pairs:
        raise ValueError("Stage 2 seeds do not reproduce the published first round")
    market_lock_at = market_lock_at or cutoff_text
    if swiss._parse_instant(market_lock_at) > cutoff:
        raise ValueError("The market lock must be at or before the stage cutoff")
    markets = load_match_markets(market_file, lambda_match, lock_at=market_lock_at) if market_file else {}
    if markets.keys() - scheduled_pairs:
        raise ValueError("Opening markets must refer to the published first round")
    if validation_simulations:
        validation_seed = seed + 1 if validation_seed is None else validation_seed
        if seed == validation_seed or (workers == 1 and abs(seed) == abs(validation_seed)):
            raise ValueError("Validation requires a different seed from the primary run")

    model, previous_stage = _fit(
        dataset, stage, cutoff.date(), stage["vrs_date"],
        registered={team.team_id: team.players for team in teams}, cutoff=cutoff)
    _estimate_stage_form(model, dataset, stage, cutoff)
    simulator = swiss.SwissSimulator(model, teams, map_pool, stage_name=stage["stage"],
                                     opening_markets=markets)
    setup_finished_at = perf_counter()
    outcomes = simulator.simulate_many(simulations=simulations, seed=seed, workers=workers)
    simulation_finished_at = perf_counter()
    result = _search(outcomes, model.data.team_names, search_simulations, candidate_k)
    del outcomes
    matrix = swiss.build_stage_matrix(model, teams, map_pool)
    result.update({
        "stage": stage["stage"], "cutoff": cutoff_text, "seed": seed,
        "manifest_sha256": dataset.manifest_sha256, "previous_stage_training": previous_stage,
        "model": model.summary(), "map_pool": list(map_pool),
        "pairing_rule_version": swiss.PAIRING_RULE_VERSION,
        "core_matrix": matrix, "team_intermediates": swiss.build_team_intermediates(model, teams, matrix, map_pool),
        "opening_predictions": _opening_predictions(stage["first_round"], matrix, markets),
        "opening_market_count": len(markets), "market_lambda_match": lambda_match if markets else 0.0,
        "market_lock_at": market_lock_at,
        "market_snapshot_at": max((market.snapshot_at for market in markets.values()), default=None),
        "simulation_workers": workers,
    })
    if validation_simulations:
        validation_started = perf_counter()
        result["validation"] = swiss.validate_recommendations(
            simulator, result["recommendations"], validation_simulations, validation_seed, workers)
        result["validation"]["elapsed_seconds"] = perf_counter() - validation_started
    result["elapsed_seconds"] = {
        "setup": setup_finished_at - started_at,
        "primary_simulation": simulation_finished_at - setup_finished_at,
        "total": perf_counter() - started_at,
    }
    return result
