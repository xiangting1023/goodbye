from django.utils import timezone
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from itertools import chain
from operator import attrgetter

from ..models import Tag, TagCollect
from goodBuy_shop.shop_utils import shopInformation_many
from goodBuy_want.want_utils import wantInformation_many
from goodBuy_shop.weighting import *
from goodBuy_want.weighting import *

from utils import *  


# -------------------------
# 前端 JS：即時搜尋標籤 API
# -------------------------
def tag_search_api(request):
    q = (request.GET.get('q') or '').strip()
    tags = Tag.objects.filter(name__icontains=q).values('name')[:10]
    return JsonResponse(list(tags), safe=False)

# -------------------------
# 標籤搜尋商店+收物帖
# -------------------------
@tag_exists_required
def tagById_one(request, tag):
    if request.user.is_authenticated:
        shops = personalized_shop_recommendation(request=request, tag=tag, limit=50)
        wants = personalized_want_recommendation(request=request, tag=tag, limit=50)
        tag.is_following = TagCollect.objects.filter(user=request.user, tag=tag).exists()

    else:
        shops = get_hot_shops(request=request, limit=50, tag=tag)
        wants = get_hot_wants(request=request, limit=50, tag=tag)
        tag.is_following = False

    shops = shopInformation_many(shops)
    wants = wantInformation_many(wants)

    for shop in shops:
        shop.post_type = 'shop'

    for want in wants:
        want.post_type = 'want'

    items = sorted(
        chain(shops, wants), 
        key=attrgetter('update'), 
        reverse=True
    )

    return render(request, 'tag_detail.html', {
        "tag": tag,
        "items": items,
    })