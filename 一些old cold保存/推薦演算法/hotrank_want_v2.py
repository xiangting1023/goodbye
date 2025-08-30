from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone

from goodBuy_want.models import Want, WantFootprints, WantBack, WantTag, WantRecommendationHistory
from goodBuy_want.recommend_config import HOT_WEIGHTS
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_wants(limit=None, days=7, owner=None, keyword=None, tag=None, request=None):
    user = getattr(request, 'user', None)
    now = timezone.now()
    recent = now - timedelta(days=days)

    # -------------------------
    # Step 1: 先過濾候選
    # -------------------------
    qs = Want.objects.filter(permission__id=1)

    # 黑名單 / 自己
    if user and user.is_authenticated:
        blocked_ids = get_blocked_user_ids(user)
        qs = qs.exclude(user_id__in=blocked_ids)
        if not owner:
            qs = qs.exclude(user=user)

    # owner 過濾
    if owner:
        qs = qs.filter(user=owner)

    # keyword / tag 過濾（單一）
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
    if not qs.exists():
        return qs.none()

    want_ids = list(qs.values_list('id', flat=True))

    # -------------------------
    # Step 2: 打分
    # -------------------------
    scores_raw = defaultdict(lambda: {'views': 0, 'replies': 0})

    # 近 N 天瀏覽
    views = (WantFootprints.objects
            .filter(date__gte=recent, want_id__in=want_ids)
            .values('want_id').annotate(vc=Count('id')))
    for v in views:
        scores_raw[v['want_id']]['views'] = v['vc']

    # 近 N 天回覆
    replies = (WantBack.objects
            .filter(date__gte=recent, want_id__in=want_ids)
            .values('want_id').annotate(rc=Count('id')))
    for r in replies:
        scores_raw[r['want_id']]['replies'] = r['rc']

    # 計分
    final_scores = {}
    for wid in want_ids:
        v = scores_raw[wid]['views']
        r = scores_raw[wid]['replies']
        final_scores[wid] = (
            HOT_WEIGHTS['recent_views'] * v +
            HOT_WEIGHTS['recent_replies'] * r
        )

    # -------------------------
    # Step 3: 排序 + 補滿 0 分到 limit
    # -------------------------
    ordered_ids = sorted(want_ids, key=lambda wid: final_scores.get(wid, 0), reverse=True)

    if limit:
        if len(ordered_ids) < limit:
            # 把沒在 ordered_ids 的候選（理論上不會有）補上
            fallback_ids = [wid for wid in want_ids if wid not in set(ordered_ids)]
            ordered_ids += fallback_ids
        ordered_ids = ordered_ids[:limit]
    
    if not qs.exists() and not (keyword or tag or owner):
        exclude_ids = set(qs.values_list('id', flat=True))
        qs = (Want.objects
            .filter(permission__id=1)
            .exclude(id__in=exclude_ids)
            .order_by('-date')[:limit or 20])


    # -------------------------
    # Step 4: 保序 QuerySet
    # -------------------------
    preserved = Case(
        *[When(id=pk, then=pos) for pos, pk in enumerate(ordered_ids)],
        output_field=IntegerField()
    )
    qs_ordered = Want.objects.filter(id__in=ordered_ids).order_by(preserved)

    # -------------------------
    # Step 5: 寫入推薦歷史
    # -------------------------
    if qs_ordered.exists():
        recommended_at = now
        history = []
        for want in qs_ordered:
            payload = {
                'want': want,
                'recommended_at': recommended_at,
                'source': 'hot_rank',
                'algorithm_version': 'v2',
            }
            if keyword:
                payload['keyword'] = keyword

            if user and user.is_authenticated:
                payload['user'] = user
            elif request:
                session_key = request.session.session_key
                if not session_key:
                    request.session.save()
                    session_key = request.session.session_key
                payload['session_key'] = session_key
            else:
                continue

            history.append(WantRecommendationHistory(**payload))

        WantRecommendationHistory.objects.bulk_create(history, ignore_conflicts=True)

    return qs_ordered