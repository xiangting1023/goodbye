from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Sum, OuterRef, Subquery
from django.shortcuts import redirect, render
from django.db import transaction

from ..forms import SecondSupplementForm
from utils import *
from ..constants import *
# -------------------------
# 查看付款憑證 - 單筆
# -------------------------
@login_required
@order_exists_required
def view_order_payment_history(request, order):

    is_seller = (order.shop.owner == request.user)
    is_buyer = (order.user == request.user)   
    
    if not (is_seller or is_buyer):
        messages.error(request, '你沒有權限查看這筆訂單的付款紀錄')
        return redirect('home')
    
    if order.payment_category == 'cash_on_delivery':
        messages.error(request, '貨到付款訂單無法查看付款紀錄')
        return redirect('home')
    
    payments = order.payments.order_by('-pay_time')

    latest_payment = payments.first() if payments.exists() else None

    return render(request, 'view_payment_proofs.html', {'payments': payments,
                                                        'lastest_payment': latest_payment})
# -------------------------
# 查看付款憑證 - 多筆 - 可商店查詢
# -------------------------
@login_required
def list_related_payments(request):
    user = request.user
    action = request.GET.get('action')
    buyer_or_seller = request.GET.get('buyer_or_seller')
    shop_id = request.GET.get('shop_id')

    confirmed_total = waiting_total = None

    if buyer_or_seller == 'buyer':
        payments = OrderPayment.objects.filter(
            order__user=user
        ).exclude(seller_state='none').order_by('-pay_time')

    elif buyer_or_seller == 'seller':
        payments = OrderPayment.objects.filter(
            order__shop__owner=user
        ).exclude(seller_state='none').order_by('-pay_time')

        if shop_id:
            try:
                shop = Shop.objects.get(id=shop_id, owner=user)
            except Shop.DoesNotExist:
                messages.error(request, '你無權查看這家商店的付款紀錄')
                return redirect('home')
            payments = payments.filter(order__shop=shop)

        confirmed_total = payments.filter(seller_state='confirmed').aggregate(Sum('amount'))['amount__sum'] or 0
        waiting_total = payments.filter(seller_state='wait confirmed').aggregate(Sum('amount'))['amount__sum'] or 0
    else:
        messages.error(request, '查詢權限錯誤')
        return redirect('home') 

    if action == 'wait_confirmed':
        payments = payments.filter(seller_state='wait confirmed')
    elif action == 'confirmed':
        payments = payments.filter(seller_state='confirmed')
    elif action == 'cancel':
        payments = payments.filter(seller_state__in=['returned', 'overdue'])

    latest_payment_per_order = OrderPayment.objects.filter(
        order=OuterRef('order')
    ).order_by('-pay_time')

    payments = payments.filter(
        id=Subquery(latest_payment_per_order.values('id')[:1])
    ).order_by('-pay_time')

    return render(request, 'payment_list_all.html', {'payments': payments,
                                                    'confirmed_total': confirmed_total,
                                                    'waiting_total': waiting_total})

# -------------------------
# 賣家確認/拒絕付款憑證
"""
    依目前訂單 pay_state_id 決定「確認收款」後要推進到哪個狀態：
        - 8(待全額匯款)   → 9(已全額匯款) 並把訂單推到 4(待出貨)
        - 2(待支付定金)   → 3(已支付定金)
        - 4(待支付尾款)   → 5(已支付尾款)
        - 6(待支付額外費用)→ 7(已支付所有費用) 並把訂單推到 4(待出貨)

    退回憑證：不改 pay_state_id，只把憑證標成 returned，並寫 remark。
"""
# -------------------------
@require_POST
@order_payment_owner_required
def audit_payment(request, payment):
    action = request.POST.get('action')

    if payment.seller_state != 'wait_confirmed':
        messages.warning(request, '這筆付款已處理過')
        return redirect('view_payment_proofs', order_id=payment.order.id)

    order = payment.order
    cur = order.pay_state_id
    print(f'目前訂單付款狀態：{cur}')

    # 這些狀態不該再審憑證（理論上流程不會到這）
    if cur in (PAY_CASH_ON_DELIVERY, PAY_WAIT_SELECT, PAY_CANCELLED, PAY_ALL_PAID, PAY_FULL_PAID):
        messages.error(request, '目前付款狀態不需處理')
        return redirect('view_payment_proofs', order_id=order.id)

    if action not in ('confirm', 'reject'):
        messages.error(request, '無效的操作')
        return redirect('view_payment_proofs', order_id=order.id)

    with transaction.atomic():
        # 更新賣家備註
        new_remark = request.POST.get('remark', '')
        if new_remark:
            payment.remark = new_remark

        if action == 'confirm':
            payment.seller_state = 'confirmed'

            # 依當前 pay_state 決定下一步
            if cur == PAY_WAIT_FULL:
                # 一次付清路徑：完成
                order.pay_state_id = PAY_FULL_PAID
                order.order_state_id = ORDER_WAIT_SHIP

            elif cur == PAY_WAIT_DEPOSIT:
                # 分期：定金確認
                order.pay_state_id = PAY_DEPOSITED

            elif cur == PAY_WAIT_FINAL:
                # 分期：尾款確認
                order.pay_state_id = PAY_FINAL_PAID

            elif cur == PAY_WAIT_EXTRA:
                # 分期：額外費用確認 → 全部完成
                order.pay_state_id = PAY_ALL_PAID
                order.order_state_id = ORDER_WAIT_SHIP

            else:
                # 其他狀態理論上不會到；保守處理
                messages.warning(request, f'目前付款狀態({cur})未定義確認邏輯，已僅標記憑證為已確認')
                payment.save()
                return redirect('view_payment_proofs', order_id=order.id)

            # 儲存訂單與憑證
            order.save()
            payment.save()
            messages.success(request, '已確認收款')

        else:  # action == 'reject'
            payment.seller_state = 'returned'
            payment.save()
            messages.success(request, '已退回憑證')

    return redirect('view_payment_proofs', order_id=order.id)

