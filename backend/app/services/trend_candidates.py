"""内置趋势日种子纯算法：标记估算来源，不访问数据库或平台。"""

import random

TREND_POOL = (
    ("led strip lights", "google"), ("pet grooming gloves", "amazon"), ("car phone holder", "amazon"),
    ("yoga mat thick", "google"), ("reusable makeup pads", "shopee"), ("baby feeding bibs", "amazon"),
    ("kitchen drawer organizer", "google"), (" camping lantern rechargeable", "amazon"),
    ("hair claw clips", "tiktok"), ("smart water bottle", "google"), ("dog cooling mat", "shopee"),
    ("wireless earbuds case", "shopee"),
)


def builtin_candidates(day, categories=()):
    """保留历史池顺序和随机抽样顺序，返回前12项估算。"""
    pool = list(TREND_POOL) + [(f"{category} wholesale", "1688") for category in categories]
    rng = random.Random(day)
    candidates = []
    for keyword, platform in pool[:12]:
        volume, growth, competition = rng.randint(800, 50000), round(rng.uniform(-15, 180), 1), rng.randint(20, 90)
        candidates.append({"keyword": keyword.strip(), "platform": platform,
                           "search_volume": volume, "growth_30d": growth, "competition": competition,
                           "source": "builtin", "note": "增长率显著" if growth > 60 else
                           ("竞争激烈" if competition > 75 else "平稳")})
    return candidates
