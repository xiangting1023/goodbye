from django.shortcuts import render , redirect

from goodBuy_shop.shop_utils import *
from goodBuy_shop.weighting import *
from goodBuy_shop.hot_rank import *

from goodBuy_want.want_utils import *
from goodBuy_want.weighting import *
from goodBuy_want.hot_rank import *

from goodBuy_tag.models import *

from itertools import chain
from operator import attrgetter
from django.db.models import Q

def homePage(request):
    # 搜尋關鍵字
    q_raw = request.GET.get('q')
    post_type = request.GET.get('type')  # sell / want 
    tag = request.GET.get('tag')         # 標籤名稱 
    
    # 搜尋字串
    q = q_raw.strip() if q_raw else ''

    # 若使用者有送出 q，但內容為空白就回首頁
    if q_raw is not None and q == '':
        return redirect('home')

    #如果搜尋有東西 就開始搜尋商店/收物帖/tag
    if q:
        # 查詢符合關鍵字的 Shop
        shops = Shop.objects.filter(
            Q(name__icontains=q) | Q(introduce__icontains=q) |
            Q(product__name__icontains=q) |
            Q(shoptag__tag__name__icontains=q),
            permission__id=1
        ).distinct()
        for shop in shops:
            shop.post_type = 'shop'

        # 查詢符合關鍵字的 Want
        wants = Want.objects.filter(
            Q(title__icontains=q) | Q(post_text__icontains=q) |
            Q(wanttag__tag__name__icontains=q),
            permission__id=1
        ).distinct()
        for want in wants:
            want.post_type = 'want'

        items = list(chain(shops, wants))
        items.sort(key=lambda x: x.update, reverse=True)

        return render(request, 'home.html',{
            'items': items,
            'q': q,
            'post_type': post_type,
        })

    #篩選
    if request.user.is_authenticated:
        shops = get_hot_shops(user=request.user, request=request, limit=10)
        wants = get_hot_wants(user=request.user, request=request, limit=10)

    else:
        # 未登入使用者直接看熱門
        shops = get_hot_shops(limit=10)
        wants = get_hot_wants(limit=10)
    
    # 篩選條件：只顯示特定 type（sell / want）
    if post_type == 'sell':
        wants = Want.objects.none()
    elif post_type == 'want':
        shops = Shop.objects.none()

    # 整理資訊
    shops = shopInformation_many(shops)
    wants = wantInformation_many(wants)

    for s in shops:
        s.post_type = 'shop'

    for w in wants:
        w.post_type = 'want'

    # 商店混和排序
    items = sorted(
        chain(shops, wants), 
        key=attrgetter('update'), 
        reverse=True
    )

    return render(request, 'home.html', locals())
