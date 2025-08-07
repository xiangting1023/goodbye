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
        shop_groups[product.shop].append({'product': product, 'quantity': quantity})

    elif cart_ids:
        cart_items = Cart.objects.select_related('product__shop').filter(id__in=cart_ids, user=request.user)
        if not cart_items:
            messages.error(request, '購物車資料無效')
            return redirect('cart')
        for item in cart_items:
            shop_groups[item.product.shop].append({'product': item.product, 'quantity': item.quantity})

    else:
        messages.error(request, '無有效商品')
        return redirect('cart')

    # created_order_ids = []

    # try:
    #     with transaction.atomic():
    #         for shop, items in shop_groups.items():
    #             if shop.purchase_priority_id != 1:
    #                 # 多帶商店 → 加入 Intent 記錄
    #                 shop = maybe_extend_rush(shop)
    #                 intent, _ = PurchaseIntent.objects.get_or_create(user=request.user, shop=shop)

    #                 for item in items:
    #                     product = item['product']
    #                     qty = item['quantity']
    #                     intent_product, created = IntentProduct.objects.get_or_create(intent=intent, product=product)

    #                     current_total = IntentProduct.objects.filter(product=product).exclude(id=intent_product.id).aggregate(
    #                         total=Sum('quantity')
    #                     )['total'] or 0
    #                     available_qty = max(product.stock - current_total, 0)

    #                     if created:
    #                         intent_product.quantity = min(qty, available_qty)
    #                     else:
    #                         intent_product.quantity = min(intent_product.quantity + qty, available_qty)

    #                     intent_product.save()

    #                     if qty > available_qty:
    #                         messages.warning(request, f'{product.name} 庫存不足，已調整為 {available_qty} 件')

    #                 messages.success(request, f'{shop.name} 多帶已加入，請等待分配結果')
    #                 continue

    #             # 一般商店 → 建立訂單
    #             total = sum(item['product'].price * item['quantity'] for item in items)

    #             order = Order.objects.create(
    #                 user=request.user,
    #                 shop=shop,
    #                 total=total,
    #                 order_state_id=1,
    #                 pay_state_id=10,
    #                 second_supplement=0,
    #                 pay=None
    #             )

    #             for item in items:
    #                 ProductOrder.objects.create(order=order, product=item['product'], quantity=item['quantity'])

    #             created_order_ids.append(order.id)
    #             messages.success(request, f'{shop.name} 訂單已建立，請選擇付款與地址')

    #         if cart_items:
    #             cart_items.delete()

    #         # 有建立 order → 進入 Step2
    #         if created_order_ids:
    #             request.session['pending_order_ids'] = created_order_ids
    #             return redirect('checkout_address_payment')

    #         # 全部是多帶 → 結束流程，不進入 Step2
    #         return redirect('order_list')

    # except Exception as e:
    #     messages.error(request, f'建立訂單失敗：{e}')
    #     return redirect('cart')
        # 如果是第二次送出（確認下單）
    if request.method == 'POST' and 'confirm_checkout' in request.POST:
        created_order_ids = []
        try:
            with transaction.atomic():
                for shop, items in shop_groups.items():
                    if shop.purchase_priority_id != 1:
                        # 多帶商店
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

                        messages.success(request, f'{shop.name} 多帶已加入，請等待分配結果')
                        continue

                    # 建立一般訂單
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

                    created_order_ids.append(order.id)
                    messages.success(request, f'{shop.name} 訂單已建立，請選擇付款與地址')

                if cart_items:
                    cart_items.delete()

                if created_order_ids:
                    request.session['pending_order_ids'] = created_order_ids
                    return redirect('checkout_address_payment')

                return redirect('order_list')

        except Exception as e:
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

    orders = Order.objects.filter(id__in=order_ids, user=request.user, pay_state_id=10)
    if not orders:
        messages.error(request, '訂單已處理或不存在')
        return redirect('order_list')

    form_by_order = {order.shop.id: OrderForm(user=request.user, shop=order.shop) for order in orders}
    addresses = UserAddress.objects.filter(user=request.user)
    user_address = UserAddress.active.filter(user=request.user).first()
    city_list = [c[0] for c in UserAddress.ADDRESS_MODE_CHOICES]

    #計算每張訂單的總價
    order_totals = {}
    for order in orders:
        total = 0
        for item in order.productorder_set.select_related('product').all():
            total += item.product.price * item.quantity
        order_totals[order.id] = total

    if request.method == 'POST':
        # address_id = request.POST.get('address_id')
        # address = get_object_or_404(UserAddress, id=address_id, user=request.user)

        # 使用者自由填的欄位
        receiver_name = request.POST.get('receiver_name')
        receiver_phone = request.POST.get('receiver_phone')
        receiver_city = request.POST.get('city')
        detail_address = request.POST.get('detail_address')

        if not all([receiver_name, receiver_phone, receiver_city, detail_address]):
            messages.error(request, '請完整填寫寄送資訊')
            return redirect('checkout_address_payment')

        address_text = f'{receiver_city} {detail_address}（收件人：{receiver_name}，電話：{receiver_phone}）'

        for order in orders:
            form = OrderForm(request.POST, user=request.user, shop=order.shop)
            if not form.is_valid():
                messages.error(request, f'{order.shop.name} 的付款方式未選擇或錯誤')
                continue

        for order in orders:
            form = OrderForm(request.POST, user=request.user, shop=order.shop)
            if not form.is_valid():
                messages.error(request, f'{order.shop.name} 的付款方式未選擇或錯誤')
                continue

            payment_method = form.cleaned_data['payment_method']
            payment_mode = form.cleaned_data.get('payment_mode')

            if payment_method == 'cash_on_delivery':
                pay_state_id = 1 # 取貨付款
                payment_mode = 'full'
            else:
                pay_state_id = 2 if payment_mode == 'deposit' else 8

            order.address = address_text
            # order.address = address
            order.payment_category = payment_method
            order.payment_mode = payment_mode
            order.pay_state_id = pay_state_id
            order.save()

            messages.success(request, f'{order.shop.name} 訂單付款資訊已設定完成')

        del request.session['pending_order_ids']
        # return redirect('order_list')
        
        # 如果全部訂單都來自多帶商店（搶購制）
        if all(order.shop.purchase_priority_id != 1 for order in orders):
            return render(request, 'checkout/MoreComp.html')  # 多帶完成頁面
        else:
            return render(request, 'checkout/complete.html')  # 一般完成頁面

    return render(request, 'checkout/step2.html', {
        'orders': orders,
        'form_by_order': form_by_order,
        'addresses': addresses,
        'order_totals': order_totals,
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
