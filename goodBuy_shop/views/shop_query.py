from django.db.models import *
from django.contrib import messages
from django.shortcuts import *
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from goodBuy_shop.models import *
from goodBuy_web.models import *
from goodBuy_order.models import IntentProduct

from goodBuy_shop.weighting import *
from goodBuy_shop.hot_rank import get_hot_shops

from utils import *
from ..shop_utils import *
from ..time_utils import *
from ..shop_forms import *

# -------------------------
# 點擊的商店是否為推薦，做推送記錄
# -------------------------
def record_shop_click(request, shop):
    filters = Q(shop=shop)
    if request.user.is_authenticated:
        filters &= Q(user=request.user)
    else:
        if not request.session.session_key:
            request.session.save()
        filters &= Q(session_key=request.session.session_key)
    ShopRecommendationHistory.objects.filter(filters).update(clicked=True)

# -------------------------
# 商店查詢 - user-id
# -------------------------
@user_exists_required
def shopByUserId_many(request, user):
    # 本人 ➜ 顯示全部商店（不排序）
    if request.user.is_authenticated and request.user == user:
        shops = shopInformation_many()
        return render(request, '自己主頁賣場', locals())

    # 非本人+有登入 ➜ 只顯示公開商店 + 推薦排序
    if request.user.is_authenticated:
        recommended = get_hot_shops(user=request.user, owner=user, request=request, limit=10)
    else:
        hot_shops = get_hot_shops(owner=user, request=request, limit=10)
        recommended = [s for s in hot_shops if s.owner_id == user.id]

    shops = shopInformation_many(recommended)
    return render(request, '別人主頁賣場', locals())

# -------------------------
# 商店查詢 - shop-id - 單一店鋪界面
# -------------------------
# @shop_exists_and_not_blacklisted()
@shop_exists_required  # 負責查出 shop 並加進 kwargs
@blacklist_check(lambda shop: shop.owner, msg='你已被此賣家封鎖', context_name='shop')  # 拿 kwargs['shop'] 來做封鎖檢查
def shopById_one(request, shop):
    #TAG
    tags = Tag.objects.filter(shoptag__shop=shop) 
    #===
    # 記錄點擊是否為推薦，做推送記錄
    record_shop_click(request, shop)

    is_rush_buy = shop.purchase_priority_id in [2, 3]

    products = list(Product.objects.filter(shop=shop))
    
    if is_rush_buy and request.user.is_authenticated:
        for product in products:
            user_claimed = IntentProduct.objects.filter(
                product=product,
                intent__user=request.user,
                intent__shop=shop
            ).aggregate(total=Sum('quantity'))['total'] or 0

            remaining_quantity = max(product.stock - user_claimed, 0)
            product.remaining_quantity = remaining_quantity
            product.claimed_quantity = user_claimed
            product.is_out_of_stock = 1 if remaining_quantity <= 0 else 0

    else:
        for product in products:
            product.is_out_of_stock = 1 if product.stock <= 0 else 0

    products.sort(key=lambda p: (p.is_out_of_stock, p.id))
    announcements = ShopAnnouncement.objects.filter(shop=shop).order_by('-update')

    # 判斷是否已收藏 ->前端 收藏按鈕切換
    if request.user.is_authenticated:
        shop.is_collected = ShopCollect.objects.filter(shop=shop, user=request.user).exists()
    else:
        shop.is_collected = False
    
    # shop擁有者
    if request.user.is_authenticated and request.user.id == shop.owner.id:
        form = AnnouncementForm(request.POST or None)

        if request.method == 'POST' and form.is_valid():
            announcement = form.save(commit=False)
            announcement.shop = shop
            announcement.update = timezone.now()
            announcement.save()
            messages.success(request, '公告發布成功')
            return redirect('shop', shop_id=shop.id)
    
        shop_images = shop.images.all()
        return render(request, 'shop_detail.html', {'form': form, 
                                                    'shop': shop, 
                                                    'products': products, 
                                                    'announcements': announcements,
                                                    'shop_images': shop_images,
                                                    'tags': tags})

    if shop.permission.id != 1:
        messages.error(request, '當前賣場不公開')
        return redirect('home')

    if request.user.is_authenticated:
        ShopFootprints.objects.update_or_create(
            user=request.user,
            shop=shop,
            defaults={'date': timezone.now()}
        )
    else:
        if not request.session.session_key:
            request.session.save()
        session_key = request.session.session_key
        ShopFootprints.objects.update_or_create(
            session_key=session_key,
            shop=shop,
            defaults={'date': timezone.now()}
        )

    announcements = ShopAnnouncement.objects.filter(shop=shop).order_by('-update')
    shop_images = shop.images.all()
    return render(request, 'shop_detail.html', locals())

# -------------------------
# 商店查詢 - search
# -------------------------
@user_exists_required
def shopBySearch(request, user=None):
    kw = request.GET.get('keyWord')
    sort = request.GET.get('sort', 'new')

    if not kw:
        messages.warning(request, "請輸入關鍵字")
        return redirect('home')

    if request.user.is_authenticated:
        SearchHistory.objects.update_or_create(
            user=request.user,
            keyword=kw,
            searched_at=timezone.now()
        )

    # 準備查詢集
    base_queryset = Shop.objects.filter(permission__id=1)
    if user:
        base_queryset = base_queryset.filter(owner=user)

    if request.user.is_authenticated:
        shops = personalized_shop_recommendation(
            request=request,
            keywords=[kw],
            exclude_seen=False,
            limit=20
        )
    else:
        shops = get_hot_shops(request, limit=20, keyword=kw)
        if user:
            shops = [s for s in shops if s.owner_id == user.id]

    # 排序
    if sort == 'old':
        shops = sorted(shops, key=lambda s: s.update)
    else:
        shops = sorted(shops, key=lambda s: s.update, reverse=True)

    shops = shopInformation_many(shops)
    return render(request, '搜尋結果界面', locals())

# -------------------------
# 商店查詢 - tag
# -------------------------
@tag_exists_required
def shopByTag(request, tag):
    if request.user.is_authenticated:
        shops = personalized_shop_recommendation(
            user=request.user,
            tags=[tag.name],
            exclude_seen=False,
            limit=100
        )
    else:
        shops = get_hot_shops(limit=100, tag=tag)
    shops = shopInformation_many(shops)
    return render(request, '搜尋結果界面', locals())

# -------------------------
# 商店查詢 - 隱私狀況（ex.查詢自己私人的商店
# -------------------------
@login_required
def shopByPermissionId(request, permission_id):
    if permission_id not in [1, 2]:
        messages.error(request, "僅支援公開/私人可見的商店查詢")
        return redirect('home')

    shops = shopInformation_many(
        Shop.objects.filter(owner=request.user, permission__id=permission_id)
    ).order_by('-date')

    return render(request, '查詢完成頁面', locals())
