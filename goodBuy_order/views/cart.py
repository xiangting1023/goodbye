from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Sum,Prefetch
from collections import defaultdict
from django.utils import timezone
from django.urls import reverse
from goodBuy_shop.models import *
from goodBuy_web.models import *
from .rush_view import maybe_extend_rush
from ..models import *
from ..forms import *
from ..utils import *
from .update_order_stste import restore_order_stock
# -------------------------
# 購物車查看
# -------------------------
@login_required(login_url='login')
def view_cart(request):
    # 抓取使用者購物車
    cart_items = (
        Cart.objects
        .filter(user=request.user)
        .select_related('product__shop')
    )
    cart_data = []
    shop_latest_update = {}

    for item in cart_items:
        product = item.product
        shop = product.shop

        is_rush_buy = shop.purchase_priority_id in [2, 3]
        claimed_quantity = 0
        remaining_quantity = product.stock

        # 搶購商店且已登入 → 顯示已搶與剩餘可搶數量
        if is_rush_buy and request.user.is_authenticated:
            claimed_quantity = (
                IntentProduct.objects
                .filter(product=product, intent__user=request.user, intent__shop=shop)
                .aggregate(total=Sum('quantity'))['total'] or 0
            )
            remaining_quantity = max(product.stock - claimed_quantity, 0)

        is_out_of_stock = remaining_quantity <= 0

        shop_id = shop.id
        if shop_id not in shop_latest_update or item.update > shop_latest_update[shop_id]:
            shop_latest_update[shop_id] = item.update

        cart_data.append({
            'shop': shop,
            'product': product,
            'cart': item,
            'is_out_of_stock': is_out_of_stock,  # 是否超出庫存
            'is_shop_closed': shop.can_reply,       # 商店是否關閉
            'claimed_quantity': claimed_quantity,   # 已搶數量
            'remaining_quantity': remaining_quantity, # 剩餘可搶數量（form max 可用這個）
        })

    grouped_data = defaultdict(list)
    for entry in cart_data:
        grouped_data[entry['shop'].id].append(entry)

    sorted_shop_ids = sorted(
        grouped_data.keys(),
        key=lambda sid: shop_latest_update[sid],
        reverse=True
    )

    grouped_cart = []
    for shop_id in sorted_shop_ids:
        items = grouped_data[shop_id]
        items.sort(key=lambda x: (x['is_out_of_stock'], x['product'].id))
        grouped_cart.append({
            'shop': items[0]['shop'],
            'items': items
        })

    return render(request, 'cart.html', {'grouped_cart': grouped_cart})

# -------------------------
# 加入購物車
# -------------------------
@login_required(login_url='login')
@product_exists_and_not_own_shop_required
def add_to_cart(request, product):
    if not product.shop.can_reply:
        messages.error(request, "該商店已截止")
        print(f'商店 {product.shop.name} 不在開放期間，無法加入購物車')
        return redirect('shop', shop_id=product.shop.id)

    try:
        quantity = int(request.POST.get('quantity', 1))
        if quantity < 1:
            messages.error(request, "數量必須大於 0")
            return redirect('shop', shop_id=product.shop.id)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('shop', shop_id=product.shop.id)

    cart = Cart(user=request.user)

    try:
        cart.add_or_update_product(product, quantity)
        print(f'加入購物車: {product.name}, 數量: {quantity}')
        messages.success(request, f'成功將 {product.name} 加入購物車')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('shop', shop_id=product.shop.id)

# -------------------------
# 移除購物車
# -------------------------
@login_required(login_url='login')
@cart_exists_required
def delete_cart_item(request, cart_item):
    cart_item.delete()
    messages.success(request, f'{cart_item.product.name} 已從購物車移除')
    return redirect('cart')

@login_required(login_url='login')
def delete_multiple_cart_items(request):
    if request.method == 'POST':
        cart_ids = request.POST.getlist('cart_ids')  # 前端傳來勾選的 cart_id list
        Cart.objects.filter(id__in=cart_ids, user=request.user).delete()
        messages.success(request, '已成功移除選取的商品')
    return redirect('cart')
# -------------------------
# 修改數量
# -------------------------
@login_required(login_url='login')
@cart_exists_required
def update_cart_quantity(request, cart_item):
    if cart_item.product.shop.is_end:
        messages.error(request, "該商店已截止，無法修改商品數量")
        return redirect('cart')
    
    try:
        new_qty = int(request.POST.get('quantity', 1))
    except ValueError:
        messages.error(request, "輸入的數量無效")
        return redirect('cart')

    if new_qty <= 0:
        messages.error(request, "數量必須大於 0")
        return redirect('cart')

    other_cart_qty = (
    Cart.objects.filter(product=cart_item.product)
        .exclude(id=cart_item.id)
        .aggregate(total=Sum('quantity'))['total'] or 0
    )
    available_stock = cart_item.product.stock - other_cart_qty

    if new_qty > available_stock:
        messages.warning(request, f'{cart_item.product.name} 最多只能購買 {available_stock} 件')
        cart_item.quantity = available_stock
    else:
        cart_item.quantity = new_qty

    cart_item.update = timezone.now()
    cart_item.save()
    messages.success(request, f'{cart_item.product.name} 數量已更新為 {cart_item.quantity}')
    referer = request.META.get('HTTP_REFERER', '/')
    return redirect(referer)

# -------------------------
# 返回結帳步驟 1
# -------------------------
@login_required(login_url='login')
def checkout_back_to_step1(request):
    order_ids = request.session.get('pending_order_ids')
    if not order_ids:
        messages.info(request, '沒有可還原的訂單')
        return redirect('checkout')

    orders = Order.objects.filter(id__in=order_ids, user=request.user, pay_state_id=10, order_state_id=1)

    # 把商品加回購物車、還原庫存、刪除訂單
    for o in orders:
        for po in ProductOrder.objects.filter(order=o).select_related('product'):
            if po.product:
                # 放回購物車
                Cart.objects.create(user=request.user, product=po.product, quantity=po.quantity)
        restore_order_stock(o)
        o.delete()

    # 清掉 session
    request.session.pop('pending_order_ids', None)
    messages.success(request, '已返回上一步，商品與庫存已還原')
    return redirect('checkout')