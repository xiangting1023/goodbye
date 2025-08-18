from django.db import models
from django.db.models import Sum, Q
from django.utils import timezone
from goodBuy_web.models import User
from .permission import Permission
from .shop_state import ShopState
from .purchase_priority import PurchasePriority
# -------------------------
# 商店
# -------------------------
class ActiveShopManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(permission__id__in=[1, 2])  # 排除 permission_id=3（已刪除）

class Shop(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    introduce = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    shop_state = models.ForeignKey(ShopState, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)
    purchase_priority = models.ForeignKey(PurchasePriority, on_delete=models.CASCADE)
    
    transfer = models.BooleanField(default=False)
    deposit = models.BooleanField(default=False)
    deposit_ratio = models.PositiveIntegerField(default=50)
    update = models.DateTimeField(auto_now_add=True)
    
    is_rush_settled = models.BooleanField(default=False)
    objects = ActiveShopManager()
    
    # 商店是否截止
    @property
    def is_active(self):
        now = timezone.now()
        return (self.permission.id == 1) and (self.start_time <= now <= self.end_time)
    
    # 商店總銷量，多帶則是已有多少人參與
    @property
    def sales_total(self):
        from goodBuy_order.models import ProductOrder, PurchaseIntent
        if self.purchase_priority.id == 1:
            return ProductOrder.objects.filter(
                order__shop=self,
                order__order_state__id=5
            ).aggregate(total=Sum('quantity'))['total'] or 0
        else:
            return PurchaseIntent.objects.filter(shop=self).values('user').distinct().count()
    
    def __str__(self):
        return self.name
    
    """
    回傳此商店所有標籤名稱（tag.name）清單。
    這是從 ShopTag 取得所有與該商店相關聯的標籤文字    
    """
    @property
    def tags(self):
        return [st.tag.name for st in self.shoptag_set.all()]