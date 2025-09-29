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
    explore_ratio=0.5,
    jitter=0.02,
    seed_scope="minute"
):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)
    owner_mode = owner is not None
    L = limit or 20

    # ---------- 黑名單 / 自己 ----------
    if user and getattr(user, "is_authenticated", False):
        blocked_ids = set(get_blocked_user_ids(user))
    else:
        blocked_ids = set()

    # ---------- 建立候選 ----------
    if owner_mode:
        # 指定 owner：只改候選集合，不套 NEW_DAYS/進行中限制
        if user and getattr(user, "is_authenticated", False) and owner == user:
            qs = Shop.objects.filter(owner=owner, permission_id__in=[1, 2])
        else:
            qs = Shop.objects.filter(owner=owner, permission_id=1)
        if blocked_ids:
            qs = qs.exclude(owner_id__in=blocked_ids)
    else:
        qs = Shop.objects.filter(permission_id=1)
        if blocked_ids:
            qs = qs.exclude(owner_id__in=blocked_ids)
        if user and getattr(user, "is_authenticated", False):
            qs = qs.exclude(owner_id=user.id)  # 避免把自己的店推給自己

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

        # 非 owner 模式：僅推進行中或最近 NEW_DAYS 更新
        qs = qs.filter(
            Q(start_time__lte=now, end_time__gte=now) |
            Q(update__gte=now - timedelta(days=NEW_DAYS))
        )

    qs = qs.distinct()
    if not qs.exists():
        return qs.none()

    # ---------- 首頁冷卻 ----------
    is_homefeed = (not owner_mode) and (not keyword) and (not tag)
    base_qs = qs
    if is_homefeed and cooldown_days and cooldown_days > 0:
        if user and getattr(user, "is_authenticated", False):
            recent_reco_ids = set(
                ShopRecommendationHistory.objects.filter(
                    user=user,
                    recommended_at__gte=now - timedelta(days=cooldown_days)
                ).values_list('shop_id', flat=True)
            )
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            sess_key = getattr(request.session, 'session_key', None)
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

            # 若整批被清光，放寬為 12 小時冷卻
            if not remain_qs.exists():
                short_ids = set(
                    ShopRecommendationHistory.objects.filter(
                        user=user if (user and getattr(user, "is_authenticated", False)) else None,
                        session_key=None if (user and getattr(user, "is_authenticated", False)) else getattr(request.session, 'session_key', None),
                        recommended_at__gte=now - timedelta(hours=12)
                    ).values_list('shop_id', flat=True)
                )
                remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

            # 再不行：只排除最新 30% 的冷卻名單
            if not remain_qs.exists():
                recent_list = list(recent_reco_ids)
                cut = int(len(recent_list) * 0.3)
                keep_exclude = set(recent_list[:cut])
                remain_qs = qs.exclude(id__in=keep_exclude)

            qs = remain_qs if remain_qs.exists() else base_qs

    if not qs.exists():
        return qs.none()

    # ---------- 熱度評分 ----------
    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {sid: 0.0 for sid in candidate_ids}

    # 最近瀏覽
    for row in (ShopFootprints.objects
                .filter(date__gte=recent, shop_id__in=candidate_ids)
                .values('shop_id').annotate(c=Count('id'))):
        sid = row['shop_id']
        scores[sid] += HOT_WEIGHTS.get('recent_views', 0) * row['c']

    # 最近成交（有效訂單：state 4、5）
    for row in (ProductOrder.objects
                .filter(order__date__gte=recent,
                        order__order_state__id__in=[4, 5],
                        product__shop_id__in=candidate_ids)
                .values('product__shop_id').annotate(c=Count('id'))):
        sid = row['product__shop_id']
        scores[sid] += HOT_WEIGHTS.get('recent_sales', 0) * row['c']

    # 新店加成（最近 NEW_DAYS 內更新）
    if HOT_WEIGHTS.get('new_shop_bonus', 0):
        recent_shop_ids = set(
            Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for sid in recent_shop_ids:
            scores[sid] += HOT_WEIGHTS['new_shop_bonus']

    # 抖動（支援 minute/hour/day）
    if jitter and jitter > 0:
        if user and getattr(user, "is_authenticated", False):
            who = f"user-{user.id}"
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        cond = f"o={getattr(owner,'id',owner)}|k={bool(keyword)}|t={getattr(tag,'id',tag)}"
        rnd = random.Random(f"shop-hot-jitter|{who}|{now.strftime(_fmt)}|{cond}")
        for sid in scores:
            scores[sid] += rnd.uniform(-jitter, jitter)

    # ---------- 排序 ----------
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)

    if owner_mode:
        # owner 模式：不做多樣性/抽樣；直接回傳排序（取前 L 或全部）
        final_ids = prelim[:L]
    else:
        # 多樣性：同店主最多 K 家
        owner_by_shop = dict(Shop.objects.filter(id__in=prelim).values_list('id', 'owner_id'))
        K_PER_OWNER = 5
        prelim_diverse, owner_count = [], defaultdict(int)
        for sid in prelim:
            oid = owner_by_shop.get(sid)
            if owner_count[oid] < K_PER_OWNER:
                prelim_diverse.append(sid)
                owner_count[oid] += 1

        # 抽樣池（權重 = softmax(scores)）
        def softmax(vals, T=0.7):
            if not vals:
                return []
            vmax = max(vals)
            exps = [math.exp((v - vmax) / T) for v in vals]
            s = sum(exps) or 1.0
            return [x / s for x in exps]

        pool = (prelim_diverse or prelim)[:200]
        if not pool:
            # 極端情況：直接退回最近更新
            return Shop.objects.filter(permission_id=1).order_by('-update')[:L]

        pool_scores = [scores[sid] for sid in pool]
        probs = softmax(pool_scores, T=0.7)

        # 機率平滑（沿用 explore_ratio）
        if explore_ratio and 0 < explore_ratio < 1:
            uniform = 1.0 / len(pool)
            probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

        # 取得「近期已推薦」名單（用於探索池優先避開）
        if user and getattr(user, "is_authenticated", False):
            who = f"user-{user.id}"
            recent_reco_ids = set(
                ShopRecommendationHistory.objects.filter(
                    user=user, recommended_at__gte=now - timedelta(days=7)
                ).values_list('shop_id', flat=True)
            )
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            sess_key = getattr(request.session, 'session_key', None)
            who = f"sess-{sess_key or 'anon'}"
            recent_reco_ids = set()
            if sess_key:
                recent_reco_ids = set(
                    ShopRecommendationHistory.objects.filter(
                        session_key=sess_key, recommended_at__gte=now - timedelta(days=7)
                    ).values_list('shop_id', flat=True)
                )

        # 建立探索池：最近更新的公開店（避開黑名單/自己），優先未被近期推薦
        _exp_base = Shop.objects.filter(permission_id=1)
        if blocked_ids:
            _exp_base = _exp_base.exclude(owner_id__in=blocked_ids)
        if user and getattr(user, "is_authenticated", False):
            _exp_base = _exp_base.exclude(owner_id=user.id)

        explore_qs = (_exp_base
                      .filter(Q(start_time__lte=now, end_time__gte=now) |
                              Q(update__gte=now - timedelta(days=NEW_DAYS)))
                      .order_by('-update')
                      .values_list('id', flat=True)[:300])
        explore_ids = [sid for sid in explore_qs if sid not in pool]
        novel_ids = [sid for sid in explore_ids if sid not in recent_reco_ids]

        # 探索名額（20%~50%，由 explore_ratio 控制）
        explore_min_pick = max(1, round(L * min(0.5, max(0.2, explore_ratio))))
        explore_pool = (novel_ids or explore_ids)[:max(1, min(200, explore_min_pick))]

        # 隨機種子（與抖動一致的顆粒度）
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        cond = f"o=None|k={bool(keyword)}|t={getattr(tag,'id',tag)}"
        rng = random.Random(f"shop-hot-pick|{who}|{now.strftime(_fmt)}|{cond}")

        final_ids = []

        # 先抽「探索名額」（均勻、無放回）
        exp_candidates = explore_pool[:]
        while exp_candidates and len(final_ids) < explore_min_pick:
            idx = rng.randrange(len(exp_candidates))
            final_ids.append(exp_candidates.pop(idx))

        # 再抽「權重名額」（依 probs、無放回）
        chosen = set(final_ids)
        sid2prob = {sid: p for sid, p in zip(pool, probs)}
        candidates = [sid for sid in pool if sid not in chosen]
        weights = [sid2prob.get(sid, 0.0) for sid in candidates]

        while candidates and len(final_ids) < L:
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

        # 若仍不足，先用最近更新補，再用分數補
        if len(final_ids) < L:
            already = set(final_ids)
            fallback = list(qs.exclude(id__in=already).order_by('-update').values_list('id', flat=True)[: (L - len(final_ids))])
            final_ids += fallback
            if len(final_ids) < L:
                rest = [sid for sid in prelim if sid not in already][: (L - len(final_ids))]
                final_ids += rest

    # ---------- 保序 + 寫歷史 ----------
    # tie-break：同分時用 update（越新越前）
    update_map = dict(Shop.objects.filter(id__in=final_ids).values_list('id', 'update'))
    final_ids = sorted(final_ids, key=lambda sid: (scores.get(sid, 0.0), update_map.get(sid)), reverse=True)

    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=final_ids).order_by(preserved)

    # 僅首頁寫入推薦歷史（owner 模式避免汙染）
    if is_homefeed:
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
            if user and getattr(user, "is_authenticated", False):
                payload['user'] = user
            else:
                if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                    request.session.save()
                sess_key = getattr(request.session, 'session_key', None)
                if not sess_key:
                    continue
                payload['session_key'] = sess_key
            history.append(ShopRecommendationHistory(**payload))
        if history:
            ShopRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered

