from django.db import models
from goodBuy_web.models import User
from .order import Order

# -------------------------
# 訂單評價&留言
# -------------------------
class Comment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)  # 評論的發表者
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments_received")  # 評論的對象
    role = models.CharField(max_length=10, choices=[("buyer", "Buyer"), ("seller", "Seller")])  # 發表者角色
    rank = models.IntegerField()
    comment = models.TextField()
    update = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'order'], name='unique_user_order_comment')
        ]

    def __str__(self):
        return f'{self.role}: {self.rank} {self.comment}'
