from collections import defaultdict
from datetime import timedelta
from django.forms import BooleanField
from django.utils import timezone
from django.db.models import Q, Case, When

from goodBuy_shop.hot_rank import get_hot_shops
from goodBuy_shop.models import Shop, ShopFootprints, ShopTag, ShopCollect
from goodBuy_order.models import ProductOrder
from goodBuy_web.models import SearchHistory, Blacklist
from goodBuy_shop.recommend_config import (
    PERSONAL_WEIGHTS, PERSONAL_PROPORTIONS,
    KEYWORD_SCORES, KEYWORD_PROPORTIONS,
    RECOMMENDED_SHOP_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, COLLECT_DAYS, VIEWED_SHOP_DAYS
)
from goodBuy_shop.models import ShopRecommendationHistory
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_shop.shop_utils import shop_is_active

# 過濾
def filter_shops(user, excluded_owner_ids, keywords=None, tags=None, owner=None, exclude_seen=False):
    if owner and owner.id in excluded_owner_ids:
        return Shop.objects.none()
    
    if excluded_owner_ids:
        shops = Shop.objects.exclude(owner_id__in=excluded_owner_ids)
    else:
        shops = Shop.objects.filter(permission__id=1)
    
    if owner:
        if owner == user:
            # 若 owner 是本人 → 顯示所有 owner 的商店（無視黑名單與截止）
            # 基本走不到
            now = timezone.now()
            shops = (
                Shop.objects.filter(owner=owner)
                .annotate(
                    is_end_db=Case(
                        When(end_time__isnull=False, end_time__lte=now, then=True),
                        default=False,
                        output_field=BooleanField()
                    )
                )
                .order_by('is_end_db', '-update')
            )
            return shops
        else:
            shops = shops.filter(owner=owner)
            print("owner 篩選，shops 數量：", shops.count())

    # kw 篩選
    if keywords:
        shops = shops.filter(
            Q(name__icontains=keywords) | 
            Q(introduce__icontains=keywords) |
            Q(product__name__icontains=keywords) | 
            Q(shoptag__tag__name__icontains=keywords), 
            permission__id=1 ).distinct()
    
    # tag 篩選
    if tags:
        shops = shops.filter(shoptag__tag=tags, permission__id=1)

    # 是否排除看過的店
    if exclude_seen:
        seen_ids = ShopFootprints.objects.filter(user=user).values_list('shop_id', flat=True)
        shops = shops.exclude(id__in=seen_ids)

    # 移除已截止商店
    shops = [s for s in shops if shop_is_active(s)]

    print("初步 shops 數量：", len(shops))
    return shops

# 評分
def score(user, shops):
    now = timezone.now()
    final_scores = defaultdict(float)

    recent_recommended_ids = set(
        ShopRecommendationHistory.objects.filter(
            user=user,
            recommended_at__gte=now - timedelta(days=7)
        ).values_list('shop_id', flat=True)
    )

    # 搜尋紀錄
    recent_searches = SearchHistory.objects.filter(
        user=user,
        searched_at__gte=now - timedelta(days=SEARCH_HISTORY_DAYS)
    ).values_list('keyword', flat=True)

    # 若有關鍵字，則使用關鍵字搜尋商店
    for kw in recent_searches:
        for shop in Shop.objects.filter(permission__id=1):
            score = (
                (kw in shop.name) * KEYWORD_SCORES['name'] * KEYWORD_PROPORTIONS['name'] +
                (kw in shop.introduce) * KEYWORD_SCORES['introduce'] * KEYWORD_PROPORTIONS['introduce'] +
                (ShopTag.objects.filter(shop=shop, tag__name=kw).exists()) * KEYWORD_SCORES['tags'] * KEYWORD_PROPORTIONS['tags']
            )
            final_scores[shop.id] += score * PERSONAL_WEIGHTS['search_keyword'] * PERSONAL_PROPORTIONS['search_history']

    # 收藏的商店
    collects = ShopCollect.objects.filter(
        user=user,
        date__gte=now - timedelta(days=COLLECT_DAYS)
    ).values_list('shop_id', flat=True)
    for sid in collects:
        final_scores[sid] += 5 * PERSONAL_PROPORTIONS['fav_related']

    # 曾購買過商品的商店
    bought = ProductOrder.objects.filter(
        order__user=user
    ).values_list('product__shop_id', flat=True)
    for sid in bought:
        final_scores[sid] += 5 * PERSONAL_PROPORTIONS['bought_related']

    # 看過的商店
    viewed_shops = ShopFootprints.objects.filter(
        user=user,
        date__gte=now - timedelta(days=VIEWED_SHOP_DAYS)
    ).values_list('shop_id', flat=True)

    for sid in viewed_shops:
        shop = Shop.objects.filter(id=sid, permission__id=1).first()
        if not shop:
            continue
        score = (
            KEYWORD_SCORES['name'] * KEYWORD_PROPORTIONS['name'] +
            KEYWORD_SCORES['introduce'] * KEYWORD_PROPORTIONS['introduce']
        )
        final_scores[shop.id] += score * PERSONAL_WEIGHTS['viewed_related_multiplier'] * PERSONAL_PROPORTIONS['viewed_related']

    # 曾交易店家（賣家）
    traded_shops = Shop.objects.filter(
        owner__in=ProductOrder.objects.filter(order__user=user).values_list('product__shop__owner', flat=True)
    )
    for s in traded_shops:
        final_scores[s.id] += PERSONAL_WEIGHTS['traded_shop_bonus'] * PERSONAL_PROPORTIONS['traded_shop']

    # 降低已推薦過的店的權重
    for sid in final_scores:
        if sid in recent_recommended_ids:
            final_scores[sid] *= RECOMMENDED_SHOP_WEIGHT_MULTIPLIER

    print('final_scores:', dict(final_scores))
    return final_scores

# 排序
def sorted_shops(shops, final_scores):
    filtered_ids = [s.id for s in shops if shop_is_active(s)]
    sorted_ids = sorted(filtered_ids, key=lambda sid: final_scores[sid], reverse=True)

    print("活躍 shop 數量：", len(sorted_ids))
    return sorted_ids

# 數量補全
def hot_completion(request, limit, sorted_ids, excluded_owner_ids):
    if limit and len(sorted_ids) < limit:
        current_ids = set(sorted_ids)

        # 熱門推薦補滿，排除黑名單、自身、已推薦
        hot_queryset = get_hot_shops(request=request)

        # 過濾黑名單、自己、已推薦過的
        hot_queryset = hot_queryset.exclude(
            id__in=current_ids,
            owner_id__in=excluded_owner_ids
        )

        # 再做切片（避免 QuerySet + slice + filter 錯誤）
        fallback_ids = list(hot_queryset.values_list('id', flat=True))[:limit - len(sorted_ids)]
        sorted_ids += fallback_ids
    
    return sorted_ids
    



# 主程式
def personalized_shop_recommendation(request, keywords=None, tags=None, owner=None, exclude_seen=False, limit=20):
    user = request.user

    if not user.is_authenticated:
        return Shop.objects.none()

    # 黑名單與自己
    blocked_ids = get_blocked_user_ids(user)
    if not owner:
        excluded_owner_ids = blocked_ids | {user.id}
    else:
        excluded_owner_ids = blocked_ids
    print("excluded_owner_ids:", excluded_owner_ids)

    shops = filter_shops(user, excluded_owner_ids, keywords=keywords, tags=tags, owner=owner, exclude_seen=exclude_seen)
    
    final_scores = score(user)
    sorted_ids = sorted_shops(shops, final_scores)

    # 若沒有關鍵字或 tag 或 owner，則補全熱門商店
    if not (keywords or tags or owner):
        sorted_ids = hot_completion(request, limit, sorted_ids, excluded_owner_ids)
    
    # 寫入推薦記錄
    for shop in shops:
        ShopRecommendationHistory.objects.create(
            user=user,
            shop=shop,
            source='personalized',
            keyword=', '.join(keywords) if keywords else None,
        )

    # 回傳 QuerySet 且保留分數順序
    from django.db.models import Case, When, IntegerField
    return Shop.objects.filter(id__in=sorted_ids).order_by(
        Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(sorted_ids)],
            output_field=IntegerField()
        )
    )
