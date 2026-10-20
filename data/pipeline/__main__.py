"""Command-line entry point for the shared dataset."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import urlencode

from .bo3 import BASE_URL, sync_matches
from .hltv import sync_matches as sync_hltv
from .hltv_browser import HltvBrowser
from .core import (DEFAULT_ROOT, FetchError, HttpCache, Store, atomic_write, export_snapshot,
                   import_legacy, json_bytes, quality_report, sync_rankings, utc_now, valid_date)


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


def parser():
    cli = argparse.ArgumentParser(prog="python -m data.pipeline",
                                  description="跨 Major 共用的比赛、地图、选手与 VRS 数据采集（HLTV 浏览器为可选依赖）")
    cli.add_argument("--data-dir", type=Path, default=DEFAULT_ROOT)
    cli.add_argument("--offline", action="store_true", help="只使用已缓存的响应")
    cli.add_argument("--interval", type=nonnegative_float, default=1.0, help="请求最小间隔秒数，默认 1")
    cli.add_argument("--timeout", type=positive_int, default=20)
    cli.add_argument("--retries", type=int, choices=range(0, 6), default=2)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("import-legacy", "sync", "sync-hltv", "rankings", "status", "export"):
        command = commands.add_parser(name)
        today = datetime.now(timezone.utc).date()
        command.add_argument("--since", type=valid_date, default=(today - timedelta(days=365)).isoformat())
        command.add_argument("--until", type=valid_date, default=today.isoformat())
        if name == "import-legacy":
            command.add_argument("--directory", type=Path,
                                 default=DEFAULT_ROOT.parent / "2026_cologne/stage3/data")
        elif name in ("sync", "sync-hltv"):
            command.add_argument("--max-matches", type=positive_int, default=5 if name == "sync-hltv" else 25,
                                 help="本次最多尝试采集的场数；再次运行会跳过完整记录")
            command.add_argument("--max-pages", type=positive_int, default=100)
            command.add_argument("--refresh", action="store_true", help="重取已有比赛和统计；适合刷新最近两天")
            if name == "sync":
                command.add_argument("--page-size", type=positive_int, default=50)
                command.add_argument("--rounds", action="store_true", help="同时缓存逐回合原始数据")
            else:
                command.add_argument("--match-url", action="append", help="只取指定比赛；可重复提供，仍检查日期范围")
                command.add_argument("--browser", type=Path, help="Chrome/Edge 可执行文件，默认自动寻找")
                command.add_argument("--headless", action="store_true", help="尝试无头模式；默认使用已验证的普通隐藏窗口")
                command.add_argument("--browser-proxy", choices=("direct", "system", "environment"), default="direct")
                command.add_argument("--page-wait", type=positive_int, default=45, help="每页等待上限秒数")
        elif name == "rankings":
            command.add_argument("--history", action="store_true", help="采集范围内全部历史快照，默认各区域最新一期")
        elif name == "export":
            command.add_argument("--event", help="快照用途标记，例如 2026_singapore；不会推断参赛队")
    commands.add_parser("probe", help="验证 BO3 比赛及选手接口、Valve 官方仓库连接")
    return cli


def probe(http):
    params = {"scope": "widget-matches", "page[limit]": 1, "page[offset]": 0,
              "sort": "-start_date,-id", "filter[matches.status][in]": "finished",
              "filter[matches.discipline_id][eq]": 1, "with": "teams,tournament,games"}
    payload, _ = http.get_json(BASE_URL + "/matches?" + urlencode(params), refresh=True)
    match = payload["results"][0]
    games = [g for g in match.get("games", []) if g.get("state") == "done" or g.get("status") == "finished"]
    if not games:
        raise ValueError("Latest BO3 result has no completed games; use sync to inspect more results")
    players, _ = http.get_json(BASE_URL + "/games/" + str(games[0]["id"]) + "/players_stats", refresh=True)
    ref, _ = http.get_json("https://api.github.com/repos/ValveSoftware/counter-strike_regional_standings/git/ref/heads/main",
                           refresh=True)
    return {"bo3": {"match_id": match["id"], "date": match["start_date"], "slug": match["slug"],
                    "map_player_rows": len(players), "sample_fields": sorted(players[0]) if players else [],
                    "player_stats_available": bool(players)}, "valve_git_commit": ref["object"]["sha"]}


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if hasattr(args, "since") and args.since > args.until:
        cli.error("--since must not be after --until")
    if args.command == "sync" and args.page_size > 100:
        cli.error("--page-size must not exceed 100")
    root = args.data_dir.resolve()
    http = HttpCache(root, offline=args.offline, interval=args.interval, timeout=args.timeout, retries=args.retries)
    if args.command == "sync-hltv":
        http = HltvBrowser(root, offline=args.offline, interval=max(2, args.interval), timeout=args.timeout,
                           retries=0, browser=args.browser, headless=args.headless, proxy=args.browser_proxy,
                           page_wait=args.page_wait)
    report = {"schema_version": 1, "command": args.command, "started_at": utc_now(), "status": "running"}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.command
    code = 0
    try:
        with Store(root) as store:
            if args.command == "import-legacy":
                report["result"] = import_legacy(store, args.directory, args.since, args.until)
                if report["result"]["rejected"]:
                    report["status"], code = "partial", 1
            elif args.command in ("sync", "sync-hltv"):
                if args.command == "sync":
                    report["result"] = sync_matches(store, http, args.since, args.until, max_matches=args.max_matches,
                                                    max_pages=args.max_pages, page_size=args.page_size,
                                                    refresh=args.refresh, rounds=args.rounds)
                else:
                    report["result"] = sync_hltv(store, http, args.since, args.until, max_matches=args.max_matches,
                                                 max_pages=args.max_pages, refresh=args.refresh, urls=args.match_url)
                result = report["result"]
                if result["errors"] or result["stats_missing_matches"] or result["pending_unchanged"]:
                    report["status"], code = "partial", 1
                elif not result["window_complete"] and not result.get("requested_urls_complete"):
                    report["status"] = "bounded"
            elif args.command == "rankings":
                report["result"] = sync_rankings(store, http, args.since, args.until, history=args.history)
            elif args.command == "export":
                report["result"] = export_snapshot(store, args.since, args.until)
                if args.event:
                    manifest_path = Path(report["result"]["snapshot"]) / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["event"] = args.event
                    atomic_write(manifest_path, json_bytes(manifest))
            elif args.command == "probe":
                report["result"] = probe(http)
                if not report["result"]["bo3"]["player_stats_available"]:
                    report["status"], code = "partial", 1
            if hasattr(args, "since"):
                report["quality"] = quality_report(store, args.since, args.until)
            report["database"] = store.summary()
        if report["status"] == "running":
            report["status"] = "ok"
    except (FetchError, ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        code = 1
    except KeyboardInterrupt:
        report.update(status="interrupted", error="Interrupted; committed matches and raw responses remain reusable")
        code = 130
    finally:
        if isinstance(http, HltvBrowser):
            try:
                http.close()
            except (OSError, subprocess.SubprocessError) as error:
                report.update(status="failed", error="Browser cleanup failed: " + str(error))
                code = 1
            report["browser_lifecycle"] = http.lifecycle
    report["finished_at"] = utc_now()
    report["requests"] = http.requests
    path = root / "reports" / "runs" / (run_id + ".json")
    atomic_write(path, json_bytes(report))
    if args.command not in ("status", "export"):
        atomic_write(root / "reports" / "latest.json", json_bytes(report))
    print(json.dumps({key: value for key, value in report.items() if key != "requests"}, ensure_ascii=False, indent=2))
    print("Report: " + str(path))
    return code


if __name__ == "__main__":
    sys.exit(main())
