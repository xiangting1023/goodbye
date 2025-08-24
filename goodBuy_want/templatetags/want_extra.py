from django import template

register = template.Library()

@register.filter
def get_cover(images_queryset):
    """回傳第一張圖片（或 None）"""
    return images_queryset.first()  # 假設封面就是第一張