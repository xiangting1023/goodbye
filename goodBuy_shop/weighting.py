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

def personalized_shop_recommendation(
    request,
    keyword=None,
    tag=None,
    owner=None,
    exclude_seen=False,
    limit=20,
    *,
    cooldown_days=0,                # 冷卻期：最近 n 天推過的先「硬排除」，測試中時間拉短
    explore_ratio=0.15,             # 探索比例：權重抽樣時，讓長尾也有機會
    jitter=0.03,                    # 輕微隨機抖動，打破同分與極靠近的分數
    seed_scope="hour"               # 抖動/抽樣的種子變化範圍："hour" 或 "day"
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Shop.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    qs = Shop.objects.filter(permission__id=1)

    # 進行中 or 近 3 天更新（讓新店也可進榜）
    NEW_DAYS = 30      # 測試資料少拉長
    qs = qs.filter(
        Q(start_time__lte=now, end_time__gte=now) |
        Q(update__gte=now - timedelta(days=NEW_DAYS))
    )

    # 黑名單 / 自己
    qs = qs.exclude(owner_id__in=blocked_ids)
    if owner:
        qs = qs.filter(owner=owner)
    else:
        qs = qs.exclude(owner=user)

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

    # 若不是「自己看自己的店」，只推「未截止且公開」或「近 30 天有更新的新店」
    if not (owner and user and owner == user):
        NEW_DAYS = 30
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
        # 無條件 → 最新公開店保底
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

    # 新店微量加成（冷啟動）
    EPS = float(PERSONAL_WEIGHTS.get('recent_new_shop_bonus', 0.0)) or 0.0
    if EPS:
        recent_shop_ids = set(
            Shop.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for sid in recent_shop_ids:
            scores[sid] += EPS

    # ---------- 輕微抖動（與使用者/時間有關，避免每次完全一樣） ----------
    if jitter and jitter > 0:
        if seed_scope == "hour":
            seed_key = f"{user.id}-{now.strftime('%Y%m%d%H')}"
        else:
            seed_key = f"{user.id}-{now.strftime('%Y%m%d')}"
        rnd = random.Random(seed_key)
        for sid in scores:
            # 在 [-jitter, +jitter] 之間加一個小噪音
            scores[sid] += rnd.uniform(-jitter, jitter)

    # ---------- 排序初稿 ----------
    prelim = sorted(candidate_ids, key=lambda sid: scores.get(sid, 0), reverse=True)

    # 多樣性：同 owner 最多 K 家
    owner_by_shop = dict(Shop.objects.filter(id__in=prelim).values_list('id', 'owner_id'))
    K_PER_OWNER = 5
    prelim_diverse, owner_count = [], defaultdict(int)
    for sid in prelim:
        oid = owner_by_shop.get(sid)
        if owner_count[oid] < K_PER_OWNER:
            prelim_diverse.append(sid)
            owner_count[oid] += 1

    if exclude_seen:
        prelim_diverse = [sid for sid in prelim_diverse if sid not in viewed_shop_ids]

    # ---------- 新增：權重抽樣 (softmax + epsilon-greedy) + 分頁 ----------
    def softmax(vals):
        # 溫度 T：越大越平，越小越尖；用 0.7 讓頭部仍明顯
        T = 0.7
        vmax = max(vals) if vals else 0.0
        exps = [math.exp((v - vmax) / T) for v in vals]
        s = sum(exps) or 1.0
        return [x / s for x in exps]

    pool = prelim_diverse[: 200]  # 限制抽樣池大小，避免超大集合性能問題
    if not pool:
        # 沒東西可抽 → 用熱門補（只在首頁流）
        if is_homefeed:
            hot = (get_hot_shops(request=request).values_list('id', flat=True))[:limit or 20]
            return Shop.objects.filter(id__in=list(hot))
        return Shop.objects.none()

    pool_scores = [scores[sid] for sid in pool]
    probs = softmax(pool_scores)

    # epsilon-greedy：以 (1-explore_ratio) 用權重抽樣，其餘均勻抽樣，避免「永遠同一批」
    if explore_ratio and 0 < explore_ratio < 1:
        uniform = 1.0 / len(pool)
        probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

    # 以 seed 決定抽樣結果（相同 hour/day & page 可重現；跨小時/天不同）
    if seed_scope == "hour":
        pick_seed = f"pick-{user.id}-{now.strftime('%Y%m%d%H')}"
    else:
        pick_seed = f"pick-{user.id}-{now.strftime('%Y%m%d')}"
    rng = random.Random(pick_seed)

    # 權重抽樣「不放回」選 limit 個
    picked = []
    candidates = pool[:]
    weights = probs[:]
    L = limit or 20
    for _ in range(min(L, len(candidates))):
        # 依當前權重抽一個
        total = sum(weights)
        if total <= 0:
            # 權重全 0 → 改均勻
            idx = rng.randrange(len(candidates))
        else:
            r = rng.uniform(0, total)
            acc = 0.0
            idx = 0
            for i, w in enumerate(weights):
                acc += w
                if r <= acc:
                    idx = i
                    break
        picked.append(candidates[idx])
        # 移除該元素（不放回）
        candidates.pop(idx)
        weights.pop(idx)

    # ---------- 若還不滿 & 是首頁流 → 熱門補位 ----------
    if len(picked) < L and is_homefeed:
        need = L - len(picked)
        already = set(picked)
        hot = (get_hot_shops(request=request)
                .exclude(id__in=already)
                .values_list('id', flat=True))
        picked += list(hot)[:need]

    if not picked:
        return Shop.objects.none()

    # ---------- 保序 + 寫歷史 ----------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(picked)],
        output_field=IntegerField()
    )
    qs_ordered = Shop.objects.filter(id__in=picked).order_by(preserved)

    # 記錄推薦歷史（照舊）
    history = []
    now_ts = timezone.now()
    for s in qs_ordered:
        history.append(ShopRecommendationHistory(
            user=user,
            shop=s,
            recommended_at=now_ts,
            source='personalized',
            keyword=keyword or None,
            algorithm_version='v3'  # 升個版號
        ))
    if history:
        ShopRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered
