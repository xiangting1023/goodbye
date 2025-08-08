from django.shortcuts import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from collections import defaultdict
from django.db.models import Sum

from goodBuy_shop.models import *
from goodBuy_shop.views import shopInformation_many
from goodBuy_web.models import *
from ..models import *
from ..utils import *
from ..rush_utils import *
from utils import *
# -------------------------
# 訂單顯示 - 全部 - 分類+all
# -------------------------
@login_required(login_url='login')
def order_list(request):
    state = request.GET.get('state')
    shop = request.GET.get('shop')

    orders = Order.objects.filter(user=request.user)

    if shop:
        try:
            shop = Shop.objects.get(id=shop)
        except:
            messages.error(request, "商店不存在")
            return redirect('home')
        
        if shop.owner != request.user:
            messages.error(request, "無權查看此商店的訂單")
            return redirect('home')
        
        if shop.permission not in [1, 2]:
            messages.error(request, "商店不存在")
            return redirect('home')
        
        orders = orders.filter(shop=shop)

    if state:
        if state == '7':
            orders = orders.filter(order_state_id__in=[7, 8, 9, 10])
        else:
            orders = orders.filter(order_state_id=state)

    if state in ['7', '8', '9', '10']:
        title = '已取消'
    elif state:
        title = OrderState.objects.get(id=state).name
    else:
        title = '全部'

    return render(request, 'order_list.html', {'title': title, 'orders': orders, 'shop': shop})
# -------------------------
# 訂單顯示 - 單一
# -------------------------
@login_required(login_url='login')
@order_exists_required
def order_detail(request, order):
    if order.user != request.user and order.shop.owner != request.user:
        messages.error(request, "無權查看此訂單")
        return redirect('home')

    product_orders = ProductOrder.objects.filter(order=order).select_related('product')

    if order.payment_category == 'remittance':
        payments = OrderPayment.objects.filter(order_id=order.id).order_by('-pay_time')
    else:
        payments = None

    deposit_amount = None
    tail_amount = None
    if order.payment_mode == 'split':
        deposit_ratio = order.shop.deposit_ratio or 50
        deposit_amount = order.total * deposit_ratio // 100
        tail_amount = (order.total - deposit_amount) + (order.second_supplement or 0)

    return render(request, 'order_detail.html', {'order':order,
                                                'product_orders': product_orders, 
                                                'payment':payments,
                                                'deposit_amount':deposit_amount,
                                                'tail_amount':tail_amount})
# -------------------------
# 待付款&付款記錄顯示 - 僅買家
# -------------------------
@login_required(login_url='login')
def my_payment_records(request):
    payments = OrderPayment.objects.filter(order__user=request.user)\
    .exclude(shop_payment__payment_account_id=1)\
    .select_related('order', 'shop_payment', 'order__shop')

    wait_confirmed = payments.filter(seller_state='wait confirmed')
    confirmed = payments.filter(seller_state='confirmed')
    returned = payments.filter(seller_state='returned')
    overdue = payments.filter(seller_state='overdue')

    return render(request, 'payment_records.html', {'wait_confirmed': wait_confirmed,
                                                    'confirmed': confirmed,
                                                    'returned': returned,
                                                    'overdue': overdue})
# -------------------------
# 多帶進行中 - 買家
# -------------------------
login_required(login_url='login')
def my_rush_shops(request):
    now = timezone.now()
    shop_ids = PurchaseIntent.objects.filter(
        user=request.user,
        shop__purchase_priority_id__in=[2, 3],
        shop__end_time__gt=now,
        shop__permission__id=1,
    ).values_list('shop_id', flat=True).distinct()

    shops = shopInformation_many(Shop.objects.filter(id__in=shop_ids))

    return render(request, 'my_rush_shops.html', {'shops': shops})
