# goodBuy_want/forms.py
from django import forms
from goodBuy_shop.models import Shop
from goodBuy_want.models import WantBack, Want

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

        qs = Shop.objects.filter(
            owner=user,
            permission__id__in=[1, 2]
        ).exclude(id__in=replied_shop_ids).order_by('-update')

        self.fields['shop'].queryset = qs

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
