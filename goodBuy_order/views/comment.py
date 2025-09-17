from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Avg
from django.contrib import messages
from django.utils.dateparse import parse_datetime

from goodBuy_order.models import Comment
from ..forms import CommentForm
from utils import *
# -------------------------
# 新增評論
# -------------------------
@login_required
@order_exists_required
def create_comment(request, order):
    # 只能評已完成的訂單
    if order.order_state_id != 6:
        messages.warning(request, '此訂單尚未完成，無法評論')
        return redirect('view_order_detail', order_id=order.id)

    buyer = order.user
    seller = order.shop.owner

    # 判斷目前使用者是否為此訂單買家或賣家
    if request.user != buyer and request.user != seller:
        messages.error(request, '您沒有權限評論這張訂單')
        return redirect('view_order_detail', order_id=order.id)

    # 依身分決定 target 與 role
    if request.user == buyer:
        role = 'buyer'
        target = seller
    else:
        role = 'seller'
        target = buyer

    # 不允許重複留言（同一發表者 x 同一訂單）
    if Comment.objects.filter(user=request.user, order=order).exists():
        messages.warning(request, '您已對此訂單留下評論')
        return redirect('view_order_detail', order_id=order.id)

    if request.method == 'POST':
        form = CommentForm(request.POST, user=request.user, target=target, role=role, order=order)
        if form.is_valid():
            form.save()
            messages.success(request, '評論新增成功')
            if role == 'buyer':
                return redirect('buyer')
            else:
                return redirect('seller')
    else:
        form = CommentForm(user=request.user, target=target, role=role, order=order)

    return render(request, 'create_comment.html', {'form': form, 'order': order, 'role': role, 'target': target})

# -------------------------
# 顯示評論和平均評價
# -------------------------
def _serialize_comment(c):
    return {
        "id": c.id,
        "order_id": c.order_id,
        "from_user": {
            "id": c.user_id,
            "username": c.user.username,
        },
        "to_user": {
            "id": c.target_id,
            "username": c.target.username,
        },
        "role": c.role,                 # 'buyer' 表示買家寫的評價、'seller' 表示賣家寫的評價
        "rank": c.rank,
        "comment": c.comment,
        "updated_at": c.update.isoformat(),
    }

def view_user_feedback_page(request, user):
    """
    - buyer_to_seller: 買家給這位使用者（作為賣家）之評論
    - seller_to_buyer: 賣家給這位使用者（作為買家）之評論
    """
    buyer_to_seller_qs = (
        Comment.objects
        .filter(target=user, role='buyer')
        .select_related('user', 'target', 'order')
        .order_by('-update')
    )
    seller_to_buyer_qs = (
        Comment.objects
        .filter(target=user, role='seller')
        .select_related('user', 'target', 'order')
        .order_by('-update')
    )

    stats = {
        "as_seller": user.average_rank_as_seller,
        "as_buyer": user.average_rank_as_buyer,
        "overall": user.average_rank_overall,
        "counts": {
            "buyer_to_seller": buyer_to_seller_qs.count(),
            "seller_to_buyer": seller_to_buyer_qs.count(),
        }
    }

    context = {
        "profile_user": user,                 # 被看的使用者
        "buyer_to_seller": buyer_to_seller_qs,
        "seller_to_buyer": seller_to_buyer_qs,
        "averages": stats,
    }
    return render(request, "user_feedback.html", context)