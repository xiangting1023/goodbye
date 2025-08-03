from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Avg
# -------------------------
# 使用者
# -------------------------
class User(AbstractUser):
    email = models.EmailField(unique=True)
    introduce = models.TextField(blank=True, null=True)
    img = models.ImageField(upload_to='user_img/', null=True, blank=True)

    def __str__(self):
        return self.username  

    @property
    def average_rank(self):
        from goodBuy_order.models import Comment
        avg = Comment.objects.filter(user=self).aggregate(avg_rank=Avg('rank'))['avg_rank']
        return round(avg, 2) if avg is not None else None