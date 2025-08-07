from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone

from goodBuy_shop.models import Shop, ShopFootprints, ShopTag, ShopRecommendationHistory
from goodBuy_order.models import ProductOrder
from goodBuy_shop.recommend_config import HOT_WEIGHTS, HOT_PROPORTIONS
from goodBuy_shop.shop_utils import shop_is_active
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_shops(limit=None, days=7, owner=None, keyword=None, tag=None, request=None):
    user = request.user if request else None
    now = timezone.now()
    recent = now - timedelta(days=days)
    scores_raw = defaultdict(lambda: {'sales': 0, 'views': 0, 'new': 0})

    # 最近瀏覽
    views = ShopFootprints.objects.filter(date__gte=recent)
    if owner:
        views = views.filter(shop__owner=owner)
    views = views.values('shop_id').annotate(vc=Count('id'))
    for v in views:
        scores_raw[v['shop_id']]['views'] += v['vc']

    # 最近成交（有效訂單）
    sales = ProductOrder.objects.filter(
        order__date__gte=recent,
        order__order_state__id__in=[4, 5]
    )
    if owner:
        sales = sales.filter(product__shop__owner=owner)
    sales = sales.values('product__shop_id').annotate(sc=Count('id'))
    for s in sales:
        scores_raw[s['product__shop_id']]['sales'] += s['sc']

    # 新店加成
    new_bonus_shops = Shop.objects.filter(update__gte=now - timedelta(days=3))
    for shop in new_bonus_shops:
        scores_raw[shop.id]['new'] = 1

    # 分數正規化（照 HOT_PROPORTIONS）
    final_scores = {}
    for sid, v in scores_raw.items():
        score = (
            HOT_WEIGHTS['recent_sales'] * v['sales'] * HOT_PROPORTIONS['recent_sales'] +
            HOT_WEIGHTS['recent_views'] * v['views'] * HOT_PROPORTIONS['recent_views'] +
            HOT_WEIGHTS['new_shop_bonus'] * v['new'] * HOT_PROPORTIONS['new_shop_bonus']
        )
        final_scores[sid] = score

    # 排序前先過濾商店條件
    sorted_ids = sorted(final_scores, key=final_scores.get, reverse=True)
    shops = Shop.objects.filter(id__in=sorted_ids, permission__id=1)

    if not sorted_ids:
        return shops.none()  # 沒有分數的店就回傳空
    
    # 排除黑名單
    if user:
        blocked_ids = get_blocked_user_ids(user)
    
    if owner:
    # 顯示 owner 的全部商店（但已截止的要排到後面）
        if owner == user:
            shops = Shop.objects.filter(owner=owner)
        else:
            shops = shops.filter(owner=owner)
        shops = sorted(shops, key=lambda s: (not shop_is_active(s), -final_scores.get(s.id, 0)))
    else:
        # 一般推薦：排除黑名單，排除已截止商店
        if user and user.is_authenticated:
            blocked_ids = get_blocked_user_ids(user)
            shops = shops.exclude(owner__id__in=blocked_ids)
            shops = shops.exclude(owner=user)
        else:
            blocked_ids = set()

        shops = [s for s in shops if shop_is_active(s)]
        shops = sorted(shops, key=lambda s: final_scores.get(s.id, 0), reverse=True)

    # 關鍵字與標籤過濾
    if keyword:
        shops = [s for s in shops if keyword.lower() in s.name.lower() or keyword in s.introduce]
    if tag:
        tag_shops = ShopTag.objects.filter(tag__name=tag).values_list('shop_id', flat=True)
        shops = [s for s in shops if s.id in tag_shops]

    # 回傳排序後的 QuerySet（保留順序）
    if isinstance(shops, list):
        shop_ids = [s.id for s in shops]
        preserved = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(shop_ids)], output_field=IntegerField())
        shops_qs = Shop.objects.filter(id__in=shop_ids).order_by(preserved)
    else:
        # QuerySet 保留順序排序
        preserved = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(sorted_ids)], output_field=IntegerField())
        shops_qs = shops.order_by(preserved)

    if limit:
        shops_qs = shops_qs[:limit]

    # 推薦歷史寫入
    if shops_qs:
        recommended_at = timezone.now()
        history_objs = []

        for shop in shops_qs:
            obj_kwargs = {
                'shop': shop,
                'recommended_at': recommended_at,
                'source': 'hot_rank',
                'algorithm_version': 'v1',  # ← 你可視需要加版本
            }

            if keyword:
                obj_kwargs['keyword'] = keyword

            if user and user.is_authenticated:
                obj_kwargs['user'] = user
            elif request:
                session_key = request.session.session_key
                if not session_key:
                    request.session.save()
                    session_key = request.session.session_key
                obj_kwargs['session_key'] = session_key
            else:
                continue

            history_objs.append(ShopRecommendationHistory(**obj_kwargs))

        ShopRecommendationHistory.objects.bulk_create(history_objs, ignore_conflicts=True)

    return shops_qs
