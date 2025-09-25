# 沒用但先不刪

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Prefetch

from goodBuy_want.models import Want
from goodBuy_shop.models import Shop


def want_and_shop_exists_required():
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, want_id, shop_id, *args, **kwargs):
            try:
                want = (
                    Want.objects
                    .select_related('permission', 'want_state', 'purchase_priority', 'user')
                    .prefetch_related('want_tag_set__tag', 'images')
                    .get(id=want_id)
                )
            except Want.DoesNotExist:
                messages.error(request, '找不到這個收物帖')
                return redirect('home')

            try:
                shop = (
                    Shop.objects
                    .select_related('permission', 'shop_state', 'purchase_priority', 'owner')
                    .prefetch_related('shop_tag_set__tag', 'images')
                    .get(id=shop_id)
                )
            except Shop.DoesNotExist:
                messages.error(request, '找不到這個商店')
                return redirect('home')

            if want.permission_id == 3:
                messages.error(request, '這篇收物帖已被刪除')
                return redirect('home')

            if shop.permission_id == 3:
                messages.error(request, '這家商店已被刪除')
                return redirect('home')

            kwargs['want'] = want
            kwargs['shop'] = shop
            return view_func(request, want, shop, *args, **kwargs)
        return _wrapped_view
    return decorator
