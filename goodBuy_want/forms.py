from django import forms
from django.forms.widgets import ClearableFileInput

from .models import Want, WantImg, WantTag
from goodBuy_tag.models import Tag
from goodBuy_shop.models import Permission, Shop
from django.db.models import Q
from django.utils import timezone
from goodBuy_want.models import WantBack, Want
from django.db.models import Min, Max
class MultipleClearableFileInput(ClearableFileInput):
    allow_multiple_selected = True

# -------------------------
# 收物帖創建/修改表單
# -------------------------
class WantForm(forms.ModelForm):
    tag_names = forms.CharField(required=False, widget=forms.HiddenInput())

    cover_index = forms.IntegerField(required=False, widget=forms.HiddenInput())
    image_order = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Want
        fields = ['title', 'post_text','permission']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '輸入收物帖標題'}),
            'post_text': forms.Textarea(attrs={'class': 'form-control', 'placeholder': '輸入收物帖內容'}),
            'permission': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_edit = kwargs.get('instance') is not None
        super().__init__(*args, **kwargs)

        self.fields['permission'].queryset = Permission.objects.filter(id__in=[1, 2])

    def save(self, commit=True):
        want = super().save(commit=False)

        if self.user:
            want.user = self.user

        if commit:
            want.save()

            # 更新標籤
            tag_names = self.cleaned_data.get('tag_names', '')
            tag_names = [t.strip() for t in tag_names.split(',') if t.strip()]
            existing_tags = Tag.objects.filter(name__in=tag_names)
            existing_names = set(existing_tags.values_list('name', flat=True))
            new_names = set(tag_names) - existing_names
            new_tags = [Tag.objects.create(name=name) for name in new_names]
            all_tags = list(existing_tags) + new_tags

            if self.is_edit:
                WantTag.objects.filter(want=want).exclude(tag__name__in=tag_names).delete()

            for tag in all_tags:
                WantTag.objects.get_or_create(want=want, tag=tag)

        return want

# -------------------------
# 收物帖回覆商店選擇表單
# -------------------------
class ChooseShopToReplyForm(forms.Form):
    shop = forms.ModelChoiceField(
        queryset=Shop.objects.none(),
        label='選擇商店',
        empty_label='請選擇商店',
        required=True
    )

    def __init__(self, *args, user=None, want: Want = None, **kwargs):
        """
        依使用者與目標 want 動態限制可選商店：
        - 只能選自己擁有的商店
        - permission 在 [1, 2]
        - 尚未回覆過該 want
        """
        super().__init__(*args, **kwargs)
        self.user = user
        self.want = want

        replied_shop_ids = WantBack.objects.filter(
            user=user, want=want
        ).values_list('shop_id', flat=True)

        now = timezone.now()
        
        qs = Shop.objects.filter(
            owner=user,
            permission__id=1,
        ).filter(
            Q(end_time__isnull=True) | Q(end_time__gt=now)   # 未設定截止 或 尚未截止
        ).exclude(
            id__in=replied_shop_ids
        ).order_by('-update')

        annotated_qs = qs.annotate(
            price_min=Min('product__price'),
            price_max=Max('product__price'),
        )

        self.fields['shop'].queryset = annotated_qs

    def clean_shop(self):
        shop = self.cleaned_data['shop']

        # 再保險檢查一次（避免被人改表單值）
        if shop.owner_id != self.user.id:
            raise forms.ValidationError('你不是此商店的擁有者。')

        if getattr(shop, 'permission_id', None) not in [1, 2]:
            raise forms.ValidationError('此商店目前不可用來回覆。')

        if WantBack.objects.filter(user=self.user, want=self.want, shop=shop).exists():
            raise forms.ValidationError('你已使用該商店回覆過此收物帖。')

        return shop
