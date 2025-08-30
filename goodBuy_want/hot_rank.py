# goodBuy_want/hot_rank.py
from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone
import math, random   # 加入抽樣與抖動

from goodBuy_want.models import (
    Want, WantFootprints, WantBack, WantRecommendationHistory
)
from goodBuy_want.recommend_config import HOT_WEIGHTS
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_wants(
    limit=None,
    days=7,
    owner=None,
    keyword=None,
    tag=None,
    request=None,
    *,
    cooldown_days=0,          # 冷卻期：最近 n 天推過的先「硬排除」
    explore_ratio=0.12,       # 探索比例：權重抽樣時，讓長尾也有機會
    jitter=0.02,              # 輕微隨機抖動，打破同分與極接近分數
    seed_scope="hour"         # 抖動/抽樣的種子變化範圍："hour" 或 "day"
):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)

    # ---------------- filter ----------------
    qs = Want.objects.filter(permission__id=1)

    # 黑名單 & 自己
    if user and user.is_authenticated:
        blocked_ids = set(get_blocked_user_ids(user))
        qs = qs.exclude(user_id__in=blocked_ids).exclude(user=user)

    # owner / keyword / tag
    if owner:
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

    # 首頁流判斷（無 owner/keyword/tag）
    is_homefeed = not (owner or keyword or tag)
    base_qs = qs

    # 首頁流的冷卻期硬排除（參照 shop 版）
    if is_homefeed and cooldown_days and cooldown_days > 0:
        if user and user.is_authenticated:
            recent_reco_ids = set(
                WantRecommendationHistory.objects.filter(
                    user=user,
                    recommended_at__gte=now - timedelta(days=cooldown_days)
                ).values_list('want_id', flat=True)
            )
        else:
            # 遊客以 session_key 記錄
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            sess_key = getattr(request.session, 'session_key', None)
            recent_reco_ids = set()
            if sess_key:
                recent_reco_ids = set(
                    WantRecommendationHistory.objects.filter(
                        session_key=sess_key,
                        recommended_at__gte=now - timedelta(days=cooldown_days)
                    ).values_list('want_id', flat=True)
                )

        if recent_reco_ids:
            # 完整排除
            remain_qs = qs.exclude(id__in=recent_reco_ids)

            if not remain_qs.exists():
                # 縮短視窗（12 小時）
                short_ids = set(
                    WantRecommendationHistory.objects.filter(
                        user=user if (user and user.is_authenticated) else None,
                        session_key=None if (user and user.is_authenticated) else getattr(request.session, 'session_key', None),
                        recommended_at__gte=now - timedelta(hours=12)
                    ).values_list('want_id', flat=True)
                )
                remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

            if not remain_qs.exists():
                # 只排除最近推過的前 30%（保留 70% 供探索）
                recent_list = list(recent_reco_ids)
                # 注意：recent_list 未排序，簡化處理保留一部分即可
                keep = set(recent_list[int(len(recent_list) * 0.3):])
                remain_qs = qs.exclude(id__in=keep)

            if not remain_qs.exists():
                # 仍 0 → 放棄冷卻，回退
                remain_qs = base_qs

            qs = remain_qs

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

    if 'new_want_bonus' in HOT_WEIGHTS and HOT_WEIGHTS.get('new_want_bonus', 0) != 0:
        recent_want_ids = set(
            Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for wid in recent_want_ids:
            scores[wid] += HOT_WEIGHTS['new_want_bonus'] * 1

    # ---------- 輕微抖動（與使用者/時間有關，避免每次完全一樣） ----------
    if jitter and jitter > 0:
        if user and user.is_authenticated:
            who = f"user-{user.id}"
        else:
            if request and not getattr(getattr(request, 'session', None), 'session_key', None):
                request.session.save()
            who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
        time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
        cond = f"o={getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
        rnd = random.Random(f"want-hot-jitter|{who}|{time_key}|{cond}")
        for wid in scores:
            scores[wid] += rnd.uniform(-jitter, jitter)

    # ---------------- 排序 + 多樣性 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0.0), reverse=True)

    author_by_want = dict(Want.objects.filter(id__in=prelim).values_list('id', 'user_id'))
    K_PER_AUTHOR = 5
    picked, author_count = [], defaultdict(int)
    for wid in prelim:
        aid = author_by_want.get(wid)
        if author_count[aid] < K_PER_AUTHOR:
            picked.append(wid)
            author_count[aid] += 1
        if limit and len(picked) >= limit:
            break

    # ---------------- 權重抽樣（softmax + epsilon-greedy） ----------------
    def softmax(vals, T=0.7):
        if not vals:
            return []
        vmax = max(vals)
        exps = [math.exp((v - vmax) / T) for v in vals]
        s = sum(exps) or 1.0
        return [x / s for x in exps]

    pool = picked[:] if picked else prelim[:]
    if not pool:
        # 最終保底：抓最近更新/建立的公開 want
        fallback = Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]
        return fallback

    pool = pool[: (limit or 20) * 10]  # 避免過大
    pool_scores = [scores[wid] for wid in pool]
    probs = softmax(pool_scores, T=0.7)

    if explore_ratio and 0 < explore_ratio < 1:
        uniform = 1.0 / len(pool)
        probs = [(1 - explore_ratio) * p + explore_ratio * uniform for p in probs]

    if user and user.is_authenticated:
        who = f"user-{user.id}"
    else:
        if request and not getattr(getattr(request, 'session', None), 'session_key', None):
            request.session.save()
        who = f"sess-{getattr(request.session, 'session_key', 'anon')}"
    time_key = now.strftime('%Y%m%d%H') if seed_scope == "hour" else now.strftime('%Y%m%d')
    cond = f"o={getattr(owner, 'id', owner)}|k={bool(keyword)}|t={getattr(tag, 'id', tag)}"
    rng = random.Random(f"want-hot-pick|{who}|{time_key}|{cond}")

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
        prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0.0), reverse=True)[: (limit or 20)]
        if not prelim:
            return Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]
        preserved = Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(prelim)],
            output_field=IntegerField()
        )
        return Want.objects.filter(id__in=prelim).order_by(preserved)

    # ---------------- 保序 + 寫歷史 ----------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(final_picks)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=final_picks).order_by(preserved)

    # 寫入推薦歷史（含使用者或 session）
    history = []
    now_ts = timezone.now()
    for w in qs_ordered:
        payload = {
            'want': w,
            'recommended_at': now_ts,
            'source': 'hot_rank',
            'algorithm_version': 'v3',  # 與 shop 版對齊
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
