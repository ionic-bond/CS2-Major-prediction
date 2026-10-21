"""Command-line entry point for the shared dataset."""

import argparse
from contextlib import nullcontext
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
from .core import (DEFAULT_ROOT, FetchError, HttpCache, Store, atomic_write, digest, export_snapshot,
                   import_legacy, json_bytes, quality_report, sync_rankings, utc_now, valid_date)
from .dataset import (Dataset, database_path, dataset_directory, export_dataset,
                      prepare_working_database, restore_database)


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
                command.add_argument("--match-urls-file", type=Path, help="UTF-8 比赛 URL 清单，每行一个；仍检查日期范围")
                command.add_argument("--replace-legacy", action="store_true",
                                     help="用直接采集数据替换同 ID 的旧 HLTV 导入；先归档旧比赛及选手记录")
                command.add_argument("--allow-partial-legacy", action="append", metavar="HLTV_ID",
                                     help="经核实源站缺表的指定比赛允许部分替换，例如 hltv:123；须同时使用 --replace-legacy")
                command.add_argument("--browser", type=Path, help="Chrome/Edge 可执行文件，默认自动寻找")
                command.add_argument("--headless", action="store_true", help="尝试无头模式；默认使用已验证的普通隐藏窗口")
                command.add_argument("--browser-proxy", choices=("direct", "system", "environment"), default="direct")
                command.add_argument("--page-wait", type=positive_int, default=45, help="每页等待上限秒数")
                command.add_argument("--stop-file", type=Path,
                                     help="此文件出现时，在当前页面/比赛处理完后安全暂停；续跑前移除")
        elif name == "rankings":
            command.add_argument("--history", action="store_true", help="采集范围内全部历史快照，默认各区域最新一期")
        elif name == "export":
            command.add_argument("--event", help="快照用途标记，例如 2026_singapore；不会推断参赛队")
    commands.add_parser("probe", help="验证 BO3 比赛及选手接口、Valve 官方仓库连接")
    commands.add_parser("export-data", help="将全部已提交的工作库记录导出为 Git 共享的 JSONL")
    commands.add_parser("verify-data", help="校验规范 JSONL 数据，不创建 SQLite")
    restore = commands.add_parser("restore-db", help="从规范 JSONL 恢复本地采集工作库")
    restore.add_argument("--replace", action="store_true", help="先备份已有工作库，再替换")
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
    if hasattr(args, "since"):
        report["window"] = {"since": args.since, "until": args.until, "timezone": "UTC"}
    if args.command == "sync-hltv" and args.stop_file:
        args.stop_file = args.stop_file.resolve()
        report["stop_file"] = str(args.stop_file)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.command
    code = 0
    collection_commands = {"import-legacy", "sync", "sync-hltv", "rankings"}
    collection_started = False
    try:
        if args.command in collection_commands:
            prepare_working_database(root)
            collection_started = True
        if args.command == "verify-data":
            report["result"] = Dataset(root).verify()
        elif args.command == "restore-db":
            report["result"] = restore_database(root, replace=args.replace)
        elif args.command == "probe":
            report["result"] = probe(http)
            if not report["result"]["bo3"]["player_stats_available"]:
                report["status"], code = "partial", 1
        else:
            if args.command == "export-data":
                if not database_path(root).exists():
                    raise ValueError("No work database to export; use restore-db or collect data first")
                prepare_working_database(root)
            use_jsonl = (args.command in ("status", "export") and
                         (dataset_directory(root) / "manifest.json").exists())
            context = nullcontext(Dataset(root)) if use_jsonl else Store(root)
            report["data_backend"] = "jsonl" if use_jsonl else "sqlite"
            with context as store:
                run_with_store(args, store, http, report)
                if hasattr(args, "since"):
                    report["quality"] = quality_report(store, args.since, args.until)
                report["database"] = store.summary()
        if report["status"] == "running":
            report["status"] = "ok"
        if report["status"] == "partial":
            code = 1
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
        if collection_started and database_path(root).exists():
            try:
                # Store has closed: only records committed before a pause/error are published.
                with Store(root) as store:
                    report["dataset_export"] = export_dataset(store)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
                report["dataset_export_error"] = f"{type(error).__name__}: {error}"
                report["status"], code = "failed", 1
    report["finished_at"] = utc_now()
    report["requests"] = http.requests
    path = root / "reports" / "runs" / (run_id + ".json")
    atomic_write(path, json_bytes(report))
    if args.command in collection_commands or args.command == "probe":
        atomic_write(root / "reports" / "latest.json", json_bytes(report))
    print(json.dumps({key: value for key, value in report.items() if key != "requests"}, ensure_ascii=False, indent=2))
    print("Report: " + str(path))
    return code


def run_with_store(args, store, http, report):
    """Dispatch commands that use a work database or the direct JSONL reader."""
    if args.command == "import-legacy":
        report["result"] = import_legacy(store, args.directory, args.since, args.until)
        if report["result"]["rejected"]:
            report["status"] = "partial"
    elif args.command in ("sync", "sync-hltv"):
        if args.command == "sync":
            report["result"] = sync_matches(store, http, args.since, args.until, max_matches=args.max_matches,
                                            max_pages=args.max_pages, page_size=args.page_size,
                                            refresh=args.refresh, rounds=args.rounds)
        else:
            urls = args.match_url
            if args.match_urls_file:
                manifest = args.match_urls_file.resolve()
                body = manifest.read_bytes()
                urls = (urls or []) + [line.strip() for line in body.decode("utf-8-sig").splitlines() if line.strip()]
                if not urls:
                    raise ValueError("Match URL manifest is empty; refusing implicit result discovery")
                report["match_urls_file"] = {"path": str(manifest), "sha256": digest(body)}
            report["result"] = sync_hltv(store, http, args.since, args.until, max_matches=args.max_matches,
                                         max_pages=args.max_pages, refresh=args.refresh, urls=urls,
                                         stop_requested=args.stop_file.exists if args.stop_file else None,
                                         replace_legacy=args.replace_legacy,
                                         allow_partial_legacy=args.allow_partial_legacy)
        result = report["result"]
        if result.get("stop_reason") == "stop_requested":
            report["status"] = "paused"
        elif result["errors"] or result["stats_missing_matches"] or result["pending_unchanged"]:
            report["status"] = "partial"
        elif not result["window_complete"] and not result.get("requested_urls_complete"):
            report["status"] = "bounded"
    elif args.command == "rankings":
        report["result"] = sync_rankings(store, http, args.since, args.until, history=args.history)
    elif args.command == "export-data":
        report["result"] = export_dataset(store)
    elif args.command == "export":
        report["result"] = export_snapshot(store, args.since, args.until)
        if args.event:
            manifest_path = Path(report["result"]["snapshot"]) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["event"] = args.event
            atomic_write(manifest_path, json_bytes(manifest))


if __name__ == "__main__":
    sys.exit(main())
