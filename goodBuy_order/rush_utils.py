from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from goodBuy_shop.models import *
from goodBuy_web.models import *
from goodBuy_order.models import PurchaseIntent, IntentProduct
from .models import *

from collections import defaultdict, namedtuple
from django.db.models import Sum
from django.utils import timezone

def get_rush_summaries(shop, user=None):
    # 只計算截止前的意向
    cutoff = shop.end_time or timezone.now()

    # 取意向，依 user / 時間 排序，避免不穩定
    # 假設你的 Model：PurchaseIntent、related_name='intent_products'，且有 created_at
    intents_qs = (
        PurchaseIntent.objects
        .filter(shop=shop, create_time__lte=cutoff)
        .select_related('user')                      # FK 用 select_related
        .prefetch_related('intent_products__product')# M2M/反向用 prefetch_related
        .order_by('user_id', 'create_time', 'id')     # 穩定時間序
    )

    IntentProduct_qs = namedtuple('IntentProduct', 'product quantity')

    # 匯總：每位使用者 → 各商品總量、總量/總額、第一筆時間、時間序列表
    per_user_products = defaultdict(lambda: defaultdict(int))  # uid -> pid -> qty
    per_user_first_ts = {}                                     # uid -> datetime
    per_user_qty = defaultdict(int)                            # uid -> int
    per_user_amount = defaultdict(lambda: 0)                   # uid -> Decimal
    per_user_items = defaultdict(list)                         # uid -> [ (created_at, product, qty, price) ]
    per_user_obj = {}                                          # uid -> <User>

    for intent in intents_qs:
        uid = intent.user_id
        per_user_obj.setdefault(uid, intent.user)
        per_user_first_ts.setdefault(uid, getattr(intent, 'created_at', timezone.now()))
        for ip in intent.intent_products.all():
            qty = int(ip.quantity or 0)
            price = getattr(ip, 'price', None)
            price = price if price is not None else ip.product.price

            per_user_products[uid][ip.product_id] += qty
            per_user_qty[uid] += qty
            per_user_amount[uid] += price * qty
            per_user_items[uid].append((getattr(intent, 'created_at', timezone.now()), ip.product, qty, price))

    # 計算 reached_*_at：在時間序累加，第一次達到最終總量/總額的時間
    reached_qty_at = {}
    reached_amount_at = {}
    for uid, items in per_user_items.items():
        final_qty = per_user_qty[uid]
        final_amt = per_user_amount[uid]

        c_qty = 0
        c_amt = 0
        rq_ts = None
        ra_ts = None

        for created_at, product, qty, price in items:  # 已按時間序
            if rq_ts is None:
                c_qty += qty
                if c_qty >= final_qty:
                    rq_ts = created_at
            if ra_ts is None:
                c_amt += price * qty
                if c_amt >= final_amt:
                    ra_ts = created_at
            if rq_ts and ra_ts:
                break

        # 萬一沒有就回退到第一筆，避免 None 破壞排序
        reached_qty_at[uid] = rq_ts or per_user_first_ts[uid]
        reached_amount_at[uid] = ra_ts or per_user_first_ts[uid]

    # 組 summaries（含 products 聚合）
    summaries = []
    for uid, pmap in per_user_products.items():
        products = []
        # 把各商品總量轉為 IntentProduct 列表
        for pid, qty in pmap.items():
            # 從 per_user_items 找到一個 product 物件（items 已 prefetch）
            # 這邊取第一個出現的 product 物件即可
            prod = next((it[1] for it in per_user_items[uid] if it[1].id == pid), None)
            if prod:
                products.append(IntentProduct_qs(prod, qty))

        row = {
            'user': per_user_obj[uid],
            'products': products,
            'total_price': per_user_amount[uid],
            'total_quantity': per_user_qty[uid],
            'reached_qty_at': reached_qty_at[uid],
            'reached_amount_at': reached_amount_at[uid],
            'first_intent_at': per_user_first_ts[uid],
            'user_id': uid,
        }

        # 若要求顯示「自己視角」：計算 available/is_successful
        if user and uid == getattr(user, 'id', None):
            self_view = []
            for prod, qty in products:
                # 其他人對該商品的總申請量（不含自己）
                others_claimed = (
                    IntentProduct.objects
                    .filter(product=prod, intent__shop=shop)
                    .exclude(intent__user=user)
                    .aggregate(total=Sum('quantity'))['total'] or 0
                )
                available = max(prod.stock - others_claimed, 0)
                self_view.append({
                    'product': prod,
                    'quantity': qty,
                    'price': prod.price,
                    'total_price': prod.price * qty,
                    'available': available,
                    'is_successful': qty <= available,
                })
            row['self_view'] = self_view

        summaries.append(row)

    # 排序（你的規則）
    if shop.purchase_priority_id == 3:  # 數量優先
        summaries.sort(key=lambda s: (
            -int(s['total_quantity']),
            s['reached_qty_at'],
            s['first_intent_at'],
            s['user_id'],
        ))
    else:  # 金額優先（含 2）
        summaries.sort(key=lambda s: (
            -float(s['total_price']),
            s['reached_amount_at'],
            s['first_intent_at'],
            s['user_id'],
        ))

    return summaries


from django.db import transaction
def maybe_extend_rush(shop):
    """
    防尾刀：剩餘 <= 5 分鐘時，最多把 end_time 以 5 分鐘為單位往後延，
    但不超過 end_time + 30 分鐘上限。
    並發安全：以 select_for_update() 鎖住該 shop。
    """
    with transaction.atomic():
        locked = Shop.objects.select_for_update().get(pk=shop.pk)
        now = timezone.now()
        if not locked.end_time:  # 沒有截止時間就不處理
            return locked

        # 已經結算就不延（若你有此欄位）
        if getattr(locked, 'is_rush_settled', False):
            return locked

        remaining = (locked.end_time - now).total_seconds()
        if remaining > 300:
            return locked

        max_end_time = locked.start_time + timedelta(minutes=30)
        proposed = locked.end_time + timedelta(minutes=5)

        if proposed <= max_end_time:
            locked.end_time = proposed
            locked.save(update_fields=['end_time'])

        return locked
