"""Runnable Singapore prediction model and Swiss Pick'Em simulator.

The module deliberately uses only the Python standard library.  It reads the
canonical JSONL dataset through :class:`Dataset` and keeps prediction inputs
separate from the collector's SQLite work database.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import itertools
import json
import math
from pathlib import Path
import random
import re
from time import perf_counter
from typing import Iterable, Mapping, Sequence

from .market import load_match_markets


STATE_NAMES = ("recent", "long", "lan_major")
ROSTER_STATE_MIX = {"recent": 0.40, "long": 0.45, "lan_major": 0.15}
RESIDUAL_PRECISION = {"team_map": 4.0, "style": 8.0}
TACTICAL_SCALE = 0.2960113082029133
RESIDUAL_SCALE = {"team_map": TACTICAL_SCALE, "style": TACTICAL_SCALE}
ROSTER_RATING_SCALE = 1.0
ROUND_SCORE_WEIGHT = 0.5
DEFAULT_ROSTER_OVERLAP_EXPONENT = 1.5
DEFAULT_OPPONENT_SATURATION_EXPONENT = 0.5
PAIRING_RULE_VERSION = "valve-major-swiss-2026"
DEFAULT_MAP_POOL_SIZE = 7
MAP_ALIASES = {"de_dust2": "Dust2", "de_nuke": "Nuke", "de_mirage": "Mirage",
               "de_inferno": "Inferno", "de_ancient": "Ancient", "de_anubis": "Anubis",
               "de_overpass": "Overpass", "de_cache": "Cache", "de_train": "Train",
               "de_cobblestone": "Cobblestone"}


def _sigmoid(value):
    if value >= 0:
        z = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(min(value, 700.0))
    return z / (1.0 + z)


def _logit(probability):
    probability = min(1.0 - 1e-6, max(1e-6, probability))
    return math.log(probability / (1.0 - probability))


def _parse_day(value):
    if isinstance(value, date):
        return value
    if not value:
        return date.min
    return date.fromisoformat(str(value)[:10])


def _parse_instant(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        instant = value
    else:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Information cutoff must include a timezone")
    return instant.astimezone(timezone.utc)


def _available_before(match, cutoff):
    """Apply an instant cutoff while retaining older date-only records."""
    day = _parse_day(match.get("date"))
    if day < cutoff.date():
        return True
    if day > cutoff.date():
        return False
    value = match.get("played_at_utc") or match.get("completed_at_utc")
    if not value:
        return False
    return _parse_instant(value) <= cutoff


def _sort_key(match):
    instant = match.get("played_at_utc") or match.get("completed_at_utc")
    return (instant or match.get("date", ""), match.get("match_id", ""))


def normalize_map_name(value):
    text = str(value or "").strip()
    return MAP_ALIASES.get(text.lower(), text)


def _team_id(team):
    return str(team.get("id") or team.get("name") or "unknown-team")


def _team_name(team):
    return str(team.get("name") or team.get("id") or "unknown-team")


def _player_ids(players):
    result = []
    for player in players or []:
        if isinstance(player, Mapping):
            value = player.get("id")
        else:
            value = player
        if value is not None:
            result.append(str(value))
    return tuple(dict.fromkeys(result))


def _lineup_for_map(team, map_row, side):
    map_players = (map_row.get("players") or {}).get(side)
    lineup = _player_ids(map_players)
    return lineup or _player_ids(team.get("players"))


def _roster_overlap(historical, target):
    """Shared players and shared teammate pairs, relative to a full roster."""
    n = max(5, len(historical), len(target))
    k = len(set(historical).intersection(target))
    return k / n, k * (k - 1) / (n * (n - 1))


@dataclass(frozen=True)
class StageTeam:
    team_id: str
    name: str
    seed: int
    players: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, value):
        team_id = str(value.get("id") or value.get("team_id") or value.get("name"))
        name = str(value.get("name") or team_id)
        return cls(team_id, name, int(value["seed"]), _player_ids(value.get("players")))


@dataclass
class TrainingExample:
    features: dict[str, float]
    label: int
    date: str
    match_id: str
    team1_id: str
    team2_id: str
    map_name: str
    weights: dict[str, float]
    lineup1: tuple[str, ...] = ()
    lineup2: tuple[str, ...] = ()
    names: tuple[str, str] = ("", "")
    round_margin: float | None = None


class PlayerTracker:
    """Within-team Rating differences for estimating an incoming lineup."""

    def __init__(self):
        self.history = defaultdict(list)

    def observe(self, day, series_lineups, ratings):
        for lineup in series_lineups:
            available = {pid: ratings[pid] for pid in lineup if pid in ratings}
            if len(available) < 2:
                continue
            average = sum(available.values()) / len(available)
            weight = len(available) / max(5, len(lineup))
            for player_id, rating in available.items():
                self.history[player_id].append((day, rating - average, weight))

    def value_before(self, player_id, cutoff):
        total = 0.0
        effective = 0.0
        for day, difference, weight in self.history.get(player_id, ()):
            if day >= cutoff:
                break
            weight *= 2.0 ** (-(cutoff - day).days / 75.0)
            total += weight * difference
            effective += weight
        return total / (effective + 3.0)


def _round_margin(map_row, label):
    left, right = map_row.get("team1_rounds"), map_row.get("team2_rounds")
    if left is None or right is None or left == right or (left > right) != bool(label):
        return None
    winner, loser = max(left, right), min(left, right)
    margin = (winner - loser) / max(1, winner + loser)
    return margin if label else -margin


class VetoModel:
    """Empirical map-selection model with shrinkage to global map frequency."""

    def __init__(self):
        self.global_maps = Counter()
        self.removed = defaultdict(Counter)
        self.picked = defaultdict(Counter)
        self.left_over = Counter()
        self._team_names = {}
        self._bo1_paths = {}
        self._bo3_paths = {}

    def observe(self, match, team_weights=None, frequency_weight=1.0):
        self._bo1_paths.clear()
        self._bo3_paths.clear()
        teams = (match.get("team1") or {}, match.get("team2") or {})
        names = {_team_name(team): _team_id(team) for team in teams}
        self._team_names.update(names)
        for map_row in match.get("maps", []):
            if map_row.get("played") and not map_row.get("default_map"):
                self.global_maps[normalize_map_name(map_row.get("name"))] += frequency_weight
        for raw_line in match.get("vetoes") or []:
            text = str(raw_line.get("source_text") if isinstance(raw_line, Mapping) else raw_line)
            text = re.sub(r"^\s*\d+\.\s*", "", text).strip()
            lowered = text.casefold()
            if " was left over" in lowered:
                map_name = text[:lowered.index(" was left over")].strip()
                self.left_over[normalize_map_name(map_name)] += 1
                continue
            for name, team_id in sorted(names.items(), key=lambda item: len(item[0]), reverse=True):
                prefix = name.casefold() + " "
                if not lowered.startswith(prefix):
                    continue
                rest = text[len(name):].strip()
                action, separator, map_name = rest.partition(" ")
                if not separator:
                    continue
                map_name = normalize_map_name(map_name)
                if action.casefold() == "removed":
                    self.removed[team_id][map_name] += team_weights[team_id] if team_weights else 1
                elif action.casefold() == "picked":
                    self.picked[team_id][map_name] += team_weights[team_id] if team_weights else 1
                break

    def weighted_preferences(self, team_id, map_pool):
        """Return the team's weighted veto observations for the stage maps."""
        bans = self.removed.get(team_id, {})
        picks = self.picked.get(team_id, {})
        return {"ban": {map_name: bans.get(map_name, 0.0) for map_name in map_pool},
                "pick": {map_name: picks.get(map_name, 0.0) for map_name in map_pool}}

    def default_pool(self, size=DEFAULT_MAP_POOL_SIZE):
        maps = [name for name, count in self.global_maps.items() if count >= 20]
        maps.sort(key=lambda name: (-self.global_maps[name], name))
        if not maps:
            maps = sorted(self.global_maps, key=lambda name: (-self.global_maps[name], name))
        return tuple(maps[:size])

    def _remove_rate(self, team_id, map_name, pool):
        counts = self.removed[str(team_id)]
        total = sum(counts.values())
        return (counts[map_name] + 1.0) / (total + len(pool))

    def _pick_weight(self, team_id, map_name, pool):
        counts = self.picked[str(team_id)]
        total = sum(counts.values())
        pick_rate = (counts[map_name] + 1.0) / (total + len(pool))
        remove_rate = self._remove_rate(team_id, map_name, pool)
        return (self.global_maps[map_name] + 5.0) * (1.0 + 2.0 * pick_rate) * (1.0 - 0.5 * remove_rate)

    def _remove_distribution(self, team_id, pool):
        counts = self.removed[str(team_id)]
        weights = {name: counts[name] + 1.0 for name in pool}
        total = sum(weights.values()) or 1.0
        return {name: value / total for name, value in weights.items()}

    def _remove_paths(self, team_id, pool, count):
        if count == 0:
            yield (), 1.0
            return
        for map_name, probability in self._remove_distribution(team_id, pool).items():
            remaining = tuple(name for name in pool if name != map_name)
            for suffix, suffix_probability in self._remove_paths(team_id, remaining, count - 1):
                yield (map_name,) + suffix, probability * suffix_probability

    def map_distribution(self, team1_id, team2_id, map_pool=None):
        pool = tuple(map_pool or self.default_pool())
        if len(pool) != 7:
            raise ValueError("Exact Major BO1 veto modeling requires seven maps")
        pair = tuple(sorted((team1_id, team2_id)))
        key = (pair, pool)
        if key not in self._bo1_paths:
            weights = defaultdict(float)
            for team_a, team_b in (pair, pair[::-1]):
                for removed_a, probability_a in self._remove_paths(team_a, pool, 2):
                    after_a = tuple(name for name in pool if name not in removed_a)
                    for removed_b, probability_b in self._remove_paths(team_b, after_a, 3):
                        after_b = tuple(name for name in after_a if name not in removed_b)
                        for removed_final, probability_final in self._remove_paths(team_a, after_b, 1):
                            remaining = tuple(name for name in after_b if name not in removed_final)
                            if len(remaining) == 1:
                                weights[remaining[0]] += 0.5 * probability_a * probability_b * probability_final
            total = sum(weights.values()) or 1.0
            self._bo1_paths[key] = {name: value / total for name, value in weights.items()}
        return dict(self._bo1_paths[key])

    @staticmethod
    def _weighted_choice(rng, weights):
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0:
            return next(iter(weights))
        target = rng.random() * total
        for name, value in weights.items():
            target -= max(0.0, value)
            if target <= 0:
                return name
        return next(reversed(weights))

    def sample_map(self, rng, team1_id, team2_id, map_pool=None):
        distribution = self.map_distribution(team1_id, team2_id, map_pool)
        return self._weighted_choice(rng, distribution)

    def _pick_distribution(self, team_id, pool):
        weights = {name: self._pick_weight(team_id, name, pool) for name in pool}
        total = sum(weights.values())
        return {name: weight / total for name, weight in weights.items()}

    def bo3_paths(self, team1_id, team2_id, map_pool=None):
        """Return paths from the official BO3 remove/pick sequence.

        The higher seed's choice of Team A or Team B is unobserved here, so
        both assignments receive equal prior probability.
        """
        pool = tuple(map_pool or self.default_pool())
        if len(pool) != 7:
            raise ValueError("Exact Major BO3 veto modeling requires seven maps")
        pair = tuple(sorted((team1_id, team2_id)))
        key = (pair, pool)
        if key not in self._bo3_paths:
            weights = defaultdict(float)
            for team_a, team_b in (pair, pair[::-1]):
                for removed_a, probability_a in self._remove_paths(team_a, pool, 1):
                    after_a = tuple(name for name in pool if name not in removed_a)
                    for removed_b, probability_b in self._remove_paths(team_b, after_a, 1):
                        after_b = tuple(name for name in after_a if name not in removed_b)
                        for first, probability_first in self._pick_distribution(team_a, after_b).items():
                            after_first = tuple(name for name in after_b if name != first)
                            for second, probability_second in self._pick_distribution(team_b, after_first).items():
                                after_second = tuple(name for name in after_first if name != second)
                                for removed_b_final, probability_b_final in self._remove_paths(
                                        team_b, after_second, 1):
                                    after_b_final = tuple(name for name in after_second
                                                          if name not in removed_b_final)
                                    for removed_a_final, probability_a_final in self._remove_paths(
                                            team_a, after_b_final, 1):
                                        remaining = tuple(name for name in after_b_final
                                                          if name not in removed_a_final)
                                        if len(remaining) == 1:
                                            weights[first, second, remaining[0]] += (
                                                0.5 * probability_a * probability_b *
                                                probability_first * probability_second *
                                                probability_b_final * probability_a_final)
            self._bo3_paths[key] = (tuple(weights), tuple(weights.values()))
        return self._bo3_paths[key]

    def sample_bo3_maps(self, rng, team1_id, team2_id, map_pool=None):
        paths, weights = self.bo3_paths(team1_id, team2_id, map_pool)
        return rng.choices(paths, weights=weights, k=1)[0]


