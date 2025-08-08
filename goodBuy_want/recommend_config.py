# -------------------------
# 熱門 Want 推薦權重
# -------------------------
HOT_WEIGHTS = {
    'recent_views': 1,     # 每次被瀏覽 +1
    'recent_replies': 5,   # 每次被回覆 +5
}

# -------------------------
# 個性化 Want 推薦權重
# -------------------------
PERSONAL_WEIGHTS = {
    'search_keyword': 4,              # 搜尋關鍵字匹配
    'viewed_related_multiplier': 0.7, # 觀看過相關 want 的關鍵字提取
    'replied_related_bonus': 2,       # 回覆過相關 want 的 tag 關聯加分
}

PERSONAL_PROPORTIONS = {
    'search_history': 0.4,
    'viewed_related': 0.4,
    'replied_related': 0.2,
}

# -------------------------
# Want 關鍵字匹配加權
# -------------------------
KEYWORD_SCORES = {
    'tags': 5,
    'title': 3,
    'post_text': 2,
}

KEYWORD_PROPORTIONS = {
    'tags': 0.5,
    'title': 0.3,
    'post_text': 0.2,
}

# -------------------------
# 已推薦加權調整
# -------------------------
RECOMMENDED_WANT_WEIGHT_MULTIPLIER = 0.5

# -------------------------
# 查詢時間範圍
# -------------------------
SEARCH_HISTORY_DAYS = 3
VIEW_DAYS = 14
REPLY_DAYS = 14
