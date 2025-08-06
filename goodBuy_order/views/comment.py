from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Avg
from django.contrib import messages
from goodBuy_order.models import Comment
from ..forms import CommentForm
from utils import *
# -------------------------
# 新增評論
# -------------------------
@login_required
@order_buyer_required
def create_comment(request, order):
    if order.order_state_id != 6:
        messages.warning(request, '此訂單尚未完成，無法評論')
        return redirect('view_order_detail', order_id=order.id)

    if Comment.objects.filter(user=request.user, order=order).exists():
        messages.warning(request, '您已對此訂單留下評論')
        return redirect('view_order_detail', order_id=order.id)

    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.user = request.user
            comment.order = order
            comment.save()
            messages.success(request, '評論新增成功')
            return redirect('view_order_detail', order_id=order.id)
    else:
        form = CommentForm()

    return render(request, 'create_comment.html', {'form': form, 'order': order})
# -------------------------
# 顯示賣家評論和平均評價
# -------------------------
@user_exists_required
@blacklist_check(lambda user: user, msg='你已被此使用者封鎖，無法查看', context_name='user')
def view_seller_comments(request, user):
    rank_filter = request.GET.get('rank')  # rank篩選
    order_param = request.GET.get('order')  # 時間排序

    comments = Comment.objects.filter(order__shop__owner=user).select_related('user', 'order')

    if rank_filter:
        try:
            rank_value = int(rank_filter)
            if 1 <= rank_value <= 5:
                comments = comments.filter(rank=rank_value)
        except ValueError:
            pass

    if order_param == 'oldest':
        comments = comments.order_by('update')
    else:
        comments = comments.order_by('-update')

    average_rank = comments.aggregate(avg_rank=Avg('rank'))['avg_rank'] or 0

    return render(request, 'seller_comment_list.html', {'average_rank': average_rank, 'comments': comments, 'user': user})