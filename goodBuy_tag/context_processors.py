# -------------------------
# 側邊欄顯示標籤
# -------------------------
from goodBuy_tag.models import Tag, TagCollect


def user_followed_tags(request):
    if not request.user.is_authenticated:
        return {'user_followed_tags': []}

    tag_ids = TagCollect.objects.filter(user=request.user)\
                                .values_list('tag_id', flat=True)
    tags = Tag.objects.filter(id__in=tag_ids).order_by('name')\
                      .only('id', 'name')  
    return {'user_followed_tags': tags}