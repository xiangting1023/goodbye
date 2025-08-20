from django.db import models
from .user import User
from django.templatetags.static import static
# -------------------------
# 個人資料
# -------------------------
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    nickname = models.CharField(max_length=30, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    @property
    def avatar_url(self):
        if self.avatar and hasattr(self.avatar, "url"):
            return self.avatar.url
        return static('img/Defuser.png')

    def __str__(self):
        return self.user.username
    