# -------------------------
# 多帶進行中 - 買家 - 單一
# -------------------------
@login_required(login_url='login')
@rush_exists_and_shop_exist_required
def my_rush_status_in_intent(request, shop, intent):
    now = timezone.now()
    remaining_seconds = (shop.end_time - now).total_seconds()

    intent_summaries = get_rush_summaries(shop, user=request.user)

    target_summary = None
    for summary in intent_summaries:
        if summary['user'] == request.user:
            target_summary = summary
            break

    if not target_summary:
        return redirect('some_error_page')

    product_list = target_summary['products']
    total_quantity = target_summary['total_quantity']
    total_price = target_summary['total_price']

    product_list.sort(key=lambda x: (not x['is_successful'], x['product'].id))

    # 顯示格式需要再測試確認
    return render(request, 'my_rush_status_in_shop.html', {'shop': shop,
                                                            'intent': intent,
                                                            'remaining_seconds': remaining_seconds,
                                                            'product_list': product_list,
                                                            'total_quantity': total_quantity,
                                                            'total_price': total_price,
                                                            'target_summary': target_summary
                                                            })
# -------------------------
# 多帶進行中 - 購買優先表格
# -------------------------
@login_required(login_url='login')
def purchase_priority_table(request, shop_id):
    shop = get_object_or_404(Shop, id=shop_id)
    priority_mode = 'amount' if shop.purchase_priority_id == 2 else 'quantity'
    title = "金額多帶優先表" if priority_mode == 'amount' else "數量多帶優先表"

    products = list(Product.objects.filter(shop=shop, is_delete=False).only('id','name','stock','price'))
    if not products:
        return render(request, 'priority_table.html', {
            'shop': shop, 'priority_mode': priority_mode, 'priority_title': title,
            'product_list': [], 'headers': [], 'rows': [], 'buyers_summary': []
        })

    product_ids = [p.id for p in products]
    prod_by_id = {p.id: p for p in products}

    intents = PurchaseIntent.objects.filter(shop=shop).select_related('user')
    intent_ids = list(intents.values_list('id', flat=True))
    user_by_intent = {pi.id: pi.user for pi in intents}

    ip_qs = (IntentProduct.objects
            .filter(intent_id__in=intent_ids, product_id__in=product_ids)
            .values('intent_id','product_id')
            .annotate(qty=Sum('quantity')))

    # 聚合買家數據
    buyers = {}
    for row in ip_qs:
        user = user_by_intent[row['intent_id']]
        uid = user.id
        pid = row['product_id']
        qty = int(row['qty'] or 0)
        if qty <= 0:
            continue
        if uid not in buyers:
            buyers[uid] = {
                'user': user,
                'username': user.profile.nickname,
                'per_product': defaultdict(int),
                'total_qty': 0,
                'total_amount': 0,
            }
        buyers[uid]['per_product'][pid] += qty
        buyers[uid]['total_qty'] += qty
        buyers[uid]['total_amount'] += qty * prod_by_id[pid].price

    buyer_list = list(buyers.values())
    key_field = 'total_amount' if priority_mode == 'amount' else 'total_qty'
    buyer_list.sort(key=lambda b: (b[key_field], b['user'].id), reverse=True)

    # 供上方總表使用的精簡資料
    buyers_summary = [
        {
            'username': b['username'],
            'total_amount': b['total_amount'],
            'total_qty': b['total_qty'],
            'product_quantities': dict(b['per_product']),  # 若你上方要看各品可留，否則可拿掉
        }
        for b in buyer_list
    ]

    # 生成分配矩陣（用「使用者名稱」填格）
    alloc_col = {pid: [] for pid in product_ids}
    for b in buyer_list:
        for pid, want_qty in b['per_product'].items():
            stock = prod_by_id[pid].stock
            if stock <= 0:
                continue
            col = alloc_col[pid]
            free_slots = max(stock - len(col), 0)
            if free_slots <= 0:
                continue
            take = min(want_qty, free_slots)
            col.extend([b['username']] * take)  # ← 用名稱，不是 rank

    max_rows = max(p.stock for p in products) if products else 0
    headers = [{'id': p.id, 'name': p.name, 'stock': p.stock} for p in products]

    rows = []
    for r in range(max_rows):
        row_cells = []
        for p in products:
            s = p.stock
            col = alloc_col[p.id]
            if r >= s:
                cell = '-'          # 超出庫存列
            else:
                cell = col[r] if r < len(col) else ''  # 有庫存未分配 → 空白
            row_cells.append(cell)
        rows.append(row_cells)

    return render(request, 'priority_table.html', {
        'shop': shop,
        'priority_mode': priority_mode,
        'priority_title': title,
        'product_list': products,
        'headers': headers,
        'rows': rows,
        'buyers_summary': buyers_summary,
    })

