from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q, Case, When, IntegerField
import math
import random

from goodBuy_want.models import (
    Want, WantFootprints, WantBack, WantRecommendationHistory
)
from goodBuy_web.models import SearchHistory
from goodBuy_web.utils import get_blocked_user_ids
from goodBuy_want.hot_rank import get_hot_wants
from goodBuy_want.recommend_config import (
    PERSONAL_WEIGHTS, KEYWORD_SCORES, RECOMMENDED_WANT_WEIGHT_MULTIPLIER,
    SEARCH_HISTORY_DAYS, VIEW_DAYS, REPLY_DAYS, NEW_DAYS, RECENT_RECO_DAYS
)

def personalized_want_recommendation(
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
    seed_scope="hour"  # 也可傳 "minute" 讓刷新更有變化
):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return Want.objects.none()

    now = timezone.now()
    blocked_ids = set(get_blocked_user_ids(user))

    # ---------------- filter ----------------
    owner_mode = owner is not None

    if owner_mode:
        # ★ 指定 owner：只調整候選集合，其他流程保留
        if user and owner == user:
            # 自己看：公開 + 僅自己可見
            qs = Want.objects.filter(user=owner, permission__id__in=[1, 2])
        else:
            # 看別人：只公開
            qs = Want.objects.filter(user=owner, permission__id=1)
        qs = qs.exclude(user_id__in=blocked_ids)  # 黑名單
    else:
        # 一般個人化：公開 + 最近更新；排黑名單 + 排自己
        qs = (Want.objects.filter(permission__id=1)
              .filter(Q(update__gte=now - timedelta(days=NEW_DAYS)))
              .exclude(user_id__in=blocked_ids)
              .exclude(user=user))

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

    # 非「自己看自己」時再保險套一次時間窗（owner_mode 不套，避免刷掉 0 分貼文）
    if not owner_mode:
        qs = qs.filter(Q(permission__id=1) & Q(update__gte=now - timedelta(days=NEW_DAYS)))

    if not qs.exists():
        return Want.objects.none()

    # ---------------- 首頁冷卻 ----------------
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
        if is_homefeed:
            return Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]
        return Want.objects.none()

    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {wid: 0.0 for wid in candidate_ids}

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
        hit_ids = set()
        for kw in recent_searches:
            hit_ids |= set(qs.filter(
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

    # 最近更新加分（沿用設定檔 recent_new_want_bonus）
    EPS = float(PERSONAL_WEIGHTS.get('recent_new_want_bonus', 0.01)) or 0.01
    if EPS:
        recent_new_ids = set(
            Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for wid in recent_new_ids:
            scores[wid] += EPS

    # 近期已推薦清單
    recent_reco_ids = set(
        WantRecommendationHistory.objects.filter(
            user=user, recommended_at__gte=now - timedelta(days=RECENT_RECO_DAYS)
        ).values_list('want_id', flat=True)
    )

    # 新穎加分：未看過、未回覆、近期未被推薦
    novelty_bonus = float(PERSONAL_WEIGHTS.get('recent_new_want_bonus', 0.01))
    for wid in candidate_ids:
        if (wid not in viewed_ids) and (wid not in replied_ids) and (wid not in recent_reco_ids):
            scores[wid] += novelty_bonus

    # 抖動（minute/hour/day/none）
    if jitter and jitter > 0:
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        rnd = random.Random(f"{user.id}-{now.strftime(_fmt)}")
        for wid in scores:
            scores[wid] += rnd.uniform(-jitter, jitter)

    # 近 N 日重推「降權」（僅在 cooldown 沒啟用且 multiplier < 1.0）
    if (cooldown_days or 0) <= 0 and RECOMMENDED_WANT_WEIGHT_MULTIPLIER < 1.0:
        for wid in recent_reco_ids:
            if wid in scores:
                scores[wid] *= RECOMMENDED_WANT_WEIGHT_MULTIPLIER

    # ---------------- 排序 + 多樣性/抽樣 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0.0), reverse=True)
    L = limit or 20

    if owner_mode:
        # ★ 有 owner：保留評分排序，不做多樣性/抽樣；回傳全部
        final_ids = prelim
    else:
        # 多樣性（同作者最多 K 篇）
        author_by_id = dict(Want.objects.filter(id__in=prelim).values_list('id', 'user_id'))
        K_PER_AUTHOR = 5
        prelim_diverse, author_count = [], defaultdict(int)
        for wid in prelim:
            aid = author_by_id.get(wid)
            if author_count[aid] < K_PER_AUTHOR:
                prelim_diverse.append(wid)
                author_count[aid] += 1

        # 看過者降權（不丟掉）
        if exclude_seen and viewed_ids:
            SEEN_PENALTY = 0.75
            for wid in prelim_diverse:
                if wid in viewed_ids:
                    scores[wid] *= SEEN_PENALTY
            prelim_diverse = sorted(prelim_diverse, key=lambda wid: scores.get(wid, 0.0), reverse=True)

        # 抽樣池
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
                hot = get_hot_wants(request=request).values_list('id', flat=True)[:L]
                return Want.objects.filter(id__in=list(hot))
            return Want.objects.none()

        pool_scores = [scores[wid] for wid in pool]
        probs = softmax(pool_scores)

        # 機率平滑（沿用 explore_ratio）
        if explore_ratio and 0 < explore_ratio < 1 and pool:
            uniform = 1.0 / len(pool)
            probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

        # 隨機種子
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        rng = random.Random(f"pick-{user.id}-{now.strftime(_fmt)}")

        picked = []

        # ===== 探索池（最近更新 & 公開；排黑名單與自己）=====
        if is_homefeed and explore_ratio and explore_ratio > 0:
            explore_qs = (Want.objects.filter(permission__id=1)
                        .exclude(user_id__in=blocked_ids)
                        .exclude(user=user)
                        .filter(Q(update__gte=now - timedelta(days=NEW_DAYS)))
                        .order_by('-update')
                        .values_list('id', flat=True)[:300])
            explore_ids = [wid for wid in explore_qs if wid not in pool]
            novel_ids = [wid for wid in explore_ids
                        if (wid not in viewed_ids and wid not in replied_ids and wid not in recent_reco_ids)]

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
                wid2prob = {wid: p for wid, p in zip(pool, probs)}
                candidates = [wid for wid in pool if wid not in chosen]
                weights = [wid2prob.get(wid, 0.0) for wid in candidates]

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

            # 不足名額只在首頁用熱榜補（且避開近期已推薦）
            if len(picked) < L:
                need = L - len(picked)
                already = set(picked)
                hot = (get_hot_wants(request=request)
                    .exclude(id__in=already | recent_reco_ids)
                    .values_list('id', flat=True))
                picked += list(hot)[:need]

        # 最終穩定排序（分數 + update 作為 tie-break）
        if picked:
            update_map = dict(Want.objects.filter(id__in=picked).values_list('id', 'update'))
            picked = sorted(picked, key=lambda wid: (scores.get(wid, 0.0), update_map.get(wid)), reverse=True)
            final_ids = picked[:L]
        else:
            final_ids = pool[:L]

    # ---------------- 保序 + 寫歷史 ----------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=final_ids).order_by(preserved)

    # 僅首頁寫入推薦歷史，避免汙染冷卻
    if is_homefeed:
        now_ts = timezone.now()
        WantRecommendationHistory.objects.bulk_create(
            [
                WantRecommendationHistory(
                    user=user,
                    want=w,
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


