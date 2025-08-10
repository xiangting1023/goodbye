from django.template.loader import render_to_string
from django.shortcuts import render



def seller(request):
    tab_order_html = render_to_string('tabs/order.html',{})
    tab_payment_html = render_to_string('tabs/payment.html',{})
    tab_shipping_html = render_to_string('tabs/shipping.html',{})

    return render(request, 'seller.html', {
        'tab_order': tab_order_html,
        'tab_payment': tab_payment_html,
        'tab_shipping': tab_shipping_html,
    })