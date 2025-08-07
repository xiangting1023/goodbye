# goodBuy_want/hot_rank.py

from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Q, Case, When, IntegerField
from django.utils import timezone

from goodBuy_want.models import Want, WantFootprints, WantBack, WantTag, WantRecommendationHistory
from goodBuy_want.recommend_config import HOT_WEIGHTS
from goodBuy_web.utils import get_blocked_user_ids


def get_hot_wants(limit=None, days=7, owner=None, keyword=None, tag=None, request=None):
    user = request.user if request else None
    now = timezone.now()
    recent = now - timedelta(days=days)
    scores_raw = defaultdict(lambda: {'views': 0, 'replies': 0})

    # 最近瀏覽
    views = WantFootprints.objects.filter(date__gte=recent)
    if owner:
        views = views.filter(want__user=owner)
    views = views.values('want_id').annotate(vc=Count('id'))
    for v in views:
        scores_raw[v['want_id']]['views'] += v['vc']

    # 最近回覆
    replies = WantBack.objects.filter(date__gte=recent)
    if owner:
        replies = replies.filter(want__user=owner)
    replies = replies.values('want_id').annotate(rc=Count('id'))
    for r in replies:
        scores_raw[r['want_id']]['replies'] += r['rc']

    # 計算最終分數
    final_scores = {}
    for wid, v in scores_raw.items():
        score = (
            v['views'] * HOT_WEIGHTS['recent_views'] +
            v['replies'] * HOT_WEIGHTS['recent_replies']
        )
        final_scores[wid] = score
    print(final_scores)
    sorted_ids = sorted(final_scores, key=final_scores.get, reverse=True)
    wants = Want.objects.filter(id__in=sorted_ids, permission__id=1)

    # 排除黑名單與自己（只有非 owner 模式下）
    if owner:
        wants = wants.filter(user=owner)
        wants = sorted(wants, key=lambda w: -final_scores.get(w.id, 0))
    else:
        if user and user.is_authenticated:
            blocked_ids = get_blocked_user_ids(user)
            wants = wants.exclude(user=user)
            wants = wants.exclude(user__id__in=blocked_ids)
        wants = sorted(wants, key=lambda w: -final_scores.get(w.id, 0))

    # 過濾關鍵字與標籤
    if keyword:
        wants = [w for w in wants if keyword.lower() in w.title.lower() or keyword in w.post_text]
    if tag:
        tag_want_ids = set(WantTag.objects.filter(tag=tag).values_list('want_id', flat=True))
        wants = [w for w in wants if w.id in tag_want_ids]

    # 回傳排序後的 QuerySet（保留順序）
    if isinstance(wants, list):
        shop_ids = [s.id for s in wants]
        preserved = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(shop_ids)], output_field=IntegerField())
        wants_qs = Want.objects.filter(id__in=shop_ids).order_by(preserved)
    else:
        # QuerySet 保留順序排序
        preserved = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(sorted_ids)], output_field=IntegerField())
        wants_qs = wants.order_by(preserved)

    if limit:
        wants_qs = wants_qs[:limit]

    # 推薦歷史寫入
    if wants_qs:
        recommended_at = timezone.now()
        history_objs = []
        for want in wants:
            obj_kwargs = {
                'want_id': want.id,
                'source': 'hot_rank',
                'recommended_at': recommended_at,
            }
            if user and user.is_authenticated:
                obj_kwargs['user'] = user
            elif request:
                session_key = request.session.session_key
                if not session_key:
                    request.session.save()
                    session_key = request.session.session_key
                obj_kwargs['session_key'] = session_key
            else:
                continue

            history_objs.append(WantRecommendationHistory(**obj_kwargs))

        WantRecommendationHistory.objects.bulk_create(history_objs, ignore_conflicts=True)

    return wants_qs
