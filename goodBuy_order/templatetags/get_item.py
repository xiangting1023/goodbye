#因為不能直接在 template 裡對 dictionary 用 [] 取值，
#需自訂 get_item filter 來幫忙取值。
from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)