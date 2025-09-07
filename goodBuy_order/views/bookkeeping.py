from datetime import datetime
from django.utils import timezone
from django.utils.timezone import make_aware
from django.db.models import Q, Case, When, Value, CharField, Sum, Prefetch
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from goodBuy_order.models import OrderPayment
from goodBuy_order.models import *

@login_required
def payment_timeline(request):
    user = request.user
    now = timezone.now()

    year = int(request.GET.get('year', now.year))
    month = int(request.GET.get('month', now.month))

    start_date = make_aware(datetime(year, month, 1))
    end_date = make_aware(datetime(year + 1, 1, 1)) if month == 12 else make_aware(datetime(year, month + 1, 1))

    # 先抓出「這位使用者是買家」的訂單 id 清單，後面一律比對 order_id
    buyer_order_ids = list(
        Order.objects.filter(user=user).values_list('id', flat=True)
    )

    qs = (
        OrderPayment.objects
        .filter(
            # 左邊：我是賣家（收入）；右邊：我是買家（支出，改成 order_id__in）
            Q(shop_payment__shop__owner=user) | Q(order_id__in=buyer_order_ids),
            pay_time__gte=start_date,
            pay_time__lt=end_date,
        )
        .annotate(
            direction_type=Case(
                When(shop_payment__shop__owner=user, then=Value('收入')),
                When(order_id__in=buyer_order_ids, then=Value('支出')),
                default=Value(''),
                output_field=CharField()
            )
        )
        .select_related('order')          # 之後還是可以帶 order 進來用
        .order_by('-pay_time')
    )

    all_payments = list(qs)

    # 批量預取對應訂單的商品（同樣用 *_id__in）
    related_order_ids = [p.order_id for p in all_payments if p.order_id]

    po_qs = (
        ProductOrder.objects
        .filter(order_id__in=related_order_ids)
        .select_related('product__shop')
    )

    orders = (
        Order.objects
        .filter(id__in=related_order_ids)
        .prefetch_related(Prefetch('productorder_set', queryset=po_qs))
    )
    order_map = {o.id: o for o in orders}

    for p in all_payments:
        o = order_map.get(p.order_id)
        if o:
            po_mgr = getattr(o, 'productorder_set', None)
            po_qs = po_mgr.all() if po_mgr else ProductOrder.objects.none()
            p.products = list(po_qs.select_related('product'))
        else:
            p.products = []

    totals = qs.values('direction_type').annotate(total=Sum('amount'))
    total_income = next((t['total'] for t in totals if t['direction_type'] == '收入'), 0) or 0
    total_expense = next((t['total'] for t in totals if t['direction_type'] == '支出'), 0) or 0

    return render(request, 'payment_timeline.html', {
        'year': year,
        'month': month,
        'all_payments': all_payments,
        'total_income': total_income,
        'total_expense': total_expense,
    })
