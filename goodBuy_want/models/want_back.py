from django.db import models
from goodBuy_shop.models import Shop
from goodBuy_web.models import User
from .want import Want

# -------------------------
# 收物帖回復
# -------------------------
class WantBack(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    want = models.ForeignKey(Want, on_delete=models.CASCADE)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'want', 'shop'], name='unique_want_reply')
        ]
    
    def __str__(self):
        return f"{self.user} 以「{self.shop}」回覆收物帖 {self.want_id}"
