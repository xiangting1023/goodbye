from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone

from goodBuy_shop.models import Shop, ShopFootprints, ShopTag, ShopRecommendationHistory
from goodBuy_order.models import ProductOrder
from goodBuy_shop.recommend_config import HOT_WEIGHTS
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_shops(limit=None, days=7, owner=None, keyword=None, tag=None, request=None):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)

    # -------------------------
    # Step 1: 先過濾（全部保持 QuerySet）
    # -------------------------
    qs = Shop.objects.filter(permission__id__in=[1, 2])

    # 黑名單 / 自己
    if user and user.is_authenticated:
        blocked_ids = get_blocked_user_ids(user)
        qs = qs.exclude(owner_id__in=blocked_ids).exclude(owner=user)

    # owner 過濾（自己看自己的店要能看到已截止）
    if owner:
        if user and owner == user:
            qs = Shop.objects.filter(owner=owner)  # 自己看：不限制時間
        else:
            qs = qs.filter(owner=owner)

    # keyword / tag 過濾
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

    # 若不是「自己看自己的店」，只推「未截止且公開」的店
    if not (owner and user and owner == user):
        NEW_DAYS = 3
        qs = qs.filter(
            Q(permission__id=1) & (
                Q(start_time__lte=now, end_time__gte=now) |            # 正在進行
                Q(update__gte=now - timedelta(days=NEW_DAYS))          # 新店(近3天更新/新增)
            )
        )

    # 沒候選就直接回傳空 QuerySet
    if not qs.exists():
        return qs.none()

    # -------------------------
    # Step 2: 打分（用 Python 算，之後用 preserved order 回到 QuerySet）
    # -------------------------
    shop_ids = list(qs.values_list('id', flat=True))
    scores_raw = defaultdict(lambda: {'sales': 0, 'views': 0, 'new': 0})

    # 近N天瀏覽
    views = (ShopFootprints.objects
            .filter(date__gte=recent, shop_id__in=shop_ids)
            .values('shop_id').annotate(vc=Count('id')))
    for v in views:
        scores_raw[v['shop_id']]['views'] = v['vc']

    # 近N天成交（有效訂單）
    sales = (ProductOrder.objects
            .filter(order__date__gte=recent,
                    order__order_state__id__in=[4, 5],
                    product__shop_id__in=shop_ids)
            .values('product__shop_id').annotate(sc=Count('id')))
    for s in sales:
        scores_raw[s['product__shop_id']]['sales'] = s['sc']

    # 新店加成（update 3天內）
    new_ids = set(
        Shop.objects.filter(id__in=shop_ids, update__gte=now - timedelta(days=3))
        .values_list('id', flat=True)
    )
    for sid in new_ids:
        scores_raw[sid]['new'] = 1

    # 計分
    final_scores = {}
    for sid in shop_ids:
        v = scores_raw[sid]['views']
        sa = scores_raw[sid]['sales']
        nb = scores_raw[sid]['new']
        final_scores[sid] = (
            HOT_WEIGHTS['recent_sales'] * sa +
            HOT_WEIGHTS['recent_views'] * v   +
            HOT_WEIGHTS['new_shop_bonus'] * nb
        )

    print(f"Hot shops scores: {final_scores}")

    # -------------------------
    # 排序
    # -------------------------
    if owner and user and owner == user:
        def active_flag(s):
            return int(s.start_time <= now <= s.end_time and s.permission_id == 1)

        base = qs.only('id', 'start_time', 'end_time', 'permission_id')
        aflag = {s.id: active_flag(s) for s in base}

        ordered_ids = sorted(
            shop_ids,
            key=lambda sid: (aflag.get(sid, 0), final_scores.get(sid, 0)),
            reverse=True
        )
    else:
        ordered_ids = sorted(shop_ids, key=lambda sid: final_scores.get(sid, 0), reverse=True)

    # -------------------------
    # 補滿到 limit：把還沒進來的候選（多半是 0 分）依目前規則接在後面
    # -------------------------
    if limit:
        if len(ordered_ids) < limit:
            # 可能因為排序前的條件造成不足；把剩下候選補上（通常是 0 分）
            fallback_ids = [sid for sid in shop_ids if sid not in set(ordered_ids)]
            ordered_ids += fallback_ids
        # 最後再切片
        ordered_ids = ordered_ids[:limit]

    if not qs.exists():
        qs = Shop.objects.filter(permission__id=1).order_by('-update')[: max(limit or 20, 20)]
    # -------------------------
    # 回傳「有順序」的 QuerySet
    # -------------------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(ordered_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=ordered_ids).order_by(preserved)

    # -------------------------
    # 寫入推薦歷史（保持你原本的 session/user 寫法）
    # -------------------------
    if qs_ordered.exists():
        recommended_at = now
        history = []
        for shop in qs_ordered:
            payload = {
                'shop': shop,
                'recommended_at': recommended_at,
                'source': 'hot_rank',
                'algorithm_version': 'v2',
            }
            if keyword:
                payload['keyword'] = keyword

            if user and user.is_authenticated:
                payload['user'] = user
            elif request:
                session_key = request.session.session_key
                if not session_key:
                    request.session.save()
                    session_key = request.session.session_key
                payload['session_key'] = session_key
            else:
                continue

            history.append(ShopRecommendationHistory(**payload))

        ShopRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered
