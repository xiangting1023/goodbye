from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from goodBuy_order.models import Order, OrderPayment
from django.shortcuts import redirect, render

from ..forms import OrderPaymentForm
from .payment import *
from .user_order import *
from utils import order_buyer_required, order_seller_required
from ..constants import *
# -------------------------
# 庫存退回
# -------------------------
def restore_order_stock(order):
    for item in order.productorder_set.select_related('product'):
        if item.product:
            item.product.stock += item.quantity
            item.product.save()
# -------------------------
# 訂單狀態修改 - ex. 付款、出貨
# -------------------------
# 買家訂單狀態修改
"""
    前端呼叫方式（POST）：
    URL:  /orders/<order_id>/buyer_action/
    Body:
    - action=chosen_payment     # 當 order_state_id == 1，導到選擇付款方式頁
    - action=cancel_order       # 當 order_state_id in [1,2]，取消訂單並還原庫存
    - action=need_pay           # 當 order_state_id == 3，導到上傳匯款憑證頁
    - action=confirm_received   # 當 order_state_id == 5，確認收貨（COD 會自動建立付款紀錄）

    成功：redirect('buyer_order_list')
    失敗：messages.error 並 redirect('buyer_order_list')
"""
# -------------------------
@require_POST
@order_buyer_required(redirect_to='buyer_order_list')
def buyer_action(request, order):
    action = request.POST.get('action')

    # 付款方式選擇
    if order.order_state_id == ORDER_CHOOSE_PAYMENT and action == 'chosen_payment':
        return redirect('choose_payment_method', order_id=order.id)

    # 取消訂單（買家）
    elif order.order_state_id in (ORDER_CHOOSE_PAYMENT, ORDER_WAIT_SELLER) and action == 'cancel_order':
        order.order_state_id = ORDER_CANCELLED
        order.pay_state_id   = PAY_CANCELLED
        restore_order_stock(order)
        messages.warning(request, '訂單已取消')

    # 上傳匯款憑證（銀行路徑）
    elif order.order_state_id == ORDER_WAIT_PAY and action == 'need_pay':
        return redirect('upload_payment_proof', order_id=order.id)

    # 確認收貨
    elif order.order_state_id == ORDER_SHIPPED and action == 'confirm_received':
        if order.payment_category == 'cash_on_delivery':
            if not order.payments.exists():
                OrderPayment.objects.create(
                    order=order,
                    amount=order.total + (order.second_supplement or 0),
                    is_paid_by_user=True,
                    seller_state='none',
                    remark='取貨付款自動記錄',
                )
        else:
            order.pay_state_id = PAY_ALL_PAID  # 7

        order.order_state_id = ORDER_RECEIVED  # 6
        messages.success(request, '已確認收貨')

    else:
        messages.error(request, '操作無效或狀態錯誤')
        return redirect('buyer')

    order.save()
    return redirect('buyer')

# -------------------------
# 賣家訂單狀態修改
"""
    賣家對訂單的操作（POST）
    前端參數：
    action =
        - confirm_order      # 當 order_state_id == 2 ：賣家確認
        - notify_payment     # 當 order_state_id == 3 ：通知買家付款（銀行）
        - reject_stock       # 當 order_state_id == 2 ：庫存不足 → 拒單
        - reject_user        # 當 order_state_id == 2 ：拒絕此用戶 → 拒單
        - reject_unsuccessful# 當 order_state_id == 2 ：流團 → 拒單
        - shipped            # 當 order_state_id == 4 ：出貨

    導向：
    成功 → POST 中的 next / HTTP_REFERER / home
    失敗 → seller_order_detail(order_id)
"""
# -------------------------
@require_POST
@order_seller_required(redirect_to='seller')
def seller_action(request, order):
    action = request.POST.get('action')

    # 2 → 賣家確認
    if order.order_state_id == ORDER_WAIT_SELLER and action == 'confirm_order':
        if order.payment_category == 'cash_on_delivery':
            order.order_state_id = ORDER_WAIT_SHIP   # COD：直接待出貨
        else:
            order.order_state_id = ORDER_WAIT_PAY    # 銀行：進入待付款/通知流程
        messages.success(request, '訂單已確認')

    # 3 → 通知買家付款（銀行）
    elif order.order_state_id == ORDER_WAIT_PAY and action == 'notify_payment':
        if not notify_buyer_to_pay(order, request):
            return redirect('seller_order_detail')

    # 2 → 拒單（庫存不足）
    elif order.order_state_id == ORDER_WAIT_SELLER and action == 'reject_stock':
        with transaction.atomic():
            order.order_state_id = ORDER_REJECT_STOCK
            order.pay_state_id   = PAY_CANCELLED
            restore_order_stock(order)
        messages.warning(request, '商品庫存不足，已拒絕交易')

    # 2 → 拒單（拒絕用戶）
    elif order.order_state_id == ORDER_WAIT_SELLER and action == 'reject_user':
        with transaction.atomic():
            order.order_state_id = ORDER_REJECT_RATING
            order.pay_state_id   = PAY_CANCELLED
            restore_order_stock(order)
        messages.warning(request, '已拒絕此用戶交易')

    # 2 → 拒單（未成團）
    elif order.order_state_id == ORDER_WAIT_SELLER and action == 'reject_unsuccessful':
        with transaction.atomic():
            order.order_state_id = ORDER_REJECT_FAILED
            order.pay_state_id   = PAY_CANCELLED
            restore_order_stock(order)
        messages.warning(request, '已告知用戶流團')

    # 4 → 出貨
    elif order.order_state_id == ORDER_WAIT_SHIP and action == 'shipped':
        # 非 COD 必須完成付款（定尾=7、一次付清=9）
        if order.payment_category != 'cash_on_delivery' and order.pay_state_id not in (PAY_ALL_PAID, PAY_FULL_PAID):
            print('尚未完成付款，無法出貨')
            messages.error(request, '尚未完成付款，無法出貨')
            return redirect('seller')
        order.order_state_id = ORDER_SHIPPED
        messages.success(request, '訂單已出貨')

    else:
        messages.error(request, '操作無效或狀態錯誤')
        return redirect('seller')

    order.save()
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'home'
    return redirect(next_url)
