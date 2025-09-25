from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import *

from ..models import *
from goodBuy_web.models import SearchHistory

from goodBuy_shop.models import *

from ..want_utils import *
from utils import *

from ..weighting import *
from ..hot_rank import *

# -------------------------
# 點擊的收物帖是否為推薦，做推送記錄
# -------------------------
def record_want_click(request, want):
    filters = Q(want=want)
    if request.user.is_authenticated:
        filters &= Q(user=request.user)
    else:
        if not request.session.session_key:
            request.session.save()
        filters &= Q(session_key=request.session.session_key)

    WantRecommendationHistory.objects.filter(filters).update(clicked=True)

# -------------------------
# 收物帖主頁推送
# -------------------------
def wantAll_update(request):
    wants = want.objects.filter(permission__id=1).order_by('-date')
    return render(request, '主頁', locals())

# -------------------------
# 收物帖查詢 - user_id
# -------------------------
@user_exists_required
def wantByUserId_many(request, user):
    wants = Want.objects.filter(owner=user)
    if not request.user.is_authenticated or request.user != user:
        wants = wants.filter(permission__id=1)

        if request.user.is_authenticated:
            recommended = personalized_want_recommendation(request.user, want_queryset=wants)
        else:
            recommended = get_hot_wants(limit=20)
            recommended = [w for w in recommended if w.user_id == user.id]

        wants = wantInformation_many(recommended)
        return render(request, '別人收物帖', locals())
    
    wants = wantInformation_many(wants)
    return render(request, 'want_detail.html', locals())

# -------------------------
# 收物帖查詢 - want_id + # 查看被回覆的收物帖
# -------------------------
@want_exists_required
@blacklist_check(lambda want: want.user, msg='你已被此賣家封鎖', context_name='want')
def wantById_one(request, want):
    record_want_click(request, want)

    # 如果是收物帖主先把 backs、tags but no return 繼續計算 shared_shops
    if request.user.is_authenticated and request.user == want.user:
        backs = (WantBack.objects
                 .filter(want=want)
                 .select_related('user', 'shop')
                 .order_by('-date'))
        tags = [t.tag for t in WantTag.objects.filter(want=want)]

    # 公開/私密檢查
    if want.permission.id == 2 and request.user != want.owner:
        messages.error(request, '當前收物帖不公開')
        return redirect('home')
    if want.permission.id == 3:
        messages.error(request, '當前收物帖不存在')
        return redirect('home')

    # 足跡邏輯（照舊，保留你原本的 is_authenticated / session 分支）

    # 計算 shared_shops
    shared_shops = []
    if request.user.is_authenticated and request.user.id == want.user_id:
        shared_shop_ids = (WantBack.objects
                           .filter(want=want)
                           .values_list('shop_id', flat=True).distinct())
        qs = (Shop.objects
              .filter(id__in=shared_shop_ids)
              .annotate(price_min=Min('product__price'),
                        price_max=Max('product__price'))
              .prefetch_related(
                  Prefetch('images', queryset=ShopImg.objects.order_by('position', 'id'))
              ))
        shared_shops = list(qs)

    return render(request, 'want_detail.html', locals())

# -------------------------
# 收物帖查詢 - search
# -------------------------
@user_exists_required
def wantBySearch(request, user=None):
    kw = request.GET.get('keyWord')
    sort = request.GET.get('sort', 'new')

    if not kw:
        messages.warning(request, "請輸入關鍵字")
        return redirect('home')

    if request.user.is_authenticated and kw:
        SearchHistory.objects.update_or_create(
            user=request.user,
            keyword=kw,
            searched_at=timezone.now()
        )

    # 準備查詢集
    base_queryset = Want.objects.filter(permission__id=1)
    if user:
        base_queryset = base_queryset.filter(owner=user)

    # 推薦邏輯
    if request.user.is_authenticated:
        wants = personalized_want_recommendation(
            request=request,
            keywords=kw,
            limit=50
        )
    else:
        wants = get_hot_wants(request=request, limit=100, keyword=kw)
        if user:
            wants = [w for w in wants if w.owner_id == user.id]

    # 排序
    if sort == 'old':
        wants = sorted(wants, key=lambda w: w.update)
    else:
        wants = sorted(wants, key=lambda w: w.update, reverse=True)

    wants = wantInformation_many(wants)
    return render(request, '搜尋結果界面', locals())

# -------------------------
# 收物帖查詢 - permission_id
# -------------------------
@login_required(login_url='login')
def wantByPermissionId(request, permission_id):
    if permission_id not in [1, 2]:
        messages.error(request, "僅支援公開/私人可見的收物帖查詢")
        return redirect('home')
    wants = wantInformation_many(Want.objects.filter(owner=request.user, permission__id=permission_id)).order_by('-date')

    return render(request, '查詢完成頁面', locals())
