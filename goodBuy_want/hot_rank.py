# goodBuy_want/hot_rank.py
from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone
import math, random   # 加入抽樣與抖動

from goodBuy_want.models import (
    Want, WantFootprints, WantBack, WantRecommendationHistory
)
from goodBuy_want.recommend_config import HOT_WEIGHTS, NEW_DAYS
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_wants(
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

    # ---------------- filter ----------------
    qs = Want.objects.filter(permission__id=1)

    # 黑名單 & 自己
    if user and user.is_authenticated:
        blocked_ids = set(get_blocked_user_ids(user))
        qs = qs.exclude(user_id__in=blocked_ids).exclude(user=user)
    else:
        blocked_ids = set()

    # owner / keyword / tag
    if owner_mode:
        # ★ 有 owner：只調整候選集合，其餘流程保留
        if user and owner == user:
            qs = Want.objects.filter(user=owner, permission__id__in=[1, 2])  # 自己：公開+僅自己可見
        else:
            qs = Want.objects.filter(user=owner, permission__id=1)           # 他人：僅公開
    elif owner:
        # （保留原邏輯的容錯）
        if user and owner == user:
            qs = Want.objects.filter(user=owner)
        else:
            qs = qs.filter(user=owner)

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

    # 若不是 owner 模式：只推公開且近 NEW_DAYS 有更新（保留原規則）
    if not owner_mode:
        qs = qs.filter(Q(permission__id=1) & Q(update__gte=now - timedelta(days=NEW_DAYS)))

    if not qs.exists():
        return qs.none()

    # 首頁流判斷（無 owner/keyword/tag）
    is_homefeed = not (owner or keyword or tag)
    base_qs = qs

    # ---------------- 首頁冷卻（避免一直重推） ----------------
    recent_reco_ids_for_user = set()
    if is_homefeed and cooldown_days and cooldown_days > 0:
        if user and user.is_authenticated:
            recent_reco_ids_for_user = set(
                WantRecommendationHistory.objects.filter(
                    user=user,
                    recommended_at__gte=now - timedelta(days=cooldown_days)
                ).values_list('want_id', flat=True)
            )
        else:
            # 匿名以 session_key 判斷
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            sess_key = getattr(request.session, 'session_key', None)
            if sess_key:
                recent_reco_ids_for_user = set(
                    WantRecommendationHistory.objects.filter(
                        session_key=sess_key,
                        recommended_at__gte=now - timedelta(days=cooldown_days)
                    ).values_list('want_id', flat=True)
                )

        if recent_reco_ids_for_user:
            remain_qs = qs.exclude(id__in=recent_reco_ids_for_user)
            # 若整批被清光，放寬為 12 小時冷卻
            if not remain_qs.exists():
                short_ids = set(
                    WantRecommendationHistory.objects.filter(
                        user=user if (user and user.is_authenticated) else None,
                        session_key=None if (user and user.is_authenticated) else getattr(request.session, 'session_key', None),
                        recommended_at__gte=now - timedelta(hours=12)
                    ).values_list('want_id', flat=True)
                )
                remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

            # 再不行：放回 70% 冷卻名單
            if not remain_qs.exists():
                recent_list = list(recent_reco_ids_for_user)
                keep = set(recent_list[int(len(recent_list) * 0.3):])
                remain_qs = qs.exclude(id__in=keep)

            qs = remain_qs if remain_qs.exists() else base_qs

    if not qs.exists():
        return qs.none()

    # ---------------- score ----------------
    candidate_ids = list(qs.values_list('id', flat=True))
    scores = {wid: 0.0 for wid in candidate_ids}

    for row in (WantFootprints.objects
                .filter(date__gte=recent, want_id__in=candidate_ids)
                .values('want_id').annotate(c=Count('id'))):
        wid = row['want_id']
        scores[wid] += HOT_WEIGHTS.get('recent_views', 0) * row['c']

    for row in (WantBack.objects
                .filter(date__gte=recent, want_id__in=candidate_ids)
                .values('want_id').annotate(c=Count('id'))):
        wid = row['want_id']
        scores[wid] += HOT_WEIGHTS.get('recent_replies', 0) * row['c']

    if HOT_WEIGHTS.get('new_want_bonus', 0):
        recent_want_ids = set(
            Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for wid in recent_want_ids:
            scores[wid] += HOT_WEIGHTS['new_want_bonus']

    # 抖動（支援 minute/hour/day）
    if jitter and jitter > 0:
        if user and user.is_authenticated:
            who = f"user-{user.id}"
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        cond = f"o={getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rnd = random.Random(f"want-hot-jitter|{who}|{now.strftime(_fmt)}|{cond}")
        for wid in scores:
            scores[wid] += rnd.uniform(-jitter, jitter)

    # ---------------- 排序 + 多樣性 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0.0), reverse=True)

    if owner_mode:
        # ★ 有 owner：不做 K_PER_AUTHOR、抽樣與 limit，確保「全部」返回
        final_picks = prelim
    else:
        author_by_want = dict(Want.objects.filter(id__in=prelim).values_list('id', 'user_id'))
        K_PER_AUTHOR = 5
        prelim_diverse, author_count = [], defaultdict(int)
        for wid in prelim:
            aid = author_by_want.get(wid)
            if author_count[aid] < K_PER_AUTHOR:
                prelim_diverse.append(wid)
                author_count[aid] += 1

        # ===== 建立抽樣池（softmax 權重）=====
        def softmax(vals, T=0.7):
            if not vals:
                return []
            vmax = max(vals)
            exps = [math.exp((v - vmax) / T) for v in vals]
            s = sum(exps) or 1.0
            return [x / s for x in exps]

        pool = (prelim_diverse or prelim)[:200]
        if not pool:
            return Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]

        pool_scores = [scores[wid] for wid in pool]
        probs = softmax(pool_scores, T=0.7)

        # 機率平滑（沿用 explore_ratio）
        if explore_ratio and 0 < explore_ratio < 1:
            uniform = 1.0 / len(pool)
            probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

        # ===== 探索池（保證探索名額）=====
        # 來源：最近更新的公開貼文；避開黑名單/自己；優先避開「近期已推薦」
        if user and user.is_authenticated:
            who = f"user-{user.id}"
            recent_reco_ids = set(
                WantRecommendationHistory.objects.filter(
                    user=user, recommended_at__gte=now - timedelta(days=7)
                ).values_list('want_id', flat=True)
            )
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            sess_key = getattr(request.session, 'session_key', None)
            who = f"sess-{sess_key or 'anon'}"
            recent_reco_ids = set()
            if sess_key:
                recent_reco_ids = set(
                    WantRecommendationHistory.objects.filter(
                        session_key=sess_key, recommended_at__gte=now - timedelta(days=7)
                    ).values_list('want_id', flat=True)
                )

        _explore_base = Want.objects.filter(permission__id=1).exclude(user_id__in=blocked_ids)
        if user and getattr(user, "is_authenticated", False):
            _explore_base = _explore_base.exclude(user_id=user.id)

        explore_qs = (_explore_base
                    .filter(Q(update__gte=now - timedelta(days=NEW_DAYS)))
                    .order_by('-update')
                    .values_list('id', flat=True)[:300])

        explore_ids = [wid for wid in explore_qs if wid not in pool]
        # 優先「近期未被推薦」的貼文
        novel_ids = [wid for wid in explore_ids if wid not in recent_reco_ids]

        need = limit or 20
        explore_min_pick = max(1, round(need * min(0.5, max(0.2, explore_ratio))))  # 20%~50%
        explore_pool = (novel_ids or explore_ids)[:max(1, min(200, explore_min_pick))]

        # ===== 隨機種子（抽樣與抖動一致的顆粒度）=====
        _fmt = {'minute': '%Y%m%d%H%M', 'hour': '%Y%m%d%H', 'day': '%Y%m%d'}.get(seed_scope, '%Y%m%d')
        cond = f"o={getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rng = random.Random(f"want-hot-pick|{who}|{now.strftime(_fmt)}|{cond}")

        final_picks = []

        # 先抽「探索名額」（均勻、無放回）
        exp_candidates = explore_pool[:]
        while exp_candidates and len(final_picks) < explore_min_pick:
            idx = rng.randrange(len(exp_candidates))
            final_picks.append(exp_candidates.pop(idx))

        # 再抽「權重名額」（依 probs、無放回）
        # 從 pool 排除已挑的探索
        chosen = set(final_picks)
        wid2prob = {wid: p for wid, p in zip(pool, probs)}
        candidates = [wid for wid in pool if wid not in chosen]
        weights = [wid2prob.get(wid, 0.0) for wid in candidates]

        while candidates and len(final_picks) < need:
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

        # 萬一還不夠，就用「最近更新」或「熱門排序」補滿
        if len(final_picks) < need:
            already = set(final_picks)
            fallback = list(qs.exclude(id__in=already).order_by('-update', '-date').values_list('id', flat=True)[:(need - len(final_picks))])
            final_picks += fallback
            if len(final_picks) < need:
                # 再保底：直接用分數排序補
                rest = [wid for wid in prelim if wid not in already][: (need - len(final_picks))]
                final_picks += rest

    # ---------------- 保序 + 寫歷史 ----------------
    # tie-break：同分時用 update 排序（越新越前）
    update_map = dict(Want.objects.filter(id__in=final_picks).values_list('id', 'update'))
    final_picks = sorted(final_picks, key=lambda wid: (scores.get(wid, 0.0), update_map.get(wid)), reverse=True)

    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_picks)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=final_picks).order_by(preserved)

    # 主頁推薦模式才寫入推薦歷史，避免汙染首頁冷卻
    if is_homefeed:
        history = []
        now_ts = timezone.now()
        for w in qs_ordered:
            payload = {
                'want': w,
                'recommended_at': now_ts,
                'source': 'hot_rank',
                'algorithm_version': 'v3',
            }
            if keyword:
                payload['keyword'] = keyword

            if user and user.is_authenticated:
                payload['user'] = user
            else:
                if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                    request.session.save()
                sess_key = getattr(request.session, 'session_key', None)
                if not sess_key:
                    continue
                payload['session_key'] = sess_key

            history.append(WantRecommendationHistory(**payload))

        if history:
            WantRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered



