from collections import defaultdict
from datetime import timedelta
from django.db.models import Q, Count, Case, When, IntegerField
from django.utils import timezone
import math, random

from goodBuy_shop.models import Shop, ShopFootprints, ShopRecommendationHistory
from goodBuy_order.models import ProductOrder
from goodBuy_shop.recommend_config import HOT_WEIGHTS, NEW_DAYS
from goodBuy_web.utils import get_blocked_user_ids

def get_hot_shops(
    limit=None,
    days=7,
    owner=None,
    keyword=None,
    tag=None,
    request=None,
    *,
    cooldown_days=0,
    explore_ratio=0.12,
    jitter=0.02,
    seed_scope="hour"
):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)

    # 黑名單 & 自己
    if user and user.is_authenticated:
        blocked_ids = set(get_blocked_user_ids(user))
    else:
        blocked_ids = set()

    # ==== 建立候選集合 ====
    owner_mode = owner is not None
    if owner_mode:
        # ★ owner 模式：只改候選的定義；不套 NEW_DAYS/進行中限制
        if user and owner == user:
            # 自己看自己的店：公開 + 僅自己可見
            qs = Shop.objects.filter(owner=owner, permission_id__in=[1, 2])
        else:
            # 看別人的店：只顯示公開
            qs = Shop.objects.filter(owner=owner, permission_id=1)
        qs = qs.exclude(owner_id__in=blocked_ids)
        qs = qs.distinct()
    else:
        # 一般熱門流
        qs = Shop.objects.filter(permission_id=1)  # 只推公開店
        if blocked_ids:
            qs = qs.exclude(owner_id__in=blocked_ids).exclude(owner=user)
        
        # keyword / tag
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

        # 非 owner 模式：僅推進行中或最近更新的
        qs = qs.filter(
            Q(start_time__lte=now, end_time__gte=now) |
            Q(update__gte=now - timedelta(days=NEW_DAYS))
        )

        # 首頁冷卻（owner 模式關閉，避免把對象的店直接排光）
        is_homefeed = not (keyword or tag)
        base_qs = qs
        if is_homefeed and cooldown_days and cooldown_days > 0:
            if user and user.is_authenticated:
                recent_reco_ids = set(
                    ShopRecommendationHistory.objects.filter(
                        user=user,
                        recommended_at__gte=now - timedelta(days=cooldown_days)
                    ).values_list('shop_id', flat=True)
                )
            else:
                if request and not request.session.session_key:
                    request.session.save()
                sess_key = getattr(getattr(request, 'session', None), 'session_key', None)
                recent_reco_ids = set()
                if sess_key:
                    recent_reco_ids = set(
                        ShopRecommendationHistory.objects.filter(
                            session_key=sess_key,
                            recommended_at__gte=now - timedelta(days=cooldown_days)
                        ).values_list('shop_id', flat=True)
                    )

            if recent_reco_ids:
                remain_qs = qs.exclude(id__in=recent_reco_ids)

                if not remain_qs.exists():
                    short_ids = set(
                        ShopRecommendationHistory.objects.filter(
                            user=user if (user and user.is_authenticated) else None,
                            session_key=None if (user and user.is_authenticated) else getattr(request.session, 'session_key', None),
                            recommended_at__gte=now - timedelta(hours=12)
                        ).values_list('shop_id', flat=True)
                    )
                    remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

                if not remain_qs.exists():
                    # 只排除最新 30%
                    recent_list = list(recent_reco_ids)
                    cut = int(len(recent_list) * 0.3)
                    keep_exclude = set(recent_list[:cut])
                    remain_qs = qs.exclude(id__in=keep_exclude)

                if not remain_qs.exists():
                    remain_qs = base_qs

                qs = remain_qs

    if not qs.exists():
        return qs.none()

    # ==== 熱度評分（owner 模式與一般模式相同） ====
    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {sid: 0.0 for sid in candidate_ids}

    # 最近瀏覽
    for row in (ShopFootprints.objects
                .filter(date__gte=recent, shop_id__in=candidate_ids)
                .values('shop_id').annotate(c=Count('id'))):
        sid = row['shop_id']
        scores[sid] += HOT_WEIGHTS['recent_views'] * row['c']

    # 最近成交（有效訂單：state 4、5）
    for row in (ProductOrder.objects
                .filter(order__date__gte=recent,
                        order__order_state__id__in=[4, 5],
                        product__shop_id__in=candidate_ids)
                .values('product__shop_id').annotate(c=Count('id'))):
        sid = row['product__shop_id']
        scores[sid] += HOT_WEIGHTS['recent_sales'] * row['c']

    # 新店加成（最近 NEW_DAYS 內更新）
    for sid in Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS)).values_list('id', flat=True):
        scores[sid] += HOT_WEIGHTS['new_shop_bonus']

    # 輕微抖動（打破同分）
    if jitter and jitter > 0:
        if user and user.is_authenticated:
            who = f"user-{user.id}"
        else:
            if request and not request.session.session_key:
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
        cond = f"o={getattr(owner,'id',owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rnd = random.Random(f"hot-jitter|{who}|{time_key}|{cond}")
        for sid in scores:
            scores[sid] += rnd.uniform(-jitter, jitter)

    # ==== 排序 / 多樣性 / 抽樣 ====
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)

    if owner_mode:
        # ★ owner 模式：不做「每位店主最多 K 家」也不做抽樣，避免把該 owner 的店濾掉。
        # 依分數排序即可；同分時已由 jitter 打散。必要時可依更新時間再做穩定次序。
        final_ids = prelim[: (limit or len(prelim))]
    else:
        # 一般熱門流：保留你原本的多樣性與抽樣
        owner_by_shop = dict(Shop.objects.filter(id__in=prelim).values_list('id', 'owner_id'))
        K_PER_OWNER = 5
        picked, owner_count = [], defaultdict(int)
        for sid in prelim:
            oid = owner_by_shop.get(sid)
            if owner_count[oid] < K_PER_OWNER:
                picked.append(sid)
                owner_count[oid] += 1
            if limit and len(picked) >= limit:
                break

        def softmax(vals, T=0.7):
            if not vals:
                return []
            vmax = max(vals)
            exps = [math.exp((v - vmax) / T) for v in vals]
            s = sum(exps) or 1.0
            return [x / s for x in exps]

        pool = picked[:] if picked else prelim[:]
        if not pool:
            prelim = prelim[: (limit or 20)]
            if not prelim:
                return Shop.objects.filter(permission_id=1).order_by('-update')[: (limit or 20)]
            preserved = Case(
                *[When(id=pk, then=pos) for pos, pk in enumerate(prelim)],
                output_field=IntegerField()
            )
            return Shop.objects.filter(id__in=prelim).order_by(preserved)

        pool = pool[: (limit or 20) * 10]
        pool_scores = [scores[sid] for sid in pool]
        probs = softmax(pool_scores, T=0.7)
        if explore_ratio and 0 < explore_ratio < 1:
            uniform = 1.0 / len(pool)
            probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

        if user and user.is_authenticated:
            who = f"user-{user.id}"
        else:
            if request and not request.session.session_key:
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
        cond = f"o=None|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rng = random.Random(f"hot-pick|{who}|{time_key}|{cond}")

        need = limit or 20
        final_ids, candidates, weights = [], pool[:], probs[:]
        for _ in range(min(need, len(candidates))):
            total = sum(weights)
            if total <= 0:
                idx = rng.randrange(len(candidates))
            else:
                r, acc, idx = rng.uniform(0, total), 0.0, 0
                for i, w in enumerate(weights):
                    acc += w
                    if r <= acc:
                        idx = i
                        break
            final_ids.append(candidates[idx])
            candidates.pop(idx)
            weights.pop(idx)

        if not final_ids:
            prelim = prelim[: (limit or 20)]
            if not prelim:
                return Shop.objects.filter(permission_id=1).order_by('-update')[: (limit or 20)]
            preserved = Case(
                *[When(id=pk, then=pos) for pos, pk in enumerate(prelim)],
                output_field=IntegerField()
            )
            return Shop.objects.filter(id__in=prelim).order_by(preserved)

    # ==== 保序 + 寫歷史（owner 模式不寫歷史，避免汙染首頁冷卻） ====
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=final_ids).order_by(preserved)

    if is_homefeed :
        history = []
        now_ts = timezone.now()
        for s in qs_ordered:
            payload = {
                'shop': s,
                'recommended_at': now_ts,
                'source': 'hot_rank',
                'algorithm_version': 'v3',
            }
            if keyword:
                payload['keyword'] = keyword
            if user and user.is_authenticated:
                payload['user'] = user
            else:
                if request and not request.session.session_key:
                    request.session.save()
                sess_key = getattr(request.session, 'session_key', None)
                if not sess_key:
                    continue
                payload['session_key'] = sess_key
            history.append(ShopRecommendationHistory(**payload))
        if history:
            ShopRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered
