from datetime import datetime
from django.utils import timezone
from decimal import Decimal
from django.utils.timezone import make_aware
from django.db.models import Q, Case, When, Value, CharField, Sum, F, DecimalField, Prefetch, IntegerField
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models.functions import ExtractMonth, Coalesce

from goodBuy_order.models import OrderPayment
from goodBuy_order.models import *
from django.shortcuts import render, get_object_or_404


# -----------------
# 月流水明細
# -----------------
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

    # 身分：我是賣家（用 order__shop__owner）或我是買家
    identity_filter = Q(order__shop__owner=user) | Q(order_id__in=buyer_order_ids)

    # 只納入：賣家已確認 或 取貨付款（字串 'none'）
    state_filter = Q(seller_state__in=['confirmed', 'none'])

    qs = (
        OrderPayment.objects
        .filter(time_filter & identity_filter & state_filter)
        .annotate(
            direction_type=Case(
                When(order__shop__owner=user, then=Value('收入')),
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

    # 總額：用同一套身分判斷
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
        'months': list(range(1, 13)),                # ← 新增
        'year_options': [year - 2, year - 1, year],  # ← 新增（要幾年自己調整）
    })

# -----------------
# 年折線圖 json
# -----------------
@login_required
def payment_year_series(request):
    """
    年度每月總收入/總支出（1..12）
    規則：
      - 計入 seller_state in ('none','confirmed')
      - 收入 = 我是賣家（order__shop__owner=user）
      - 支出 = 我是買家（order__user=user）
    """
    user = request.user
    year = int(request.GET.get('year') or timezone.now().year)

    state_q = Q(seller_state__in=['none', 'confirmed'])

    months = list(range(1, 13))
    income, expense = [], []

    for m in months:
        start_date = make_aware(datetime(year, m, 1))
        end_date = make_aware(datetime(year + 1, 1, 1)) if m == 12 else make_aware(datetime(year, m + 1, 1))

        time_q = Q(pay_time__gte=start_date, pay_time__lt=end_date)

        # 收入：我是賣家
        inc = (
            OrderPayment.objects
            .filter(time_q & state_q & Q(order__shop__owner=user))
            .aggregate(total=Coalesce(
                Sum('amount'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=18, decimal_places=2)
            ))
        )['total'] or Decimal('0.00')

        # 支出：我是買家
        exp = (
            OrderPayment.objects
            .filter(time_q & state_q & Q(order__user=user))
            .aggregate(total=Coalesce(
                Sum('amount'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=18, decimal_places=2)
            ))
        )['total'] or Decimal('0.00')

        income.append(float(inc))
        expense.append(float(exp))

    net = [round(income[i] - expense[i], 2) for i in range(12)]
    cum_net, run = [], 0.0
    for v in net:
        run += v
        cum_net.append(round(run, 2))

    return JsonResponse({
        'year': year,
        'months': months,
        'income': income, # 收入
        'expense': expense, # 支出
        'net': net, # 月淨額
        'cum_net': cum_net, # 總淨額
    })

# -----------------
# 月圓餅圖
# -----------------
@login_required
def by_shop_income_expense_summary(request):
    """
    同時回傳「以賣場分組的支出(買家)」與「收入(賣家)」兩組圓餅圖資料。
    參數：
      - ?year=YYYY（預設今年）
      - ?month=MM（可選）
      - ?top_expense=8（可選）
      - ?top_income=8（可選）
    """
    user = request.user
    now = timezone.now()
    year = int(request.GET.get('year', now.year))
    month_str = request.GET.get('month')
    top_exp = int(request.GET.get('top_expense', 8))
    top_inc = int(request.GET.get('top_income', 8))

    # 時間範圍
    if month_str:
        month = int(month_str)
        start_date = make_aware(datetime(year, month, 1))
        end_date = make_aware(datetime(year + 1, 1, 1)) if month == 12 else make_aware(datetime(year, month + 1, 1))
        scope_month = month
    else:
        start_date = make_aware(datetime(year, 1, 1))
        end_date = make_aware(datetime(year + 1, 1, 1))
        scope_month = None

    # 共用條件
    time_filter  = Q(pay_time__gte=start_date, pay_time__lt=end_date)
    state_filter = Q(seller_state__in=['confirmed', 'none'])

    # 支出（我是買家）
    buyer_order_ids = list(
        Order.objects.filter(user=user).values_list('id', flat=True)
    )
    exp_rows = (
        OrderPayment.objects
        .filter(time_filter & state_filter & Q(order_id__in=buyer_order_ids))
        .values('order__shop_id', 'order__shop__name')
        .annotate(sum_amount=Coalesce(
            Sum('amount'),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ))
        .order_by('-sum_amount')
    )

    # 收入（我是賣家）
    inc_rows = (
        OrderPayment.objects
        .filter(time_filter & state_filter & Q(order__shop__owner=user))
        .values('order__shop_id', 'order__shop__name')
        .annotate(sum_amount=Coalesce(
            Sum('amount'),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ))
        .order_by('-sum_amount')
    )

    def to_pie(rows, top_k):
        total = float(sum((r['sum_amount'] or 0) for r in rows))
        if total == 0:
            return {"total": 0.0, "labels": [], "values": [], "percents": []}
        labels, values, acc = [], [], 0.0
        for idx, r in enumerate(rows):
            name = r['order__shop__name'] or f"Shop#{r['order__shop_id']}"
            amt = float(r['sum_amount'] or 0)
            if idx < top_k - 1:
                labels.append(name); values.append(round(amt, 2)); acc += amt
            else:
                break
        others = total - acc
        if others > 0: labels.append("其他"); values.append(round(others, 2))
        percents = [round(v * 100.0 / total, 2) for v in values]
        return {
            "total": round(total, 2),
            "labels": labels,
            "values": values,
            "percents": percents
        }

    return JsonResponse({
        "scope": {"year": year, "month": scope_month},
        "expense": to_pie(exp_rows, top_exp),
        "income":  to_pie(inc_rows, top_inc),
    })

# -----------------
# 單筆付款明細
# -----------------
@login_required
def payment_detail(request, payment_id):
    payment = get_object_or_404(OrderPayment, id=payment_id)
    return render(request, "payment_timeline_search.html", {
        "payment": payment,
        "order": payment.order,
    })
