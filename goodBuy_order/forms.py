from django import forms
from django.core.exceptions import ValidationError

from goodBuy_order.models import OrderPayment, Comment
from goodBuy_shop.models import ShopPayment

# -------------------------
# 地址、付款方式選擇
# -------------------------
PAYMENT_KIND_BANK = 'bank'
PAYMENT_KIND_COD  = 'cod'  

class ChoosePaymentForm(forms.Form):
    payment_method = forms.ChoiceField(
        choices=[(PAYMENT_KIND_COD, '取貨付款'), (PAYMENT_KIND_BANK, '銀行匯款')],
        widget=forms.RadioSelect
    )
    payment_account = forms.ModelChoiceField(
        queryset=ShopPayment.objects.none(),  # 預設空 QuerySet
        required=False,
        empty_label=None,
        widget=forms.RadioSelect
    )

    def __init__(self, *args, shop=None, remittance_qs=None, **kwargs):
        """
        shop: 當前訂單所屬商店（目前僅做語意保留）
        remittance_qs: 該商店的「銀行匯款」ShopPayment 查詢集
        """
        super().__init__(*args, **kwargs)
        self.shop = shop
        self.remittance_qs = remittance_qs if remittance_qs is not None else ShopPayment.objects.none()
        self.fields['payment_account'].queryset = self.remittance_qs

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('payment_method')
        account = cleaned.get('payment_account')

        if method == PAYMENT_KIND_BANK:
            if not self.remittance_qs.exists():
                raise forms.ValidationError('此商店未設定銀行匯款帳戶')
            if not account:
                self.add_error('payment_account', '請選擇匯款帳戶')
            elif not self.remittance_qs.filter(pk=account.pk).exists():
                self.add_error('payment_account', '匯款帳戶無效')

        return cleaned
    
# -------------------------
# 上傳付款憑證
# -------------------------
class OrderPaymentForm(forms.ModelForm):

    payment_account = forms.ModelChoiceField(
        queryset=ShopPayment.objects.none(),
        label='匯款帳戶',
        required=True,
        error_messages={
            'required': '請選擇匯款帳戶',
            'invalid_choice': '匯款帳戶無效',
        },
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = OrderPayment
        fields = ['payment_account', 'pay_proof', 'remark']
        widgets = {
            'pay_proof': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'remark': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '其他備註（可選）'
            }),
        }
        labels = {
            'pay_proof': '匯款憑證上傳',
            'remark': '備註',
        }

    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop('order', None)
        remit_accounts = kwargs.pop('remit_accounts', None)

        super().__init__(*args, **kwargs)

        if remit_accounts is not None:
            self.fields['payment_account'].queryset = remit_accounts
        else:
            self.fields['payment_account'].queryset = ShopPayment.objects.none()

    # ------ 單欄位驗證 ------

    def clean_payment_account(self):
        acct = self.cleaned_data.get('payment_account')
        if acct is None:
            raise ValidationError('請選擇匯款帳戶')
        return acct

    def clean_pay_proof(self):
        f = self.cleaned_data.get('pay_proof')
        if not f:
            raise ValidationError('請上傳匯款憑證')


        # （可選）檔案大小與副檔名/Content-Type 檢查
        max_mb = 5
        if f.size > max_mb * 1024 * 1024:
            raise ValidationError(f'檔案過大，請小於 {max_mb} MB')

        allowed_ct = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
        if getattr(f, 'content_type', None) not in allowed_ct:
            raise ValidationError('只接受 JPEG/PNG/GIF/WEBP 圖片')
        return f

    # ------ 儲存 ------
    def save(self, commit=True):
        if self.order is None:
            raise ValueError('OrderPaymentForm 需要傳入 order 參數')
        
        # 只呼叫一次 super().save
        instance: OrderPayment = super().save(commit=False)
        
        # 由後端決定金額
        instance.amount = self.order.first_amount
        instance.order = self.order
        instance.shop_payment = self.cleaned_data['payment_account']
        instance.is_paid_by_user = True
        instance.seller_state = 'wait_confirmed'

        if commit:
            instance.save()
        return instance
    
# -------------------------
# 二次補款金額設定
# -------------------------
class SecondSupplementForm(forms.Form):
    second_supplement = forms.IntegerField(
        required=True,
        min_value=0,
        label='補款金額',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '請輸入金額（元）'})
    )
# -------------------------
# 評論表單
# -------------------------
class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['rank', 'comment']
        widgets = {
            # 'rank': forms.HiddenInput(), 改點星星
            'rank': forms.NumberInput(attrs={'min': 1, 'max': 5, 'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'placeholder': '請留下您的評價'}),
        }
        labels = {
            'rank': '評分（1~5）',
            'comment': '評論內容'
        }
