from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField
import math
import random


from goodBuy_shop.models import (
    Shop, ShopFootprints, ShopRecommendationHistory
)
from goodBuy_order.models import ProductOrder
from goodBuy_web.models import SearchHistory
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_shop.hot_rank import get_hot_shops
from goodBuy_shop.recommend_config import (
    PERSONAL_WEIGHTS, KEYWORD_SCORES, RECOMMENDED_SHOP_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, VIEW_DAYS, ORDER_DAYS,
)

def personalized_shop_recommendation(request, keyword=None, tag=None, owner=None, exclude_seen=False, limit=20):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Shop.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    qs = Shop.objects.filter(permission__id=1)

    # 進行中 or 近 3 天更新（讓新店也可進榜）
    NEW_DAYS = 3
    qs = qs.filter(
        Q(start_time__lte=now, end_time__gte=now) |
        Q(update__gte=now - timedelta(days=NEW_DAYS))
    )

    # 黑名單 & 自己（未指定 owner 時排除自己）
    qs = qs.exclude(owner_id__in=blocked_ids)
    if owner:
        qs = qs.filter(owner=owner)
    else:
        qs = qs.exclude(owner=user)

    # 單一 keyword / tag
    if keyword:
        qs = qs.filter(
            Q(name__icontains=keyword) |
            Q(introduce__icontains=keyword) |
            Q(shoptag__tag__name__icontains=keyword) |
            Q(owner__username__icontains=keyword)
        )
    if tag:
        qs = qs.filter(shoptag__tag=tag)

    qs = qs.distinct()
    if not qs.exists():
        # 無條件 → 最新公開店保底
        if not (keyword or owner or tag):
            return Shop.objects.filter(permission__id=1).order_by('-update')[: (limit or 20)]
        return qs.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {sid: 0.0 for sid in candidate_ids}

    # ---------------- score ----------------
    # 搜尋紀錄 + 入口 keyword
    recent_searches = list(
        SearchHistory.objects.filter(
            user=user, searched_at__gte=now - timedelta(days=SEARCH_HISTORY_DAYS)
        ).values_list('keyword', flat=True)
    )
    if keyword:
        recent_searches.append(keyword)
    recent_searches = [kw for kw in recent_searches if kw]

    if recent_searches:
        kw_base = (KEYWORD_SCORES['name'] + KEYWORD_SCORES['introduce'] + KEYWORD_SCORES['tags']) \
                  * PERSONAL_WEIGHTS['search_keyword']
        for kw in recent_searches:
            matched_ids = set(qs.filter(
                Q(name__icontains=kw) |
                Q(introduce__icontains=kw) |
                Q(shoptag__tag__name__icontains=kw) |
                Q(owner__username__icontains=kw)
            ).values_list('id', flat=True))
            for sid in matched_ids:
                scores[sid] += kw_base

    # 最近看過的商店（弱）
    viewed_shop_ids = set(
        ShopFootprints.objects.filter(
            user=user,
            date__gte=now - timedelta(days=VIEW_DAYS),
            shop_id__in=candidate_ids
        ).values_list('shop_id', flat=True)
    )
    if viewed_shop_ids:
        add_viewed = (KEYWORD_SCORES['name'] + KEYWORD_SCORES['introduce']) \
                     * PERSONAL_WEIGHTS['viewed_related_multiplier']
        for sid in viewed_shop_ids:
            scores[sid] += add_viewed

    # 近期在這些商店下過單（強互動）
    ordered_shop_ids = set(
        ProductOrder.objects.filter(
            order__user=user,
            order__date__gte=now - timedelta(days=ORDER_DAYS),
            product__shop_id__in=candidate_ids
        ).values_list('product__shop_id', flat=True)
    )
    if ordered_shop_ids:
        add_order = KEYWORD_SCORES['tags'] * PERSONAL_WEIGHTS.get('traded_shop_bonus', 1.0)
        for sid in ordered_shop_ids:
            scores[sid] += add_order

    # 新店微量加成（冷啟動）
    EPS = float(PERSONAL_WEIGHTS.get('recent_new_shop_bonus', 0.0)) or 0.0
    if EPS:
        recent_shop_ids = set(
            Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for sid in recent_shop_ids:
            scores[sid] += EPS

    # 最近已推過 → 降權
    recent_reco = set(
        ShopRecommendationHistory.objects.filter(
            user=user, recommended_at__gte=now - timedelta(days=7)
        ).values_list('shop_id', flat=True)
    )
    for sid in list(scores.keys()):
        if sid in recent_reco:
            scores[sid] *= RECOMMENDED_SHOP_WEIGHT_MULTIPLIER

    # ---------------- 排序 + 多樣性（同 owner 最多 K 家） ----------------
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0), reverse=True)

    owner_by_shop = dict(Shop.objects.filter(id__in=prelim).values_list('id', 'owner_id'))
    K_PER_OWNER = 5
    picked, owner_count = [], defaultdict(int)
    for sid in prelim:
        oid = owner_by_shop.get(sid)
        if owner_count[oid] < K_PER_OWNER:
            picked.append(sid)
            owner_count[oid] += 1

    if exclude_seen:
        picked = [sid for sid in picked if sid not in viewed_shop_ids]

    # ---------------- 補滿（僅在沒有 keyword/owner/tag 時才用熱門補） ----------------
    need = max((limit or 20) - len(picked), 0)
    if need and not (keyword or owner or tag):
        hot = (get_hot_shops(request=request)
            .exclude(id__in=set(picked) | recent_reco)
            .values_list('id', flat=True))
        picked += list(hot)[:need]

    if not picked:
        return Shop.objects.none()
    if limit:
        picked = picked[:limit]

    # ---------------- 保序 + 寫歷史 ----------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(picked)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=picked).order_by(preserved)

    history = []
    now_ts = timezone.now()
    for s in qs_ordered:
        history.append(ShopRecommendationHistory(
            user=user,
            shop=s,
            recommended_at=now_ts,
            source='personalized',
            keyword=keyword or None,
            algorithm_version='v2'
        ))
    if history:
        ShopRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered