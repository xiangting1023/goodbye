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
    SEARCH_HISTORY_DAYS, VIEW_DAYS, ORDER_DAYS,NEW_DAYS, RECENT_RECO_DAYS
)

def personalized_shop_recommendation(
    request,
    keyword=None,
    tag=None,
    owner=None,
    exclude_seen=False,
    limit=20,
    *,
    cooldown_days=0,
    explore_ratio=0.5,
    jitter=0.05,
    seed_scope="minute"
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Shop.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    # ★★ owner 模式：只調整候選集合，其它評分流程不變 ★★
    if owner is not None:
        if user and owner == user:
            # 自己看自己的店：公開 + 僅自己可見
            qs = Shop.objects.filter(owner=owner, permission_id__in=[1, 2])
        else:
            # 看別人的店：該 owner 的全部公開店
            qs = Shop.objects.filter(owner=owner, permission_id=1)
        qs = qs.exclude(owner_id__in=blocked_ids)
    else:
        # 一般個人化流：公開店，且「進行中或近 NEW_DAYS 有更新」
        qs = (Shop.objects.filter(permission_id=1)
              .filter(Q(start_time__lte=now, end_time__gte=now) |
                      Q(update__gte=now - timedelta(days=NEW_DAYS)))
              .exclude(owner_id__in=blocked_ids)
              .exclude(owner=user))

    # keyword / tag 過濾（兩種模式都要）
    if keyword:
        qs = qs.filter(
            Q(name__icontains=keyword) |
            Q(introduce__icontains=keyword) |
            Q(shoptag__tag__name__icontains=keyword) |
            Q(owner__username__icontains=keyword)
        )
    if tag:
        qs = qs.filter(shoptag__tag=tag)
        print(len(qs))

    qs = qs.distinct()

    # 有傳 owner（無論是不是自己）就不再加時間窗，避免把 owner 的 0 分店刷掉
    if owner is None:
        qs = qs.filter(
            Q(permission__id=1) & (
                Q(start_time__lte=now, end_time__gte=now) |
                Q(update__gte=now - timedelta(days=NEW_DAYS))
            )
        )

    if not qs.exists():
        return qs.none()

    # ---------- 首頁：冷卻期硬排除（最近推過的不要再推） ----------
    is_homefeed = not (keyword or owner or tag)
    if is_homefeed and cooldown_days and cooldown_days > 0:
        cool_ids = set(
            ShopRecommendationHistory.objects.filter(
                user=user,
                recommended_at__gte=now - timedelta(days=cooldown_days)
            ).values_list('shop_id', flat=True)
        )
        if cool_ids:
            qs = qs.exclude(id__in=cool_ids)

    if not qs.exists():
        if is_homefeed:
            return Shop.objects.filter(permission__id=1).order_by('-update')[: (limit or 20)]
        return qs.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {sid: 0.0 for sid in candidate_ids}

    # ---------------- score ----------------
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
        matched_ids = set()
        for kw in recent_searches:
            matched_ids |= set(qs.filter(
                Q(name__icontains=kw) |
                Q(introduce__icontains=kw) |
                Q(shoptag__tag__name__icontains=kw) |
                Q(owner__username__icontains=kw)
            ).values_list('id', flat=True))
        for sid in matched_ids:
            scores[sid] += kw_base

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

    # 新店曝光（沿用設定檔）
    EPS = float(PERSONAL_WEIGHTS.get('new_shop_bonus', 0.0)) or 0.0
    if EPS:
        recent_shop_ids = set(
            Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for sid in recent_shop_ids:
            scores[sid] += EPS

    # 對「未看過、未下單、7天內未被推薦」者，給一點新穎加分（沿用 new_shop_bonus）
    recent_rec_ids = set(
        ShopRecommendationHistory.objects.filter(
            user=user, recommended_at__gte=now - timedelta(days=max(RECENT_RECO_DAYS, 7))
        ).values_list('shop_id', flat=True)
    )
    novelty_bonus = float(PERSONAL_WEIGHTS.get('new_shop_bonus', 0.8))
    for sid in candidate_ids:
        if (sid not in viewed_shop_ids) and (sid not in ordered_shop_ids) and (sid not in recent_rec_ids):
            scores[sid] += novelty_bonus

    # 抖動（minute/hour/day 對應種子）
    if jitter and jitter > 0:
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        rnd = random.Random(f"{user.id}-{now.strftime(_fmt)}")
        for sid in scores:
            scores[sid] += rnd.uniform(-jitter, jitter)

    # 近 N 日重推「降權」：僅在 cooldown 沒啟用時才生效（你設定檔目前是 1.0，不會進來）
    if (cooldown_days or 0) <= 0 and RECOMMENDED_SHOP_WEIGHT_MULTIPLIER < 1.0:
        recent_rec_ids2 = set(
            ShopRecommendationHistory.objects.filter(
                user=user,
                recommended_at__gte=now - timedelta(days=RECENT_RECO_DAYS)
            ).values_list('shop_id', flat=True)
        )
        for sid in recent_rec_ids2:
            if sid in scores:
                scores[sid] *= RECOMMENDED_SHOP_WEIGHT_MULTIPLIER

    # ---------- 排序初稿 ----------
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)

    owner_mode = owner is not None
    L = limit or 20

    if owner_mode:
        # 有 owner：保留評分，但不做多樣性/抽樣，回傳前 L
        final_ids = prelim[:L]
    else:
        # 多樣性（同 owner 最多 K 家）
        owner_by_shop = dict(Shop.objects.filter(id__in=prelim).values_list('id', 'owner_id'))
        K_PER_OWNER = 10
        prelim_diverse, owner_count = [], defaultdict(int)
        for sid in prelim:
            oid = owner_by_shop.get(sid)
            if owner_count[oid] < K_PER_OWNER:
                prelim_diverse.append(sid)
                owner_count[oid] += 1

        # 看過者降權（不丟掉）
        if exclude_seen:
            SEEN_PENALTY = 0.75
            for sid in prelim_diverse:
                if sid in viewed_shop_ids:
                    scores[sid] *= SEEN_PENALTY
            prelim_diverse = sorted(prelim_diverse, key=lambda sid: scores.get(sid, 0.0), reverse=True)

        # 構建抽樣池與權重
        def softmax(vals, T=0.9):
            if not vals:
                return []
            m = max(vals)
            exps = [math.exp((v - m) / T) for v in vals]
            s = sum(exps) or 1.0
            return [x / s for x in exps]

        pool = prelim_diverse[:200]
        if not pool:
            if is_homefeed:
                hot = get_hot_shops(request=request).values_list('id', flat=True)[:L]
                return Shop.objects.filter(id__in=list(hot))
            return Shop.objects.none()

        pool_scores = [scores[sid] for sid in pool]
        probs = softmax(pool_scores)

        # 機率平滑（沿用 explore_ratio）
        if explore_ratio and 0 < explore_ratio < 1 and pool:
            uniform = 1.0 / len(pool)
            probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

        # 隨機種子（支援 minute/hour/day）
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        rng = random.Random(f"pick-{user.id}-{now.strftime(_fmt)}")

        picked = []

        # ===== 探索池（最近更新 & 進行中，排除黑名單與自己）=====
        if is_homefeed and explore_ratio and explore_ratio > 0:
            explore_qs = (Shop.objects.filter(permission_id=1)
                        .exclude(owner_id__in=blocked_ids)
                        .exclude(owner=user)
                        .filter(Q(start_time__lte=now, end_time__gte=now) |
                                Q(update__gte=now - timedelta(days=NEW_DAYS)))
                        .order_by('-update')
                        .values_list('id', flat=True)[:300])
            explore_ids = [sid for sid in explore_qs if sid not in pool]
            novel_ids = [sid for sid in explore_ids
                        if (sid not in viewed_shop_ids and sid not in ordered_shop_ids and sid not in recent_rec_ids)]

            # 用 explore_ratio 決定探索保底名額（20%~50%）
            explore_min_pick = max(1, round(L * min(0.5, max(0.2, explore_ratio))))
            explore_pool = (novel_ids or explore_ids)[:max(1, min(200, explore_min_pick))]

            # 先抽探索名額（均勻、無放回）
            exp_candidates = explore_pool[:]
            while exp_candidates and len(picked) < explore_min_pick:
                idx = rng.randrange(len(exp_candidates))
                picked.append(exp_candidates.pop(idx))

            # 再抽個人化名額（依 probs、無放回）
            remaining_L = L - len(picked)
            if remaining_L > 0 and pool:
                chosen = set(picked)
                sid2prob = {sid: p for sid, p in zip(pool, probs)}
                candidates = [sid for sid in pool if sid not in chosen]
                weights = [sid2prob.get(sid, 0.0) for sid in candidates]

                for _ in range(min(remaining_L, len(candidates))):
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
                    picked.append(candidates[idx])
                    candidates.pop(idx)
                    weights.pop(idx)

            # 不足名額只在首頁用熱榜補
            if len(picked) < L:
                need = L - len(picked)
                already = set(picked)
                hot = (get_hot_shops(request=request)
                    .exclude(id__in=already)
                    .values_list('id', flat=True))
                picked += list(hot)[:need]

        # 一定要賦值 final_ids（不論是否補熱榜）
        if picked:
            update_map = dict(Shop.objects.filter(id__in=picked).values_list('id', 'update'))
            picked = sorted(picked, key=lambda sid: (scores.get(sid, 0.0), update_map.get(sid)), reverse=True)
            final_ids = picked[:L]
        else:
            # 極少數狀況抽不到時，直接取 pool 前 L
            final_ids = pool[:L]

    # 保序排序（依抽樣後 final_ids 的順序）
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=final_ids).order_by(preserved)

    # 只有在主頁推送才寫入推薦歷史，避免汙染首頁冷卻
    if is_homefeed:
        now_ts = timezone.now()
        ShopRecommendationHistory.objects.bulk_create(
            [
                ShopRecommendationHistory(
                    user=user,
                    shop=w,
                    recommended_at=now_ts,
                    source='personalized',
                    keyword=keyword or None,
                    algorithm_version='v3',
                )
                for w in qs_ordered
            ],
            ignore_conflicts=True,
        )

    return qs_ordered


