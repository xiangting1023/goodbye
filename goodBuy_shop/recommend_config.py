# -------------------------
# 熱門商店推薦權重
# -------------------------
HOT_WEIGHTS = {
    'recent_sales': 5,      # 每筆成交加 2 分
    'recent_views': 1,      # 每次瀏覽加 1 分
    'new_shop_bonus': 3,    # 新店 3 天內額外加分
}

# -------------------------
# 個性化推薦權重
# -------------------------
PERSONAL_WEIGHTS = {
    'search_keyword': 5,          # 每筆搜尋對應店加 5 分
    'viewed_related_multiplier': 0.8,  # 已看過店提取的關鍵字打分 x 0.8
    'traded_shop_bonus': 1,       # 活躍商店加分
}

PERSONAL_PROPORTIONS = {
    'search_history': 0.25,
    'fav_related': 0.25,
    'bought_related': 0.25,
    'viewed_related': 0.20,
    'traded_shop': 0.05,
}

# -------------------------
# 關鍵字匹配打分
# -------------------------
KEYWORD_SCORES = {
    'tags': 5,
    'name': 3,
    'introduce': 2,
}

KEYWORD_PROPORTIONS = {
    'tags': 0.50,
    'name': 0.30,
    'introduce': 0.20,
}

# -------------------------
# 附加策略控制
# -------------------------
RECOMMENDED_SHOP_WEIGHT_MULTIPLIER = 0.5  # 若已在近 7 天內推薦，則推薦分數乘上 0.5

# -------------------------
# 查詢時間控制
# -------------------------
SEARCH_HISTORY_DAYS = 3
COLLECT_DAYS = 14
VIEWED_SHOP_DAYS = 14
