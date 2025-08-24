from django.urls import path
from goodBuy_want.views import *
# from goodBuy_want.test import *

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('add/', add_want, name='add_want'),
    path('<int:want_id>/', wantById_one, name='want_detail'),
    path('<int:want_id>/edit/', edit_want, name='edit_want'),
    path('<int:want_id>/delete/', delete_want, name='delete_want'),
    path('<int:want_id>/delete_image/<int:image_id>/', delete_want_image, name='delete_want_image'),
    path('<int:want_id>/cover/<int:image_id>/', set_cover_image, name='set_cover_image'),

    path('search/', wantBySearch, name='want_search'),
    path('search/user/<int:user_id>/', wantBySearch, name='want_search_by_user'),
    

    # path('<int:want_id>/test-reply/', test_choose_shop_reply_api, name='test_choose_shop_reply_api'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)