from django.shortcuts import render, get_object_or_404, redirect
from goodBuy_web.models import User
from goodBuy_shop.models import Shop, ShopImg
from goodBuy_shop.weighting import personalized_shop_recommendation
from goodBuy_shop.hot_rank import get_hot_shops
from goodBuy_want.models import Want, WantImg
from goodBuy_want.weighting import personalized_want_recommendation
from goodBuy_want.hot_rank import get_hot_wants
from django.db.models import Case, When, IntegerField, F
from django.utils import timezone
from goodBuy_web.models import Blacklist
from utils.decorators_shortcuts import user_exists_required
from django.utils import timezone

@user_exists_required
def view_profile(request, user):
    profile_user = user
    is_blocked = False
    block_reason = None

    # === 黑名單判斷 ===
    if request.user != profile_user and request.user.is_authenticated:
        you_blocked = Blacklist.objects.filter(user=request.user, black_user=profile_user).exists()
        blocked_by = Blacklist.objects.filter(user=profile_user, black_user=request.user).exists()

        if you_blocked and blocked_by:
            block_reason = "您已封鎖對方"
            is_blocked = True
        elif you_blocked:
            block_reason = "您已經封鎖對方"
            is_blocked = True
        elif blocked_by:
            block_reason = "對方已封鎖您，無法查看主頁"
        else:
            block_reason = None

    if request.user.is_authenticated:
        if profile_user == request.user:
            now = timezone.now()
            user_shops = (
                            Shop.objects
                            .filter(owner=profile_user)
                            .annotate(
                                is_active=Case(
                                    When(permission_id=1, start_time__lte=now, end_time__gte=now, then=1),
                                    default=0, output_field=IntegerField()
                                ),
                            )
                            .order_by(
                                'permission_id',                 # 公開在前
                                F('is_active').desc(),           # 進行中在前
                                '-update',                       # 最近更新在前
                                '-id',                           # 打破同分，確保穩定順序
                            )
                        )
            user_wants = Want.objects.filter(user=profile_user).order_by('permission_id', '-update')
        else:
            user_shops = personalized_shop_recommendation(request=request, owner=profile_user)
            user_wants = personalized_want_recommendation(request=request, owner=profile_user)
    else:
        user_shops = get_hot_shops(request=request, owner=profile_user)
        user_wants = get_hot_wants(request=request, owner=profile_user)

    # ========================
    # 判斷截止日期
    # ========================
    now = timezone.now()   
    for shop in user_shops:
        # 截止日期判斷 
        if getattr(shop, 'end_time', None):
            shop.is_ended = shop.end_time <= now
        else:
            shop.is_ended = False

    # 幫每個 shop 補 cover_img、價格等欄位
    for shop in user_shops:
        shop.cover_img = ShopImg.objects.filter(shop=shop, is_cover=True).first()
        products = shop.product_set.all()
        if products.exists():
            prices = [p.price for p in products]
            shop.price_min = min(prices)
            shop.price_max = max(prices)
        else:
            shop.price_min = shop.price_max = 0
        shop.status = shop.shop_state.name if hasattr(shop, 'shop_state') else ''

    # 幫每個 want 補 cover_img 和狀態
    for want in user_wants:
        want.cover_img = WantImg.objects.filter(want=want, is_cover=True).first()
        want.status = want.permission.name if hasattr(want, 'permission') else ''

    # ---------- 信譽度 & 基本統計 ----------
    average_rank = profile_user.average_rank if profile_user.average_rank else '無評價'
    fans_count = getattr(profile_user, "fans_count", 0)
    shop_count = user_shops.count()
    buy_count = getattr(profile_user, "buy_count", 0)

    return render(request, 'common/profile.html', {
        'profile_user': profile_user,
        'user_shops': user_shops,
        'user_wants': user_wants,
        'average_rank': average_rank,
        'fans_count': fans_count,
        'shop_count': shop_count,
        'buy_count': buy_count,
        'is_blocked': is_blocked,
        'block_reason': block_reason,
    })

def user_more(request, user_id, tab):
    profile_user = get_object_or_404(User, id=user_id)
    if tab == 'shops':
        if request.user.is_authenticated and request.user == profile_user:
            items = Shop.objects.filter(owner=profile_user).order_by('-update')
        elif request.user.is_authenticated:
            items = personalized_shop_recommendation(request=request, owner=profile_user, limit=10)
        else:
            items = get_hot_shops(request=request, owner=profile_user, limit=10)
        
        for shop in items:
            shop.cover_img = ShopImg.objects.filter(shop=shop, is_cover=True).first()
            products = shop.product_set.all()
            if products.exists():
                prices = [p.price for p in products]
                shop.price_min = min(prices)
                shop.price_max = max(prices)
            else:
                shop.price_min = shop.price_max = 0
            shop.status = shop.shop_state.name if hasattr(shop, 'shop_state') else ''
        is_shop = True
    elif tab == 'wants':
        if request.user.is_authenticated and request.user == profile_user:
            items = Want.objects.filter(owner=profile_user).order_by('-date')
        elif request.user.is_authenticated:
            items = personalized_want_recommendation(user=request.user, owner=profile_user, request=request, limit=10)
        else:
            items = get_hot_wants(owner=profile_user, request=request, limit=10)

        for want in items:
            want.cover_img = WantImg.objects.filter(want=want, is_cover=True).first()
            want.status = want.permission.name if hasattr(want, 'permission') else ''
        is_shop = False
    else:
        # 參數錯誤，回首頁或 404
        return redirect('home')

    return render(request, 'common/user_more.html', {
        'profile_user': profile_user,
        'tab': tab,      # 給 template 用於 if 判斷
        'items': items,  # 賣場或收物列表
        'is_shop': is_shop,
    })
