from django.urls import path
from goodBuy_order.views import *


urlpatterns = [
    path('<int:user_id>/feedback/', view_user_feedback_page, name='view_user_feedback_page'),
    path('payments/timeline/', payment_timeline, name='payment_timeline'),
    path("payments/yearly/", payment_year_series, name="payment_year_series"),
    path('payments/expense-by-shop/', expense_by_shop, name='expense_by_shop'),
]