"""Render the Stage 2 results, matchup tables, and map matrix."""

from __future__ import annotations

import json
from pathlib import Path

from ..stage1.report import (
    _compact_matrix, _full_map_matrix, _map_strength_table, _pct, _veto_preference_table,
)


def render(result_path, stage_path, readme_path, matrix_path):
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    stage = json.loads(Path(stage_path).read_text(encoding="utf-8"))
    by_id = result["team_intermediates"]
    teams = sorted(by_id.values(), key=lambda team: team["seed"])
    by_strength = sorted(teams, key=lambda team: (-team["model_strength_index"], team["seed"]))
    ids_by_name = {team["name"]: team_id for team_id, team in by_id.items()}
    validated = result.get("validation", {}).get("recommendations", [])
    inputs = result["previous_stage_training"]
    prior = result["model"]["global_strength"]["prior"]
    search = result["search"]
    lines = [
        f"# {stage['stage']} Pick'Em", "",
        f"{stage['starts_on']} 至 {stage['ends_on']}，16 队进行瑞士轮，8 队晋级 Stage 3。"
        "在 2 个 3–0、6 个 3–1/3–2、2 个 0–3 位置中至少猜中 5 个即通过。",
        "", "## 推荐组合", "",
        "候选按主模拟通过率排列。独立模拟重新估计每个固定组合的通过率。",
        "", "| 候选 | 3–0 | 3–1/3–2 | 0–3 | 主模拟通过率 | 期望命中 | 独立验证通过率 |",
        "| ---: | :--- | :--- | :--- | ---: | ---: | ---: |",
    ]
    for index, candidate in enumerate(result["recommendations"]):
        picks = {"3-0": [], "advance": [], "0-3": []}
        for row in candidate["selection"]:
            picks[row["slot"]].append(by_id[row["team_id"]]["name"])
        first = "**首选**" if index == 0 else str(index + 1)
        comparison = _pct(validated[index]["pass_probability"]) if validated else "—"
        lines.append(
            f"| {first} | {'、'.join(picks['3-0'])} | {'、'.join(picks['advance'])} | "
            f"{'、'.join(picks['0-3'])} | {_pct(candidate['pass_probability'])} | "
            f"{candidate['expected_correct']:.2f}/10 | {comparison} |"
        )
    if validated:
        low, high = validated[0]["confidence_interval_95"]
        lines += ["", f"首选的 95% 模拟区间为 {_pct(low)} 至 {_pct(high)}，对应抽样误差。"]
        if len(validated) > 1:
            runner_up = validated[1]
            gap = runner_up["primary_pass_gap"]
            low, high = runner_up["primary_pass_gap_interval_95"]
            lines.append(f"首选与次选的通过率差在同一批验证路径上为 {gap * 100:+.3f} 个百分点，"
                         f"95% 模拟区间为 {low * 100:+.3f} 至 {high * 100:+.3f} 个百分点。")

    lines += [
        "", "## 首轮对阵", "",
        "概率从左侧队伍的视角读取。模型概率对赛前地图池和 BP 倾向取平均，盘口只用于首轮。",
        "", "| 对阵 | 开赛时间 UTC | 数据模型 | 市场 | 融合 |",
        "| :--- | :--- | ---: | ---: | ---: |",
    ]
    for row in result["opening_predictions"]:
        left, right = (by_id[row[field]]["name"] for field in ("team1_id", "team2_id"))
        lines.append(f"| {left} vs {right} | {row['start'][11:16]} | {_pct(row['model_probability'])} | "
                     f"{_pct(row['market_probability'])} | {_pct(row['blended_probability'])} |")

    lines += [
        "", "## 队伍强度与瑞士轮战绩", "",
        "强度指数为对其余 15 队的 BO1 胜率在对数几率上取平均后折回 0–100。"
        "历史地图胜率直接统计赛前记录中的实打地图。",
        "", "| 队伍 | 种子 | 地图场数 | 地图胜率 | 强度指数 | 3–0 | 3–1/3–2 | 总晋级 | 0–3 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for team in by_strength:
        row = result["marginals"][ids_by_name[team["name"]]]
        lines.append(
            f"| {team['name']} | {team['seed']} | {team['map_battles']} | {_pct(team['map_win_rate'])} | "
            f"{team['model_strength_index']:.2f} | {_pct(row['3-0'])} | {_pct(row['advance'])} | "
            f"{_pct(row['3-0'] + row['advance'])} | {_pct(row['0-3'])} |"
        )

    lines += [
        "", "## 逐图模型强度", "",
        "每张图按对其余 15 队的单图胜率计算强度指数，50 对应平均对数几率为零。",
        "", *_map_strength_table(result["core_matrix"], by_strength, ids_by_name, result["map_pool"]),
        "", "## 队伍 BP 偏好", "",
        "按时间和阵容重合度加权后，各列出占比最高的两张禁图和选图。",
        "", *_veto_preference_table(by_strength),
        "", "## 队伍 BO1 胜率矩阵", "",
        "行是预测胜方，列是对手。BO3 概率见结果 JSON，分地图概率见完整矩阵。",
        "", _compact_matrix(result, teams),
        "", "## 数据与运行", "",
        f"以 `{result['cutoff']}` 为赛前截止，拟合使用 {result['model']['examples']:,} 张地图。"
        f"本届 Stage 1 的 {inputs['series']} 场、{inputs['maps']} 张图都纳入训练，"
        f"其中 {inputs['maps_exempted_from_post_vrs_discount']} 张免除 VRS 截止后折扣。"
        f"全球 VRS 快照为 {prior['vrs_date']}，先验系数为 **{prior['strength']:g}**。",
        "", f"数据清单 SHA-256 为 `{result['manifest_sha256']}`。",
        "",
        f"主模拟 {result['simulations']:,} 条路径，取其中 {search['search_simulations']:,} 条搜索候选。"
        f"每个槽位的候选池按边际概率截取前 {search['candidate_k']} 队。",
    ]
    if validated:
        lines[-1] += f"独立验证另用 {result['validation']['simulations']:,} 条路径。"
    if result["opening_market_count"]:
        lines += [
            "", f"首轮使用 {result['opening_market_count']} 场 Polymarket 数据，"
            f"所用的最晚时间桶为 `{result['market_snapshot_at']}`，"
            f"市场在对数几率上的系数为 {result['market_lambda_match']:.2f}。",
        ]
    lines += [
        "", "[模型与复跑命令](model.md) · [阶段配置](stage.json) · [冻结赔率](market_history.json) · "
        "[结果 JSON](result.json) · [完整地图矩阵](matrix_3d.md)",
        "", f"[官方瑞士轮规则]({stage['sources']['seeding']}) · [首轮赛程]({stage['sources']['opening_matches']})",
    ]
    Path(readme_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    matrix = [f"# {stage['stage']} 逐图胜率矩阵", "",
              "每个单元格给出行队伍在该地图上击败列队伍的概率。"]
    for map_name in result["map_pool"]:
        matrix += ["", f"## {map_name}", "", _full_map_matrix(result, teams, map_name)]
    Path(matrix_path).write_text("\n".join(matrix) + "\n", encoding="utf-8")
