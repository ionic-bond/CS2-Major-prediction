"""Render the Stage 1 result JSON into human-readable Markdown reports."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import fmean

from .prediction import _logit, _sigmoid


def _pct(value):
    return "-" if value is None else f"{value * 100:.2f}%"


def _team_rows(result):
    rows = list(result["team_intermediates"].values())
    return sorted(rows, key=lambda row: (row["seed"], row["name"]))


def _compact_matrix(result, teams):
    matrix = result["core_matrix"]
    ids_by_name = {value["name"]: key for key, value in matrix.items()}
    lines = ["| 队伍 | " + " | ".join(team["name"] for team in teams) + " |",
             "| :--- | " + " | ".join("---:" for _ in teams) + " |"]
    for team in teams:
        row_id = ids_by_name[team["name"]]
        cells = []
        for other in teams:
            if other["name"] == team["name"]:
                cells.append("-")
            else:
                other_id = ids_by_name[other["name"]]
                cells.append(_pct(matrix[row_id]["opponents"][other_id]["bo1"]))
        lines.append("| " + team["name"] + " | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _full_map_matrix(result, teams, map_name):
    matrix = result["core_matrix"]
    ids_by_name = {value["name"]: key for key, value in matrix.items()}
    lines = ["| 队伍 | " + " | ".join(team["name"] for team in teams) + " |",
             "| :--- | " + " | ".join("---:" for _ in teams) + " |"]
    for team in teams:
        row_id = ids_by_name[team["name"]]
        cells = []
        for other in teams:
            if other["name"] == team["name"]:
                cells.append("-")
            else:
                other_id = ids_by_name[other["name"]]
                cells.append(_pct(matrix[row_id]["opponents"][other_id]["maps"][map_name]))
        lines.append("| " + team["name"] + " | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _map_strength_table(matrix, strength_teams, ids_by_name, map_pool):
    lines = ["| 队伍 | " + " | ".join(map_pool) + " |",
             "| :--- | " + " | ".join("---:" for _ in map_pool) + " |"]
    for team in strength_teams:
        opponents = matrix[ids_by_name[team["name"]]]["opponents"].values()
        cells = []
        for map_name in map_pool:
            average_logit = fmean(_logit(row["maps"][map_name]) for row in opponents)
            cells.append(f"{100.0 * _sigmoid(average_logit):.2f}")
        lines.append("| " + team["name"] + " | " + " | ".join(cells) + " |")
    return lines


def _veto_preference_table(strength_teams):
    lines = ["| 队伍 | 常禁地图 | 常选地图 | 禁图总权重 | 选图总权重 |",
             "| :--- | :--- | :--- | ---: | ---: |"]
    for team in strength_teams:
        preferences = team.get("veto_preferences", {})
        columns, totals = [], []
        for action in ("ban", "pick"):
            weights = preferences.get(action, {})
            total = sum(weights.values())
            top_maps = sorted(weights, key=lambda name: (-weights[name], name))[:2]
            entries = [f"{name} ({_pct(weights[name] / total)})"
                       for name in top_maps if weights[name] > 0]
            columns.append("、".join(entries) or "—")
            totals.append(f"{total:.2f}")
        lines.append("| " + " | ".join([team["name"], *columns, *totals]) + " |")
    return lines


def render(result_path, stage_path, readme_path, matrix_path):
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    stage = json.loads(Path(stage_path).read_text(encoding="utf-8"))
    teams = _team_rows(result)
    team_data = result["team_intermediates"]
    ids_by_name = {row["name"]: key for key, row in team_data.items()}
    strength_teams = sorted(teams, key=lambda team: (-team["model_strength_index"], team["name"]))
    recommendations = result["recommendations"]
    lines = [
        "# PGL Major Singapore 2026 Stage 1 Pick'Em",
        "",
        "2026-11-24 至 2026-11-27，16 队进行瑞士轮，8 队晋级 Stage 2。竞猜共 10 个位置，至少命中 5 个即可通过。",
        "",
        "## 推荐组合",
        "",
        "按模型估计的通过概率排列。3-0、3-1/3-2、0-3 分别选 2、6、2 队，每栏按对应的最终战绩计分。",
        "",
        "| 候选 | 3-0 | 3-1/3-2 | 0-3 | 通过概率 | 期望命中 |",
        "| ---: | :--- | :--- | :--- | ---: | ---: |",
    ]
    for index, candidate in enumerate(recommendations, 1):
        slots = {"3-0": [], "advance": [], "0-3": []}
        for pick in candidate["selection"]:
            slots[pick["slot"]].append(pick["name"])
        rank = "**首选**" if index == 1 else str(index)
        lines.append(
            f"| {rank} | {', '.join(slots['3-0'])} | "
            f"{', '.join(slots['advance'])} | {', '.join(slots['0-3'])} | "
            f"{_pct(candidate['pass_probability'])} | {candidate['expected_correct']:.2f}/10 |"
        )
    validation = result.get("validation")
    if validation and validation.get("recommendations"):
        lines += [
            "", "## 独立种子验证", "",
            f"用另一次 {validation['simulations']:,} 条路径的模拟评估上表各组填法。区间反映模拟抽样误差。", "",
            "| 候选 | 独立验证通过概率 | 95% 模拟区间 | 独立验证期望命中 |",
            "| ---: | ---: | :--- | ---: |",
        ]
        for index, row in enumerate(validation["recommendations"], 1):
            low, high = row["confidence_interval_95"]
            lines.append(
                f"| {index} | {_pct(row['pass_probability'])} | "
                f"{_pct(low)} - {_pct(high)} | {row['expected_correct']:.2f}/10 |"
            )
        if len(validation["recommendations"]) > 1:
            runner_up = validation["recommendations"][1]
            if "primary_pass_gap" in runner_up:
                gap = runner_up["primary_pass_gap"]
                low, high = runner_up["primary_pass_gap_interval_95"]
                lines += [
                    "",
                    f"在同一批验证路径上，首选减次选的通过概率差为 {gap * 100:+.3f} 个百分点，"
                    f"95% 模拟区间为 {low * 100:+.3f} 至 {high * 100:+.3f} 个百分点。",
                ]
    lines += [
        "",
        "## 首轮对阵",
        "",
        "表内概率均从左侧队伍 A 的视角读取。赔率融合只用于首轮，随后对阵由瑞士轮模拟产生。",
        "",
        "| 对阵 | A 仅全局实力 | A 完整模型 | A 市场 | 差值（百分点） | A 首轮融合 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["opening_predictions"]:
        team1, team2 = (team_data[row[key]] for key in ("team1_id", "team2_id"))
        probability = row["model_probability"]
        market_probability = row["market_probability"]
        strength_difference = team1["global_score"] - team2["global_score"]
        strength_probability = 1.0 / (1.0 + math.exp(-strength_difference))
        gap = "-" if market_probability is None else f"{(probability - market_probability) * 100:+.2f}"
        lines.append(f"| {team1['name']} vs {team2['name']} | {_pct(strength_probability)} | "
                     f"{_pct(probability)} | {_pct(market_probability)} | {gap} | "
                     f"{_pct(row['blended_probability'])} |")

    lines += [
        "",
        "## 队伍历史与模型强度",
        "",
        "场数和胜率统计预测快照中的 HLTV 实打地图，每张图计入双方各自的记录。模型强度指数将该队对其余 15 队的 BO1 胜率转为对数几率，取平均后换回百分数。",
        "",
        "| 队伍 | 地图场数 | 地图胜率 | 近 90 天地图 | 近 90 天胜率 | 模型强度指数 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in strength_teams:
        lines.append("| {name} | {battles} | {rate} | {recent} | {recent_rate} | {strength:.2f} |".format(
            name=row["name"], battles=row["map_battles"], rate=_pct(row["map_win_rate"]),
            recent=row["recent_map_battles"], recent_rate=_pct(row["recent_map_win_rate"]),
            strength=row["model_strength_index"]))

    lines += [
        "", "## 逐图模型强度", "",
        "每张图取该队对其余 15 队的单图胜率，先平均对数几率，再换算成与综合强度同口径的 0–100 指数。50 对应平均对数几率为零。",
        "",
        *_map_strength_table(result["core_matrix"], strength_teams, ids_by_name, result["map_pool"]),
    ]
    if any("veto_preferences" in row for row in strength_teams):
        lines += [
            "", "## 队伍 BP 偏好", "",
            "历史禁图和选图记录以 75 天为半衰期，并按与本届阵容的重合度折算。"
            "禁图和选图各列出当前七图池中权重最高的两张，括号是该图占同类动作总权重的比例。"
            "总权重反映经衰减和阵容折算后的记录量。",
            "",
            *_veto_preference_table(strength_teams),
        ]

    lines += ["", "## 队伍 BO1 胜率矩阵", "", _compact_matrix(result, teams),
              "", "分地图的胜率见 [完整矩阵](matrix_3d.md)。",
              "", "## 瑞士轮各战绩概率", "",
              "瑞士轮模拟结合赛前实力、队伍阶段状态和官方配对规则。[Valve 瑞士轮规则](https://github.com/ValveSoftware/counter-strike_rules_and_regs/blob/main/major-supplemental-rulebook.md#swiss-bracket)", "",
              "| 队伍 | 3-0 | 3-1/3-2 | 0-3 | 1-3 / 2-3 |",
              "| :--- | ---: | ---: | ---: | ---: |"]
    for team in teams:
        row = result["marginals"][ids_by_name[team["name"]]]
        eliminated = 1 - row["3-0"] - row["advance"] - row["0-3"]
        lines.append(f"| {team['name']} | {_pct(row['3-0'])} | {_pct(row['advance'])} | {_pct(row['0-3'])} | {_pct(eliminated)} |")

    search = result["search"]
    search_count = search["search_simulations"]
    candidate_k = search["candidate_k"]
    lines += [
        "",
        "## 数据与计算",
        "",
        f"用 {search_count:,} 条瑞士轮路径搜索竞猜组合，每种槽位取边际概率最高的 {candidate_k} 队作为候选，"
        f"最终在 {result['simulations']:,} 条主路径上评估入围组合。",
    ]
    if result["opening_market_count"]:
        lines += [
            "",
            f"首轮使用 {result['opening_market_count']} 场 Polymarket 盘口，冻结价格的时间为 "
            f"`{result['market_snapshot_at']}`。赔率以 {result['market_lambda_match']:.2f} 的权重融合到对数几率。",
        ]
    lines += [
        "",
        "模型以赛前 HLTV 战绩和五人阵容估计队伍实力，并用 Valve VRS 约束不同赛程之间的实力比较。"
        "选图按官方 BO1/BO3 流程模拟，两种 BP 顺序各占 50%。",
        "",
        "[模型与运行参数](model.md) · [全局实力与 VRS](vrs.md) · [冻结赔率](market_history.json) · "
        "[阶段配置](stage.json) · [正式结果](result.json)",
    ]
    Path(readme_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    matrix_lines = ["# Stage 1 完整三维胜率矩阵", "", "本文件展示队伍、对手和地图三个维度。每个表格的行是左侧队伍，列是对手，单元格是该行队伍在对应地图上的胜率。", ""]
    for map_name in stage["map_pool"]:
        matrix_lines += [f"## {map_name}", "", _full_map_matrix(result, teams, map_name), ""]
    Path(matrix_path).write_text("\n".join(matrix_lines) + "\n", encoding="utf-8")

