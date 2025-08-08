from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField

from goodBuy_want.models import (
    Want, WantFootprints, WantTag, WantBack, WantRecommendationHistory
)
from goodBuy_web.models import SearchHistory
from goodBuy_want.hot_rank import get_hot_wants
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_want.recommend_config import (
    PERSONAL_WEIGHTS, PERSONAL_PROPORTIONS,
    KEYWORD_SCORES, KEYWORD_PROPORTIONS,
    RECOMMENDED_WANT_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, VIEW_DAYS, REPLY_DAYS
)

def personalized_want_recommendation(
    request,
    keyword=None,
    tag=None,
    owner=None,
    exclude_seen=False,
    limit=20
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Want.objects.none()

    now = timezone.now()

    # -------------------------
    # Step 1: 先過濾
    # -------------------------
    qs = Want.objects.filter(user__isnull=False)

    blocked_ids = set(get_blocked_user_ids(user))
    if owner and owner != user:
        excluded_owner_ids = blocked_ids | {user.id}
    else:
        excluded_owner_ids = blocked_ids

    qs = qs.exclude(user_id__in=excluded_owner_ids)

    if owner:
        qs = qs.filter(user=owner)

    # 單一 keyword / tag 過濾
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword) |
            Q(post_text__icontains=keyword) |
            Q(wanttag__tag__name__icontains=keyword) |
            Q(user__username__icontains=keyword)
        )
    if tag:
        qs = qs.filter(wanttag__tag=tag)

    qs = qs.distinct()
    if not qs.exists():
        return qs.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    final_scores = defaultdict(float)

    # -------------------------
    # Step 2: 打分
    # -------------------------

    # (A) 搜尋紀錄 + 外部 keyword（單一）
    recent_searches = list(
        SearchHistory.objects.filter(
            user=user,
            searched_at__gte=now - timedelta(days=SEARCH_HISTORY_DAYS)
        ).values_list('keyword', flat=True)
    )
    if keyword:
        recent_searches.append(keyword)
    recent_searches = [kw for kw in recent_searches if kw]

    if recent_searches:
        # 這裡把每個 kw 個別找匹配（限候選）
        for kw in recent_searches:
            matched_ids = set(
                qs.filter(
                    Q(title__icontains=kw) |
                    Q(post_text__icontains=kw) |
                    Q(wanttag__tag__name__icontains=kw) |
                    Q(user__username__icontains=kw)
                ).values_list('id', flat=True)
            )
            kw_score = (
                KEYWORD_SCORES['title']     * KEYWORD_PROPORTIONS['title'] +
                KEYWORD_SCORES['post_text'] * KEYWORD_PROPORTIONS['post_text'] +
                KEYWORD_SCORES['tags']      * KEYWORD_PROPORTIONS['tags']
            )
            add = kw_score * PERSONAL_WEIGHTS['search_keyword'] * PERSONAL_PROPORTIONS['search_history']
            for wid in matched_ids:
                final_scores[wid] += add

    # (B) 最近看過
    viewed_ids = set(
        WantFootprints.objects.filter(
            user=user,
            date__gte=now - timedelta(days=VIEW_DAYS),
            want_id__in=candidate_ids
        ).values_list('want_id', flat=True)
    )
    if viewed_ids:
        viewed_add = (
            (KEYWORD_SCORES['title'] * KEYWORD_PROPORTIONS['title'] +
             KEYWORD_SCORES['post_text'] * KEYWORD_PROPORTIONS['post_text'])
            * PERSONAL_WEIGHTS['viewed_related_multiplier'] * PERSONAL_PROPORTIONS['viewed_related']
        )
        for wid in viewed_ids:
            final_scores[wid] += viewed_add

    # (C) 最近回覆
    replied_ids = set(
        WantBack.objects.filter(
            user=user,
            date__gte=now - timedelta(days=REPLY_DAYS),
            want_id__in=candidate_ids
        ).values_list('want_id', flat=True)
    )
    if replied_ids:
        replied_add = (
            KEYWORD_SCORES['tags'] * KEYWORD_PROPORTIONS['tags']
            * PERSONAL_WEIGHTS['replied_related_bonus'] * PERSONAL_PROPORTIONS['replied_related']
        )
        for wid in replied_ids:
            final_scores[wid] += replied_add

    # (D) 降低已推薦
    recent_recommended_ids = set(
        WantRecommendationHistory.objects.filter(
            user=user,
            recommended_at__gte=now - timedelta(days=7)
        ).values_list('want_id', flat=True)
    )
    if recent_recommended_ids:
        for wid in list(final_scores.keys()):
            if wid in recent_recommended_ids:
                final_scores[wid] *= RECOMMENDED_WANT_WEIGHT_MULTIPLIER

    # -------------------------
    # Step 3: 排序 + 補滿
    # -------------------------
    sorted_ids = sorted(final_scores, key=final_scores.get, reverse=True)
    wants = Want.objects.filter(id__in=sorted_ids).exclude(user_id__in=excluded_owner_ids)

    # 排除已看過（選配）
    seen_ids = set()
    if exclude_seen:
        seen_ids = viewed_ids
        wants = wants.exclude(id__in=seen_ids)

    filtered_ids = set(wants.values_list('id', flat=True))
    ordered_ids = [wid for wid in sorted_ids if wid in filtered_ids]

    if limit and len(ordered_ids) < limit:
        need = limit - len(ordered_ids)
        hot_qs = get_hot_wants(request=request, owner=owner).exclude(
            id__in=set(ordered_ids) | recent_recommended_ids,
            user_id__in=excluded_owner_ids
        )
        ordered_ids += list(hot_qs.values_list('id', flat=True))[:need]

    if not ordered_ids:
        return Want.objects.none()

    # -------------------------
    # Step 4: 保序回傳
    # -------------------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(ordered_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=ordered_ids).order_by(preserved)

    # -------------------------
    # Step 5: 寫入推薦歷史（單一 keyword 字串）
    # -------------------------
    now_ts = timezone.now()
    history = [
        WantRecommendationHistory(
            user=user,
            want=want,
            recommended_at=now_ts,
            source='personalized',
            keyword=keyword if keyword else None
        )
        for want in qs_ordered
    ]
    if history:
        WantRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    # Debug
    print("Final scores:", dict(final_scores))
    print("候選數量：", len(candidate_ids))
    print("排序後 ID：", ordered_ids)
    print("seen_ids：", list(seen_ids) if exclude_seen else "未排除")
    print("黑名單/自己排除作者 IDs：", list(excluded_owner_ids))

    return qs_ordered
