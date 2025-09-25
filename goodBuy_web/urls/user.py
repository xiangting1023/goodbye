from django.urls import path
from goodBuy_web.views import *

urlpatterns = [
    path('editprofile/', editProfile, name='editprofile'),
    path('payment_accounts/', payment_accounts, name='payment_accounts'),
]