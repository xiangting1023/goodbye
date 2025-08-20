from django import forms
from django.contrib.auth import authenticate , get_user_model
from goodBuy_web.models import *

#=============================
#登入驗證帳號密碼
#=============================
class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        u, p = cleaned.get('username'), cleaned.get('password')
        if not u or not p:
            return cleaned

        user = authenticate(username=u, password=p)
        if user is None:
            # 不分帳號/密碼錯
            self.add_error('password', '帳號或密碼錯誤')
        else:
            self.user = user
        return cleaned

User = get_user_model()

#=============================
#新帳號註冊（檢查唯一性 & 密碼一致性）
#=============================
class RegisterForm(forms.ModelForm):
    # 覆寫username
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class":"form-control", "placeholder":"用戶名稱（可留空）"})
    )
        
    password = forms.CharField(
        label="密碼",
        widget=forms.PasswordInput(attrs={"class":"form-control", "placeholder":"密碼"})
    )
    password2 = forms.CharField(
        label="確認密碼",
        widget=forms.PasswordInput(attrs={"class":"form-control", "placeholder":"再次輸入密碼"})
    )

    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class":"form-control", "placeholder":"用戶名稱（可留空）"}),
            "email": forms.EmailInput(attrs={"class":"form-control", "placeholder":"Email"}),
        }

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            raise forms.ValidationError("Email 不可為空")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("該電子郵件已被註冊")
        return email

    def clean(self):
        cleaned = super().clean()
        u = cleaned.get("username")
        email = cleaned.get("email")
        p1 = cleaned.get("password")
        p2 = cleaned.get("password2")

        # username 可留空 -> 用 email 前綴
        if not u and email:
            base = email.split("@")[0][:140]
            candidate = base
            i = 1
            # 防撞名：username 最長 150
            while User.objects.filter(username=candidate).exists():
                suffix = str(i)
                candidate = (base[:150-len(suffix)] if len(base) + len(suffix) > 150 else base) + suffix
                i += 1
            cleaned["username"] = candidate

        else:
            # 有填 username → 檢查唯一
            if u and User.objects.filter(username=u).exists():
                self.add_error("username", "該用戶名已被使用")
            cleaned["username"] = u  # 帶回 strip 後的值


        if u and User.objects.filter(username=u).exists():
            self.add_error("username", "該用戶名已被使用")

        if p1 or p2:
            if not p1 or not p2:
                self.add_error("password2", "請完整輸入密碼與確認密碼")
            elif p1 != p2:
                self.add_error("password2", "兩次輸入的密碼不相符")
        return cleaned

#=============================
#修改基本資料（避免重複）
#=============================
class UserBasicForm(forms.Form):
    username = forms.CharField(required=False)
    email = forms.EmailField(required=True)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)  # for unique check
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if self.user and User.objects.filter(email=email).exclude(id=self.user.id).exists():
            raise forms.ValidationError("此電子郵件已被使用")
        return email

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if username and self.user and User.objects.filter(username=username).exclude(id=self.user.id).exists():
            raise forms.ValidationError("此用戶名已被使用")
        return username

#=============================
#修改密碼（檢查兩次輸入一致性）
#=============================
class ChangePasswordForm(forms.Form):
    new_password = forms.CharField(required=False, widget=forms.PasswordInput)
    confirm_password = forms.CharField(required=False, widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_password")
        # 兩欄至少有一欄填，就要求兩欄都填且相同；兩欄都空＝不改密碼
        if p1 or p2:
            if not p1 or not p2:
                self.add_error("confirm_password", "請完整輸入新密碼與確認密碼")
            elif p1 != p2:
                self.add_error("confirm_password", "新密碼與確認密碼不一致")
        return cleaned

#=============================
#管理收件地址
#=============================
class AddressForm(forms.Form):
    name = forms.CharField(required=False)
    phone = forms.CharField(required=False)
    city = forms.ChoiceField(required=False, choices=UserAddress.ADDRESS_MODE_CHOICES)
    address = forms.CharField(required=False)
    
    #驗證電話號碼 不知道目前需不需要
    # def clean_phone(self):
    #     phone = (self.cleaned_data.get("phone") or "").strip()
    #     if phone and not re.match(r"^09\d{8}$", phone):
    #         raise forms.ValidationError("手機格式需為 09 開頭共 10 碼")
    #     return phone