from datetime import datetime
from django.utils import timezone
from django.utils.timezone import make_aware
from django.db.models import Q, Case, When, Value, CharField, Sum, F, DecimalField, Prefetch
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

    # 這位使用者當買家的訂單 id
    buyer_order_ids = list(Order.objects.filter(user=user).values_list('id', flat=True))

    # 期間
    time_filter = Q(pay_time__gte=start_date, pay_time__lt=end_date)

    # ★ 身分：我是賣家（用 order__shop__owner）或我是買家
    identity_filter = Q(order__shop__owner=user) | Q(order_id__in=buyer_order_ids)

    # 只納入：賣家已確認 或 取貨付款（字串 'none'）
    state_filter = Q(seller_state__in=['confirmed', 'none'])

    qs = (
        OrderPayment.objects
        .filter(time_filter & identity_filter & state_filter)
        .annotate(
            direction_type=Case(
                When(order__shop__owner=user, then=Value('收入')),   # ★ 改這裡
                When(order_id__in=buyer_order_ids, then=Value('支出')),
                default=Value(''),
                output_field=CharField()
            )
        )
        .select_related('order')
        .order_by('-pay_time')
    )

    all_payments = list(qs)

    # 預取商品，避免 N+1
    related_order_ids = [p.order_id for p in all_payments if p.order_id]
    po_qs = ProductOrder.objects.filter(order_id__in=related_order_ids).select_related('product__shop')
    orders = Order.objects.filter(id__in=related_order_ids).prefetch_related(Prefetch('productorder_set', queryset=po_qs))
    order_map = {o.id: o for o in orders}

    for p in all_payments:
        o = order_map.get(p.order_id)
        if o:
            po_mgr = getattr(o, 'productorder_set', None)
            po_qs_each = po_mgr.all() if po_mgr else ProductOrder.objects.none()
            p.products = list(po_qs_each.select_related('product'))
        else:
            p.products = []

    # ★ 總額：用同一套身分判斷
    agg = (
        OrderPayment.objects
        .filter(time_filter & identity_filter & state_filter)
        .aggregate(
            total_income=Sum(
                Case(
                    When(order__shop__owner=user, then=F('amount')),   # ★ 改這裡
                    default=0, output_field=DecimalField()
                )
            ),
            total_expense=Sum(
                Case(
                    When(order_id__in=buyer_order_ids, then=F('amount')),
                    default=0, output_field=DecimalField()
                )
            ),
        )
    )
    total_income  = agg['total_income']  or 0
    total_expense = agg['total_expense'] or 0

    return render(request, 'payment_timeline.html', {
        'year': year,
        'month': month,
        'all_payments': all_payments,
        'total_income': total_income,
        'total_expense': total_expense,
    })
