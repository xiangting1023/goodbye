# from django.utils import timezone
# from django.shortcuts import render
# from django.http import JsonResponse
# from django.db.models import *

# from ..models import *
# from goodBuy_shop.models import Shop, ShopTag
# from goodBuy_web.models import SearchHistory

# from utils import *
# from goodBuy_shop.views.shop_query import shopInformation_many

# # -------------------------
# # 前端js，使用者輸入文字實時查詢相似標籤
# # -------------------------
# def tag_search_api(request):
#     q = request.GET.get('q', '')
#     tags = Tag.objects.filter(name__icontains=q).values('name')[:10]
#     return JsonResponse(list(tags), safe=False)
# # -------------------------
# # 單標籤查詢
# # -------------------------
# @tag_exists_required
# def tagById_one(request, tag):
#     shop_ids = ShopTag.objects.filter(tag=tag).values_list('shop_id', flat=True)
#     shops = shopInformation_many(Shop.objects.filter((Q(id__in=shop_ids) & Q(permission__id=1))))
#     return render(request, 'tag.html', locals())
# # -------------------------
# # 標籤search
# # -------------------------
# def tagBySearch(request):
#     kw = request.GET.get('keyWord')
#     if not kw:
#         messages.warning(request, "請輸入關鍵字")
#         return redirect('home')
    
#     SearchHistory.objects.update_or_create(
#         user=request.user if request.user.is_authenticated else None,
#         keyword=kw,
#         searched_at=timezone.now()
#     )

#     tags = Tag.objects.filter(tag__name__icontains=kw)
#     return render(request, 'tag_search.html', locals())

