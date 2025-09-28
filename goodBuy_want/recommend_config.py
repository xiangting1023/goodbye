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
    'search_keyword': 9,              # 搜尋意圖最強，權重拉高
    'viewed_related_multiplier': 0.6, # 看過=弱意圖，避免蓋過搜尋/回覆
    'replied_related_bonus': 3,       # 回覆過=中強意圖
}

# -------------------------
# Want 關鍵字匹配加權（命中欄位的基礎分）
# -------------------------
KEYWORD_SCORES = {
    'tags': 8,        # 標籤最精準
    'title': 6,       # 標題次之
    'post_text': 4,   # 內文說明再弱一些
}

# -------------------------
# 已推薦加權調整
# -------------------------
RECOMMENDED_WANT_WEIGHT_MULTIPLIER = 1.0  # 若已在近 7 天內推薦，則推薦分數乘上此數

# -------------------------
# 查詢時間範圍
# -------------------------
SEARCH_HISTORY_DAYS = 3
VIEW_DAYS = 14
REPLY_DAYS = 14
NEW_DAYS = 30
RECENT_RECO_DAYS = 7