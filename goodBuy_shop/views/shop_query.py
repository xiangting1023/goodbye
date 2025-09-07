from django.db.models import *
from django.contrib import messages
from django.shortcuts import *
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponse, HttpResponseForbidden
from django.urls import reverse

from goodBuy_shop.models import *
from goodBuy_web.models import *
from goodBuy_order.models import IntentProduct
from goodBuy_tag.models import Tag

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

    products = list(Product.objects.select_related('shop').filter(shop=shop))

    if is_rush_buy and request.user.is_authenticated:
        # 搶購 + 已登入：顯示「自己還能搶多少」
        for product in products:
            user_claimed = (
                IntentProduct.objects
                .filter(product=product, intent__user=request.user, intent__shop=shop)
                .aggregate(total=Sum('quantity'))['total'] or 0
            )
            remaining_quantity = max(product.stock - user_claimed, 0)

            product.claimed_quantity = user_claimed
            product.remaining_quantity = product.effective_stock_for(request.user)
            product.is_out_of_stock = 1 if remaining_quantity <= 0 else 0
    else:
        # 非搶購 或 未登入：直接用庫存顯示
        for product in products:
            product.claimed_quantity = 0
            product.remaining_quantity = max(product.stock, 0)
            product.is_out_of_stock = 1 if product.remaining_quantity <= 0 else 0

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

        copied_text = request.session.pop('copied_shop_info', None) # 複製商店資訊
        shop_images = shop.images.all()
        return render(request, 'shop_detail.html', {'form': form, 
                                                    'shop': shop, 
                                                    'products': products, 
                                                    'announcements': announcements,
                                                    'shop_images': shop_images,
                                                    'tags': tags,
                                                    'copied_text': copied_text,})

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

    copied_text = request.session.pop('copied_shop_info', None) # 複製商店資訊
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

# -------------------------
# 商店複製 - 複製該商店資訊
# -------------------------
'''
複製格式：
該商店分配優先模式 #該商店狀態(現貨/非現貨) #該商店tag
商店/賣場名
商品名稱1 - 庫存數量 - 商品價格
商品介紹
該商店網址
'''
@login_required(login_url='login')
def copy_shop_info(request, shop_id):
    shop = get_object_or_404(
        Shop._base_manager.select_related('purchase_priority', 'shop_state', 'permission'),
        pk=shop_id
    )

    # 僅限擁有者
    if shop.owner_id != request.user.id:
        messages.error(request, "複製失敗，只有商店擁有者可以操作")
        return redirect('shop', shop_id=shop.id)

    try:
        # header
        priority_text = (shop.purchase_priority.name or '').strip()
        state_text = '現貨' if '現貨' in (shop.shop_state.name or '') else '非現貨'
        tag_names = Tag.objects.filter(shoptag__shop=shop).values_list('name', flat=True)
        tags_text = " ".join(f"#{t}" for t in tag_names) if tag_names else ""
        header_line = f"#{priority_text} #{state_text}"
        if tags_text:
            header_line = f"{header_line} {tags_text}"

        # 商品列表
        products = Product.objects.filter(shop=shop).order_by('id')
        product_lines = [
            f"{p.name} - 數量{max(int(p.stock or 0), 0)} - 價格{int(p.price)}"
            for p in products
        ]

        # 商店網址
        shop_url = request.build_absolute_uri(reverse('shop', kwargs={'shop_id': shop.id}))

        # 組合文字
        lines = [
            header_line,
            f"商店：{shop.name}",
            *product_lines,
            "",
            (shop.introduce or "").strip(),
            "",
            "快來GoodBuy逛逛吧！",
            shop_url,
        ]
        text = "\n".join(lines).strip() + "\n"

        # 存進 session，方便你在前端需要的地方再取出
        request.session['copied_shop_info'] = text

        messages.success(request, "商店資訊複製成功")
    except Exception as e:
        messages.error(request, f"複製失敗，請再試一次：{e}")

    # 無論成功或失敗，都回到商店詳情頁
    return redirect('shop', shop_id=shop.id)