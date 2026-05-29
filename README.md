# CS2 Major Pick'Em 分析工具

对CS2 Major通行证竞猜进行数据驱动的分析和策略模拟。

## 目录结构

```
CS/
├── README.md
└── 2026_cologne/          # IEM Cologne Major 2026
    ├── stage1/            # Stage 1 (Challenger Stage)
    │   ├── README.md      # 分析总结 & 事后复盘
    │   ├── team_rating.py # 队伍综合评分脚本
    │   └── pickem_strategy.py  # Pick'Em策略模拟
    ├── stage2/            # Stage 2 (Legends Stage)
    └── stage3/            # Stage 3 (Champions Stage)
```

## 分析方法

1. **数据收集**: HLTV排名、近期战绩、Polymarket赔率、阵容变动
2. **综合评分**: 多维度加权 (市场30% + HLTV 25% + 战绩25% + 阵容10% + 赛区10%)
3. **策略模拟**: Monte Carlo模拟评估各策略的P(≥5)

## 赛事记录

| 赛事 | 日期 | 策略 | 结果 |
|:---|:---|:---|:---|
| 2026 Cologne Stage 1 | 2026-06-02~05 | 铁壁 (策略A) | 待定 |
