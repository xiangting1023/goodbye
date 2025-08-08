from django.db import models
from django.db.models import Sum
from .shop import Shop
import os
from django.conf import settings

# -------------------------
# 存在的商品
# -------------------------
class ActiveProductManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_delete=False)

# -------------------------
# 商品
# -------------------------
class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255)
    price = models.IntegerField()
    stock = models.IntegerField()
    amount = models.IntegerField()
    introduce = models.TextField(blank=True, null=True)
    img = models.ImageField(upload_to='product_img/', blank=True, null=True)
    is_delete = models.BooleanField(default=False)

    objects = ActiveProductManager() 

    def __str__(self):
        return self.name
    
    # -------------------------
    # 更換圖片後刪除原圖片
    # -------------------------
    def save(self, *args, **kwargs):
        try:
            this = Product.objects.get(id=self.id)
            if this.img != self.img and this.img and os.path.isfile(this.img.path):
                os.remove(this.img.path)
        except Product.DoesNotExist:
            pass
        super().save(*args, **kwargs)

    # -------------------------
    # 庫存回傳
    # ------------------------- 
    def effective_stock_for(self, user=None):
        """
        若 user 已登入且本商品所屬商店為搶購模式 (purchase_priority_id != 1)，
        回傳「庫存 - 使用者自己目前已意向的數量」，
        讓使用者知道 *自己* 還能再搶多少。
        其他情況回傳原本 stock。
        """
        # 非搶購或未登入 → 回傳原本庫存
        if not self.shop or self.shop.purchase_priority_id == 1 or not (user and user.is_authenticated):
            return max(int(self.stock or 0), 0)

        # 延遲匯入，避免循環引用
        from goodBuy_order.models import PurchaseIntent, IntentProduct

        # 找出這位使用者在此商店的意向（通常是一筆）
        intent = PurchaseIntent.objects.filter(user=user, shop=self.shop).first()
        if not intent:
            # 還沒建立意向 → 尚未搶任何數量
            return max(int(self.stock or 0), 0)

        # 這位使用者對此商品已經意向的數量
        my_qty = (
            IntentProduct.objects
            .filter(intent=intent, product=self)
            .aggregate(total=Sum('quantity'))['total'] or 0
        )

        remaining_for_me = max((self.stock or 0) - my_qty, 0)
        return int(remaining_for_me)