def _event_flags(match):
    event = str(match.get("event") or "")
    lowered = event.casefold()
    major = "major" in lowered
    lan = bool(match.get("is_lan")) or major
    return lan, major


def _feature_add(features, key, value):
    if value:
        features[key] = features.get(key, 0.0) + float(value)


def _style_key(team1_id, team2_id, map_name):
    pair = sorted((str(team1_id), str(team2_id)))
    sign = 1.0 if str(team1_id) == pair[0] else -1.0
    return f"style:{pair[0]}|{pair[1]}|{map_name}", sign


def _feature_vector(team1_id, team2_id, map_name, lineup1, lineup2,
                    reference_lineups, roster_overlap_exponent):
    """Every feature changes sign when the two teams swap columns."""
    features = {}
    team1_id, team2_id = str(team1_id), str(team2_id)
    _feature_add(features, f"team:{team1_id}", 1.0)
    _feature_add(features, f"team:{team2_id}", -1.0)
    player1, pairs1 = _roster_overlap(lineup1, reference_lineups.get(team1_id, ()))
    player2, pairs2 = _roster_overlap(lineup2, reference_lineups.get(team2_id, ()))
    _feature_add(features, f"team_map:{team1_id}|{map_name}", player1 ** roster_overlap_exponent)
    _feature_add(features, f"team_map:{team2_id}|{map_name}", -(player2 ** roster_overlap_exponent))
    style_key, style_sign = _style_key(team1_id, team2_id, map_name)
    _feature_add(features, style_key, style_sign * pairs1 * pairs2)
    if lineup1:
        _feature_add(features, f"lineup:{team1_id}|{'/'.join(sorted(lineup1))}", 1.0)
    if lineup2:
        _feature_add(features, f"lineup:{team2_id}|{'/'.join(sorted(lineup2))}", -1.0)
    return features


class HistoricalTrainingData:
    def __init__(self, examples, veto_model, player_tracker,
                 map_counts, team_names, reference_date, reference_lineups, player_nicks,
                 roster_overlap_exponent):
        self.examples = examples
        self.veto_model = veto_model
        self.player_tracker = player_tracker
        self.map_counts = map_counts
        self.team_names = team_names
        self.reference_date = reference_date
        self.reference_lineups = reference_lineups
        self.player_nicks = player_nicks
        self.roster_overlap_exponent = float(roster_overlap_exponent)

    def prediction_features(self, team1, team2, map_name):
        lineup1 = tuple(team1.players)
        lineup2 = tuple(team2.players)
        return _feature_vector(team1.team_id, team2.team_id, normalize_map_name(map_name),
                               lineup1, lineup2,
                               self.reference_lineups, self.roster_overlap_exponent)


def _reference_rosters(matches, reference_day, registered):
    rosters, nicks = {}, {}
    for match in matches:
        if _parse_day(match["date"]) > reference_day:
            continue
        for row in match.get("maps", []):
            if not row.get("played") or row.get("default_map") or row.get("winner") not in ("team1", "team2"):
                continue
            for side in ("team1", "team2"):
                team = match[side]
                players = (row.get("players") or {}).get(side) or team.get("players") or []
                lineup = tuple(sorted(_player_ids(players)))
                if lineup:
                    rosters[_team_id(team)] = lineup
                for player in players:
                    if isinstance(player, Mapping) and player.get("id") and player.get("nick"):
                        nicks[str(player["id"])] = player["nick"].casefold()
    rosters.update({key: tuple(sorted(lineup)) for key, lineup in (registered or {}).items() if lineup})
    return rosters, nicks


def build_training_data(matches: Iterable[Mapping], player_stats: Iterable[Mapping],
                        reference_date=None, vrs_cutoff="2026-11-02", registered=None,
                        roster_overlap_exponent=DEFAULT_ROSTER_OVERLAP_EXPONENT):
    matches = sorted(matches, key=_sort_key)
    if not matches:
        raise ValueError("No matches available for model fitting")
    reference_day = _parse_day(reference_date or matches[-1].get("date"))
    cutoff_day = _parse_day(vrs_cutoff) if vrs_cutoff else None
    targets, nicks = _reference_rosters(matches, reference_day, registered)
    stats_by_match = defaultdict(dict)
    for row in player_stats:
        if row.get("scope") == "series" and row.get("map_name") == "All maps" and \
                str(row.get("rating_version")) == "3.0":
            player = row.get("player_id")
            rating = row.get("hltv_rating")
            if player is not None and rating is not None:
                stats_by_match[row.get("match_id")][str(player)] = float(rating)

    player_tracker = PlayerTracker()
    veto_model = VetoModel()
    examples = []
    map_counts = Counter()
    team_names = {}
    for match in matches:
        day = _parse_day(match.get("date"))
        if day > reference_day:
            continue
        teams = (match.get("team1") or {}, match.get("team2") or {})
        ids = (_team_id(teams[0]), _team_id(teams[1]))
        names = (_team_name(teams[0]), _team_name(teams[1]))
        team_names.update({ids[0]: names[0], ids[1]: names[1]})
        series_lineups = (_player_ids(teams[0].get("players")), _player_ids(teams[1].get("players")))
        is_lan, is_major = _event_flags(match)
        event_quality = 1.0 + (0.15 if is_lan else 0.0) + (0.20 if is_major else 0.0)
        days = max(0, (reference_day - day).days)
        post_cutoff = bool(cutoff_day and day > cutoff_day and day < reference_day)
        weights = {
            "recent": event_quality * 2.0 ** (-days / 75.0),
            "long": event_quality * 2.0 ** (-days / 365.0) * (0.60 if post_cutoff else 1.0),
            "lan_major": event_quality * 2.0 ** (-days / 365.0) *
                         (1.0 if is_lan or is_major else 0.15) * (0.60 if post_cutoff else 1.0),
        }
        played = [m for m in match.get("maps", []) if m.get("played") and not m.get("default_map")]
        for map_row in played:
            map_name = normalize_map_name(map_row.get("name"))
            if not map_name:
                continue
            map_counts[map_name] += 1
            lineups = (tuple(sorted(_lineup_for_map(teams[0], map_row, "team1"))),
                       tuple(sorted(_lineup_for_map(teams[1], map_row, "team2"))))
            winner = map_row.get("winner")
            if winner not in ("team1", "team2"):
                continue
            label = int(winner == "team1")
            features = _feature_vector(ids[0], ids[1], map_name,
                                       lineups[0], lineups[1],
                                       targets, roster_overlap_exponent)
            examples.append(TrainingExample(features, label, day.isoformat(),
                                            str(match.get("match_id")), ids[0], ids[1], map_name,
                                            dict(weights), *lineups, names, _round_margin(map_row, label)))

        age_weight = 2.0 ** (-days / 75.0)
        veto_weights = {tid: age_weight * _roster_overlap(lineup, targets.get(tid, ()))[0] ** roster_overlap_exponent
                        for tid, lineup in zip(ids, series_lineups)}
        veto_model.observe(match, veto_weights, age_weight)
        player_tracker.observe(day, series_lineups, stats_by_match.get(match.get("match_id"), {}))

    if not examples:
        raise ValueError("No played map observations available for model fitting")
    return HistoricalTrainingData(examples, veto_model, player_tracker,
                                  map_counts, team_names, reference_day, targets, nicks,
                                  roster_overlap_exponent)


class SparseLogistic:
    """Paired logistic regression with L2 shrinkage and no first-column intercept."""

    def __init__(self, epochs=14, learning_rate=0.65, l2=0.04):
        self.epochs = int(epochs)
        self.learning_rate = float(learning_rate)
        self.l2 = float(l2)
        self.weights = {}

    def fit(self, examples: Sequence[TrainingExample], weight_name, fixed_weights=None,
            match_factors=None, group_precision=None):
        if not examples:
            raise ValueError("Cannot fit a logistic model with no examples")
        fixed_weights = fixed_weights or {}
        self.weights.update(fixed_weights)
        match_factors = match_factors or {}
        group_precision = group_precision or {}
        observations = []
        for example in examples:
            weight = example.weights[weight_name] * match_factors.get(example.match_id, 1.0)
            offset = sum(fixed_weights[k] * v for k, v in example.features.items() if k in fixed_weights)
            terms = [(k, v) for k, v in example.features.items() if k not in fixed_weights]
            observations.append((weight, offset, terms, example.label))
        feature_mass = defaultdict(float)
        for weight, _, terms, _ in observations:
            for key, value in terms:
                feature_mass[key] += weight * value * value
        penalties = {key: group_precision.get(key.partition(":")[0], 0.0) for key in feature_mass}
        if not feature_mass:
            return self
        for _ in range(self.epochs):
            gradients = defaultdict(float)
            for weight, offset, terms, label in observations:
                score = offset + sum(self.weights.get(k, 0.0) * v for k, v in terms)
                error = (_sigmoid(score) - label) * weight
                for key, value in terms:
                    gradients[key] += error * value
            rate = self.learning_rate / math.sqrt(1.0 + _)
            for key in feature_mass:
                coefficient = self.weights.get(key, 0.0)
                mass = max(1.0, feature_mass.get(key, 0.0))
                penalty = penalties[key]
                gradient = (gradients[key] + (self.l2 * mass + penalty) * coefficient) / (mass + penalty)
                self.weights[key] = coefficient - rate * gradient
        return self

    def predict_logit(self, features):
        return sum(self.weights.get(key, 0.0) * value for key, value in features.items())

    def metrics(self, examples: Sequence[TrainingExample], weight_name):
        total = 0.0
        logloss = 0.0
        brier = 0.0
        for example in examples:
            weight = max(0.0, example.weights.get(weight_name, 0.0))
            if weight <= 0:
                continue
            probability = min(1.0 - 1e-12, max(1e-12, _sigmoid(self.predict_logit(example.features))))
            logloss += weight * (-(example.label * math.log(probability) +
                                   (1 - example.label) * math.log(1 - probability)))
            brier += weight * (probability - example.label) ** 2
            total += weight
        if total == 0:
            return {"log_loss": None, "brier": None, "weight": 0.0}
        return {"log_loss": logloss / total, "brier": brier / total, "weight": total}


class GlobalStrengthModel:
    """One opponent-adjusted strength score per historical team."""

    def __init__(self, data: HistoricalTrainingData, *, state_mix=None, epochs=14, l2=1.0,
                 match_weight_factors=None, weight_summary=None, prior_anchors=None,
                 prior_strength=0.0, prior_summary=None, anchor_reliability=None,
                 round_score_weight=ROUND_SCORE_WEIGHT, roster_rating_scale=ROSTER_RATING_SCALE):
        self.data = data
        self.state_mix = dict(state_mix or ROSTER_STATE_MIX)
        self.epochs = int(epochs)
        self.l2 = float(l2)
        self.match_weight_factors = dict(match_weight_factors or {})
        self.weight_summary = dict(weight_summary or {})
        self.prior_anchors = dict(prior_anchors or {})
        self.prior_strength = float(prior_strength)
        self.prior_summary = dict(prior_summary or {})
        self.anchor_reliability = anchor_reliability or {}
        self.round_score_weight = float(round_score_weight)
        self.roster_rating_scale = float(roster_rating_scale)
        self.scored_maps = 0
        self.roster_overlap_exponent = float(getattr(
            data, "roster_overlap_exponent", DEFAULT_ROSTER_OVERLAP_EXPONENT))
        self.roster_scores = {}
        self.roster_score_variances = {}
        self._roster_links = []
        self._roster_offsets = []
        self._current_rosters = {}
        self.scores = {}
        self.score_variances = {}
        self.iterations = 0
        self._prior_indices = ()

    @staticmethod
    def _dot(left, right):
        return sum(a * b for a, b in zip(left, right))

    def _roster_precision(self, vector):
        # Historical roster strength conditional on the target: mean r*s, variance (1-r²)/l2.
        result = [self.l2 * value for value in vector]
        for old, current, carry, precision in self._roster_links:
            residual = precision * (vector[old] - carry * vector[current])
            result[old] += residual - self.l2 * vector[old]
            result[current] -= carry * residual
        return result

    def _objective(self, scores, edges):
        value = (0.5 * self._dot(scores, self._roster_precision(scores))
                 - self._dot(scores, self._roster_offsets))
        for index, anchor, precision in self._prior_indices:
            value += 0.5 * precision * (scores[index] - anchor) ** 2
        for team1, team2, label, weight in edges:
            logit = scores[team1] - scores[team2]
            value += weight * (max(0.0, logit) +
                               math.log1p(math.exp(-abs(logit))) - label * logit)
        return value

    def _gradient_hessian_weights(self, scores, edges):
        gradient = [value - offset for value, offset in
                    zip(self._roster_precision(scores), self._roster_offsets)]
        for index, anchor, precision in self._prior_indices:
            gradient[index] += precision * (scores[index] - anchor)
        hessian_weights = []
        for team1, team2, label, weight in edges:
            logit = scores[team1] - scores[team2]
            error = weight * (_sigmoid(logit) - label)
            gradient[team1] += error
            gradient[team2] -= error
            probability = _sigmoid(logit)
            hessian_weights.append(weight * probability * (1.0 - probability))
        return gradient, hessian_weights

    def _hessian_vector(self, vector, edges, hessian_weights):
        result = self._roster_precision(vector)
        for index, _, precision in self._prior_indices:
            result[index] += precision * vector[index]
        for (team1, team2, _, _), weight in zip(edges, hessian_weights):
            difference = weight * (vector[team1] - vector[team2])
            result[team1] += difference
            result[team2] -= difference
        return result

    def _solve_newton_direction(self, gradient, edges, hessian_weights):
        """Solve H direction = gradient without materializing the graph matrix."""
        direction = [0.0] * len(gradient)
        residual = list(gradient)
        search = list(residual)
        residual_norm = self._dot(residual, residual)
        if residual_norm <= 1e-20:
            return direction
        for _ in range(min(120, max(20, len(gradient) // 4))):
            hessian_search = self._hessian_vector(search, edges, hessian_weights)
            denominator = self._dot(search, hessian_search)
            if denominator <= 0.0:
                break
            step = residual_norm / denominator
            for index in range(len(direction)):
                direction[index] += step * search[index]
                residual[index] -= step * hessian_search[index]
            next_norm = self._dot(residual, residual)
            if next_norm <= residual_norm * 1e-12:
                break
            search_factor = next_norm / residual_norm
            for index in range(len(search)):
                search[index] = residual[index] + search_factor * search[index]
            residual_norm = next_norm
        return direction

    def fit(self):
        if self.l2 <= 0.0:
            raise ValueError("Global strength fitting requires positive l2")
        targets = self.data.reference_lineups
        current = {tid: (tid, targets.get(tid, ())) for tid in self.data.team_names.keys() | targets.keys()}
        self._current_rosters = current
        nodes = set(current.values())
        weights = [
            sum(self.state_mix[state] * example.weights[state] for state in STATE_NAMES)
            * self.match_weight_factors.get(example.match_id, 1.0)
            * (1.0 + self.round_score_weight * abs(example.round_margin or 0.0))
            for example in self.data.examples
        ]
        self.scored_maps = sum(example.round_margin is not None for example in self.data.examples)
        totals = defaultdict(lambda: [0.0, 0.0])
        first_played = {}
        for example, weight in zip(self.data.examples, weights):
            left = (example.team1_id, example.lineup1)
            right = (example.team2_id, example.lineup2)
            nodes.update((left, right))
            first_played.setdefault(left, example.date)
            first_played.setdefault(right, example.date)
            label = example.label
            if left > right:
                left, right, label = right, left, 1 - label
            totals[left, right][0] += weight * label
            totals[left, right][1] += weight
        index = {node: i for i, node in enumerate(sorted(nodes))}
        self._roster_links = []
        self._roster_offsets = [0.0] * len(index)
        player_value = lru_cache(maxsize=None)(self.data.player_tracker.value_before)
        for (tid, lineup), i in index.items():
            ref = current[tid]
            if ref != (tid, lineup):
                carry = _roster_overlap(lineup, ref[1])[0] ** self.roster_overlap_exponent
                if carry:
                    precision = self.l2 / (1.0 - carry ** 2)
                    self._roster_links.append((i, index[ref], carry, precision))
                    day = _parse_day(first_played.get(ref, self.data.reference_date))
                    outgoing = sum(player_value(pid, day) for pid in set(lineup) - set(ref[1]))
                    incoming = sum(player_value(pid, day) for pid in set(ref[1]) - set(lineup))
                    # A stronger incoming lineup raises the current score
                    # implied by the old lineup's record.
                    shift = carry * self.roster_rating_scale * (outgoing - incoming) / max(5, len(lineup), len(ref[1]))
                    self._roster_offsets[i] += precision * shift
                    self._roster_offsets[index[ref]] -= precision * shift * carry
        self._prior_indices = [(index[current[tid]], anchor,
                                self.prior_strength * self.anchor_reliability.get(tid, 1.0))
                               for tid, anchor in self.prior_anchors.items() if tid in current]
        edges = [(index[a], index[b], wins / total, total)
                 for (a, b), (wins, total) in totals.items() if total > 0]
        scores = [0.0] * len(index)
        for epoch in range(max(1, self.epochs)):
            gradient, hessian_weights = self._gradient_hessian_weights(scores, edges)
            direction = self._solve_newton_direction(gradient, edges, hessian_weights)
            directional_derivative = self._dot(gradient, direction)
            if directional_derivative <= 1e-12:
                break
            objective = self._objective(scores, edges)
            step = 1.0
            candidate = list(scores)
            while step >= 1e-8:
                candidate = [score - step * value for score, value in zip(scores, direction)]
                if self._objective(candidate, edges) <= objective - 1e-4 * step * directional_derivative:
                    break
                step *= 0.5
            if step < 1e-8:
                break
            maximum_update = max(abs(step * value) for value in direction)
            scores = candidate
            self.iterations = epoch + 1
            if maximum_update < 1e-7:
                break
        self.roster_scores = {node: scores[i] for node, i in index.items()}
        self.scores = {tid: self.roster_scores[node] for tid, node in current.items()}
        self._estimate_score_variances(index, edges)
        return self

    def _estimate_score_variances(self, index, edges):
        """Estimate marginal score variance from the fitted Hessian diagonal.

        This approximation omits covariance between connected lineups. It is
        used to draw shared simulation uncertainty.
        """
        _, hessian_weights = self._gradient_hessian_weights(
            [self.roster_scores[node] for node, _ in sorted(index.items(), key=lambda item: item[1])], edges)
        diagonal = [self.l2] * len(index)
        for old, current, carry, precision in self._roster_links:
            diagonal[old] += precision
            diagonal[current] += precision * carry * carry
        for node_index, _, precision in self._prior_indices:
            diagonal[node_index] += precision
        for (left, right, _, _), weight in zip(edges, hessian_weights):
            diagonal[left] += weight
            diagonal[right] += weight
        variances = {node: 1.0 / max(1e-9, diagonal[position])
                     for node, position in index.items()}
        self.roster_score_variances = variances
        self.score_variances = {
            team_id: variances.get(node, 1.0 / max(1e-9, self.l2))
            for team_id, node in self._current_rosters.items()
        }

    def score(self, team_id, lineup=None):
        current = self.scores.get(str(team_id), 0.0)
        if lineup is None:
            return current
        key = (str(team_id), tuple(sorted(lineup)))
        if key in self.roster_scores:
            return self.roster_scores[key]
        ref = self.data.reference_lineups.get(str(team_id), ())
        return _roster_overlap(key[1], ref)[0] ** self.roster_overlap_exponent * current

    def score_variance(self, team_id, lineup=None):
        team_id = str(team_id)
        current_node = self._current_rosters.get(team_id, (team_id, ()))
        current_variance = self.score_variances.get(team_id, 1.0 / max(1e-9, self.l2))
        if lineup is None:
            return current_variance
        key = (team_id, tuple(sorted(lineup)))
        if key in self.roster_score_variances:
            return self.roster_score_variances[key]
        ref = current_node[1]
        carry = _roster_overlap(key[1], ref)[0] ** self.roster_overlap_exponent
        prior_variance = 1.0 / max(1e-9, self.l2)
        return carry * carry * current_variance + (1.0 - carry * carry) * prior_variance

    def score_uncertainty(self, team_id, lineup=None):
        return math.sqrt(max(0.0, self.score_variance(team_id, lineup)))

    def summary(self):
        values = list(self.scores.values())
        return {
            "examples": len(self.data.examples),
            "teams": len(self.scores),
            "rosters": len(self.roster_scores),
            "reference_date": self.data.reference_date.isoformat(),
            "state_mix": self.state_mix,
            "epochs": self.epochs,
            "l2": self.l2,
            "optimizer": "symmetric_pairwise_logistic_newton_cg",
            "iterations": self.iterations,
            "roster_overlap_exponent": self.roster_overlap_exponent,
            "weight_adjustment": self.weight_summary,
            "prior": self.prior_summary,
            "score_min": min(values) if values else 0.0,
            "score_max": max(values) if values else 0.0,
            "score_uncertainty_min": min((math.sqrt(value) for value in self.score_variances.values()),
                                         default=0.0),
            "score_uncertainty_max": max((math.sqrt(value) for value in self.score_variances.values()),
                                         default=0.0),
        }


class UnifiedMapModel:
    def __init__(self, data: HistoricalTrainingData, *, global_strength, epochs=14, l2=0.04,
                 strength_uncertainty_scale=1.0):
        self.data = data
        self.state_mix = dict(global_strength.state_mix)
        self.epochs = epochs
        self.l2 = l2
        self.global_strength = global_strength
        self.strength_uncertainty_scale = float(strength_uncertainty_scale)
        self.models = {}
        self._map_logits = {}
        self.team_sigma = {}
        self.population_sigma = 0.0
        self.stability_summary = {}

    def fit(self):
        self._map_logits.clear()
        fixed = {f"team:{team_id}": score for team_id, score in self.global_strength.scores.items()}
        for (tid, lineup), score in self.global_strength.roster_scores.items():
            if lineup:
                fixed[f"lineup:{tid}|{'/'.join(lineup)}"] = score - self.global_strength.score(tid)
        factors = self.global_strength.match_weight_factors
        for state in STATE_NAMES:
            self.models[state] = SparseLogistic(epochs=self.epochs, l2=self.l2).fit(
                self.data.examples, state, fixed, factors, RESIDUAL_PRECISION)
            weights = self.models[state].weights
            for key in weights.keys() - fixed.keys():
                weights[key] *= RESIDUAL_SCALE.get(key.partition(":")[0], 1.0)
        return self

    def sigma(self, team_id):
        return self.team_sigma.get(str(team_id), self.population_sigma)

    def strength_sigma(self, team_id, lineup=None):
        return self.global_strength.score_uncertainty(team_id, lineup)

    def sample_stage_shocks(self, rng, teams):
        """Draw one persistent performance and strength uncertainty per team."""
        shocks = {}
        for team in teams:
            performance_sigma = self.sigma(team.team_id)
            strength_sigma = self.strength_uncertainty_scale * self.strength_sigma(team.team_id, team.players)
            total_sigma = math.sqrt(performance_sigma ** 2 + strength_sigma ** 2)
            shocks[team.team_id] = rng.gauss(0.0, total_sigma)
        return shocks

    def logit_parts(self, team1, team2, map_name, best_of=1, is_lan=False, is_major=False):
        features = self.data.prediction_features(team1, team2, map_name)
        strength = self.global_strength
        parts = {"global": strength.score(team1.team_id, team1.players) -
                           strength.score(team2.team_id, team2.players)}
        for key, value in features.items():
            kind = key.partition(":")[0]
            if kind in RESIDUAL_PRECISION:
                coefficient = sum(self.state_mix[s] * self.models[s].weights.get(key, 0.0)
                                  for s in STATE_NAMES)
                parts[kind] = parts.get(kind, 0.0) + coefficient * value
        return parts

    def map_probability(self, team1, team2, map_name, best_of=1, is_lan=False,
                        is_major=False, stage_shocks=None):
        key = (team1, team2, map_name, best_of, is_lan, is_major)
        if key not in self._map_logits:
            self._map_logits[key] = sum(self.logit_parts(*key).values())
        score = self._map_logits[key]
        if stage_shocks:
            score += stage_shocks.get(team1.team_id, 0.0) - stage_shocks.get(team2.team_id, 0.0)
        return _sigmoid(score)

    def expected_series_probability(self, team1, team2, best_of, map_pool, stage_shocks=None,
                                    is_lan=True, is_major=True):
        """Return a deterministic pre-match probability for market blending."""
        best_of = int(best_of or 1)
        if best_of <= 1:
            distribution = self.data.veto_model.map_distribution(team1.team_id, team2.team_id, map_pool)
            return sum(weight * self.map_probability(team1, team2, map_name, best_of, is_lan,
                                                     is_major, stage_shocks)
                       for map_name, weight in distribution.items())
        if best_of == 3:
            paths, weights = self.data.veto_model.bo3_paths(team1.team_id, team2.team_id, map_pool)
            probabilities = {name: self.map_probability(team1, team2, name, best_of, is_lan,
                                                        is_major, stage_shocks)
                             for name in dict.fromkeys(itertools.chain.from_iterable(paths))}
            wins = []
            for (first, second, decider), weight in zip(paths, weights):
                a, b, c = probabilities[first], probabilities[second], probabilities[decider]
                wins.append(weight * (a * b + (a * (1 - b) + (1 - a) * b) * c))
            return math.fsum(wins)
        if team1.team_id > team2.team_id:
            return 1.0 - self.expected_series_probability(
                team2, team1, best_of, map_pool, stage_shocks, is_lan, is_major)
        seed_text = f"{team1.team_id}|{team2.team_id}|{best_of}|{'/'.join(map_pool or ())}"
        seed = sum((index + 1) * ord(char) for index, char in enumerate(seed_text))
        rng = random.Random(seed)
        trials = 256
        wins = 0
        for _ in range(trials):
            if self.sample_series(rng, team1, team2, best_of, map_pool, stage_shocks, is_lan, is_major):
                wins += 1
        return wins / trials

    def sample_series(self, rng, team1, team2, best_of, map_pool, stage_shocks=None,
                      is_lan=True, is_major=True, probability_override=None):
        # Assign random draws to the same physical team when a caller swaps columns.
        if team1.team_id > team2.team_id:
            other_probability = None if probability_override is None else 1.0 - probability_override
            return not self.sample_series(rng, team2, team1, best_of, map_pool, stage_shocks,
                                          is_lan, is_major, other_probability)
        if probability_override is not None:
            return rng.random() < probability_override
        if int(best_of or 1) <= 1:
            maps = (self.data.veto_model.sample_map(rng, team1.team_id, team2.team_id, map_pool),)
        elif int(best_of) == 3:
            maps = self.data.veto_model.sample_bo3_maps(rng, team1.team_id, team2.team_id, map_pool)
        else:
            maps = tuple(map_pool or self.data.veto_model.default_pool())
        wins = [0, 0]
        for map_name in maps:
            probability = self.map_probability(team1, team2, map_name, best_of, is_lan,
                                               is_major, stage_shocks)
            if rng.random() < probability:
                wins[0] += 1
            else:
                wins[1] += 1
            if int(best_of or 1) == 1 or max(wins) >= (int(best_of) // 2 + 1):
                break
        return wins[0] > wins[1]

    def summary(self):
        metrics = {state: self.models[state].metrics(self.data.examples, state)
                   for state in STATE_NAMES}
        sigmas = list(self.team_sigma.values())
        return {
            "examples": len(self.data.examples),
            "teams": len(self.data.team_names),
            "maps": dict(self.data.map_counts),
            "reference_date": self.data.reference_date.isoformat(),
            "state_mix": self.state_mix,
            "metrics": metrics,
            "global_strength": self.global_strength.summary(),
            "scored_maps": self.global_strength.scored_maps,
            "round_score_weight": self.global_strength.round_score_weight,
            "roster_rating_scale": self.global_strength.roster_rating_scale,
            "residual_precision": RESIDUAL_PRECISION,
            "residual_scale": dict(RESIDUAL_SCALE),
            "population_sigma": self.population_sigma,
            "stability": self.stability_summary,
            "team_sigma_count": len(sigmas),
            "team_sigma_min": min(sigmas) if sigmas else self.population_sigma,
            "team_sigma_max": max(sigmas) if sigmas else self.population_sigma,
            "strength_uncertainty": True,
            "strength_uncertainty_scale": self.strength_uncertainty_scale,
        }


@dataclass
class _SimState:
    team: StageTeam
    wins: int = 0
    losses: int = 0
    opponents: list[str] = None

    def __post_init__(self):
        if self.opponents is None:
            self.opponents = []

    @property
    def record(self):
        return self.wins, self.losses


def _buchholz(state, states):
    return sum(states[opponent].wins - states[opponent].losses for opponent in state.opponents)


ROUND_4_5_PAIRING_TABLE = (
    ((0, 5), (1, 4), (2, 3)),
    ((0, 5), (1, 3), (2, 4)),
    ((0, 4), (1, 5), (2, 3)),
    ((0, 4), (1, 3), (2, 5)),
    ((0, 3), (1, 5), (2, 4)),
    ((0, 3), (1, 4), (2, 5)),
    ((0, 5), (1, 2), (3, 4)),
    ((0, 4), (1, 2), (3, 5)),
    ((0, 2), (1, 5), (3, 4)),
    ((0, 2), (1, 4), (3, 5)),
    ((0, 3), (1, 2), (4, 5)),
    ((0, 2), (1, 3), (4, 5)),
    ((0, 1), (2, 5), (3, 4)),
    ((0, 1), (2, 4), (3, 5)),
    ((0, 1), (2, 3), (4, 5)),
)


def _pair_group(items, states, round_number=None):
    """Apply the Valve Major Swiss pairing priority to one score group.

    Rounds 2 and 3 repeatedly pair the highest seeded remaining team with the
    lowest seeded team that avoids a rematch. Rounds 4 and 5 use Valve's
    published 15-row table for six-team groups.
    """
    ordered = sorted(items, key=lambda item: (-_buchholz(item, states), item.team.seed, item.team.team_id))

    if round_number in (4, 5) and len(ordered) == 6:
        fewest_rematches = 4
        best_pairs = None
        for row in ROUND_4_5_PAIRING_TABLE:
            pairs = [(ordered[left], ordered[right]) for left, right in row]
            rematches = sum(second.team.team_id in first.opponents for first, second in pairs)
            if rematches == 0:
                return pairs
            if rematches < fewest_rematches:
                fewest_rematches, best_pairs = rematches, pairs
        return best_pairs

    def search(remaining):
        if not remaining:
            return []
        first = remaining[0]
        # The first entry has the highest current seed. The search walks from
        # the lowest available seed to implement the published high-low rule.
        for index in range(len(remaining) - 1, 0, -1):
            candidate = remaining[index]
            if candidate.team.team_id in first.opponents:
                continue
            rest = remaining[1:index] + remaining[index + 1:]
            result = search(rest)
            if result is not None:
                return [(first, candidate)] + result
        return None

    pairs = search(ordered)
    if pairs is not None:
        return pairs

    # The rule avoids rematches when possible. A rare history can make a
    # perfect matching impossible, so retain high-low priority and minimize
    # the number of unavoidable rematches instead of aborting the simulation.
    def search_minimum_rematches(remaining):
        if not remaining:
            return 0, []
        first = remaining[0]
        best = None
        for index in range(len(remaining) - 1, 0, -1):
            candidate = remaining[index]
            rest = remaining[1:index] + remaining[index + 1:]
            rematches, suffix = search_minimum_rematches(rest)
            rematches += int(candidate.team.team_id in first.opponents)
            option = (rematches, [(first, candidate)] + suffix)
            if best is None or option[0] < best[0]:
                best = option
        return best

    rematches, pairs = search_minimum_rematches(ordered)
    if pairs is None:
        raise ValueError(f"Unable to pair Swiss round {round_number}")
    return pairs


class SwissSimulator:
    def __init__(self, model: UnifiedMapModel, teams: Sequence[StageTeam], map_pool=None,
                 *, stage_name="Stage 1", opening_markets=None):
        if len(teams) != 16:
            raise ValueError("Swiss simulator requires exactly 16 teams")
        seeds = [team.seed for team in teams]
        if len(set(seeds)) != len(seeds):
            raise ValueError("Stage seeds must be unique")
        self.model = model
        self.teams = tuple(sorted(teams, key=lambda team: (team.seed, team.team_id)))
        self.map_pool = tuple(map_pool or model.data.veto_model.default_pool())
        self.stage_name = stage_name
        self.opening_markets = dict(opening_markets or {})

    def _initial_pairs(self, states):
        ordered = sorted(states.values(), key=lambda state: state.team.seed)
        return list(zip(ordered[:8], ordered[8:]))

    def _round_pairs(self, states, round_number):
        if round_number == 1:
            return self._initial_pairs(states)
        groups = defaultdict(list)
        for state in states.values():
            if state.wins < 3 and state.losses < 3:
                groups[state.record].append(state)
        ordered_groups = sorted(groups.items(), key=lambda item: (-item[0][0], item[0][1]))
        pairs = []
        floater = None
        for _, group in ordered_groups:
            if floater is not None:
                group = [floater] + group
                floater = None
            group = sorted(group, key=lambda item: (-_buchholz(item, states), item.team.seed, item.team.team_id))
            if len(group) % 2:
                floater = group.pop()
            pairs.extend(_pair_group(group, states, round_number))
        if floater is not None:
            candidates = [state for state in states.values()
                          if state.wins < 3 and state.losses < 3 and state is not floater]
            if not candidates:
                raise RuntimeError("Unable to pair final Swiss floater")
            candidate = min(candidates, key=lambda item: (item.team.seed, item.team.team_id))
            pairs.append((floater, candidate))
        return pairs

    @staticmethod
    def _format_for(round_number, state1, state2):
        if round_number <= 2:
            return 1
        if round_number == 3:
            return 3 if any((state.wins == 2 or state.losses == 2) for state in (state1, state2)) else 1
        return 3

    def simulate_once(self, rng):
        states = {team.team_id: _SimState(team) for team in self.teams}
        shocks = self.model.sample_stage_shocks(rng, self.teams)
        for round_number in range(1, 6):
            for state1, state2 in self._round_pairs(states, round_number):
                if state1.team.team_id == state2.team.team_id:
                    raise RuntimeError("Swiss pairing produced a self-match")
                best_of = self._format_for(round_number, state1, state2)
                state1.opponents.append(state2.team.team_id)
                state2.opponents.append(state1.team.team_id)
                market = self.opening_markets.get(frozenset((state1.team.team_id, state2.team.team_id))) \
                    if round_number == 1 else None
                if market is None:
                    first_wins = self.model.sample_series(rng, state1.team, state2.team, best_of,
                                                          self.map_pool, shocks, is_lan=True, is_major=True)
                else:
                    data_probability = self.model.expected_series_probability(
                        state1.team, state2.team, best_of, self.map_pool, shocks, True, True)
                    final_probability = market.probability_for(state1.team.team_id, state2.team.team_id,
                                                               data_probability)
                    first_wins = self.model.sample_series(
                        rng, state1.team, state2.team, best_of, self.map_pool, shocks,
                        is_lan=True, is_major=True, probability_override=final_probability)
                if first_wins:
                    state1.wins += 1
                    state2.losses += 1
                else:
                    state2.wins += 1
                    state1.losses += 1
        outcomes = {}
        for state in states.values():
            if state.wins == 3:
                outcomes[state.team.team_id] = f"3-{state.losses}"
            elif state.losses == 3:
                outcomes[state.team.team_id] = f"{state.wins}-3"
            else:
                raise RuntimeError(f"Incomplete Swiss state for {state.team.team_id}: {state.record}")
        return outcomes

    def simulate_many(self, simulations=10000, seed=0, workers=1):
        if simulations <= 0:
            raise ValueError("simulations must be positive")
        workers = int(workers)
        if workers <= 1:
            rng = random.Random(seed)
            return [self.simulate_once(rng) for _ in range(simulations)]
        workers = min(workers, simulations)
        size, remainder = divmod(simulations, workers)
        chunks = [(size + (index < remainder), f"stage-simulation:{seed}:{index}")
                  for index in range(workers)]
        with ProcessPoolExecutor(max_workers=workers,
                                 initializer=_init_simulation_worker,
                                 initargs=(self,)) as pool:
            results = pool.map(_simulate_chunk, chunks)
            return [outcome for chunk in results for outcome in chunk]


_SIMULATION_WORKER = None


def _init_simulation_worker(simulator):
    global _SIMULATION_WORKER
    _SIMULATION_WORKER = simulator


def _simulate_chunk(arguments):
    count, seed = arguments
    return _SIMULATION_WORKER.simulate_many(count, seed=seed, workers=1)


class PickemOptimizer:
    def __init__(self, outcomes: Sequence[Mapping[str, str]], team_names=None):
        outcomes = list(outcomes)
        if not outcomes:
            raise ValueError("Pick'Em optimizer requires simulation outcomes")
        self.team_ids = tuple(sorted(outcomes[0]))
        self.team_names = dict(team_names or {})
        self.count = len(outcomes)
        self.all_mask = (1 << self.count) - 1
        self.masks = self._build_masks(outcomes)

    def _build_masks(self, outcomes):
        masks = {}
        byte_count = (self.count + 7) // 8
        for team_id in self.team_ids:
            undefeated = bytearray(byte_count)
            advance = bytearray(byte_count)
            winless = bytearray(byte_count)
            by_record = {"3-0": undefeated, "3-1": advance, "3-2": advance, "0-3": winless}
            for index, outcome in enumerate(outcomes):
                bits = by_record.get(outcome[team_id])
                if bits is not None:
                    bits[index >> 3] |= 1 << (index & 7)
            masks[team_id, "3-0"] = int.from_bytes(undefeated, "little")
            masks[team_id, "advance"] = int.from_bytes(advance, "little")
            masks[team_id, "0-3"] = int.from_bytes(winless, "little")
        return masks

    def marginals(self):
        result = {}
        for team_id in self.team_ids:
            result[team_id] = {
                "name": self.team_names.get(team_id, team_id),
                "3-0": self.masks[(team_id, "3-0")].bit_count() / self.count,
                "advance": self.masks[(team_id, "advance")].bit_count() / self.count,
                "0-3": self.masks[(team_id, "0-3")].bit_count() / self.count,
            }
        return result

    @staticmethod
    def _add_item(bits, mask):
        next_bits = [0] * (len(bits) + 1)
        inverse = ~mask
        for score, current in enumerate(bits):
            next_bits[score] |= current & inverse
            next_bits[score + 1] |= current & mask
        return tuple(next_bits)

    def _score_bits(self, selection):
        bits = (self.all_mask,)
        for team_id, category in selection:
            bits = self._add_item(bits, self.masks[(team_id, category)])
        return bits

    def _stats(self, bits):
        passing = 0
        expected = 0.0
        for score, mask in enumerate(bits):
            count = mask.bit_count()
            expected += score * count / self.count
            if score >= 5:
                passing += count
        return passing / self.count, expected

    @staticmethod
    def _upper_pass_probability(bits, remaining_slots, count):
        threshold = max(0, 5 - remaining_slots)
        return sum(mask.bit_count() for score, mask in enumerate(bits) if score >= threshold) / count

    @staticmethod
    def _canonical_selection(selection):
        return tuple(sorted(selection, key=lambda item: (item[1], item[0])))

    @staticmethod
    def _consider_candidate(top, candidate, limit=5):
        top.append(candidate)
        top.sort(key=lambda item: (-item["pass_probability"],
                                   -item["expected_correct"], item["selection"]))
        if len(top) > limit:
            del top[limit:]

    def evaluate_selection(self, selection):
        """Measure one legal selection against this optimizer's simulation rows."""
        canonical = self._canonical_selection(tuple(selection))
        passing, expected = self._stats(self._score_bits(canonical))
        category_order = {"3-0": 0, "advance": 1, "0-3": 2}
        return {
            "selection": [
                {"team_id": team_id, "name": self.team_names.get(team_id, team_id), "slot": category}
                for team_id, category in sorted(canonical,
                                                 key=lambda item: (category_order[item[1]], item[0]))
            ],
            "pass_probability": passing,
            "expected_correct": expected,
        }

    def _optimize_exact(self, candidate_k):
        marginals = self.marginals()
        top_30 = sorted(self.team_ids, key=lambda team: (-marginals[team]["3-0"], team))[:candidate_k]
        top_adv = sorted(self.team_ids, key=lambda team: (-marginals[team]["advance"], team))[:max(candidate_k, 10)]
        top_03 = sorted(self.team_ids, key=lambda team: (-marginals[team]["0-3"], team))[:candidate_k]
        top_candidates = []

        def search_advance(base, selected, ordered, start, bits, depth):
            remaining_slots = 6 - depth
            if len(top_candidates) >= 5:
                upper = self._upper_pass_probability(bits, remaining_slots, self.count)
                if upper < top_candidates[-1]["pass_probability"]:
                    return
            if depth == 6:
                passing, expected = self._stats(bits)
                self._consider_candidate(top_candidates, {
                    "selection": self._canonical_selection(base),
                    "pass_probability": passing,
                    "expected_correct": expected,
                })
                return
            choices_left = 6 - depth
            last = len(ordered) - choices_left
            for index in range(start, last + 1):
                team_id = ordered[index]
                search_advance(
                    base + ((team_id, "advance"),), selected | {team_id}, ordered,
                    index + 1, self._add_item(bits, self.masks[(team_id, "advance")]), depth + 1)

        for pair_30 in itertools.combinations(top_30, 2):
            for pair_03 in itertools.combinations(top_03, 2):
                used = set(pair_30).union(pair_03)
                if len(used) != 4:
                    continue
                base = tuple((team, "3-0") for team in pair_30) + tuple((team, "0-3") for team in pair_03)
                bits = self._score_bits(base)
                available = [team for team in top_adv if team not in used]
                search_advance(base, used, available, 0, bits, 0)
        return top_candidates, marginals

    def optimize(self, candidate_k=12):
        ranked_candidates, marginals = self._optimize_exact(candidate_k)
        if not ranked_candidates:
            raise ValueError("No legal Pick'Em candidate found")
        best = self.evaluate_selection(ranked_candidates[0]["selection"])
        best["recommendations"] = [self.evaluate_selection(candidate["selection"])
                                    for candidate in ranked_candidates[:5]]
        best["marginals"] = marginals
        best["simulations"] = self.count
        best["search"] = {"candidate_k": candidate_k, "mode": "exact",
                          "global_optimum_proven": candidate_k >= len(self.team_ids)}
        return best


def fit_model_from_dataset(dataset, since="0001-01-01", until="9999-12-31", reference_date=None,
                           vrs_cutoff="2026-11-02", epochs=14, l2=0.04,
                           registered=None,
                           roster_overlap_exponent=DEFAULT_ROSTER_OVERLAP_EXPONENT,
                           opponent_saturation_exponent=DEFAULT_OPPONENT_SATURATION_EXPONENT,
                           strength_uncertainty_scale=1.0, information_cutoff=None,
                           round_score_weight=ROUND_SCORE_WEIGHT, roster_rating_scale=ROSTER_RATING_SCALE):
    matches = list(dataset.rows("matches", since, until, source="hltv"))
    cutoff = _parse_instant(information_cutoff)
    if cutoff is not None:
        matches = [row for row in matches if _available_before(row, cutoff)]
    match_ids = {row.get("match_id") for row in matches}
    stats = [row for row in dataset.rows("player_stats", since, until, source="hltv")
             if row.get("match_id") in match_ids]
    if reference_date is None:
        reference_date = max((row.get("date") for row in matches), default=until)
    data = build_training_data(matches, stats, reference_date=reference_date, vrs_cutoff=vrs_cutoff,
                               registered=registered,
                               roster_overlap_exponent=roster_overlap_exponent)
    strength = _fit_global_strength(data, dataset, vrs_cutoff, "global",
                                    opponent_saturation_exponent=opponent_saturation_exponent,
                                    round_score_weight=round_score_weight, roster_rating_scale=roster_rating_scale)
    return UnifiedMapModel(data, epochs=epochs, l2=l2, global_strength=strength,
                           strength_uncertainty_scale=strength_uncertainty_scale).fit()


def _vrs_snapshot_index(dataset, through_date, region="global"):
    snapshots = defaultdict(lambda: defaultdict(list))
    for row in dataset.rows("rankings", "0001-01-01", through_date, source="valve"):
        if row["region"] == region:
            snapshots[row["date"]][row["team_name"].casefold()].append(row)
    return sorted(snapshots), snapshots


def estimate_stage_form(model, dataset, information_cutoff=None):
    """Estimate persistent form from maps that were future at each fit date."""
    reference = model.data.reference_date
    stages = defaultdict(lambda: [0.0, 0.0])
    population = [0.0, 0.0]
    pair_count = 0
    windows = []
    for days_back in (63, 42, 21):
        start = reference - timedelta(days=days_back)
        end = start + timedelta(days=21)
        before = (start - timedelta(days=1)).isoformat()
        dates, _ = _vrs_snapshot_index(dataset, before)
        if not dates:
            continue
        forecast = fit_model_from_dataset(
            dataset, until=before, reference_date=start, vrs_cutoff=dates[-1],
            epochs=model.epochs, l2=model.l2,
            roster_overlap_exponent=model.data.roster_overlap_exponent,
            opponent_saturation_exponent=model.global_strength.weight_summary["opponent_saturation_exponent"],
            strength_uncertainty_scale=model.strength_uncertainty_scale,
            round_score_weight=model.global_strength.round_score_weight,
            roster_rating_scale=model.global_strength.roster_rating_scale)
        lineups = forecast.data.reference_lineups
        events = defaultdict(list)
        windows.append(start.isoformat())
        for match in dataset.rows("matches", start.isoformat(), end.isoformat(), source="hltv"):
            day = _parse_day(match["date"])
            # Include the reference day only for the last window, and only
            # for records available by the forecast's instant cutoff.
            if day >= end and (end != reference or information_cutoff is None
                               or not _available_before(match, information_cutoff)):
                continue
            event = match.get("event_id")
            if not event:
                continue
            raw_teams = (match["team1"], match["team2"])
            ids = tuple(_team_id(team) for team in raw_teams)
            if any(not lineups.get(tid) for tid in ids):
                continue
            teams = [StageTeam(tid, _team_name(team), seed, lineups[tid])
                     for seed, (tid, team) in enumerate(zip(ids, raw_teams), 1)]
            error = info = 0.0
            carry_to_stage = [0.0, 0.0]
            for row in match.get("maps", []):
                if (not row.get("played") or row.get("default_map") or not row.get("name")
                        or row.get("winner") not in ("team1", "team2")):
                    continue
                actual = [_lineup_for_map(raw, row, side)
                          for raw, side in zip(raw_teams, ("team1", "team2"))]
                same = [_roster_overlap(lineup, team.players)[0] ** model.data.roster_overlap_exponent
                        for lineup, team in zip(actual, teams)]
                weight = math.prod(same)
                p = forecast.map_probability(*teams, row["name"], match.get("best_of") or 1)
                change = weight * p * (1.0 - p)
                error += weight * (float(row["winner"] == "team1") - p)
                info += change
                for index, tid in enumerate(ids):
                    carry_to_stage[index] += change * _roster_overlap(
                        actual[index], model.data.reference_lineups.get(tid, ()))[0] ** model.data.roster_overlap_exponent
            if info:
                for index, tid in enumerate(ids):
                    events[event, tid].append((ids[1-index], day, (-1) ** index * error / info,
                                               info, carry_to_stage[index] / info))
        for (_, tid), series in events.items():
            for left, right in itertools.combinations(series, 2):
                opponent, day, error, info, carry = left
                other, other_day, other_error, other_info, other_carry = right
                if opponent == other:
                    continue
                weight = info * other_info * 2.0 ** (-abs((day - other_day).days) / 7.0
                                                     - (reference - max(day, other_day)).days / 75.0)
                # The product of two separated forecast residuals captures
                # persistent team form. Parameter uncertainty is already
                # sampled separately from the fitted strength graph.
                moment = error * other_error
                population[0] += weight * moment
                population[1] += weight
                inherited = weight * carry * other_carry
                stages[tid][0] += inherited * moment
                stages[tid][1] += inherited
                pair_count += 1
    variance = max(0.0, population[0] / population[1]) if population[1] else 0.0
    model.population_sigma = min(0.75, max(0.10, 0.22 * math.sqrt(variance)))
    model.team_sigma = {
        tid: min(0.75, max(0.10, 0.22 * math.sqrt(max(
            0.0, (moment + 20.0 * variance) / (mass + 20.0)))))
        for tid, (moment, mass) in stages.items() if mass > 0.0
    }
    model.stability_summary = {
        "window_starts": windows, "window_days": 21, "series_pairs": pair_count,
        "population_form_variance": variance,
        "population_sigma": model.population_sigma,
    }


def _ranked_roster(rows, nicknames, overlap_exponent=DEFAULT_ROSTER_OVERLAP_EXPONENT):
    if not rows:
        return None, 0.0
    def overlap(row):
        roster = tuple(nick.casefold() for nick in row["roster"])
        return _roster_overlap(nicknames, roster)[0]
    row = max(rows, key=lambda item: (overlap(item), -item["rank"]))
    return row, overlap(row) ** overlap_exponent


def _fit_vrs_logit_slope(observations):
    slope = 2.0
    for _ in range(30):
        gradient = hessian = 0.0
        for difference, label, weight in observations:
            p = _sigmoid(slope * difference)
            gradient += weight * difference * (p - label)
            hessian += weight * difference ** 2 * p * (1.0 - p)
        if hessian <= 1e-12:
            break
        step = gradient / hessian
        slope -= step
        if abs(step) < 1e-8:
            break
    return max(0.1, min(8.0, slope))


def _strength_evidence(data, dataset, vrs_date, region,
                       opponent_saturation_exponent=DEFAULT_OPPONENT_SATURATION_EXPONENT):
    """Use only past ranking snapshots and match the actual roster on each map."""
    if vrs_date > data.reference_date.isoformat():
        raise ValueError("VRS snapshot must be available at the forecast date")
    days, snapshots = _vrs_snapshot_index(dataset, vrs_date, region)
    if vrs_date not in snapshots:
        raise ValueError(f"No {region} VRS snapshot on {vrs_date}")
    latest = snapshots[vrs_date]
    targets = data.reference_lineups
    def nicks(lineup):
        return tuple(data.player_nicks[pid] for pid in lineup if pid in data.player_nicks)

    series_sizes = Counter(ex.match_id for ex in data.examples)
    match_pairs = {}
    pair_matches = defaultdict(set)
    for ex in data.examples:
        pair = tuple(sorted((ex.team1_id, ex.team2_id)))
        match_pairs[ex.match_id] = pair
        pair_matches[pair].add(ex.match_id)
    pair_factors = {
        pair: len(match_ids) ** (-float(opponent_saturation_exponent))
        for pair, match_ids in pair_matches.items()
    }
    observations = []
    known = 0
    lookup = {}
    for ex in data.examples:
        position = bisect_left(days, ex.date) - 1
        snapshot = days[position] if position >= 0 else None
        ranked = []
        for name, lineup in zip(ex.names, (ex.lineup1, ex.lineup2)):
            key = (snapshot, name, lineup)
            if key not in lookup:
                rows = snapshots[snapshot].get(name.casefold(), ()) if snapshot else ()
                lookup[key] = _ranked_roster(rows, nicks(lineup), data.roster_overlap_exponent)
            row, overlap = lookup[key]
            age = (_parse_day(ex.date) - _parse_day(snapshot)).days if row else 0
            reliability = overlap * 2.0 ** (-age / 75.0)
            ranked.append((row, reliability))
            known += reliability > 0
        (a, wa), (b, wb) = ranked
        if wa * wb > 0:
            observations.append(((a["points"] - b["points"]) / 1000.0, ex.label,
                                 wa * wb / math.sqrt(series_sizes[ex.match_id]) *
                                 pair_factors[match_pairs[ex.match_id]]))

    factors = {
        mid: 1.0 / math.sqrt(size) * pair_factors[match_pairs[mid]]
        for mid, size in series_sizes.items()
    }
    count = len(factors)
    weight_summary = {
        "method": "opponent_adjusted_roster_graph_with_series_and_opponent_saturation",
        "vrs_date": vrs_date, "vrs_region": region, "matches": count,
        "known_team_fraction": known / (2 * len(data.examples)),
        "mean_series_factor": sum(factors.values()) / count,
        "opponent_saturation_exponent": float(opponent_saturation_exponent),
        "unique_opponent_pairs": len(pair_factors),
        "mean_opponent_pair_factor": (sum(pair_factors.values()) / len(pair_factors)
                                      if pair_factors else 1.0),
    }
    slope = _fit_vrs_logit_slope(observations)
    points = [row["points"] for group in latest.values() for row in group]
    center = sum(points) / len(points)
    anchors, reliability = {}, {}
    freshness = 2.0 ** (-(data.reference_date - _parse_day(vrs_date)).days / 75.0)
    for tid, name in data.team_names.items():
        group = latest.get(name.casefold(), ())
        row, overlap = _ranked_roster(group, nicks(targets.get(tid, ())), data.roster_overlap_exponent)
        if row and overlap:
            anchors[tid] = slope * (row["points"] - center) / 1000.0
            reliability[tid] = overlap * freshness
    prior_summary = {
        "method": "roster_and_age_weighted_vrs_prior", "vrs_date": vrs_date, "vrs_region": region,
        "center_points": center, "logit_slope_per_1000_points": slope,
        "calibration_examples": len(observations), "anchored_teams": len(anchors),
    }
    return factors, weight_summary, anchors, reliability, prior_summary


def _fit_global_strength(data, dataset, vrs_date, vrs_region, epochs=14, l2=1.0,
                         vrs_prior_strength=8.0,
                         opponent_saturation_exponent=DEFAULT_OPPONENT_SATURATION_EXPONENT,
                         round_score_weight=ROUND_SCORE_WEIGHT, roster_rating_scale=ROSTER_RATING_SCALE):
    factors, weights, anchors, reliability, prior_summary = _strength_evidence(
        data, dataset, vrs_date, vrs_region, opponent_saturation_exponent)
    prior_summary["strength"] = vrs_prior_strength
    return GlobalStrengthModel(data, epochs=epochs, l2=l2, match_weight_factors=factors,
                               weight_summary=weights, prior_anchors=anchors,
                               prior_strength=vrs_prior_strength, prior_summary=prior_summary,
                               anchor_reliability=reliability, round_score_weight=round_score_weight,
                               roster_rating_scale=roster_rating_scale).fit()


def load_stage_file(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    teams = tuple(StageTeam.from_json(item) for item in payload.get("teams", []))
    if len(teams) != 16:
        raise ValueError("Stage file must contain exactly 16 teams")
    map_pool = tuple(normalize_map_name(value) for value in payload.get("map_pool", []))
    cutoff = payload.get("cutoff")
    return payload, teams, map_pool, cutoff


def build_stage_matrix(model, teams, map_pool):
    matrix = {}
    for team1 in teams:
        opponents = {}
        for team2 in teams:
            if team1.team_id == team2.team_id:
                continue
            maps = {map_name: model.map_probability(team1, team2, map_name, 1, True, True)
                    for map_name in map_pool}
            opponents[team2.team_id] = {
                "name": team2.name,
                "bo1": model.expected_series_probability(team1, team2, 1, map_pool, None, True, True),
                "bo3": model.expected_series_probability(team1, team2, 3, map_pool, None, True, True),
                "maps": maps,
            }
        matrix[team1.team_id] = {"name": team1.name, "opponents": opponents}
    return matrix


def build_team_intermediates(model, teams, matrix, map_pool):
    history = {team.team_id: {"map_battles": 0, "map_wins": 0,
                              "recent_map_battles": 0, "recent_map_wins": 0}
               for team in teams}
    recent_cutoff = model.data.reference_date - timedelta(days=90)
    for example in model.data.examples:
        for team_id, win in ((example.team1_id, example.label), (example.team2_id, 1 - example.label)):
            if team_id in history:
                stats = history[team_id]
                stats["map_battles"] += 1
                stats["map_wins"] += win
                if _parse_day(example.date) >= recent_cutoff:
                    stats["recent_map_battles"] += 1
                    stats["recent_map_wins"] += win

    result = {}
    for team in teams:
        stats = history[team.team_id]
        opponent_rows = matrix[team.team_id]["opponents"].values()
        logits = [_logit(row["bo1"]) for row in opponent_rows]
        average_logit = sum(logits) / len(logits) if logits else 0.0
        battles = stats["map_battles"]
        recent_battles = stats["recent_map_battles"]
        result[team.team_id] = {
            "name": team.name,
            "seed": team.seed,
            "map_battles": battles,
            "map_wins": stats["map_wins"],
            "map_win_rate": stats["map_wins"] / battles if battles else None,
            "recent_map_battles": recent_battles,
            "recent_map_wins": stats["recent_map_wins"],
            "recent_map_win_rate": stats["recent_map_wins"] / recent_battles if recent_battles else None,
            "model_strength_logit": average_logit,
            "model_strength_index": 100.0 * _sigmoid(average_logit),
            "veto_preferences": model.data.veto_model.weighted_preferences(team.team_id, map_pool),
        }
        result[team.team_id]["global_score"] = model.global_strength.score(team.team_id)
        result[team.team_id]["global_score_uncertainty"] = model.global_strength.score_uncertainty(
            team.team_id, team.players)
        result[team.team_id]["stage_form_sigma"] = model.sigma(team.team_id)
    return result


def validate_recommendations(simulator, recommendations, simulations, seed, workers=1):
    optimizer = PickemOptimizer(
        simulator.simulate_many(simulations=simulations, seed=seed, workers=workers),
        simulator.model.data.team_names)
    rows = []
    primary_passes = None
    for candidate in recommendations:
        selection = tuple((item["team_id"], item["slot"]) for item in candidate["selection"])
        measured = optimizer.evaluate_selection(selection)
        probability = measured["pass_probability"]
        standard_error = math.sqrt(probability * (1.0 - probability) / simulations)
        measured.update({
            "standard_error": standard_error,
            "confidence_interval_95": [max(0.0, probability - 1.96 * standard_error),
                                       min(1.0, probability + 1.96 * standard_error)],
        })
        # Score masks are disjoint, so their sum selects every passing path.
        passes = sum(optimizer._score_bits(selection)[5:])
        if primary_passes is None:
            primary_passes = passes
        else:
            gap = rows[0]["pass_probability"] - probability
            discordant = (primary_passes ^ passes).bit_count() / simulations
            half_width = 1.96 * math.sqrt((discordant - gap ** 2) / simulations)
            measured["primary_pass_gap"] = gap
            measured["primary_pass_gap_interval_95"] = [gap - half_width, gap + half_width]
        rows.append(measured)
    return {
        "seed": seed,
        "simulations": simulations,
        "recommendations": rows,
        "same_model_and_markets": True,
        "selection_fixed_from_primary_run": True,
    }


def run_stage_prediction(dataset, stage_file, simulations=10000, seed=0, epochs=14, l2=0.04,
                         market_file=None, lambda_match=0.0, candidate_k=12, search_simulations=5000,
                         roster_overlap_exponent=DEFAULT_ROSTER_OVERLAP_EXPONENT,
                         opponent_saturation_exponent=DEFAULT_OPPONENT_SATURATION_EXPONENT,
                         strength_uncertainty_scale=1.0,
                         validation_simulations=0, validation_seed=None,
                         market_lock_at=None, workers=1):
    started_at = perf_counter()
    if validation_simulations:
        validation_seed = seed + 1 if validation_seed is None else int(validation_seed)
        if abs(validation_seed) == abs(seed):
            raise ValueError("Validation requires a different seed from the primary run")
    payload, teams, map_pool, cutoff = load_stage_file(stage_file)
    reference_date = _parse_day(cutoff or payload.get("date") or date.today().isoformat())
    information_cutoff = _parse_instant(cutoff) if cutoff else None
    model = fit_model_from_dataset(dataset, until=reference_date.isoformat(), reference_date=reference_date,
                                   epochs=epochs, l2=l2,
                                   registered={t.team_id: t.players for t in teams},
                                   roster_overlap_exponent=roster_overlap_exponent,
                                   opponent_saturation_exponent=opponent_saturation_exponent,
                                   strength_uncertainty_scale=strength_uncertainty_scale,
                                   information_cutoff=information_cutoff)
    estimate_stage_form(model, dataset, information_cutoff)
    opening_markets = (load_match_markets(market_file, lambda_match, lock_at=market_lock_at)
                       if market_file else {})
    market_snapshot_at = None
    if market_file:
        market_payload = json.loads(Path(market_file).read_text(encoding="utf-8"))
        if isinstance(market_payload, Mapping):
            market_snapshot_at = market_payload.get("snapshot_at")
        if market_snapshot_at is None:
            snapshots = [market.snapshot_at for market in opening_markets.values()
                          if market.snapshot_at]
            market_snapshot_at = max(snapshots) if snapshots else None
    simulator = SwissSimulator(model, teams, map_pool, stage_name=payload.get("stage", "Stage 1"),
                               opening_markets=opening_markets)
    setup_finished_at = perf_counter()
    outcomes = simulator.simulate_many(simulations=simulations, seed=seed, workers=workers)
    simulation_finished_at = perf_counter()
    search_count = len(outcomes)
    search_outcomes = outcomes
    if search_simulations < len(outcomes):
        stride = len(outcomes) / float(search_simulations)
        indices = [min(len(outcomes) - 1, int(index * stride)) for index in range(search_simulations)]
        search_outcomes = [outcomes[index] for index in indices]
        search_count = len(search_outcomes)
    optimizer = PickemOptimizer(search_outcomes, model.data.team_names)
    result = optimizer.optimize(candidate_k=candidate_k)
    if search_outcomes is not outcomes:
        search_metadata = dict(result["search"])
        full_optimizer = PickemOptimizer(outcomes, model.data.team_names)
        refined = []
        for candidate in result["recommendations"]:
            selection = tuple((item["team_id"], item["slot"]) for item in candidate["selection"])
            refined.append(full_optimizer.evaluate_selection(selection))
        refined.sort(key=lambda item: (-item["pass_probability"],
                                      -item["expected_correct"],
                                      tuple((row["slot"], row["team_id"]) for row in item["selection"])))
        result = dict(refined[0])
        result["recommendations"] = refined
        result["marginals"] = full_optimizer.marginals()
        result["simulations"] = len(outcomes)
        result["search"] = search_metadata
    result["search"]["search_simulations"] = search_count
    result["search"]["evaluation_simulations"] = len(outcomes)
    if search_outcomes is not outcomes:
        result["search"]["global_optimum_proven"] = False
    del outcomes, search_outcomes
    core_matrix = build_stage_matrix(model, teams, simulator.map_pool)
    result["core_matrix"] = core_matrix
    result["opening_predictions"] = []
    ordered = sorted(teams, key=lambda team: team.seed)
    for team, opponent in zip(ordered[:8], ordered[8:]):
        probability = core_matrix[team.team_id]["opponents"][opponent.team_id]["bo1"]
        market = opening_markets.get(frozenset((team.team_id, opponent.team_id)))
        market_probability = None
        if market is not None:
            market_probability = (market.market_probability if team.team_id == market.team1_id
                                  else 1.0 - market.market_probability)
        result["opening_predictions"].append({
            "team1_id": team.team_id, "team2_id": opponent.team_id,
            "model_probability": probability, "market_probability": market_probability,
            "blended_probability": (market.probability_for(team.team_id, opponent.team_id, probability)
                                    if market else probability),
            "lambda_match": market.lambda_match if market else None,
            "market_id": market.market_id if market else None,
            "snapshot_at": market.snapshot_at if market else None,
        })
    result["team_intermediates"] = build_team_intermediates(model, teams, core_matrix, simulator.map_pool)
    result.update({"stage": payload.get("stage", "Stage 1"), "cutoff": cutoff,
                   "seed": seed, "model": model.summary(),
                   "map_pool": list(simulator.map_pool),
                   "pairing_rule_version": PAIRING_RULE_VERSION,
                   "opening_market_count": len(opening_markets),
                   "market_lambda_match": float(lambda_match) if opening_markets else 0.0,
                   "market_snapshot_at": market_snapshot_at,
                   "market_lock_at": market_lock_at,
                   "simulation_workers": int(workers)})
    if validation_simulations:
        validation_started_at = perf_counter()
        result["validation"] = validate_recommendations(
            simulator, result["recommendations"], validation_simulations, validation_seed, workers)
        result["validation"]["elapsed_seconds"] = perf_counter() - validation_started_at
    result["elapsed_seconds"] = {
        "setup": setup_finished_at - started_at,
        "primary_simulation": simulation_finished_at - setup_finished_at,
        "total": perf_counter() - started_at,
    }
    return result


