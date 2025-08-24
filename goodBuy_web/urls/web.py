from django.urls import path
from goodBuy_web.views import *
from goodBuy_web.views.user_login_register import *

urlpatterns = [
    path('', homePage, name='home'),
    path('login/', logins, name='login'),
    path('register/', register, name='register'),
    path('logout/', logouts, name='logout'),


    # path('test/hot_shop', test_hot_shops, name='test_personalized_shop_unfiltered'),
    # path('test/hot_want', test_hot_wants, name='test_personalized_want_unfiltered'),
    # path('test/shop', test_personalized_shops, name='test_shop_recommendation'),
    # path('test/want', test_personalized_wants, name='test_want_recommendation'),

]