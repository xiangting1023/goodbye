#=============================
#舊檔在一些old cold保存 因為這邊大改我不確定腦袋燒了沒
#=============================

from django.shortcuts import *
from goodBuy_web.models import *
from django.contrib.auth import  authenticate,login,logout , update_session_auth_hash
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from ..forms import *

#=============================
#登入
#=============================
def logins(request):
    if request.user.is_active:
        return redirect('home')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password']
        )
        if user:
            login(request, user)
            return redirect('home')
        else:
            form.add_error(None, "帳號或密碼錯誤")

    return render(request, 'common/login.html', {'form': form})

#=============================
#註冊
#=============================
def register(request):
    if request.user.is_active:
        return redirect('home')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email    = form.cleaned_data['email']
            password = form.cleaned_data['password']

            User.objects.create_user(username=username, email=email, password=password)
            return redirect('login')
        # 失敗：直接 render，欄位下會顯示錯誤
        else:
            print("REGISTER ERRORS =>", form.errors)
        return render(request, 'common/register.html', {'form': form})

    # GET
    form = RegisterForm()
    return render(request, 'common/register.html', {'form': form})

#=============================
#登出
#=============================
def logouts(request):
    logout(request)
    return redirect('/')

#=============================
#修改密碼
#=============================
@login_required
def change_pass(request):
    form = ChangePasswordForm(request.POST or None, user=request.user)
    # if request.method == 'POST':
    # current_password = request.POST.get('current_password')
    # new_password = request.POST.get('new_password')
    # confirm_password = request.POST.get('confirm_password')

    if request.method == 'POST' and form.is_valid():
        new_password = form.cleaned_data['new_password'] 
        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, '密碼修改成功')
        return redirect('editprofile')  # 返回編輯個人資料頁面
    return render(request, 'common/change_pass.html', {'form': form})

#=============================
#更改個人檔案
#=============================
@login_required
def editProfile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    # 下拉選單縣市
    city_choices = getattr(UserAddress, "ADDRESS_MODE_CHOICES", [])

    # 目前使用者預設地址（可能為 None）
    user_address = getattr(UserAddress, "active", UserAddress.objects).filter(user=user).first()

    # 初始值
    initial_user = {
        "username": user.username or "",
        "email": user.email or "",
    }
    initial_addr = {
        "name": getattr(user_address, "name", "") if user_address else "",
        "phone": getattr(user_address, "phone", "") if user_address else "",
        "city": getattr(user_address, "city", "") if user_address else "",
        "address": getattr(user_address, "address", "") if user_address else "",
    }

    if request.method == "POST":
        # 1) 建立三張表單
        user_form = UserBasicForm(request.POST, user=user)
        pwd_form  = ChangePasswordForm(request.POST, user=request.user)

        # 把前端自定義欄位名稱映射成 AddressForm 需要的 name/phone/city/address
        data = request.POST.copy()
        mapping = [
            ("address_name", "name"),
            ("address_phone", "phone"),
            ("address_city", "city"),
            ("address_detail", "address"),
        ]
        for src, dst in mapping:
            if src in data and not data.get(dst):
                data[dst] = data[src]
        addr_form = AddressForm(data)

        # 2) 決定哪些表單需要驗證
        pwd_submitted = any((request.POST.get(k) or "").strip() for k in ["new_password", "confirm_password"])
        addr_submitted = any((data.get(k) or "").strip() for k in ["name", "phone", "city", "address"])

        user_ok = user_form.is_valid()
        pwd_ok  = (pwd_form.is_valid()  if pwd_submitted else True)
        addr_ok = (addr_form.is_valid() if addr_submitted else True)

        if not (user_ok and pwd_ok and addr_ok):
            return render(request, "common/edit_profile.html", {
                "user_form": user_form,
                "pwd_form": pwd_form,
                "addr_form": addr_form,
                "city_choices": city_choices,
                "user_address": user_address,
                "accounts": PaymentAccount.active.filter(user=user),
            })

        # 3) 寫入 User（email/username）
        email = (user_form.cleaned_data.get("email") or "").strip()
        username = (user_form.cleaned_data.get("username") or "").strip()
        user.email = email
        if username:
            user.username = username
        user.save()

        # 4) 寫入密碼（有輸入才變更）
        if pwd_submitted:
            old_password = pwd_form.cleaned_data.get("old_password") or ""
            new_password = pwd_form.cleaned_data.get("new_password") or ""
            confirm_password = pwd_form.cleaned_data.get("confirm_password") or ""
            if old_password and new_password and confirm_password:
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # 保持登入

        # 5) 寫入 Profile（暱稱/自介/頭像）
        profile.nickname = request.POST.get("nickname", "") or ""
        profile.bio = request.POST.get("bio", "") or ""
        if "avatar" in request.FILES:
            profile.avatar = request.FILES["avatar"]
        profile.save()

        # 6) 地址：有輸入才建立/更新
        if addr_submitted:
            name = addr_form.cleaned_data.get("name") or ""
            phone = addr_form.cleaned_data.get("phone") or ""
            city = addr_form.cleaned_data.get("city") or ""
            address_detail = addr_form.cleaned_data.get("address") or ""

            address, created = UserAddress.objects.get_or_create(
                user=user,
                is_delete=False,
                defaults={
                    "name": name,
                    "phone": phone,
                    "city": city,
                    "address": address_detail
                }
            )
            if not created:
                address.name = name
                address.phone = phone
                address.city = city
                address.address = address_detail
                address.save()

        messages.success(request, "已更新個人資料")
        return redirect("editprofile")

    # GET：建立表單（帶初始值）
    user_form = UserBasicForm(initial=initial_user, user=user)
    pwd_form  = ChangePasswordForm()
    addr_form = AddressForm(initial=initial_addr)

    return render(request, "common/edit_profile.html", {
        "user_form": user_form,
        "pwd_form": pwd_form,
        "addr_form": addr_form,
        "city_choices": city_choices,
        "user_address": user_address,
        "accounts": PaymentAccount.active.filter(user=user),
    })


