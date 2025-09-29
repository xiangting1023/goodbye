# -------------------------
# 熱門商店推薦權重
# -------------------------
HOT_WEIGHTS = {
    'recent_sales': 5,      # 每筆成交加 5 分
    'recent_views': 1,      # 每次瀏覽加 1 分
    'new_shop_bonus': 3,    # 新店 3 天內額外加分
}

# -------------------------
# 個性化推薦權重
# -------------------------
PERSONAL_WEIGHTS = {
    'search_keyword': 9,               # 搜尋關鍵字 → 強烈意圖
    'viewed_related_multiplier': 0.6,  # 瀏覽過 → 弱意圖
    'traded_shop_bonus': 2.5,           # 曾購買過 → 高信任
    'collected_shop_bonus': 1.8,        # 收藏過 → 中等意圖
    'new_shop_bonus': 0.8,       # 新店曝光 → 冷啟動幫助
}

# -------------------------
# 關鍵字匹配打分
# -------------------------
KEYWORD_SCORES = {
    'tags': 8,       # 精準分類
    'name': 6,       # 店名相關
    'introduce': 4,  # 內容相關
}

# -------------------------
# 附加策略控制
# -------------------------
RECOMMENDED_SHOP_WEIGHT_MULTIPLIER = 1.0  # 若已在近 7 天內推薦，則推薦分數乘上此數

# -------------------------
# 查詢時間控制
# -------------------------
SEARCH_HISTORY_DAYS = 7
COLLECT_DAYS = 14
VIEW_DAYS = 14
ORDER_DAYS = 90
NEW_DAYS = 60
RECENT_RECO_DAYS = 7