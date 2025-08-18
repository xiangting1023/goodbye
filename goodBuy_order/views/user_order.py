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
from ..utils import *
from utils.decorators_shortcuts import *
from goodBuy_web.models.user_address import UserAddress

# 把 PaymentAccount.payment.name（中文/顯示名）對應到 Order.payment_category choices 的值
PAYMENT_NAME_TO_CHOICE = {
    '取貨付款': 'cash_on_delivery',
    '匯款': 'remittance',
}
# -------------------------
# 商品下單
# -------------------------
'''
@login_required(login_url='login')
def checkout(request):
    cart_ids = request.POST.getlist('cart_ids') if request.method == 'POST' else []
    product_id = request.GET.get('product_id')
    quantity = int(request.GET.get('quantity', 1))

    shop_groups = defaultdict(list)
    cart_items = []
    single_product = None

    # 單品快速下單（來源為 GET）
    if product_id:
        product = get_object_or_404(Product, id=product_id, is_delete=False)
        shop = product.shop
        shop_groups[shop].append({'product': product, 'quantity': quantity})
        single_product = product

    # 購物車下單（來源為 POST）
    elif cart_ids:
        cart_items = Cart.objects.select_related('product__shop').filter(id__in=cart_ids, user=request.user)
        if not cart_items:
            messages.error(request, '購物車資料無效')
            return redirect('cart')

        for item in cart_items:
            product = item.product
            shop_groups[product.shop].append({'product': product, 'quantity': item.amount})

    else:
        messages.error(request, '無有效商品')
        return redirect('cart')

    orders_created = []
    if request.method == 'POST' and 'checkout_submit' in request.POST:
        # 為每間 shop 處理一次下單流程
        for shop, items in shop_groups.items():
            if shop.is_end:
                messages.error(request, f'{shop.name} 商店已結束營業')
                continue

            form = OrderForm(request.POST, user=request.user, shop=shop)
            if not form.is_valid():
                messages.error(request, f'{shop.name} 的表單驗證失敗')
                continue

            address = form.cleaned_data['address']
            payment_method = form.cleaned_data['payment_method']
            payment_mode = form.cleaned_data.get('payment_mode')

            # 搶購流程
            if shop.purchase_priority_id != 1:
                shop = maybe_extend_rush(shop)
                intent, _ = PurchaseIntent.objects.get_or_create(user=request.user, shop=shop)

                for item in items:
                    product = item['product']
                    qty = item['quantity']
                    intent_product, created = IntentProduct.objects.get_or_create(intent=intent, product=product)

                    current_total = IntentProduct.objects.filter(product=product).exclude(id=intent_product.id).aggregate(
                        total=Sum('quantity')
                    )['total'] or 0
                    available_qty = max(product.stock - current_total, 0)

                    if created:
                        intent_product.quantity = min(qty, available_qty)
                    else:
                        intent_product.quantity = min(intent_product.quantity + qty, available_qty)

                    intent_product.save()

                    if qty > available_qty:
                        messages.warning(request, f'{product.name} 庫存不足，已調整為 {available_qty} 件')

                messages.success(request, f'{shop.name} 多帶商品已加入')
                continue

            # 一般建立訂單流程
            try:
                with transaction.atomic():
                    total = 0
                    locked_products = []

                    for item in items:
                        product = Product.objects.select_for_update().get(id=item['product'].id)
                        qty = item['quantity']
                        if product.stock < qty:
                            raise Exception(f'{product.name} 庫存不足')
                        product.stock = F('stock') - qty
                        product.save()
                        total += product.price * qty
                        locked_products.append((product, qty))

                    if payment_method == 'cash_on_delivery':
                        pay_state = 1
                        payment_mode = 'full'
                    else:
                        pay_state = 2 if payment_mode == 'deposit' else 8

                    order = Order.objects.create(
                        user=request.user,
                        shop=shop,
                        total=total,
                        address=address,
                        payment_category=payment_method,
                        payment_mode=payment_mode,
                        pay_state_id=PayState.objects.get(id=pay_state),
                        order_state_id=1,
                        second_supplement=0,
                        pay=None
                    )

                    for product, qty in locked_products:
                        ProductOrder.objects.create(order=order, product=product, amount=qty)

                    orders_created.append(order)
                    messages.success(request, f'{shop.name} 訂單已建立')
            except Exception as e:
                messages.error(request, f'{shop.name} 下單失敗：{e}')

        # 清除購物車項目
        if cart_items:
            cart_items.delete()

        if orders_created:
            return redirect('order_list')

    # 顯示頁面（GET）
    form_by_shop = {shop: OrderForm(user=request.user, shop=shop) for shop in shop_groups}

    return render(request, 'checkout.html', {
        'shop_groups': shop_groups,
        'form_by_shop': form_by_shop,
        'single_product': single_product,
    })
'''

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
            return redirect('cart')
        if product.shop.permission_id != 1:
            messages.error(request, f'{product.shop.name} 商店已下架')
            return redirect('cart')
        if product.shop.is_end:
            messages.error(request, f'{product.shop.name} 商店尚未開啟或已結束')
            return redirect('cart')
        
        shop_groups[product.shop].append({'product': product, 'quantity': quantity})

    elif cart_ids:
        cart_items = Cart.objects.select_related('product__shop').filter(id__in=cart_ids, user=request.user)
        if not cart_items:
            messages.error(request, '購物車資料無效')
            return redirect('cart')
        for item in cart_items:
            if item.product.stock < quantity:
                messages.error(request, f'{item.product.name} 庫存不足')
                return redirect('cart')
            if item.product.shop.permission_id != 1:
                messages.error(request, f'{item.product.shop.name} 商店已下架')
            if item.product.shop.is_active:
                messages.error(request, f'{item.product.shop.name} 商店尚未開啟或已結束')
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
                return redirect('cart')

        except Exception as e:
            print(e)
            messages.error(request, f'建立訂單失敗：{e}')
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
        return redirect('order_list')

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
            # 預設：店家沒設定任何付款 → 取貨付款
            payment_category = 'cash_on_delivery'
            payment_mode = request.POST.get(f'payment_mode_{o.id}', 'full')  # 'full' / 'split'

            if payments:
                pa_id = request.POST.get(f'payment_account_{o.id}')
                if pa_id:
                    try:
                        payment_account = PaymentAccount.objects.select_related('payment').get(id=pa_id)
                        payment_name = payment_account.payment.name  # e.g. '取貨付款'、'匯款'
                        payment_category = PAYMENT_NAME_TO_CHOICE.get(payment_name, 'cash_on_delivery')
                    except PaymentAccount.DoesNotExist:
                        payment_category = 'cash_on_delivery'

            # 取貨付款 → 強制一次付清
            if payment_category == 'cash_on_delivery':
                pay_state_id = 1
                payment_mode = 'full'
            else:
                # 匯款：'split' 視為「訂金+尾款」→ 2，'full' → 8
                pay_state_id = 2 if payment_mode == 'split' else 8

            # 寫入訂單
            o.address = addr
            o.payment_category = payment_category      # 必須是 choices 的值
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
@login_required(login_url='login')
@order_buyer_required
def choose_payment_method(order, request=None):
    if order.order_state_id != 1:
        messages.error(request, '訂單狀態錯誤，無法選擇付款方式')
        return redirect('buyer_order_detail', order_id=order.id)
    
    shop = order.shop
    shop_payment_links = ShopPayment.objects.filter(shop=shop).select_related('payment_account')

    available_payment_methods = []
    remittance_accounts = []

    if shop.transfer:
        remittance_accounts = shop_payment_links.exclude(payment_account__id=1)
        if remittance_accounts.exists():
            available_payment_methods.append('remittance')

        if shop_payment_links.filter(payment_account__id=1).exists():
            available_payment_methods.append('cash_on_delivery')
    else:
        available_payment_methods.append('cash_on_delivery')

    if not available_payment_methods:
        messages.error(request, '此商店未設定任何可用付款方式')
        return redirect('buyer_order_detail', order_id=order.id)

    if request.method == 'POST':
        selected_method = request.POST.get('payment_method')

        if selected_method not in available_payment_methods:
            messages.error(request, '付款方式無效')
            return redirect('order_payment_choice', order_id=order.id)

        order.payment_category = selected_method

        if selected_method == 'remittance':
            try:
                selected_account_id = int(request.POST.get('payment_account_id'))
            except (TypeError, ValueError, ShopPayment.DoesNotExist):
                messages.error(request, '請選擇有效的匯款帳戶')
                return redirect('order_payment_choice', order_id=order.id)

        order.order_state_id = 2
        order.save()

        messages.success(request, '付款方式已選擇')
        return redirect('buyer_order_detail', order_id=order.id)

    return render(request, 'payment_choice.html', {'available_payment_methods': available_payment_methods,
                                                'remittance_accounts': remittance_accounts,})

