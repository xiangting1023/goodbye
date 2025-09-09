from datetime import datetime
from django.utils import timezone
from django.utils.timezone import make_aware
from django.db.models import Q, Case, When, Value, CharField, Sum, F, DecimalField, Prefetch
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth, Coalesce

from goodBuy_order.models import OrderPayment
from goodBuy_order.models import *

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

# -----------------
# 年折線圖 json
# -----------------
@login_required
def payment_year_series(request):
    """
    回傳年度每月收入/支出數據，供前端（Chart.js 等）畫折線圖。
    GET 參數：?year=YYYY（預設今年）
    """
    user = request.user
    now = timezone.now()
    year = int(request.GET.get('year', now.year))

    start_date = make_aware(datetime(year, 1, 1))
    end_date   = make_aware(datetime(year + 1, 1, 1))

    # 我是買家的訂單 id
    buyer_order_ids = list(Order.objects.filter(user=user).values_list('id', flat=True))

    time_filter      = Q(pay_time__gte=start_date, pay_time__lt=end_date)
    identity_filter  = Q(order__shop__owner=user) | Q(order_id__in=buyer_order_ids)
    state_filter     = Q(seller_state__in=['confirmed', 'none'])

    base_qs = (
        OrderPayment.objects
        .filter(time_filter & identity_filter & state_filter)
        .annotate(month=TruncMonth('pay_time'))
        .values('month')
        .annotate(
            income = Coalesce(Sum(
                Case(
                    When(order__shop__owner=user, then=F('amount')),
                    default=Value(0),
                    output_field=DecimalField()
                )
            ), Value(0)),
            expense = Coalesce(Sum(
                Case(
                    When(order_id__in=buyer_order_ids, then=F('amount')),
                    default=Value(0),
                    output_field=DecimalField()
                )
            ), Value(0)),
        )
        .order_by('month')
    )

    # 建 1~12 月空陣列，塞進去
    months   = list(range(1, 13))
    income   = [0] * 12
    expense  = [0] * 12
    for row in base_qs:
        m = row['month'].month  # 1..12
        income[m-1]  = float(row['income'] or 0)
        expense[m-1] = float(row['expense'] or 0)

    net = [round(income[i] - expense[i], 2) for i in range(12)]
    # 累積淨額（看全年現金流走向，蠻有用）
    cum_net = []
    run = 0
    for v in net:
        run += v
        cum_net.append(round(run, 2))

    return JsonResponse({
        'year': year,
        'months': months,       # [1..12]
        'income': income,       # 每月收入
        'expense': expense,     # 每月支出
        'net': net,             # 每月淨額
        'cum_net': cum_net,     # 累積淨額（可選）
    })

# -----------------
# 月圓餅圖
# -----------------
@login_required
def expense_by_shop(request):
    """
    回傳「以賣場(Shop)分組的支出」資料，供前端畫圓餅圖。
    - 只統計：買家、seller_state in ('confirmed','none')
    - 範圍：?year=YYYY（必/預設今年），?month=MM（有則當月，無則全年）
    - Top N：?top=8（其餘合併為「其他」）
    回傳：
    {
    "scope": {"year": 2025, "month": 9 or null},
    "total": 12345.0,
    "labels": ["KITTY SHOP", "NCT周邊店", "其他"],
    "values": [5000.0, 4000.0, 3345.0],
    "percents": [40.5, 32.4, 27.1]
    }
    """
    user = request.user
    now = timezone.now()
    year = int(request.GET.get('year', now.year))
    month_str = request.GET.get('month')
    top_k = int(request.GET.get('top', 8))

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

    # 我是買家的訂單 id
    buyer_order_ids = list(Order.objects.filter(user=user).values_list('id', flat=True))

    time_filter     = Q(pay_time__gte=start_date, pay_time__lt=end_date)
    identity_filter = Q(order_id__in=buyer_order_ids)          # ← 只算支出
    state_filter    = Q(seller_state__in=['confirmed', 'none'])

    # 以賣場分組的支出加總
    rows = (
        OrderPayment.objects
        .filter(time_filter & identity_filter & state_filter)
        .values('order__shop_id', 'order__shop__name')
        .annotate(
            sum_amount = Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )
        .order_by('-sum_amount')
    )

    # 整理 Top N + 其他
    labels, values = [], []
    total = 0.0
    for r in rows:
        amt = float(r['sum_amount'] or 0)
        total += amt

    # 沒資料
    if total == 0:
        return JsonResponse({
            "scope": {"year": year, "month": scope_month},
            "total": 0.0,
            "labels": [],
            "values": [],
            "percents": []
        })

    acc = 0.0
    for idx, r in enumerate(rows):
        name = r['order__shop__name'] or f"Shop#{r['order__shop_id']}"
        amt = float(r['sum_amount'] or 0)
        if idx < top_k - 1:  # 前 top_k-1
            labels.append(name)
            values.append(amt)
            acc += amt
        else:
            break
    # 其他
    others = total - acc
    if others > 0:
        labels.append("其他")
        values.append(others)

    # 百分比
    percents = [round(v * 100.0 / total, 2) for v in values]

    return JsonResponse({
        "scope": {"year": year, "month": scope_month},
        "total": round(total, 2),
        "labels": labels,
        "values": [round(v, 2) for v in values],
        "percents": percents
    })

# -----------------