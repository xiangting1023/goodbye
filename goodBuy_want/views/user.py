from django.db.models import *
from django.contrib import messages
from django.shortcuts import *
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError

from ..utils import *
from utils import *

from ..models import *
from goodBuy_want.form import ChooseShopToReplyForm
from goodBuy_want.views.want_query import *
from goodBuy_web.models import *

# -------------------------
# 收物帖足跡
# -------------------------
@login_required(login_url='login')
def my_want_footprints(request):
    want_ids = WantFootprints.objects.filter(user=request.user).values_list('want_id', flat=True)
    wants = wantInformation_many(want.objects.filter(id__in=want_ids).order_by('-date'))
    return render(request, '足跡頁面', locals())

# -------------------------
# 選擇商店並回復收物帖
# -------------------------
@login_required(login_url='login')
@want_exists_required
def choose_shop_and_reply(request, want):
    """
    GET：顯示「可用來回覆」的商店下拉（或列表）
    POST：建立 WantBack（以所選商店回覆）
    """

    # 不能回覆自己的收物帖
    if want.user_id == request.user.id:
        messages.error(request, '不能回覆自己發布的收物帖。')
        return redirect('want_detail', want_id=want.id)

    if request.method == 'POST':
        form = ChooseShopToReplyForm(request.POST, user=request.user, want=want)
        if form.is_valid():
            shop = form.cleaned_data['shop']
            try:
                with transaction.atomic():
                    obj, created = WantBack.objects.get_or_create(
                        user=request.user, want=want, shop=shop
                    )
            except IntegrityError:
                created = False  # 撞到唯一鍵就當成已存在

            if created:
                messages.success(request, f'你已成功以「{shop.name}」回覆該收物帖！')
            else:
                messages.warning(request, f'你已經以「{shop.name}」回覆過這個收物帖了！')

            return redirect('want_detail', want_id=want.id)
    else:
        form = ChooseShopToReplyForm(user=request.user, want=want)

    return render(request, 'choose_shop_to_reply.html', {
        'want': want,
        'form': form,
    })

# -------------------------
# 查看被回復的收物帖
# -------------------------