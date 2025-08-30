# goodBuy_want/weighting.py
from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField

from goodBuy_want.models import (
    Want, WantFootprints, WantBack, WantRecommendationHistory
)
from goodBuy_web.models import SearchHistory
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_want.hot_rank import get_hot_wants
from goodBuy_want.recommend_config import (
    PERSONAL_WEIGHTS,
    KEYWORD_SCORES,
    RECOMMENDED_WANT_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, VIEW_DAYS, REPLY_DAYS,
)

def personalized_want_recommendation(
    request,
    keyword=None,
    tag=None,
    owner=None,
    exclude_seen=False,
    limit=20,
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Want.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    qs = Want.objects.filter(permission__id=1).exclude(user_id__in=blocked_ids)

    if owner:
        qs = qs.filter(user=owner)
    else:
        qs = qs.exclude(user=user)  # 不推自己的貼文（除非指定 owner）

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
        # 無任何條件 → 用最新公開貼文保底
        if not (keyword or tag or owner):
            return Want.objects.filter(permission__id=1).order_by('-date')[: (limit or 20)]
        return qs.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {wid: 0.0 for wid in candidate_ids}  # 先全部設 0，確保新貼文也會出現

    # ---------------- 2) 打分 ----------------
    # 搜尋紀錄 + 入口 keyword（強）
    recent_searches = list(
        SearchHistory.objects.filter(
            user=user, searched_at__gte=now - timedelta(days=SEARCH_HISTORY_DAYS)
        ).values_list('keyword', flat=True)
    )
    if keyword:
        recent_searches.append(keyword)
    recent_searches = [kw for kw in recent_searches if kw]

    if recent_searches:
        kw_base = (KEYWORD_SCORES['title'] + KEYWORD_SCORES['post_text'] + KEYWORD_SCORES['tags']) \
                  * PERSONAL_WEIGHTS['search_keyword']
        for kw in recent_searches:
            hit_ids = set(qs.filter(
                Q(title__icontains=kw) |
                Q(post_text__icontains=kw) |
                Q(wanttag__tag__name__icontains=kw) |
                Q(user__username__icontains=kw)
            ).values_list('id', flat=True))
            for wid in hit_ids:
                scores[wid] += kw_base

    # 看過（弱）
    viewed_ids = set(
        WantFootprints.objects.filter(
            user=user,
            date__gte=now - timedelta(days=VIEW_DAYS),
            want_id__in=candidate_ids
        ).values_list('want_id', flat=True)
    )
    if viewed_ids:
        add_viewed = (KEYWORD_SCORES['title'] + KEYWORD_SCORES['post_text']) \
                     * PERSONAL_WEIGHTS['viewed_related_multiplier']
        for wid in viewed_ids:
            scores[wid] += add_viewed

    # 回覆過（中強）
    replied_ids = set(
        WantBack.objects.filter(
            user=user,
            date__gte=now - timedelta(days=REPLY_DAYS),
            want_id__in=candidate_ids
        ).values_list('want_id', flat=True)
    )
    if replied_ids:
        add_reply = KEYWORD_SCORES['tags'] * PERSONAL_WEIGHTS['replied_related_bonus']
        for wid in replied_ids:
            scores[wid] += add_reply

    # 新貼文微量加成（打破 0 分同分）
    NEW_DAYS = 3
    EPS = 0.01
    recent_new_ids = set(
        Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
        .values_list('id', flat=True)
    )
    for wid in recent_new_ids:
        scores[wid] += EPS

    # E) 降低最近已推薦
    recent_reco = set(
        WantRecommendationHistory.objects.filter(
            user=user, recommended_at__gte=now - timedelta(days=7)
        ).values_list('want_id', flat=True)
    )
    for wid in list(scores.keys()):
        if wid in recent_reco:
            scores[wid] *= RECOMMENDED_WANT_WEIGHT_MULTIPLIER

    # ---------------- 3) 排序 + 多樣性 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0), reverse=True)

    # 同作者最多 K 筆
    author_by_id = dict(Want.objects.filter(id__in=prelim).values_list('id', 'user_id'))
    K_PER_AUTHOR = 5
    picked, author_count = [], defaultdict(int)
    for wid in prelim:
        aid = author_by_id.get(wid)
        if author_count[aid] < K_PER_AUTHOR:
            picked.append(wid)
            author_count[aid] += 1

    if exclude_seen:
        picked = [wid for wid in picked if wid not in viewed_ids]

    # ---------------- 4) 補滿（只有完全無條件時才用熱門） ----------------
    need = max((limit or 20) - len(picked), 0)
    if need and not (keyword or owner or tag):
        hot = (get_hot_wants(request=request)
            .exclude(id__in=set(picked) | recent_reco)
            .values_list('id', flat=True))
        picked += list(hot)[:need]

    if not picked:
        return Want.objects.none()

    if limit:
        picked = picked[:limit]

    # ---------------- 5) 保序 + 寫推薦歷史 ----------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(picked)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=picked).order_by(preserved)

    # 寫歷史
    history = []
    now_ts = timezone.now()
    for w in qs_ordered:
        history.append(WantRecommendationHistory(
            user=user,
            want=w,
            recommended_at=now_ts,
            source='personalized',
            keyword=keyword or None
        ))
    if history:
        WantRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered
