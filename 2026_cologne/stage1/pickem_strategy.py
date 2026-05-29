"""
IEM Cologne Major 2026 - Stage 1 Pick'Em 策略模拟
"""
import random
import math

random.seed(42)
SIMULATIONS = 200000

# ==================== 各队概率估计 ====================
# 基于综合分析(HLTV排名+近期战绩+Polymarket赔率)

team_probs = {
    #                    晋级概率   3-0概率   0-3概率
    "GamerLegion":      (0.93,     0.28,     0.00),
    "BetBoom":          (0.88,     0.22,     0.00),
    "B8":               (0.83,     0.15,     0.01),
    "Heroic":           (0.72,     0.10,     0.02),
    "TYLOO":            (0.68,     0.09,     0.03),
    "Team Liquid":      (0.62,     0.07,     0.04),
    "BIG":              (0.58,     0.06,     0.05),
    "SINNERS":          (0.52,     0.05,     0.06),
    # --- 晋级线 ---
    "MIBR":             (0.48,     0.04,     0.08),
    "M80":              (0.42,     0.03,     0.10),
    "NRG":              (0.28,     0.02,     0.18),
    "Lynn Vision":      (0.20,     0.01,     0.25),
    "Sharks":           (0.15,     0.01,     0.32),
    "Gaimin Gladiators":(0.12,     0.01,     0.38),
    "FlyQuest":         (0.10,     0.00,     0.42),
    "THUNDER dOWNUNDER":(0.05,     0.00,     0.58),
}

# ==================== 策略定义 ====================

strategies = {
    "策略A: 铁壁 (最保守)": {
        "desc": "3-0当废票，全力保晋级和0-3",
        "logic": "用最弱的两队填3-0(纯bonus)，6个晋级位放最强6队，0-3放最明显的两队",
        "picks_3_0": ["MIBR", "M80"],
        "picks_advance": ["GamerLegion", "BetBoom", "B8", "Heroic", "TYLOO", "Team Liquid"],
        "picks_0_3": ["THUNDER dOWNUNDER", "Gaimin Gladiators"],
    },
    "策略B: 稳健 (保守)": {
        "desc": "牺牲1个top队到3-0，换取多cover一支边缘队",
        "logic": "GL放3-0(~28%命中)，腾出1个晋级位给BIG；另一个3-0随便放",
        "picks_3_0": ["GamerLegion", "MIBR"],
        "picks_advance": ["BetBoom", "B8", "Heroic", "TYLOO", "Team Liquid", "BIG"],
        "picks_0_3": ["THUNDER dOWNUNDER", "Gaimin Gladiators"],
    },
    "策略C: 平衡 (中等风险)": {
        "desc": "两个top队放3-0，大幅增加cover面",
        "logic": "GL+BB放3-0，晋级位多cover两支中等队；0-3选最弱两队",
        "picks_3_0": ["GamerLegion", "BetBoom"],
        "picks_advance": ["B8", "Heroic", "TYLOO", "Team Liquid", "BIG", "SINNERS"],
        "picks_0_3": ["THUNDER dOWNUNDER", "Gaimin Gladiators"],
    },
    "策略D: 冒险 (激进)": {
        "desc": "最大化覆盖面，尝试押中更多队",
        "logic": "GL+BB放3-0，0-3选TdU+FQ，晋级位向下延伸到MIBR",
        "picks_3_0": ["GamerLegion", "BetBoom"],
        "picks_advance": ["B8", "Heroic", "TYLOO", "Team Liquid", "BIG", "MIBR"],
        "picks_0_3": ["THUNDER dOWNUNDER", "FlyQuest"],
    },
    "策略E: 赌狗 (极端激进)": {
        "desc": "GL+B8放3-0，0-3选冷门，追求高分",
        "logic": "赌GL和B8都3-0，0-3放TdU+Sharks，晋级cover更多中等队",
        "picks_3_0": ["GamerLegion", "B8"],
        "picks_advance": ["BetBoom", "Heroic", "TYLOO", "Team Liquid", "BIG", "SINNERS"],
        "picks_0_3": ["THUNDER dOWNUNDER", "Sharks"],
    },
}


def simulate_tournament():
    """模拟一次Swiss赛制的结果"""
    results = {}
    for team, (adv_p, p30, p03) in team_probs.items():
        r = random.random()
        if r < p30:
            results[team] = "3-0"
        elif r < p30 + p03:
            results[team] = "0-3"
        elif r < adv_p:
            # 晋级但不是3-0 (3-1 or 3-2)
            results[team] = "advance"
        else:
            # 被淘汰但不是0-3 (1-3 or 2-3)
            results[team] = "eliminated"
    return results


def evaluate_picks(strategy, tournament_result):
    """评估一组picks在某次模拟中的得分"""
    correct = 0
    details = []

    for team in strategy["picks_3_0"]:
        hit = tournament_result[team] == "3-0"
        if hit:
            correct += 1
        details.append(("3-0", team, hit))

    for team in strategy["picks_advance"]:
        hit = tournament_result[team] in ("3-0", "advance")
        if hit:
            correct += 1
        details.append(("晋级", team, hit))

    for team in strategy["picks_0_3"]:
        hit = tournament_result[team] == "0-3"
        if hit:
            correct += 1
        details.append(("0-3", team, hit))

    return correct, details


# ==================== 运行模拟 ====================

print("=" * 85)
print("  IEM Cologne Major 2026 Stage 1 — Pick'Em 策略分析")
print("  Monte Carlo模拟 ×", f"{SIMULATIONS:,}")
print("=" * 85)

for name, strategy in strategies.items():
    score_dist = [0] * 11  # 0-10分的分布
    total_score = 0

    for _ in range(SIMULATIONS):
        result = simulate_tournament()
        score, _ = evaluate_picks(strategy, result)
        score_dist[score] += 1
        total_score += score

    avg = total_score / SIMULATIONS
    p5 = sum(score_dist[5:]) / SIMULATIONS * 100
    p6 = sum(score_dist[6:]) / SIMULATIONS * 100
    p7 = sum(score_dist[7:]) / SIMULATIONS * 100

    print()
    print(f"  {'─'*80}")
    print(f"  {name}")
    print(f"  {strategy['desc']}")
    print(f"  逻辑: {strategy['logic']}")
    print(f"  {'─'*80}")
    print(f"  3-0: {', '.join(strategy['picks_3_0'])}")
    print(f"  晋级: {', '.join(strategy['picks_advance'])}")
    print(f"  0-3: {', '.join(strategy['picks_0_3'])}")
    print()
    print(f"  期望得分: {avg:.2f}/10")
    print(f"  ✅ P(≥5分): {p5:.1f}%   |  P(≥6分): {p6:.1f}%   |  P(≥7分): {p7:.1f}%")
    print()

    # 得分分布柱状图
    print(f"  得分分布:")
    max_pct = max(score_dist) / SIMULATIONS * 100
    for s in range(11):
        pct = score_dist[s] / SIMULATIONS * 100
        bar = "█" * int(pct / max_pct * 30) if max_pct > 0 else ""
        marker = " ← 目标" if s == 5 else ""
        print(f"    {s:>2}分: {pct:5.1f}% {bar}{marker}")

# ==================== 策略对比总结 ====================

print()
print("=" * 85)
print("  策略对比总结")
print("=" * 85)
print()
print(f"  {'策略':<30} {'期望分':<10} {'P(≥5)':<10} {'P(≥6)':<10} {'P(≥7)':<10}")
print(f"  {'─'*68}")

for name, strategy in strategies.items():
    score_dist = [0] * 11
    total = 0
    for _ in range(SIMULATIONS):
        result = simulate_tournament()
        score, _ = evaluate_picks(strategy, result)
        score_dist[score] += 1
        total += score
    avg = total / SIMULATIONS
    p5 = sum(score_dist[5:]) / SIMULATIONS * 100
    p6 = sum(score_dist[6:]) / SIMULATIONS * 100
    p7 = sum(score_dist[7:]) / SIMULATIONS * 100
    short_name = name.split(":")[0].strip() + name.split("(")[1].replace(")", "").strip() if "(" in name else name
    print(f"  {name:<30} {avg:<10.2f} {p5:<10.1f}% {p6:<10.1f}% {p7:<10.1f}%")

print()
print("  💡 建议:")
print("  • 目标是'对5个': 选择P(≥5)最高的策略")
print("  • 如果P(≥5)差距不大(<3%): 选期望分更高的策略(上限更高)")
print("  • 0-3位的关键抉择: GG vs FQ — GG排名更低但FQ状态更差")
print("  • 3-0位的核心问题: 把GL放3-0等于用~28%概率的pick换取多cover一支~55-60%的边缘队")
