from django.db.models import *
from django.contrib import messages
from django.shortcuts import *
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from ..models import *
from goodBuy_web.models import *
from utils import *
from ..shop_utils import *

# -------------------------
# 收藏商店
# -------------------------
@shop_exists_required
@blacklist_check(lambda shop: shop.owner, msg='你已被此賣家封鎖，無法查看', context_name='shop')
def shop_collect_toggle(request, shop):
    if shop.owner == request.user:
        messages.warning(request, '不可以收藏自己的商店喔')
    else:
        obj = ShopCollect.objects.filter(user=request.user, shop=shop).first()
        if obj:
            obj.delete()
            messages.info(request, '已取消收藏')
        else:
            ShopCollect.objects.create(user=request.user, shop=shop, date=timezone.now())
            messages.success(request, '收藏成功')

    return redirect('shop', shop_id=shop.id)

# -------------------------
# 查看收藏的商店
# -------------------------
@login_required(login_url='login')
def my_shops_collected(request):
    shop_ids = ShopCollect.objects.filter(user=request.user).values_list('shop_id', flat=True)
    shops = shopInformation_many(Shop.objects.filter(id__in=shop_ids).order_by('-update'))

    # ========================
    # 判斷截止日期
    # ========================
    now = timezone.now()
    for shop in shops:
        # 只對賣場卡片判斷
        if getattr(shop, 'end_time', None):
            # 若 end_time 有值且已過期
            shop.is_ended = shop.end_time <= now
        else:
            # 沒有設定截止日（永久商店）→ 不算結束
            shop.is_ended = False


    return render(request, 'shop_collects.html', locals())
# -------------------------
# 商店足跡
# -------------------------
@login_required(login_url='login')
def my_shop_footprints(request):
    shop_ids = ShopFootprints.objects.filter(user=request.user).values_list('shop_id', flat=True)
    shops = shopInformation_many(Shop.objects.filter(id__in=shop_ids).order_by('-update'))
    return render(request, 'shop_footprints.html', locals())