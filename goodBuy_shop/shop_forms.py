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
        required=False,  # 先設 False，在 clean() 裡自訂強制規則
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

        # 只允許 permission 顯示 id 1/2，並移除空白選項
        self.fields['permission'].queryset = Permission.objects.filter(id__in=[1, 2])
        self.fields['permission'].empty_label = None

        # shop_state / purchase_priority 也移除空白選項
        # （假設兩者是外鍵 ModelChoiceField；若是 IntegerField + choices 可忽略）
        if hasattr(self.fields['shop_state'], 'empty_label'):
            self.fields['shop_state'].empty_label = None
        if hasattr(self.fields['purchase_priority'], 'empty_label'):
            self.fields['purchase_priority'].empty_label = None

        # 預設值（僅建立時、生的 GET 顯示用；編輯或 POST 就不動）
        if not self.is_edit and not self.data:
            # 這裡假設三個 model 的 id=1 為你想要的預設
            # 若專案中預設不是 1，換成實際 id 或改成 .first()
            default_shop_state = getattr(ShopState.objects.filter(id=1).first(), 'id', None)
            default_priority = getattr(PurchasePriority.objects.filter(id=1).first(), 'id', None)
            default_permission = getattr(Permission.objects.filter(id=1).first(), 'id', None)

            if default_shop_state is not None:
                self.fields['shop_state'].initial = default_shop_state
            if default_priority is not None:
                self.fields['purchase_priority'].initial = default_priority
            if default_permission is not None:
                self.fields['permission'].initial = default_permission

        # 付款帳號清單
        if self.user:
            user_accounts = PaymentAccount.objects.filter(user=self.user, is_delete=False)

            if self.is_edit:
                shop_account_ids = ShopPayment.objects.filter(
                    shop=self.instance
                ).values_list('payment_account_id', flat=True)
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

        # --- 1) 商店名稱不可為空（去空白）
        name = cleaned.get('name')
        if name is None or not str(name).strip():
            self.add_error('name', '商店名稱不可為空（不得全為空白）。')
        else:
            cleaned['name'] = str(name).strip()

        # --- 2) 至少選一種支援的付款方式
        payment_qs = cleaned.get('payment_ids')
        # ModelMultipleChoiceField 回來是 queryset-like；用 exists() / len 檢查都可
        if not payment_qs or payment_qs.count() == 0:
            self.add_error('payment_ids', '請至少選擇一種支援的付款方式。')

        # --- 3) 金額/數量優先 ⇒ 必須有結單時間；且 end > start
        start_time = cleaned.get('start_time')
        end_time   = cleaned.get('end_time')
        priority   = cleaned.get('purchase_priority')

        def _priority_value(p):
            if p is None:
                return None
            return getattr(p, 'id', p)  # 外鍵用 p.id，整數用 p

        pval = _priority_value(priority)

        if pval in (2, 3) and not end_time:
            self.add_error('end_time', '使用「金額/數量優先」分配時，必須設定結單時間。')

        if start_time and end_time and end_time <= start_time:
            self.add_error('end_time', '結單時間必須晚於開始時間。')

        return cleaned

    def save(self, commit=True):
        shop = super().save(commit=False)

        # 你原本的時間轉換
        shop.start_time = timeFormatChange_now(shop.start_time)
        if shop.end_time:   # 只有在使用者有輸入結束時間時才做轉換
            shop.end_time = timeFormatChange_longtime(shop.end_time)
        else:
            shop.end_time = None   # 沒輸入就存 NULL，代表永久商店

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
