"""Run the PGL Major Singapore 2026 Stage 1 prediction and render its reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from data.pipeline.core import atomic_write, json_bytes
from data.pipeline.dataset import Dataset

from .prediction import run_stage_prediction
from .report import render


STAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = STAGE_DIR.parents[1] / "data"


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def nonnegative_float(value):
    result = float(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return result


def unit_float(value):
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return result


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m 2026_singapore.stage1.run")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    commands = parser.add_subparsers(dest="command", required=True)

    predict = commands.add_parser("predict-stage", help="simulate Stage 1 and search Pick'Em")
    predict.add_argument("--stage-file", type=Path, default=STAGE_DIR / "stage.json")
    predict.add_argument("--simulations", type=positive_int, default=10000)
    predict.add_argument("--seed", type=int, default=0)
    predict.add_argument("--epochs", type=positive_int, default=14)
    predict.add_argument("--l2", type=nonnegative_float, default=0.04)
    predict.add_argument("--market-file", type=Path)
    predict.add_argument("--lambda-match", type=unit_float, default=0.0)
    predict.add_argument("--market-lock-at",
                         help="use the latest market snapshots at or before this UTC instant")
    predict.add_argument("--candidate-k", type=positive_int, default=12,
                         help="number of marginal candidates retained in the exact search")
    predict.add_argument("--search-simulations", type=positive_int, default=5000,
                         help="paths used by exact search before full-sample remeasurement")
    predict.add_argument("--roster-overlap-exponent", type=nonnegative_float, default=1.5)
    predict.add_argument("--opponent-saturation-exponent", type=nonnegative_float, default=0.5)
    predict.add_argument("--strength-uncertainty-scale", type=nonnegative_float, default=1.0)
    predict.add_argument("--validation-simulations", type=positive_int, default=0,
                         help="independent paths used to measure fixed recommendations")
    predict.add_argument("--validation-seed", type=int)
    predict.add_argument("--workers", type=positive_int, default=1,
                         help="parallel worker processes for primary and validation paths")
    predict.add_argument("--output", type=Path)

    report = commands.add_parser("render-report", help="从 result.json 生成 README 和完整三维矩阵")
    report.add_argument("--result-file", type=Path, default=STAGE_DIR / "result.json")
    report.add_argument("--stage-file", type=Path, default=STAGE_DIR / "stage.json")
    report.add_argument("--readme", type=Path, default=STAGE_DIR / "README.md")
    report.add_argument("--matrix", type=Path, default=STAGE_DIR / "matrix_3d.md")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = {"stage": "2026_singapore_stage1", "command": args.command,
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if args.command == "render-report":
        render(args.result_file, args.stage_file, args.readme, args.matrix)
        report["result"] = {"readme": str(args.readme.resolve()), "matrix": str(args.matrix.resolve())}
    else:
        dataset = Dataset(args.data_dir.resolve())
        result = run_stage_prediction(
            dataset, args.stage_file, simulations=args.simulations, seed=args.seed,
            epochs=args.epochs, l2=args.l2, market_file=args.market_file,
            lambda_match=args.lambda_match, market_lock_at=args.market_lock_at,
            candidate_k=args.candidate_k, search_simulations=args.search_simulations,
            roster_overlap_exponent=args.roster_overlap_exponent,
            opponent_saturation_exponent=args.opponent_saturation_exponent,
            strength_uncertainty_scale=args.strength_uncertainty_scale,
            validation_simulations=args.validation_simulations, validation_seed=args.validation_seed,
            workers=args.workers)
        result["manifest_sha256"] = report["manifest_sha256"] = dataset.manifest_sha256
        report["result"] = result
        if args.output:
            output = args.output.resolve()
            atomic_write(output, json_bytes(result))
            report["result_file"] = str(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