# -------------------------
# 賣家通知付款
"""
    付款提醒狀態機（只處理 pay_state_id，必要時推進 order_state_id）

    依據你的對照表：
        2 待支付定金      → 可通知（不改狀態，仍 2）
        3 已支付定金      → 轉 4：待支付尾款（提醒尾款）
        4 待支付尾款      → 已在等待尾款（可重發提醒，但狀態仍 4）
        5 已支付尾款      → 若 second_supplement>0 → 6 待支付額外費用
                            否則 → 7 已支付所有費用（並把訂單推到待出貨）
        6 待支付額外費用  → 可重發提醒（狀態仍 6）
        8 待全額匯款      → 可通知（不改狀態，仍 8）
        7/9/10/11         → 不允許再通知
        1                  → COD 不需匯款，亦不通知
"""
# -------------------------
def notify_buyer_to_pay(order, request=None):
    cur = order.pay_state_id

    if cur in (PAY_CASH_ON_DELIVERY, PAY_ALL_PAID, PAY_FULL_PAID, PAY_WAIT_SELECT, PAY_CANCELLED):
        if request:
            messages.error(request, '目前付款狀態不允許通知付款')
        return False

    if cur == PAY_WAIT_DEPOSIT:
        if request:
            messages.success(request, '已通知買家支付「訂金」')
        order.save()
        return True

    if cur == PAY_DEPOSITED:
        order.pay_state_id = PAY_WAIT_FINAL
        if request:
            messages.success(request, '已通知買家支付「尾款」')
        order.save()
        return True

    if cur == PAY_WAIT_FINAL:
        if request:
            messages.success(request, '已再次通知買家支付「尾款」')
        order.save()
        return True

    if cur == PAY_FINAL_PAID:
        if order.second_supplement and order.second_supplement > 0:
            order.pay_state_id = PAY_WAIT_EXTRA
            if request:
                messages.success(request, '已通知買家支付「額外費用」')
        else:
            order.pay_state_id = PAY_ALL_PAID      # 7
            order.order_state_id = ORDER_WAIT_SHIP # 4
            if request:
                messages.success(request, '已確認買家已支付所有費用')
        order.save()
        return True

    if cur == PAY_WAIT_EXTRA:
        if request:
            messages.success(request, '已再次通知買家支付「額外費用」')
        order.save()
        return True

    if cur == PAY_WAIT_FULL:
        if request:
            messages.success(request, '已通知買家完成「全額匯款」')
        order.save()
        return True

    if request:
        messages.error(request, '目前付款狀態無對應的通知流程')
    return False

# -------------------------
# 賣家設定二次補款
# -------------------------
@order_seller_required
def set_second_supplement(request, order):
    if request.method == 'POST':
        form = SecondSupplementForm(request.POST)
        if form.is_valid():
            order.second_supplement = form.cleaned_data['second_supplement']
            order.save()

            messages.success(request, '補款金額已更新')
            return redirect('seller_order_detail', order_id=order.id)
    else:
        form = SecondSupplementForm(initial={'second_supplement': order.second_supplement or 0})

    return render(request, 'set_second_supplement.html', {'form': form})
