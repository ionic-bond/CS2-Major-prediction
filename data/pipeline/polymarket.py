"""Collect public Polymarket CLOB price-history snapshots.

The collector stores paired Yes/No token prices and the source response
metadata. It does not claim to reconstruct historical order books because the
public price-history endpoint exposes traded/mid-price observations only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode

from .core import DEFAULT_ROOT, FetchError, HttpCache, atomic_write, json_bytes, utc_now


GAMMA_MARKET_URL = "https://gamma-api.polymarket.com/markets/{}"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"


def _jsonish(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _market_rows(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("markets") or payload.get("records") or []
    raise ValueError("Market file must contain an array or an object with markets")


def _outcome_tokens(payload):
    tokens = payload.get("clobTokenIds") or payload.get("clob_token_ids")
    tokens = _jsonish(tokens)
    outcomes = _jsonish(payload.get("outcomes"))
    if isinstance(tokens, dict):
        return {str(key).casefold(): str(value) for key, value in tokens.items()}
    if not isinstance(tokens, list) or len(tokens) < 2:
        token_rows = payload.get("tokens") or []
        if isinstance(token_rows, list):
            pairs = {}
            for row in token_rows:
                if not isinstance(row, dict):
                    continue
                outcome = str(row.get("outcome") or row.get("name") or "").casefold()
                token = row.get("token_id") or row.get("tokenId") or row.get("id")
                if outcome and token is not None:
                    pairs[outcome] = str(token)
            if len(pairs) >= 2:
                return pairs
        return {}
    if isinstance(outcomes, list) and len(outcomes) == len(tokens):
        pairs = {str(outcome).casefold(): str(token)
                 for outcome, token in zip(outcomes, tokens)}
        if "yes" in pairs and "no" in pairs:
            return {"yes": pairs["yes"], "no": pairs["no"]}
        if len(tokens) == 2:
            return {"yes": str(tokens[0]), "no": str(tokens[1])}
        return pairs
    return {"yes": str(tokens[0]), "no": str(tokens[1])}


def _resolve_market(row, http, refresh=False):
    direct = _outcome_tokens(row)
    metadata = dict(row)
    if "yes" in direct and "no" in direct:
        return metadata, direct
    market_id = row.get("condition_id") or row.get("conditionId") or row.get("market_id")
    if market_id is None:
        raise ValueError("Market row needs market_id or token IDs")
    try:
        payload, response = http.get_json(GAMMA_MARKET_URL.format(market_id), refresh=refresh)
    except FetchError:
        slug = row.get("market_slug") or row.get("slug")
        if not slug:
            raise
        query = urlencode({"slug": str(slug)})
        payload, response = http.get_json(GAMMA_MARKETS_URL + "?" + query, refresh=refresh)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise FetchError(f"Gamma market response is not an object: {market_id}")
    merged = {**payload, **metadata}
    tokens = _outcome_tokens(payload)
    if "yes" not in tokens or "no" not in tokens:
        raise ValueError(f"Gamma market has no Yes/No token pair: {market_id}")
    merged["gamma_source_url"] = response.get("url")
    return merged, tokens


def _history(payload):
    if isinstance(payload, dict):
        payload = payload.get("history") or payload.get("prices") or []
    if not isinstance(payload, list):
        raise FetchError("CLOB prices-history response has no history array")
    result = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("t") or row.get("timestamp") or row.get("ts")
        price = row.get("p") if row.get("p") is not None else row.get("price")
        if timestamp is None or price is None:
            continue
        result.append((int(float(timestamp)), float(price)))
    return result


def _fetch_history(http, token_id, start_ts=None, end_ts=None, interval=None,
                   fidelity=None, refresh=False):
    params = {"market": str(token_id)}
    if start_ts is not None:
        params["startTs"] = int(start_ts)
    if end_ts is not None:
        params["endTs"] = int(end_ts)
    if interval:
        params["interval"] = interval
    if fidelity is not None:
        params["fidelity"] = int(fidelity)
    url = CLOB_HISTORY_URL + "?" + urlencode(params)
    payload, response = http.get_json(url, refresh=refresh)
    return _history(payload), response, url


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _paired_rows(yes_history, no_history, bucket_seconds, metadata, token_ids):
    yes_by_bucket = {timestamp // bucket_seconds: price for timestamp, price in yes_history}
    no_by_bucket = {timestamp // bucket_seconds: price for timestamp, price in no_history}
    rows = []
    for bucket in sorted(set(yes_by_bucket).intersection(no_by_bucket)):
        yes = yes_by_bucket[bucket]
        no = no_by_bucket[bucket]
        if not 0.0 <= yes <= 1.0 or not 0.0 <= no <= 1.0 or yes + no <= 0.0:
            continue
        rows.append({
            "market_id": str(metadata.get("market_id") or metadata.get("condition_id") or ""),
            "market_slug": metadata.get("market_slug") or metadata.get("slug"),
            "team1_id": metadata.get("team1_id"),
            "team2_id": metadata.get("team2_id"),
            "yes_token_id": token_ids["yes"],
            "no_token_id": token_ids["no"],
            "snapshot_at": _iso(bucket * bucket_seconds),
            "time_bucket": f"{bucket_seconds}s",
            "yes_price": yes,
            "no_price": no,
            "market_probability": yes / (yes + no),
            "price_pair_complete": True,
            "liquidity": metadata.get("liquidity"),
            "volume": metadata.get("volume") or metadata.get("volumeNum"),
            "spread": metadata.get("spread"),
            "source": "polymarket_clob_prices_history",
        })
    return rows


def collect_history(market_file, output, *, root=DEFAULT_ROOT, start_ts=None,
                    end_ts=None, interval="1h", fidelity=None, bucket_seconds=3600,
                    offline=False, refresh=False, interval_seconds=1.0,
                    timeout=20, retries=2):
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    http = HttpCache(root, offline=offline, interval=interval_seconds,
                     timeout=timeout, retries=retries)
    snapshots = []
    resolved = []
    for source_row in _market_rows(market_file):
        metadata, token_ids = _resolve_market(source_row, http, refresh=refresh)
        yes_history, yes_response, yes_url = _fetch_history(
            http, token_ids["yes"], start_ts, end_ts, interval, fidelity, refresh)
        no_history, no_response, no_url = _fetch_history(
            http, token_ids["no"], start_ts, end_ts, interval, fidelity, refresh)
        rows = _paired_rows(yes_history, no_history, bucket_seconds, metadata, token_ids)
        for row in rows:
            row["yes_source"] = {"url": yes_url, "sha256": yes_response.get("sha256"),
                                  "fetched_at": yes_response.get("fetched_at")}
            row["no_source"] = {"url": no_url, "sha256": no_response.get("sha256"),
                                 "fetched_at": no_response.get("fetched_at")}
        snapshots.extend(rows)
        resolved.append({"market_id": row.get("market_id") if rows else metadata.get("market_id"),
                         "yes_token_id": token_ids["yes"], "no_token_id": token_ids["no"],
                         "yes_points": len(yes_history), "no_points": len(no_history),
                         "paired_points": len(rows)})
    result = {
        "schema_version": 1,
        "source": "polymarket_clob_prices_history",
        "collected_at": utc_now(),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "interval": interval,
        "fidelity": fidelity,
        "bucket_seconds": bucket_seconds,
        "market_file": str(Path(market_file).resolve()),
        "markets": snapshots,
        "resolved_markets": resolved,
        "requests": http.requests,
        "note": "Prices-history supplies paired token prices. Historical order-book depth and spread are not reconstructed.",
    }
    atomic_write(Path(output), json_bytes(result))
    return result


def _parser():
    parser = argparse.ArgumentParser(prog="python -m data.pipeline.polymarket")
    parser.add_argument("--market-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--fidelity", type=int)
    parser.add_argument("--bucket-seconds", type=int, default=3600)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--request-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    result = collect_history(
        args.market_file, args.output, root=args.data_dir.resolve(),
        start_ts=args.start_ts, end_ts=args.end_ts, interval=args.interval,
        fidelity=args.fidelity, bucket_seconds=args.bucket_seconds,
        offline=args.offline, refresh=args.refresh,
        interval_seconds=args.request_interval, timeout=args.timeout,
        retries=args.retries)
    print(json.dumps({"output": str(args.output.resolve()),
                      "markets": len(result["resolved_markets"]),
                      "snapshots": len(result["markets"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
