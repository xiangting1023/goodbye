from django.urls import path
from goodBuy_order.views import *

urlpatterns = [
    path('checkout/', checkout_step1, name='checkout'),
    path('checkout/address_payment', checkout_step2, name='checkout_address_payment'),
    path('buyer_action/<int:order_id>/', buyer_action, name='buyer_action'),
    path('seller_action/<int:order_id>/', seller_action, name='seller_action'),
    #path('batch_seller_action/', batch_seller_action, name='batch_seller_action'),
]