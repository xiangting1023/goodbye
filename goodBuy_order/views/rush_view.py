# 無用但先不刪

from django.shortcuts import *
from django.contrib import messages
from collections import defaultdict

from goodBuy_shop.models import *
from goodBuy_web.models import *
from ..models import *
from ..utils import *
from ..rush_utils import *
# -------------------------
# 多帶商店顯示所有人多帶情況 - 流水表
# -------------------------
@shop_exists_and_is_rush_required
def rush_status(request, shop):
    all_products = Product.objects.filter(shop=shop, is_delete=False)
    intent_summaries = get_rush_summaries(shop, request.user)

    product_claimed = defaultdict(int)
    allocation_rows = []

    while True:
        row = {}
        all_empty = True

        for summary in intent_summaries:
            for ip in summary['products']:
                current_allocated = product_claimed[ip.product.id]
                available_stock = ip.product.stock
                if current_allocated < available_stock and ip.quantity > 0:
                    row[ip.product.id] = {
                        'username': summary['user'].username,
                        'is_self': summary['user'].id == request.user.id,
                    }
                    product_claimed[ip.product.id] += 1
                    ip.quantity -= 1
                    all_empty = False
                    break

        if all_empty:
            break
        allocation_rows.append(row)

    return render(request, 'user_rush_status.html', locals())

# -------------------------
# 多帶商店顯示所有人多帶情況 - 交叉表
# -------------------------
@shop_exists_and_is_rush_required
def rush_cross_table(request, shop):
    intent_summaries = get_rush_summaries(shop, request.user)

    cross_table = []
    for summary in intent_summaries:
        cross_table.append({
            'user': summary['user'],
            'total_quantity': summary['total_quantity'],
            'total_price': summary['total_price'],
        })

    return render(request, 'rush_cross_simple.html', locals())
