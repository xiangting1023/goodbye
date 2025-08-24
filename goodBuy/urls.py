from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from goodBuy_web.views.user_login_register import *
from goodBuy_web.views import *
from goodBuy_shop.views import my_shops_collected

urlpatterns = [
    # 共同頁面
    path('', include('goodBuy_web.urls')),
    path('user/', include('goodBuy_web.urls.user')),

    path('shop/', include('goodBuy_shop.urls.shop')),
    path('shop/action/', include('goodBuy_shop.urls.shop_action')),
    path('shop/user/', include('goodBuy_shop.urls.user')),

    path('want/', include('goodBuy_want.urls.want')),
    path('want/reply/', include('goodBuy_want.urls.want_reply')),
    # path('want/action/', include('goodBuy_want.urls.want_action')),

    path('tag/', include('goodBuy_tag.urls.tag')),
    path('tag/user/', include('goodBuy_tag.urls.user')),

    path('order/', include('goodBuy_order.urls.order')),
    path('order/action/', include('goodBuy_order.urls.order_action')),
    path('order/payment/', include('goodBuy_order.urls.payment')),
    path('cart/', include('goodBuy_order.urls.cart')),
    path('comment/', include('goodBuy_order.urls.comment')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
