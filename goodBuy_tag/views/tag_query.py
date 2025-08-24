from django.utils import timezone
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages

from ..models import Tag
from goodBuy_shop.models import Shop, ShopTag
from goodBuy_web.models import SearchHistory
from goodBuy_shop.views.shop_query import shopInformation_many
# 如果你的 decorator 在 utils 裡，建議精準匯入（避免 *）
# from utils import tag_exists_required
from utils import *  # 若你現階段只能用這個也可先保留


# -------------------------
# 前端 JS：即時搜尋標籤 API
# -------------------------
def tag_search_api(request):
    q = (request.GET.get('q') or '').strip()
    tags = Tag.objects.filter(name__icontains=q).values('name')[:10]
    return JsonResponse(list(tags), safe=False)


# -------------------------
# 單一標籤頁（依 ID）
# -------------------------
@tag_exists_required
def tagById_one(request, tag):
    shop_ids = ShopTag.objects.filter(tag=tag).values_list('shop_id', flat=True)
    shops_qs = Shop.objects.filter(Q(id__in=shop_ids) & Q(permission__id=1)).distinct()
    shops = shopInformation_many(shops_qs)
    return render(request, 'tag.html', {"shops": shops, "tag": tag})


# -------------------------
# 標籤搜尋（關鍵字）
# -------------------------
def tagBySearch(request):
    # 取關鍵字（相容 kw / keyWord）
    kw = (request.GET.get('kw') or request.GET.get('keyWord') or '').strip()

    # 記錄搜尋歷史（僅登入者；先 update 沒有再 create，避免 MultipleObjectsReturned）
    if kw and request.user.is_authenticated:
        qs = SearchHistory.objects.filter(user=request.user, keyword=kw)
        if qs.exists():
            qs.update(searched_at=timezone.now())
        else:
            SearchHistory.objects.create(
                user=request.user,
                keyword=kw,
                searched_at=timezone.now()
            )

    # 先把符合的標籤列出來（頁面上會顯示 #標籤）
    tags = Tag.objects.filter(name__icontains=kw) if kw else Tag.objects.none()

    # 找出「有這些標籤名稱」的商店（只顯示 permission.id = 1）
    if kw:
        shops_qs = (Shop.objects
                    .filter(shoptag__tag__name__icontains=kw, permission__id=1)
                    .distinct())
        shops = shopInformation_many(shops_qs) if shops_qs.exists() else []
    else:
        shops = []

    # 回傳頁面
    return render(request, 'tag_search.html', {
        'kw': kw,
        'tags': tags,
        'shops': shops,
    })
