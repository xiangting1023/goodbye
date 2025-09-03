from django.template.loader import render_to_string
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from goodBuy_order.models import Order, OrderPayment, ProductOrder



@login_required
def seller(request):
    pending_orders = Order.objects.filter(
        shop__owner=request.user,
        order_state_id=2
    ).select_related('shop', 'order_state', 'user')

    pending_payments = OrderPayment.objects.filter(
        order__shop__owner=request.user,
        seller_state='wait_confirmed'
    ).select_related('order', 'shop_payment', 'order__user').order_by('-pay_time')

    shipping_orders = ProductOrder.objects.filter(
        order__shop__owner=request.user,
        order__order_state_id=4
    ).select_related('order', 'product', 'order__user')

    shipped_orders = ProductOrder.objects.filter(
        order__shop__owner=request.user,
        order__order_state_id=5
    ).select_related('order', 'product', 'order__user')
    pending_payments = OrderPayment.objects.filter(
    order__shop__owner=request.user,
    seller_state='wait_confirmed'
    )

    return render(request, 'seller.html', {
        'pending_orders': pending_orders,
        'payments': pending_payments,
        'shipping_orders': shipping_orders,
        'shipped_orders': shipped_orders,
    })