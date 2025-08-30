from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField
import math            # 【變更】為 softmax 引入
import random          # 【變更】為 jitter/抽樣引入

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
    *,
    cooldown_days=0,                # 冷卻期：最近 n 天推過的先「硬排除」，測試中時間拉短
    explore_ratio=0.15,             # 探索比例：權重抽樣時，讓長尾也有機會
    jitter=0.03,                    # 輕微隨機抖動，打破同分與極靠近的分數
    seed_scope="hour"               # 抖動/抽樣的種子變化範圍："hour" 或 "day"
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Want.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    qs = Want.objects.filter(permission__id=1)
    
    # 近 3 天更新（讓新店也可進榜）
    NEW_DAYS = 30        # 測試資料少拉長
    qs = qs.filter(
        Q(update__gte=now - timedelta(days=NEW_DAYS))
    )
    
    # 黑名單 / 自己
    qs = qs.exclude(user_id__in=blocked_ids)
    if owner:
        qs = qs.filter(user=owner)
    else:
        qs = qs.exclude(user=user)

    # 關鍵字 / 標籤
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

    # 若不是「自己看自己的」，只推「未截止且公開」或「近 30 天有更新」
    if not (owner and user and owner == user):
        NEW_DAYS = 30
        qs = qs.filter(
            Q(permission__id=1) & (
                Q(update__gte=now - timedelta(days=NEW_DAYS))
            )
        )

    if not qs.exists():
        return qs.none()
    
    # 首頁流（無 keyword/owner/tag）判定 & 冷卻期硬排除
    is_homefeed = not (keyword or owner or tag)
    if is_homefeed and cooldown_days and cooldown_days > 0:
        cooled = set(
            WantRecommendationHistory.objects.filter(
                user=user, recommended_at__gte=now - timedelta(days=cooldown_days)
            ).values_list('want_id', flat=True)
        )
        if cooled:
            qs = qs.exclude(id__in=cooled)

    if not qs.exists():
        # 首頁無結果 → 用最新公開貼文保底
        if is_homefeed:
            return Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]
        return Want.objects.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {wid: 0.0 for wid in candidate_ids}  # 先全部設 0，確保新貼文也會出現

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

    # 新帖微量加成（冷啟動）
    EPS = float(PERSONAL_WEIGHTS.get('recent_new_want_bonus', 0.01)) or 0.01
    recent_new_ids = set(
        Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
        .values_list('id', flat=True)
    )
    for wid in recent_new_ids:
        scores[wid] += EPS

    recent_reco = set(
        WantRecommendationHistory.objects.filter(
            user=user, recommended_at__gte=now - timedelta(days=7)
        ).values_list('want_id', flat=True)
    )
    for wid in list(scores.keys()):
        if wid in recent_reco:
            scores[wid] *= RECOMMENDED_WANT_WEIGHT_MULTIPLIER

    # ---------- 輕微抖動（與使用者/時間有關，避免每次完全一樣） ----------
    if jitter and jitter > 0:
        if seed_scope == "hour":
            seed_key = f"{user.id}-{now.strftime('%Y%m%d%H')}"
        else:
            seed_key = f"{user.id}-{now.strftime('%Y%m%d')}"
        rnd = random.Random(seed_key)
        for wid in scores:
            scores[wid] += rnd.uniform(-jitter, jitter)

    # ---------------- 排序 + 多樣性 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0), reverse=True)

    author_by_id = dict(Want.objects.filter(id__in=prelim).values_list('id', 'user_id'))
    K_PER_AUTHOR = 5
    prelim_diverse, author_count = [], defaultdict(int)
    for wid in prelim:
        aid = author_by_id.get(wid)
        if author_count[aid] < K_PER_AUTHOR:
            prelim_diverse.append(wid)
            author_count[aid] += 1

    if exclude_seen:
        prelim_diverse = [wid for wid in prelim_diverse if wid not in viewed_ids]

    # ---------------- 權重抽樣（softmax + epsilon-greedy） ----------------
    def softmax(vals):
        T = 0.7  # 溫度：越大越平，越小越尖
        vmax = max(vals) if vals else 0.0
        exps = [math.exp((v - vmax) / T) for v in vals]
        s = sum(exps) or 1.0
        return [x / s for x in exps]

    pool = prelim_diverse[:200]  # 限制抽樣池，避免超大集合性能問題
    if not pool:
        # 沒東西可抽 → 首頁用熱門保位
        if is_homefeed:
            hot = (get_hot_wants(request=request).values_list('id', flat=True))[:limit or 20]
            return Want.objects.filter(id__in=list(hot))
        return Want.objects.none()

    pool_scores = [scores[wid] for wid in pool]
    probs = softmax(pool_scores)
    if explore_ratio and 0 < explore_ratio < 1:
        uniform = 1.0 / len(pool)
        probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

    # 以 seed 決定抽樣結果（相同 hour/day 可重現）
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
        total = sum(weights)
        if total <= 0:
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
        candidates.pop(idx)
        weights.pop(idx)

    # ---------- 若還不滿 & 是首頁流 → 熱門補位 ----------
    if len(picked) < L and is_homefeed:
        need = L - len(picked)
        already = set(picked)
        hot = (get_hot_wants(request=request)
                .exclude(id__in=already | recent_reco)
                .values_list('id', flat=True))
        picked += list(hot)[:need]

    if not picked:
        return Want.objects.none()

    # 最終裁切
    if limit:
        picked = picked[:limit]

    # ---------- 保序 + 寫歷史 ----------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(picked)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=picked).order_by(preserved)

    # 寫歷史（加上版本號）
    history = []
    now_ts = timezone.now()
    for w in qs_ordered:
        history.append(WantRecommendationHistory(
            user=user,
            want=w,
            recommended_at=now_ts,
            source='personalized',
            keyword=keyword or None,
            algorithm_version='v3'  # 【變更】標版本，便於 A/B 與回溯
        ))
    if history:
        WantRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered
