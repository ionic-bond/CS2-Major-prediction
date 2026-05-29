"""
IEM Cologne Major 2026 - Stage 1 Pick'Em 分析脚本
数据截止: 2026年5月29日
"""
import math

# ==================== 原始数据 ====================

teams = {
    "GamerLegion": {
        "hltv_rank": 11,
        "region": "EU",
        "roster_stability": 0.85,
        "recent_results_score": 75,  # IEM Atlanta亚军，击败Astralis/Liquid/Legacy
        "notable": "IEM Atlanta亚军，近期状态极好",
        "opening_opponent": "NRG",
    },
    "B8": {
        "hltv_rank": 15,
        "region": "EU",
        "roster_stability": 0.80,
        "recent_results_score": 60,  # EU中上游，击败FUT/BC.Game，对NaVi/Astralis有来有回
        "notable": "EU中上游稳定队伍，大赛经验丰富",
        "opening_opponent": "TYLOO",
    },
    "BetBoom": {
        "hltv_rank": 20,
        "region": "CIS",
        "roster_stability": 0.85,
        "recent_results_score": 70,  # IEM Atlanta第4，击败Vitality
        "notable": "IEM Atlanta第4，击败Vitality",
        "opening_opponent": "Gaimin Gladiators",
    },
    "Heroic": {
        "hltv_rank": 25,
        "region": "EU",
        "roster_stability": 0.65,
        "recent_results_score": 42,  # 新阵容磨合中
        "notable": "2025换血后磨合中，底蕴强但当前不稳定",
        "opening_opponent": "Sharks",
    },
    "Team Liquid": {
        "hltv_rank": 26,
        "region": "INT",
        "roster_stability": 0.80,
        "recent_results_score": 40,  # 近期胜少负多，输Astralis/GL/PARIVISION/MongolZ
        "notable": "传统强队近期低迷，胜少负多",
        "opening_opponent": "BIG",
    },
    "MIBR": {
        "hltv_rank": 28,
        "region": "SA",
        "roster_stability": 0.80,
        "recent_results_score": 45,  # SA中上游
        "notable": "SA老牌劲旅，阵容经验丰富",
        "opening_opponent": "THUNDER dOWNUNDER",
    },
    "TYLOO": {
        "hltv_rank": 30,
        "region": "Asia",
        "roster_stability": 0.90,
        "recent_results_score": 55,  # ESL Challenger冠军3-0，BLAST曾击败FaZe
        "notable": "亚洲最强，ESL Challenger冠军，曾击败FaZe",
        "opening_opponent": "B8",
    },
    "BIG": {
        "hltv_rank": 32,
        "region": "EU",
        "roster_stability": 0.70,
        "recent_results_score": 35,  # 2026年1月重建后排名下滑
        "notable": "blameF/tabseN领衔重建，名气大于当前实力",
        "opening_opponent": "Team Liquid",
    },
    "SINNERS": {
        "hltv_rank": 32,
        "region": "EU",
        "roster_stability": 0.85,
        "recent_results_score": 35,  # EU区域赛中游
        "notable": "捷克战队，EU区域赛尚可",
        "opening_opponent": "FlyQuest",
    },
    "NRG": {
        "hltv_rank": 34,
        "region": "NA",
        "roster_stability": 0.75,
        "recent_results_score": 30,  # NA中游偏下
        "notable": "老将nitr0带队，整体竞争力有限",
        "opening_opponent": "GamerLegion",
    },
    "M80": {
        "hltv_rank": 35,
        "region": "NA",
        "roster_stability": 0.75,
        "recent_results_score": 32,  # NA中游，输MOUZ/Falcons/paiN，赢Liquid/Iowa
        "notable": "NA中游，面对强队胜率低",
        "opening_opponent": "Lynn Vision",
    },
    "Lynn Vision": {
        "hltv_rank": 45,
        "region": "Asia",
        "roster_stability": 0.85,
        "recent_results_score": 22,  # 亚洲中游
        "notable": "中国队伍，国际LAN经验有限",
        "opening_opponent": "M80",
    },
    "Gaimin Gladiators": {
        "hltv_rank": 46,
        "region": "SA",
        "roster_stability": 0.80,
        "recent_results_score": 18,  # 近期3连败
        "notable": "fer/HEN1领衔但近期3连败状态差",
        "opening_opponent": "BetBoom",
    },
    "Sharks": {
        "hltv_rank": 50,
        "region": "SA",
        "roster_stability": 0.80,
        "recent_results_score": 20,  # SA中下游
        "notable": "SA区域队伍，国际LAN经验少",
        "opening_opponent": "Heroic",
    },
    "FlyQuest": {
        "hltv_rank": 56,
        "region": "Asia/OCE",
        "roster_stability": 0.80,
        "recent_results_score": 15,  # 输给5star/JiJieHao/TYLOO等
        "notable": "jks是亮点但整体实力弱，输给亚洲二线队",
        "opening_opponent": "SINNERS",
    },
    "THUNDER dOWNUNDER": {
        "hltv_rank": 80,
        "region": "OCE",
        "roster_stability": 0.85,
        "recent_results_score": 10,  # 排名最低
        "notable": "排名最低，Dexter/Liazz有经验但队伍整体最弱",
        "opening_opponent": "MIBR",
    },
}

# Polymarket 首轮赔率 (2026-05-29)
polymarket_odds = {
    ("GamerLegion", "NRG"): (0.71, 0.29),
    ("B8", "TYLOO"): (0.56, 0.44),
    ("Heroic", "Sharks"): (0.61, 0.39),
    ("BetBoom", "Gaimin Gladiators"): (0.71, 0.29),
    ("BIG", "Team Liquid"): (0.53, 0.47),
    ("M80", "Lynn Vision"): (0.59, 0.41),
    ("MIBR", "THUNDER dOWNUNDER"): (0.71, 0.29),
    ("SINNERS", "FlyQuest"): (0.55, 0.45),
}

# ==================== Bradley-Terry 隐含实力推算 ====================
# 从配对赔率推算隐含实力: P(A>B) = s_A / (s_A + s_B) → s_A/s_B = p/(1-p)
# 将所有队伍的log-strength锚定在一起

def derive_implied_strengths():
    log_ratios = {}
    for (t1, t2), (p1, p2) in polymarket_odds.items():
        log_ratios[(t1, t2)] = math.log(p1 / p2)

    # 用HLTV排名作为锚点，将独立的配对比值串联起来
    # 给每队一个基于HLTV排名的先验log-strength
    hltv_prior = {}
    for name, data in teams.items():
        hltv_prior[name] = math.log(max(1, 100 - data["hltv_rank"]))

    # 迭代调整: 用市场赔率修正HLTV先验
    strengths = {name: math.exp(v) for name, v in hltv_prior.items()}

    for _ in range(50):
        new_strengths = dict(strengths)
        for (t1, t2), (p1, p2) in polymarket_odds.items():
            market_ratio = p1 / p2
            current_ratio = strengths[t1] / strengths[t2]
            # 用市场比值拉动当前比值（市场权重0.6，先验0.4）
            target_ratio = market_ratio ** 0.6 * current_ratio ** 0.4
            mid = math.sqrt(strengths[t1] * strengths[t2])
            new_strengths[t1] = mid * math.sqrt(target_ratio)
            new_strengths[t2] = mid / math.sqrt(target_ratio)
        strengths = new_strengths

    # 归一化到0-100
    min_s = min(strengths.values())
    max_s = max(strengths.values())
    normalized = {}
    for name, s in strengths.items():
        normalized[name] = (s - min_s) / (max_s - min_s) * 80 + 20  # 20-100
    return normalized

# ==================== 综合评分 ====================

def calculate_composite_scores():
    implied = derive_implied_strengths()

    region_bonus = {
        "EU": 5, "CIS": 4, "INT": 4, "NA": 2, "SA": 2, "Asia": 1, "Asia/OCE": 0, "OCE": 0,
    }

    results = {}
    for name, data in teams.items():
        # HLTV排名分 (0-100)
        rank_score = max(0, 100 - (data["hltv_rank"] - 1) * 1.1)

        # 近期战绩分 (0-100)
        results_score = data["recent_results_score"]

        # 市场隐含实力 (20-100)
        market_score = implied[name]

        # 阵容稳定度 (0-100)
        stability_score = data["roster_stability"] * 100

        # 赛区加成
        region_score = region_bonus.get(data["region"], 0)

        # 综合: 市场30% + HLTV排名25% + 近期战绩25% + 阵容稳定10% + 赛区10%
        composite = (
            market_score * 0.30 +
            rank_score * 0.25 +
            results_score * 0.25 +
            stability_score * 0.10 +
            region_score * 0.10 * 10  # 放大到类似量级
        )
        results[name] = round(composite, 1)

    return results, implied


def estimate_advance_probability(score, all_scores):
    """粗略估算晋级概率: 前8名晋级"""
    sorted_scores = sorted(all_scores.values(), reverse=True)
    rank_in_16 = sum(1 for s in sorted_scores if s > score) + 1

    # 用sigmoid函数估算，中间队伍(排名8-9)约50%
    x = (8.5 - rank_in_16) * 0.8
    prob = 1 / (1 + math.exp(-x))
    return round(prob * 100, 1)


# ==================== 输出 ====================

scores, market_implied = calculate_composite_scores()
sorted_teams = sorted(scores.items(), key=lambda x: x[1], reverse=True)

print("=" * 80)
print("  IEM Cologne Major 2026 - Stage 1 队伍综合实力评分")
print("  (数据源: HLTV排名 + 近期战绩 + Polymarket赔率 + 阵容稳定度 + 赛区)")
print("=" * 80)
print()
print(f"{'#':<3} {'队伍':<22} {'综合分':<8} {'市场分':<8} {'HLTV':<6} {'晋级概率':<10} {'首轮对手'}")
print("-" * 80)

for i, (name, score) in enumerate(sorted_teams, 1):
    data = teams[name]
    adv_prob = estimate_advance_probability(score, scores)
    mkt = market_implied[name]
    marker = ""
    if i <= 3:
        marker = "🟢"
    elif i <= 8:
        marker = "🟡"
    elif i <= 12:
        marker = "🟠"
    else:
        marker = "🔴"
    print(f"{marker}{i:<2} {name:<22} {score:<8.1f} {mkt:<8.1f} #{data['hltv_rank']:<5} {adv_prob:>5.1f}%     vs {data['opening_opponent']}")

print()
print("=" * 80)
print("  Polymarket 首轮赔率")
print("=" * 80)
print()
for (t1, t2), (p1, p2) in polymarket_odds.items():
    bar1 = "█" * int(p1 * 30)
    bar2 = "█" * int(p2 * 30)
    print(f"  {t1:<22} {p1*100:4.0f}% {bar1}")
    print(f"  {t2:<22} {p2*100:4.0f}% {bar2}")
    print()

print("=" * 80)
print("  分层分析")
print("=" * 80)
print()

tier_boundaries = [
    ("🟢 T1 - 晋级热门 (>75%概率)", lambda s: s >= sorted_teams[3][1]),
    ("🟡 T2 - 有机会晋级 (40-75%)", lambda s: sorted_teams[7][1] <= s < sorted_teams[3][1]),
    ("🟠 T3 - 晋级困难 (15-40%)", lambda s: sorted_teams[11][1] <= s < sorted_teams[7][1]),
    ("🔴 T4 - 淘汰候选 (<15%)", lambda s: s < sorted_teams[11][1]),
]

for tier_name, check_fn in tier_boundaries:
    tier_teams = [(n, s) for n, s in sorted_teams if check_fn(s)]
    if tier_teams:
        print(f"  {tier_name}")
        for n, s in tier_teams:
            adv = estimate_advance_probability(s, scores)
            print(f"    {n:<22} {s:.1f}分  晋级{adv:.0f}%  | {teams[n]['notable']}")
        print()

print("=" * 80)
print("  首轮对阵预测")
print("=" * 80)
print()

for (t1, t2), (p1, p2) in polymarket_odds.items():
    s1, s2 = scores[t1], scores[t2]
    fav = t1 if p1 > p2 else t2
    fav_p = max(p1, p2)
    diff_label = ""
    if fav_p >= 0.70:
        diff_label = "大优"
    elif fav_p >= 0.60:
        diff_label = "小优"
    else:
        diff_label = "均势"
    print(f"  {t1} vs {t2}")
    print(f"    → {fav} {diff_label} ({fav_p*100:.0f}%), 综合分 {s1:.1f} vs {s2:.1f}")
    print()
