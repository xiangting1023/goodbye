from django.urls import path
from goodBuy_want.views import *

urlpatterns = [
    path('<int:want_id>/', choose_shop_and_reply, name='choose_shop_and_reply'),
]