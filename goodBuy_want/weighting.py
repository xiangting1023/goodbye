from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField

from goodBuy_want.models import Want, WantFootprints, WantTag, WantBack, WantRecommendationHistory
from goodBuy_web.models import SearchHistory
from goodBuy_want.hot_rank import get_hot_wants
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_want.recommend_config import (
    PERSONAL_WEIGHTS, PERSONAL_PROPORTIONS,
    KEYWORD_SCORES, KEYWORD_PROPORTIONS,
    RECOMMENDED_WANT_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, VIEW_DAYS, REPLY_DAYS
)

def personalized_want_recommendation(request, keywords=None, tags=None, owner=None, exclude_seen=False, limit=20):
    user = request.user

    if not user.is_authenticated:
        return Want.objects.none()

    now = timezone.now()
    final_scores = defaultdict(float)

    # 黑名單與自己
    blocked_ids = get_blocked_user_ids(user)
    if owner and owner != user:
        excluded_owner_ids = set(blocked_ids) | {user.id}
    else:
        excluded_owner_ids = blocked_ids

    # 近期推薦過的收物帖
    recent_recommended_ids = set(
        WantRecommendationHistory.objects.filter(
            user=user,
            recommended_at__gte=now - timedelta(days=7)
        ).values_list('want_id', flat=True)
    )

    # 搜尋紀錄
    recent_searches = SearchHistory.objects.filter(
        user=user,
        searched_at__gte=now - timedelta(days=SEARCH_HISTORY_DAYS)
    ).values_list('keyword', flat=True)

    for kw in recent_searches:
        for want in Want.objects.filter(user__isnull=False).exclude(user_id__in=blocked_ids):
            score = (
                (kw in want.title) * KEYWORD_SCORES['title'] * KEYWORD_PROPORTIONS['title'] +
                (kw in want.post_text) * KEYWORD_SCORES['post_text'] * KEYWORD_PROPORTIONS['post_text'] +
                (WantTag.objects.filter(want=want, tag__name=kw).exists()) * KEYWORD_SCORES['tags'] * KEYWORD_PROPORTIONS['tags']
            )
            final_scores[want.id] += score * PERSONAL_WEIGHTS['search_keyword'] * PERSONAL_PROPORTIONS['search_history']

    # 看過的收物帖
    viewed_ids = WantFootprints.objects.filter(
        user=user,
        date__gte=now - timedelta(days=VIEW_DAYS)
    ).values_list('want_id', flat=True)

    for wid in viewed_ids:
        want = Want.objects.filter(id=wid).first()
        if not want:
            continue
        score = (
            KEYWORD_SCORES['title'] * KEYWORD_PROPORTIONS['title'] +
            KEYWORD_SCORES['post_text'] * KEYWORD_PROPORTIONS['post_text']
        )
        final_scores[wid] += score * PERSONAL_WEIGHTS['viewed_related_multiplier'] * PERSONAL_PROPORTIONS['viewed_related']

    # 曾經回覆過的收物帖 → tag 加分
    replied_ids = WantBack.objects.filter(
        user=user,
        date__gte=now - timedelta(days=REPLY_DAYS)
    ).values_list('want_id', flat=True)

    for wid in replied_ids:
        tag_score = KEYWORD_SCORES['tags'] * KEYWORD_PROPORTIONS['tags']
        final_scores[wid] += tag_score * PERSONAL_WEIGHTS['replied_related_bonus'] * PERSONAL_PROPORTIONS['replied_related']

    # 降低已推薦者分數
    for wid in final_scores:
        if wid in recent_recommended_ids:
            final_scores[wid] *= RECOMMENDED_WANT_WEIGHT_MULTIPLIER

    # 排除黑名單作者
    sorted_ids = sorted(final_scores, key=final_scores.get, reverse=True)
    wants = Want.objects.filter(id__in=sorted_ids).exclude(user__id__in=blocked_ids)

    # 排除已看過的
    if exclude_seen:
        seen_ids = set(viewed_ids)
        wants = wants.exclude(id__in=seen_ids)

    # 保留排序
    filtered_ids = list(wants.values_list('id', flat=True))
    sorted_ids = [wid for wid in sorted_ids if wid in filtered_ids]

    if limit and len(sorted_ids) < limit:
        current_ids = set(sorted_ids)

        # 熱門推薦補滿，排除黑名單、自身、已推薦
        hot_queryset = get_hot_wants(request=request, owner=owner)

        # 過濾黑名單、自己、已推薦過的
        hot_queryset = hot_queryset.exclude(
            id__in=current_ids,
            user_id__in=excluded_owner_ids
        )

        # 再做切片（避免 QuerySet + slice + filter 錯誤）
        fallback_ids = list(hot_queryset.values_list('id', flat=True))[:limit - len(sorted_ids)]
        sorted_ids += fallback_ids


    # 寫入推薦記錄
    for want in wants.filter(id__in=sorted_ids):
        WantRecommendationHistory.objects.create(
            user=user,
            want=want,
            source='personalized',
            keyword=', '.join(keywords) if keywords else None
        )

    print("Final scores:", dict(final_scores))
    print("初步 want 數量：", len(wants))
    print("excluded_owner_ids:", excluded_owner_ids)
    print("seen_ids:", list(seen_ids) if exclude_seen else "未排除")
    print("活躍 want 數量：", len(sorted_ids))
    
    print("原始推薦 ID：", list(final_scores.keys()))
    print("排序後 ID：", sorted_ids)
    print("排除黑名單與自己後 ID：", list(wants.values_list('id', flat=True)))

    return Want.objects.filter(id__in=sorted_ids).order_by(
        Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(sorted_ids)],
            output_field=IntegerField()
        )
    )
