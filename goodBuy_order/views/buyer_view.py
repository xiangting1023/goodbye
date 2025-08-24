from django.template.loader import render_to_string
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from goodBuy_order.models import Order, OrderPayment, ProductOrder

@login_required
def buyer(request):
    
    # 我的訂單（例如：2=待下單）
    my_orders = Order.objects.filter(
        user=request.user,
        order_state_id=2
    ).select_related('shop', 'order_state')

    # 付款紀錄（假設 seller_state 無關，改成付款狀態過濾）
    my_payments = OrderPayment.objects.filter(
        order__user=request.user
    ).select_related('order', 'shop_payment').order_by('-pay_time')

    # 收貨管理
    # 待收貨（假設 4=已出貨）
    waiting_receiving = ProductOrder.objects.filter(
        order__user=request.user,
        order__order_state_id=4
    ).select_related('order', 'product')

    # 已收貨（假設 5=已完成）
    received_orders = ProductOrder.objects.filter(
        order__user=request.user,
        order__order_state_id=5
    ).select_related('order', 'product')

    # 渲染 Tab HTML
    tabs_order_html = render_to_string('btabs/border.html', {'my_orders': my_orders})
    tabs_payment_html = render_to_string('btabs/bpayment.html', {'my_payments': my_payments})
    tabs_shipping_html = render_to_string('btabs/bshipping.html', {
        'waiting_receiving': waiting_receiving,
        'received_orders': received_orders
    })

    return render(request, 'buyer.html', {
        'btabs_order': tabs_order_html,
        'btabs_payment': tabs_payment_html,
        'btabs_shipping': tabs_shipping_html,
    })
