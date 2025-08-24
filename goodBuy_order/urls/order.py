from django.urls import path
from goodBuy_order.views import *
from goodBuy_order.views.seller_view import *
from goodBuy_order.views.buyer_view import *

urlpatterns = [
    path('orders/buyer/', order_list, {'role': 'buyer'}, name='buyer_order_list'),
    path('orders/seller/', order_list, {'role': 'seller'}, name='seller_order_list'),
    path('detail/<int:order_id>/', order_detail, name='order_detail'),
    
    path('payment_records/', my_payment_records, name='my_payment_records'),
    path('rush/shops/', my_rush_shops, name='my_rush_shops'),
    path('rush/<int:shop_id>/<int:intent_id>/', my_rush_status_in_intent, name='my_rush_status_in_intent'),
    path('priority/<int:shop_id>/', purchase_priority_table, name='priority_table'),
    path('seller/', seller, name='seller'),
    path('buyer/', buyer, name='buyer'),
    path('order/action/seller_action/<int:order_id>/', seller_action, name='seller_action'),  # 接單/付款確認操作
]