# -------------------------
# 買家上傳付款憑證
# -------------------------
@login_required(login_url='login')
@order_buyer_required
def upload_payment_proof(request, order):
    if order.payment_category != 'remittance':
        messages.error(request, '此訂單不需匯款，無法上傳憑證')
        return redirect('buyer_order_detail', order_id=order.id)

    if order.has_pending_payment_proof:
        messages.error(request, '您已上傳付款憑證，請等待賣家確認或退回後再試')
        return redirect('buyer_order_detail', order_id=order.id)

    remit_accounts = ShopPayment.objects.filter(shop=order.shop).exclude(payment_account__id=1)

    if request.method == 'POST':
        form = OrderPaymentForm(request.POST, request.FILES)
        account_id = request.POST.get('payment_account_id')

        if not account_id:
            messages.error(request, '請選擇匯款帳戶')
            return redirect('buyer_order_detail', order_id=order.id)

        try:
            shop_payment = remit_accounts.get(id=account_id)
        except ShopPayment.DoesNotExist:
            messages.error(request, '匯款帳戶無效')
            return redirect('buyer_order_detail', order_id=order.id)

        if form.is_valid():
            payment_record = form.save(commit=False)
            payment_record.order = order
            payment_record.shop_payment = shop_payment
            payment_record.is_paid_by_user = True
            payment_record.seller_state = 'wait_confirmed'
            payment_record.save()

            messages.success(request, '匯款資訊已上傳，等待賣家確認')
            return redirect('buyer_order_detail', order_id=order.id)
        else:
            messages.error(request, '表單內容有誤，請重新確認')
    else:
        form = OrderPaymentForm()

    return render(request, 'upload_payment.html', {'remit_accounts':remit_accounts,
                                                    'form': form,
                                                    'order': order})
