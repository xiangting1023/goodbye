from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Sum
from collections import defaultdict

from goodBuy_shop.models import *
from goodBuy_web.models import *
from .rush_view import maybe_extend_rush
from ..models import *
from ..forms import *
from utils.decorators_shortcuts import *
from goodBuy_web.models.user_address import UserAddress

# 把 PaymentAccount.payment.name（中文/顯示名）對應到 Order.payment_category choices 的值
PAYMENT_NAME_TO_CHOICE = { '取貨付款': 'cash_on_delivery', '匯款': 'remittance',}
COD_NAMES = {'取貨付款', '貨到付款', 'COD'}

# -------------------------
# 商品下單
# -------------------------
@login_required(login_url='login')
def checkout_step1(request):
    cart_ids = request.POST.getlist('cart_ids') if request.method == 'POST' else []
    
    product_id = request.GET.get('product_id')
    quantity = int(request.GET.get('quantity', 1))

    shop_groups = defaultdict(list)
    cart_items = []

    # 解析購買資料
    if product_id:
        product = get_object_or_404(Product, id=product_id, is_delete=False)
        if product.stock < quantity:
            messages.error(request, f'{product.name} 庫存不足')
            print(f'{product.name} 庫存不足')
            return redirect('cart')
        if product.shop.permission_id != 1:
            messages.error(request, f'{product.shop.name} 商店已下架')
            print(f'{product.shop.name} 商店已下架')
            return redirect('cart')
        if not product.shop.can_order:
            messages.error(request, f'{product.shop.name} 商店尚未開啟或已結束')
            print(f'{product.shop.name} 商店尚未開啟或已結束')
            return redirect('cart')
        
        shop_groups[product.shop].append({'product': product, 'quantity': quantity})

    elif cart_ids:
        cart_items = Cart.objects.select_related('product__shop').filter(id__in=cart_ids, user=request.user)
        if not cart_items:
            messages.error(request, '購物車資料無效')
            return redirect('cart')
        for item in cart_items:
            if item.product.stock < item.quantity:
                messages.error(request, f'{item.product.name} 庫存不足')
                print(f'{item.product.name} 庫存不足')
                return redirect('cart')
            if item.product.shop.permission_id != 1:
                messages.error(request, f'{item.product.shop.name} 商店已下架')
                print(f'{item.product.shop.name} 商店已下架')
            if not item.product.shop.can_order:
                messages.error(request, f'{item.product.shop.name} 商店尚未開啟或已結束')
                print(f'{item.product.shop.name} 商店尚未開啟或已結束')
                return redirect('cart')
            
            shop_groups[item.product.shop].append({'product': item.product, 'quantity': item.quantity})

    else:
        messages.error(request, '無有效商品')
        return redirect('cart')

        # 如果是第二次送出（確認下單）
    if request.method == 'POST' and 'confirm_checkout' in request.POST:
        created_order_ids = []
        print(shop_groups)
        try:
            with transaction.atomic():
                for shop, items in shop_groups.items():
                    if shop.purchase_priority_id != 1:
                        # 多帶商店（搶購）
                        shop = maybe_extend_rush(shop)

                        # 建立/取得本次多帶（行為本身不扣庫存）
                        intent, _ = PurchaseIntent.objects.get_or_create(
                            user=request.user,
                            shop=shop,
                        )
                        print(intent)

                        affected_product_ids = []

                        for item in items:
                            # 重新查商品 + 加鎖，避免併發問題；不要用 is_delete 擠掉資料
                            try:
                                product = (Product.objects
                                        .select_for_update()
                                        .select_related('shop')
                                        .get(pk=item['product'].id))
                            except Product.DoesNotExist:
                                raise ValueError(f'商品不存在或已被刪除：{item["product"].name}')

                            # 商品必須屬於迭代中的商店
                            if product.shop_id != shop.id:
                                raise ValueError(f'{product.name} 不屬於商店 {shop.name}')

                            # 數量檢查
                            qty = int(item.get('quantity') or 0)
                            if qty <= 0:
                                raise ValueError(f'{product.name} 數量需大於 0')

                            # 取得/建立 IntentProduct
                            # 關鍵：defaults 先給 quantity=0，避免 NOT NULL 錯誤
                            ip, created = IntentProduct.objects.get_or_create(
                                intent=intent,
                                product=product,
                                defaults={'quantity': 0}
                            )
                            # 再加鎖拿到最新行（避免 create 路徑沒鎖到）
                            ip = IntentProduct.objects.select_for_update().get(pk=ip.pk)

                            # 計算目前自己已多帶數量
                            current_total = (
                                    IntentProduct.objects
                                    .filter(product=product, intent__user=request.user)
                                    .aggregate(total=Sum('quantity'))['total'] or 0
                                )

                            # 可分配數量 = 現庫存 - 其他人已意向的數量（不扣庫存）
                            available_qty = max(product.stock - current_total, 0)

                            # 目標數量 = 既有意向 + 本次新增，封頂於可分配數量
                            new_qty = min(ip.quantity + qty, available_qty)

                            if new_qty != ip.quantity:
                                ip.quantity = new_qty
                                ip.save(update_fields=['quantity'])

                            if qty > available_qty:
                                print(f'{product.name} 庫存不足，已調整為 {available_qty} 件')
                                messages.warning(request, f'{product.name} 庫存不足，已調整為 {available_qty} 件')

                            affected_product_ids.append(product.id)

                        # 刪除購物車中「已加入搶購」的商品項目（不影響其他商店/商品）
                        if cart_items:
                            cart_items.filter(product_id__in=affected_product_ids).delete()


                        print(f'{shop.name} 搶購意向已更新，包含商品：{", ".join([item["product"].name for item in items])}')
                        messages.success(request, f'{shop.name} 多帶已加入，請等待分配結果')
                        continue

                    # 一般訂單（會扣庫存）
                    total = sum(item['product'].price * item['quantity'] for item in items)

                    order = Order.objects.create(
                        user=request.user,
                        shop=shop,
                        total=total,
                        order_state_id=1,
                        pay_state_id=10,
                        second_supplement=0,
                        pay=None
                    )

                    for item in items:
                        ProductOrder.objects.create(order=order, product=item['product'], quantity=item['quantity'])

                        # 扣庫存（加鎖 + update）
                        rows = Product.objects.filter(
                            id=item['product'].id, is_delete=False,
                            stock__gte=item['quantity']
                        ).update(stock=F('stock') - item['quantity'])
                        if rows == 0:
                            raise ValueError(f'{item["product"].name} 庫存不足')

                    created_order_ids.append(order.id)

                if cart_items:
                    cart_items.delete()

                if created_order_ids:
                    request.session['pending_order_ids'] = created_order_ids
                    return redirect('checkout_address_payment')

                # 走到這裡代表這次都是「多帶」
                return render(request, 'checkout/MoreComp.html', {'shop': shop})

        except Exception as e:
            print(e)
            messages.error(request, f'建立訂單失敗：{e}')
            return redirect('cart')

    # 確認商店類型
    has_normal = any(shop.purchase_priority_id == 1 for shop in shop_groups.keys())
    has_rush   = any(shop.purchase_priority_id != 1 for shop in shop_groups.keys())
    if has_normal and has_rush:
        messages.error(request, '一般商店與多帶商店不可同時結帳，請分開勾選送出')
        return redirect('cart')
    
    # 先計算價格
    totals_by_shop = {}

    for shop, items in shop_groups.items():
        total = sum(item['product'].price * item['quantity'] for item in items)
        totals_by_shop[shop.id] = total
    
    is_rush_mode = all(shop.purchase_priority_id != 1 for shop in shop_groups.keys())
    
    # 否則第一次進來，就顯示「商品確認畫面」
    return render(request, 'checkout/step1.html', {
        'shop_groups': dict(shop_groups),  # 要轉 dict 才能 .items
        'cart_items': cart_items,
        'totals_by_shop': totals_by_shop,  # 商店小計金額
        'cart_ids': [item.id for item in cart_items],  # 傳給下一步
        'is_rush_mode': is_rush_mode,
    })


