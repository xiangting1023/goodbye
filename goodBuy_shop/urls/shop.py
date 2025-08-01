from django.urls import path
from goodBuy_shop.views import *
from django.conf.urls.static import static

urlpatterns = [
    path('add/', add_shop, name='add_shop'),
    # path('<int:shop_id>/add_product/', add_product_to_shop_view, name='add_shop_product'),
    path('<int:shop_id>/edit/', edit_shop, name='shop_edit'),
    path('<int:shop_id>/delete/', deleteShop, name='shop_delete'),

    # 查詢
    path('<int:shop_id>/',shopById_one, name='shop'),
    path('<int:user_id>/',shopByUserId_many, name='shop_page'),
    path('<int:tag_id>/',shopByTag, name='shop_tag'),

    #搜尋
    path('shop/search/', shopBySearch, name='shop_search'),
    path('shop/search/user/<int:user_id>/', shopBySearch, name='shop_search_by_user'),

    #公告
    path('<int:shop_id>/announcement/add/', addAnnouncement, name='add_announcement'),
    path('announcement/<int:announcement_id>/edit/', editAnnouncement, name='edit_announcement'),
    path('announcement/<int:announcement_id>/delete/', deleteAnnouncement, name='delete_announcement'),

    # 圖片裁切
    path('crop/', shop_crop_view, name='shop_crop_view'),
    path('crop/delete/', delete_cropped_image, name='delete_cropped_image'),
    path('crop/select/', select_cropped_images, name='select_cropped_images'),
    path('api/crop-image/', crop_image_api, name='crop_image_api'), #js呼叫使用
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)