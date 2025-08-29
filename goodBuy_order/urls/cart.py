from django.urls import path
from goodBuy_order.views import *

urlpatterns = [
    path('', view_cart, name='cart'),
    path('add/<int:product_id>/', add_to_cart, name='add_to_cart'),
    path('delete/<int:cart_item>/', delete_cart_item, name='delete_cart_item'),
    path('delete_selected/', delete_multiple_cart_items, name='delete_multiple_cart_items'),
    path('update_quantity/<int:cart_item>/', update_cart_quantity, name='update_cart_quantity'),
]
