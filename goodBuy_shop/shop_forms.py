from django import forms
from django.forms.widgets import ClearableFileInput
from django.http import QueryDict

from goodBuy_shop.models import *
from goodBuy_tag.models import Tag
from goodBuy_web.models import PaymentAccount
from .time_utils import timeFormatChange_now, timeFormatChange_longtime

class MultipleClearableFileInput(ClearableFileInput):
    allow_multiple_selected = True

class ImageUploadForm(forms.Form):
    image = forms.ImageField()

class ShopForm(forms.ModelForm):
    tag_names = forms.CharField(required=False, widget=forms.HiddenInput())

    payment_ids = forms.ModelMultipleChoiceField(
        queryset=PaymentAccount.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )

    start_time = forms.DateTimeField(
        input_formats=['%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        required=False
    )
    end_time = forms.DateTimeField(
        input_formats=['%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        required=False
    )

    class Meta:
        model = Shop
        fields = [
            'name', 'introduce', 'start_time', 'end_time',
            'shop_state', 'permission', 'purchase_priority',
            'deposit', 'deposit_ratio'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '輸入商店名稱'}),
            'introduce': forms.Textarea(attrs={'class': 'form-control', 'placeholder': '輸入商店介紹'}),
            'deposit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'deposit_ratio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '例如 50 表示 50%'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_edit = kwargs.get('instance') is not None and kwargs.get('instance').pk is not None

        super().__init__(*args, **kwargs)

        self.fields['permission'].queryset = Permission.objects.filter(id__in=[1, 2])

        if self.user:
            user_accounts = PaymentAccount.objects.filter(user=self.user, is_delete=False)

            if self.is_edit:
                shop_account_ids = ShopPayment.objects.filter(shop=self.instance).values_list('payment_account_id', flat=True)
                shop_accounts = PaymentAccount.objects.filter(id__in=shop_account_ids)
                full_queryset = (user_accounts | shop_accounts).distinct()
            else:
                full_queryset = user_accounts

            self.fields['payment_ids'].queryset = full_queryset

        if self.is_edit:
            self.fields['payment_ids'].initial = ShopPayment.objects.filter(
                shop=self.instance
            ).values_list('payment_account_id', flat=True)

    def clean(self):
        cleaned = super().clean()

        start_time = cleaned.get('start_time')
        end_time   = cleaned.get('end_time')
        priority   = cleaned.get('purchase_priority')

        # 兼容：priority 可能是整數欄位，也可能是外鍵物件
        def _priority_value(p):
            if p is None: 
                return None
            return getattr(p, 'id', p)  # 外鍵用 p.id，整數用 p

        pval = _priority_value(priority)

        # 規則：金額優先(2)或數量優先(3) ⇒ 必須有結單時間
        if pval in (2, 3):
            if not end_time:
                self.add_error('end_time', '使用「金額/數量優先」分配時，必須設定結單時間。')
                print('金額/數量優先分配時，必須設定結單時間。')

        # 建議的合理性檢查：同時填了才檢查先後
        if start_time and end_time:
            if end_time <= start_time:
                self.add_error('end_time', '結單時間必須晚於開始時間。')
                print('結單時間必須晚於開始時間。')

    def save(self, commit=True):
        shop = super().save(commit=False)

        shop.start_time = timeFormatChange_now(shop.start_time)
        shop.end_time = timeFormatChange_longtime(shop.end_time)

        if self.user:
            shop.owner = self.user

        if commit:
            try:
                shop.save()
            except Exception as e:
                raise forms.ValidationError(f'商店儲存失敗：{e}')

            payment_ids = set(self.cleaned_data.get('payment_ids').values_list('id', flat=True))
            old_payment_ids = set(ShopPayment.objects.filter(shop=shop).values_list('payment_account_id', flat=True))
            if self.is_edit:
                for pid in payment_ids - old_payment_ids:
                    ShopPayment.objects.create(shop=shop, payment_account_id=pid)
                ShopPayment.objects.filter(shop=shop, payment_account_id__in=(old_payment_ids - payment_ids)).delete()
            else:
                for pid in payment_ids:
                    ShopPayment.objects.create(shop=shop, payment_account_id=pid)

            # 更新標籤
            tag_names = self.data.getlist('tag_names') if isinstance(self.data, (dict, QueryDict)) else []
            existing_tags = Tag.objects.filter(name__in=tag_names)
            existing_names = set(existing_tags.values_list('name', flat=True))
            new_names = set(tag_names) - existing_names
            new_tags = [Tag.objects.create(name=name) for name in new_names]
            all_tags = list(existing_tags) + new_tags

            if self.is_edit:
                ShopTag.objects.filter(shop=shop).exclude(tag__name__in=tag_names).delete()

            for tag in all_tags:
                ShopTag.objects.get_or_create(shop=shop, tag=tag)

        return shop

class ShopImgForm(forms.ModelForm):
    class Meta:
        model = ShopImg
        fields = ['img', 'is_cover']
        widgets = {
            'img': ClearableFileInput(attrs={'class': 'form-control'}),
        }

class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = ShopAnnouncement
        fields = ['title', 'announcement']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '想要公告什麼事嗎...? 點我開始輸入'}),
            'announcement': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': '公告內容'}),
        }
        labels = {
            'title': '標題',
            'announcement': '公告內容',
        }