@login_required(login_url='login')
def checkout_step2(request):
    print(request.POST)
    order_ids = request.session.get('pending_order_ids')
    if not order_ids:
        messages.error(request, '找不到待處理的訂單')
        return redirect('checkout')

    orders = (
        Order.objects
        .filter(id__in=order_ids, user=request.user, pay_state_id=10)  # 10: 你原本的「待設定」狀態
        .select_related('shop')
    )
    if not orders:
        messages.error(request, '訂單已處理或不存在')
        return redirect('buyer')

    # 小計
    order_totals = {
        o.id: sum(po.product.price * po.quantity for po in o.productorder_set.select_related('product'))
        for o in orders
    }

    # 每張訂單允許的付款帳戶 (ShopPayment -> PaymentAccount)
    allowed_payments = {}
    allow_deposit_by_order = {}
    for o in orders:
        q = (ShopPayment.objects
            .filter(shop=o.shop)
            .select_related('payment_account', 'payment_account__payment'))
        allowed_payments[o.id] = list(q)
        allow_deposit_by_order[o.id] = bool(getattr(o.shop, 'allow_deposit', False))

    user_address = UserAddress.active.filter(user=request.user).first()
    addresses = UserAddress.objects.filter(user=request.user)
    city_list = [c[0] for c in UserAddress.ADDRESS_MODE_CHOICES]

    if request.method == 'POST':
        # 收件資料
        receiver_name = request.POST.get('receiver_name', '').strip()
        receiver_phone = request.POST.get('receiver_phone', '').strip()
        receiver_city = request.POST.get('city', '').strip()
        detail_address = request.POST.get('detail_address', '').strip()

        if not all([receiver_name, receiver_phone, receiver_city, detail_address]):
            messages.error(request, '請完整填寫寄送資訊')
            return redirect('checkout_address_payment')

        # 依唯一約束建立/重用地址 (user, phone, city, address)
        addr, created = UserAddress.objects.get_or_create(
            user=request.user,
            phone=receiver_phone,
            city=receiver_city,
            address=detail_address,
            defaults={'name': receiver_name}
        )

        if not created and addr.name != receiver_name:
            addr.name = receiver_name
            addr.save(update_fields=['name'])

        # 逐張訂單設定付款與地址
        for o in orders:
            payments = allowed_payments.get(o.id, [])

            payment_account = None
            payment_category = 'cash_on_delivery'   # 預設 COD
            payment_mode = request.POST.get(f'payment_mode_{o.id}', 'full')  # 'full' / 'split'

            sp_id = request.POST.get(f'payment_account_{o.id}')
            print(sp_id)
            if sp_id:
                sp = (ShopPayment.objects
                        .select_related('payment_account__payment')
                        .filter(payment_account__id=sp_id, shop=o.shop)
                        .first())
                if sp and sp.payment_account:
                    pname = (getattr(sp.payment_account.payment, 'name', '') or '').strip()
                    print(pname)
                    if pname in COD_NAMES:
                        payment_category = 'cash_on_delivery'
                    else:
                        payment_category = 'remittance'
                else:
                    payment_category = 'cash_on_delivery'

            # 取貨付款 → 強制一次付清
            if payment_category == 'cash_on_delivery':
                pay_state_id = 1
                payment_mode = 'full'
            else:
                allow_deposit = bool(getattr(o.shop, 'allow_deposit', False))
                if not allow_deposit:
                    payment_mode = 'full'
                pay_state_id = 2 if payment_mode == 'split' else 8

            # 寫入訂單
            o.address = addr
            o.payment_category = payment_category      # 'cash_on_delivery' or 'remittance'
            o.payment_mode = payment_mode              # 'full' / 'split'
            o.pay_state_id = pay_state_id
            o.order_state_id = 2
            o.save()

        messages.success(request, f'{o.shop.name} 訂單付款資訊已設定完成')

        request.session.pop('pending_order_ids', None)

        # 完成頁：全是多帶店 → MoreComp，否則一般
        if all(o.shop.purchase_priority_id != 1 for o in orders):
            return render(request, 'checkout/MoreComp.html')
        else:
            return render(request, 'checkout/complete.html')

    return render(request, 'checkout/step2.html', {
        'orders': orders,
        'order_totals': order_totals,
        'allowed_payments': allowed_payments,
        'allow_deposit_by_order': allow_deposit_by_order,
        'addresses': addresses,
        'user_address': user_address,
        'city_list': city_list,
    })

# -------------------------
# 買家選擇付款方式
# -------------------------
PAY_STATE_AWAITING_METHOD = 10
ORDER_STATE_INIT = 1

@login_required(login_url='login')
@order_exists_required 
def choose_payment_method(request, order):
    # 擁有者檢查
    if order.user != request.user:
        messages.error(request, '沒有權限操作此訂單')
        return redirect('order_list')

    # 狀態校正：確保進到選付款頁可被後續 view 撈到
    changed = False
    if getattr(order, 'order_state_id', None) != ORDER_STATE_INIT:
        order.order_state_id = ORDER_STATE_INIT
        changed = True
    if getattr(order, 'pay_state_id', None) != PAY_STATE_AWAITING_METHOD:
        order.pay_state_id = PAY_STATE_AWAITING_METHOD
        changed = True
    if changed:
        order.save(update_fields=['order_state_id', 'pay_state_id'])

    # 寫入 session（存「整數 ID」陣列）
    request.session['pending_order_ids'] = [int(order.id)]
    # （理論上不需要，但保險起見）
    request.session.modified = True

    # 轉去結帳頁
    return redirect('checkout_address_payment')

