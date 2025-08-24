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
    city_choices = UserAddress.ADDRESS_MODE_CHOICES
    user_address = UserAddress.active.filter(user=user).first()

    # default值 檢測GET 或 驗證失敗回填
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
        user_form = UserBasicForm(request.POST, user=user)
        pwd_form = ChangePasswordForm(request.POST)
        addr_form = AddressForm(request.POST)

        # 驗證三個 form
        is_ok = user_form.is_valid() and pwd_form.is_valid() and addr_form.is_valid()

        if not is_ok:
            # 驗證失敗的話返回原頁面 render，帶著 form
            return render(request, "common/edit_profile.html", {
                "user_form": user_form,
                "pwd_form": pwd_form,
                "addr_form": addr_form,
                "city_choices": city_choices,
                "user_address": user_address,
                "accounts": PaymentAccount.active.filter(user=user),
            })

        # 驗證後寫入資料
        # User: email / username
        email = user_form.cleaned_data["email"].strip()
        username = (user_form.cleaned_data["username"] or "").strip()
        user.email = email
        if username:
            user.username = username
        user.save()

        # Password（兩欄都填才改）
        new_password = pwd_form.cleaned_data.get("new_password") or ""
        confirm_password = pwd_form.cleaned_data.get("confirm_password") or ""
        if new_password and confirm_password:
            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)  # 不要登出

        # Profile：暱稱 / 自介 / 頭像
        profile.nickname = request.POST.get("nickname", "") or ""
        profile.bio = request.POST.get("bio", "") or ""
        if "avatar" in request.FILES:
            profile.avatar = request.FILES["avatar"]
        profile.save()

        # Address：建立或更新
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

    # 第一次進來
    user_form = UserBasicForm(initial=initial_user, user=user)
    pwd_form = ChangePasswordForm()
    addr_form = AddressForm(initial=initial_addr)

    return render(request, "common/edit_profile.html", {
        "user_form": user_form,
        "pwd_form": pwd_form,
        "addr_form": addr_form,
        "city_choices": city_choices,
        "user_address": user_address,
        "accounts": PaymentAccount.active.filter(user=user),
    })