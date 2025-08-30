from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone
import math, random

from goodBuy_shop.models import Shop, ShopFootprints, ShopRecommendationHistory
from goodBuy_order.models import ProductOrder
from goodBuy_shop.recommend_config import HOT_WEIGHTS
from goodBuy_web.utils import get_blocked_user_ids

def get_hot_shops(
    limit=None,
    days=7,
    owner=None,
    keyword=None,
    tag=None,
    request=None,
    *,
    cooldown_days=0,                # 冷卻期：最近 n 天推過的先「硬排除」，測試中時間拉短
    explore_ratio=0.12,             # 探索比例：權重抽樣時，讓長尾也有機會
    jitter=0.02,                    # 輕微隨機抖動，打破同分與極靠近的分數
    seed_scope="hour"               # 抖動/抽樣的種子變化範圍："hour" 或 "day"
):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)

    # ---------------- filter ----------------
    qs = Shop.objects.filter(permission__id=1)

    # 黑名單 & 自己
    if user and user.is_authenticated:
        blocked_ids = set(get_blocked_user_ids(user))
        qs = qs.exclude(owner_id__in=blocked_ids).exclude(owner=user)

    # owner / keyword / tag
    if owner:
        if user and owner == user:
            qs = Shop.objects.filter(owner=owner)
        else:
            qs = qs.filter(owner=owner)

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

    # 非「自己看自己的店」：只推公開進行中或近 3 天更新的新店
    NEW_DAYS = 7    # 測試資料少拉長
    if not (owner and user and owner == user):
        qs = qs.filter(
            Q(permission__id=1) & (
                Q(start_time__lte=now, end_time__gte=now) |
                Q(update__gte=now - timedelta(days=NEW_DAYS))
            )
        )

    if not qs.exists():
        return qs.none()

    # 首頁流的冷卻期硬排除
    is_homefeed = not (owner or keyword or tag)
    base_qs = qs  # 留一份原始候選，供後面保底用

    if is_homefeed and cooldown_days and cooldown_days > 0:
        # 取近 cooldown_days 推送過的 shop_id
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
            # 先嘗試完整排除
            remain_qs = qs.exclude(id__in=recent_reco_ids)

            if not remain_qs.exists():
                # ① 完整排除導致 0 → 縮短窗口再試（例如改成 12 小時）
                short_ids = set(
                    ShopRecommendationHistory.objects.filter(
                        user=user if (user and user.is_authenticated) else None,
                        session_key=None if (user and user.is_authenticated) else getattr(request.session, 'session_key', None),
                        recommended_at__gte=now - timedelta(hours=12)
                    ).values_list('shop_id', flat=True)
                )
                remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

            if not remain_qs.exists():
                # 還是 0 → 只排除最近推過的前 30%（保留 70% 供探索）
                recent_list = list(recent_reco_ids)
                keep = set(recent_list[int(len(recent_list) * 0.3):])  # 只排除較新的那一段
                remain_qs = qs.exclude(id__in=keep)

            if not remain_qs.exists():
                # ③ 仍然 0 → 直接放棄冷卻，回到 base_qs（避免 0 筆）
                remain_qs = base_qs

            qs = remain_qs

    # ---------------- score ----------------
    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {sid: 0.0 for sid in candidate_ids}

    # 熱度 = 近 N 天成交 / 瀏覽 / 新店加成（沿用你原本 HOT_WEIGHTS）
    # views
    for row in (ShopFootprints.objects
                .filter(date__gte=recent, shop_id__in=candidate_ids)
                .values('shop_id').annotate(c=Count('id'))):
        sid = row['shop_id']
        scores[sid] += HOT_WEIGHTS['recent_views'] * row['c']

    # sales（有效訂單：state 4、5）
    for row in (ProductOrder.objects
                .filter(order__date__gte=recent,
                        order__order_state__id__in=[4, 5],
                        product__shop_id__in=candidate_ids)
                .values('product__shop_id').annotate(c=Count('id'))):
        sid = row['product__shop_id']
        scores[sid] += HOT_WEIGHTS['recent_sales'] * row['c']

    # new shop bonus（update 3 天內）
    recent_shop_ids = set(
        Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
        .values_list('id', flat=True)
    )
    for sid in recent_shop_ids:
        scores[sid] += HOT_WEIGHTS['new_shop_bonus'] * 1

    # 自己看自己的店：用「active 優先」作為加權
    if owner and user and owner == user:
        base = Shop.objects.filter(id__in=candidate_ids).only('id', 'start_time', 'end_time', 'permission_id')
        ACTIVE_BONUS = max(scores.values(), default=1.0) + 1.0
        for s in base:
            if s.permission_id == 1 and (s.start_time <= now <= s.end_time):
                scores[s.id] += ACTIVE_BONUS

    # 輕微抖動（同 personalized_*）
    if jitter and jitter > 0:
        if user and user.is_authenticated:
            who = f"user-{user.id}"
        else:
            if request and not request.session.session_key:
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
        cond = f"o={owner and getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rnd = random.Random(f"hot-jitter|{who}|{time_key}|{cond}")
        for sid in scores:
            scores[sid] += rnd.uniform(-jitter, jitter)

    # ---------------- 排序 + 多樣性（同 owner 最多 K 家） ----------------
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)

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

    # 權重抽樣
    def softmax(vals, T=0.7):
        if not vals:
            return []
        vmax = max(vals)
        exps = [math.exp((v - vmax) / T) for v in vals]
        s = sum(exps) or 1.0
        return [x / s for x in exps]

    # 從多樣性過的候選再抽樣，讓每次結果更有變化
    pool = picked[:] if picked else prelim[:]
    if not pool:
        prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)
        prelim = prelim[: (limit or 20)]
        if not prelim:
            # 最終保底：抓最近更新的公開店
            return Shop.objects.filter(permission__id=1).order_by('-update')[: (limit or 20)]
        preserved = Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(prelim)],
            output_field=IntegerField()
        )
        return Shop.objects.filter(id__in=prelim).order_by(preserved)

    pool = pool[: (limit or 20) * 10]  # 避免過大
    pool_scores = [scores[sid] for sid in pool]
    probs = softmax(pool_scores, T=0.7)

    if explore_ratio and 0 < explore_ratio < 1:
        uniform = 1.0 / len(pool)
        probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

    # 用同一種 seed 機制，與 personalized_* 對齊
    if user and user.is_authenticated:
        who = f"user-{user.id}"
    else:
        if request and not request.session.session_key:
            request.session.save()
        who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
    time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
    cond = f"o={owner and getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
    rng = random.Random(f"hot-pick|{who}|{time_key}|{cond}")

    need = limit or 20
    final_picks, candidates, weights = [], pool[:], probs[:]
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
        final_picks.append(candidates[idx])
        candidates.pop(idx)
        weights.pop(idx)

    if not final_picks:
    # 退回純分數排序 or 最近更新
        prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0.0), reverse=True)[: (limit or 20)]
        if not prelim:
            return Shop.objects.filter(permission__id=1).order_by('-update')[: (limit or 20)]
        preserved = Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(prelim)],
            output_field=IntegerField()
        )
        return Shop.objects.filter(id__in=prelim).order_by(preserved)


    # ---------------- 保序 + 寫歷史 ----------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_picks)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=final_picks).order_by(preserved)

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
