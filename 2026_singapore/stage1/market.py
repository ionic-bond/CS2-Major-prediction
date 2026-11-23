"""Load frozen Polymarket snapshots and blend opening-match probabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
import json
import math
from pathlib import Path


def _clip(value):
    return min(1.0 - 1e-6, max(1e-6, float(value)))


def normalize_binary_prices(yes_price, no_price):
    yes = float(yes_price)
    no = float(no_price)
    if not math.isfinite(yes) or not math.isfinite(no) or yes < 0 or no < 0 or yes + no <= 0:
        raise ValueError("Binary market prices must be finite and have a positive sum")
    return yes / (yes + no)


def _instant(value):
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("Market timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_market_row(row):
    """Normalize one historical snapshot without discarding provenance fields."""
    normalized = dict(row)
    if normalized.get("market_probability") is None:
        if normalized.get("yes_price") is None or normalized.get("no_price") is None:
            raise ValueError("Market snapshot requires market_probability or Yes/No prices")
        normalized["market_probability"] = normalize_binary_prices(
            normalized["yes_price"], normalized["no_price"])
    probability = float(normalized["market_probability"])
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("market_probability must be between zero and one")
    if normalized.get("snapshot_at") is not None:
        normalized["snapshot_at"] = _instant(normalized["snapshot_at"]).isoformat()
    return normalized


def select_snapshot(records, *, market_id=None, team1_id=None, team2_id=None,
                    match_start_at=None, lock_at=None):
    """Select the latest snapshot available before a forecast lock.

    ``match_start_at`` is used when no explicit lock is supplied. A missing
    pre-lock snapshot returns ``None`` instead of using a later price.
    """
    if lock_at is None:
        lock_at = match_start_at
    cutoff = _instant(lock_at) if lock_at is not None else None
    candidates = []
    for raw in records:
        row = normalize_market_row(raw)
        if market_id is not None and str(row.get("market_id")) != str(market_id):
            continue
        ids = {str(row.get("team1_id")), str(row.get("team2_id"))}
        if team1_id is not None and str(team1_id) not in ids:
            continue
        if team2_id is not None and str(team2_id) not in ids:
            continue
        timestamp = _instant(row.get("snapshot_at"))
        if timestamp is None or (cutoff is not None and timestamp > cutoff):
            continue
        candidates.append((timestamp, row))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def blend_probability(data_probability, market_probability, lambda_match):
    lambda_match = float(lambda_match)
    if not 0.0 <= lambda_match <= 1.0:
        raise ValueError("lambda_match must be between 0 and 1")
    data_logit = math.log(_clip(data_probability) / (1.0 - _clip(data_probability)))
    market_logit = math.log(_clip(market_probability) / (1.0 - _clip(market_probability)))
    score = (1.0 - lambda_match) * data_logit + lambda_match * market_logit
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, score))))


@dataclass(frozen=True)
class MatchMarket:
    team1_id: str
    team2_id: str
    market_probability: float
    lambda_match: float
    market_id: str | None = None
    snapshot_at: str | None = None

    def probability_for(self, team1_id, team2_id, data_probability):
        if str(team1_id) == self.team1_id and str(team2_id) == self.team2_id:
            market = self.market_probability
        elif str(team1_id) == self.team2_id and str(team2_id) == self.team1_id:
            market = 1.0 - self.market_probability
        else:
            raise ValueError("Market teams do not match the requested pair")
        return blend_probability(data_probability, market, self.lambda_match)


def _read_records(path):
    path = Path(path)
    if path.suffix.casefold() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("markets") or payload.get("records") or []
    raise ValueError("Market file must contain a JSON array, object, or JSONL")


def load_match_markets(path, lambda_match=0.0, lock_at=None):
    """Load normalized opening-match overlays from JSON or JSONL.

    Rows may provide ``market_probability`` directly or ``yes_price`` and
    ``no_price``.  A row-level ``lambda_match`` takes precedence over the
    command-line default.
    """
    result = {}
    rows = _read_records(path)
    if lock_at is not None:
        grouped = defaultdict(list)
        for row in rows:
            key = frozenset((str(row.get("team1_id") or row.get("team1")),
                             str(row.get("team2_id") or row.get("team2"))))
            grouped[key].append(row)
        rows = [selected for group in grouped.values()
                if (selected := select_snapshot(group, lock_at=lock_at)) is not None]
    for raw_row in rows:
        row = normalize_market_row(raw_row)
        team1_id = str(row.get("team1_id") or row.get("team1"))
        team2_id = str(row.get("team2_id") or row.get("team2"))
        if not team1_id or not team2_id or team1_id == "None" or team2_id == "None":
            raise ValueError("Market row requires team1_id and team2_id")
        probability = float(row["market_probability"])
        market = MatchMarket(team1_id, team2_id, probability,
                             float(row.get("lambda_match", lambda_match)),
                             str(row["market_id"]) if row.get("market_id") is not None else None,
                             row.get("snapshot_at"))
        key = frozenset((team1_id, team2_id))
        if not 0.0 <= market.lambda_match <= 1.0:
            raise ValueError("lambda_match must be between 0 and 1")
        if key in result:
            raise ValueError(f"Duplicate market overlay for {team1_id} and {team2_id}")
        result[key] = market
    return result


