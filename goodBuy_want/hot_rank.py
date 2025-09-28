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
    cooldown_days=0,    # 測資少先壓低冷卻期避免無法刷新
    explore_ratio=0.12,
    jitter=0.02,
    seed_scope="hour"
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
        qs = qs.filter(
            Q(permission__id=1) & Q(update__gte=now - timedelta(days=NEW_DAYS))
        )

    if not qs.exists():
        return qs.none()

    # 首頁流判斷（無 owner/keyword/tag）
    is_homefeed = not (owner or keyword or tag)
    base_qs = qs

    # 首頁冷卻期（owner_mode 下 is_homefeed 為 False，不觸發）
    if is_homefeed and cooldown_days and cooldown_days > 0:
        if user and user.is_authenticated:
            recent_reco_ids = set(
                WantRecommendationHistory.objects.filter(
                    user=user,
                    recommended_at__gte=now - timedelta(days=cooldown_days)
                ).values_list('want_id', flat=True)
            )
        else:
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
            remain_qs = qs.exclude(id__in=recent_reco_ids)
            if not remain_qs.exists():
                short_ids = set(
                    WantRecommendationHistory.objects.filter(
                        user=user if (user and user.is_authenticated) else None,
                        session_key=None if (user and user.is_authenticated) else getattr(request.session, 'session_key', None),
                        recommended_at__gte=now - timedelta(hours=12)
                    ).values_list('want_id', flat=True)
                )
                remain_qs = qs.exclude(id__in=short_ids) if short_ids else qs

            if not remain_qs.exists():
                recent_list = list(recent_reco_ids)
                keep = set(recent_list[int(len(recent_list) * 0.3):])
                remain_qs = qs.exclude(id__in=keep)

            if not remain_qs.exists():
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

    if HOT_WEIGHTS.get('new_want_bonus', 0):
        recent_want_ids = set(
            Want.objects.filter(id__in=candidate_ids, update__gte=now - timedelta(days=NEW_DAYS))
            .values_list('id', flat=True)
        )
        for wid in recent_want_ids:
            scores[wid] += HOT_WEIGHTS['new_want_bonus']

    # 抖動
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

    # ---------------- 排序 + 多樣性/抽樣 ----------------
    prelim = sorted(candidate_ids, key=lambda wid: scores.get(wid, 0.0), reverse=True)

    if owner_mode:
        # ★ 有 owner：不做 K_PER_AUTHOR、抽樣與 limit，確保「全部」返回
        final_picks = prelim
    else:
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

        # 權重抽樣（softmax + epsilon-greedy）
        def softmax(vals, T=0.7):
            if not vals:
                return []
            vmax = max(vals)
            exps = [math.exp((v - vmax) / T) for v in vals]
            s = sum(exps) or 1.0
            return [x / s for x in exps]

        pool = picked[:] if picked else prelim[:]
        if not pool:
            return Want.objects.filter(permission__id=1).order_by('-update', '-date')[: (limit or 20)]

        pool = pool[: (limit or 20) * 10]
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
