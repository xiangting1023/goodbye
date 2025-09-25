import os
import shutil
import uuid

from django.db.models import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import *
from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from goodBuy_shop.models import *
from goodBuy_web.models import *
from utils import *
from ..shop_forms import *
from goodBuy_tag.models import Tag
from ..yolo_models.yolo_detect  import crop_detected_objects

# -------------------------
# 新增商店
# -------------------------
@login_required(login_url='login')
def add_shop(request):
    if not PaymentAccount.active.filter(user=request.user).exists():
        messages.error(request, "請先到「付款帳號管理」新增至少一組帳號，才能建立商店。")
        print("使用者沒有付款帳號，無法建立商店")
        return redirect("payment_accounts")
    
    form = ShopForm(request.POST or None, request.FILES or None, user=request.user)
    selected_images = request.session.get('final_selected_images', [])
    if request.method == 'POST':
        if form.is_valid():
            shop = form.save()

            #TAG
            #儲存標籤
            tag_names = request.POST.get('tag_names', '')
            for name in tag_names.split(','):
                name = name.strip()
                if name:
                    tag_obj, _ = Tag.objects.get_or_create(name=name)
                    ShopTag.objects.get_or_create(shop=shop, tag=tag_obj)
            #===

            # 封面圖片處理
            print("上傳圖片檔案們：", request.FILES.getlist('images'))
            images = request.FILES.getlist('images')
            cover_index_str = request.POST.get('cover_index')
            try:
                cover_index = int(cover_index_str)
            except (TypeError, ValueError):
                cover_index = -1
            order_str = request.POST.get('image_order')
            if order_str:
                order_list = list(map(int, order_str.split(',')))
                sorted_images = [images[i] for i in order_list if i < len(images)]
            else:
                sorted_images = images

            for idx, img in enumerate(sorted_images):
                ShopImg.objects.create(shop=shop, img=img, is_cover=(idx == cover_index), position=idx)

            for img_path in request.POST.getlist('selected_images'):
                src_path = os.path.join(settings.MEDIA_ROOT, img_path.replace('/', os.sep))
                filename = os.path.basename(img_path)
                target_rel_path = os.path.join('product', filename)
                dst_path = os.path.join(settings.MEDIA_ROOT, target_rel_path)

                os.makedirs(os.path.dirname(dst_path), exist_ok=True)

                if os.path.exists(src_path):
                    shutil.move(src_path, dst_path)
                    ShopImg.objects.create(shop=shop, img=target_rel_path)
                
            # 商品處理
            names = request.POST.getlist('product_name[]')
            prices = request.POST.getlist('product_price[]')
            qtys = request.POST.getlist('product_qty[]')

            # AI 切割圖路徑
            product_images = []
            image_names = request.POST.getlist('product_image_name[]')  

            for i in range(len(names)):
                uploaded = request.FILES.get(f'product_image_{i}')
                if uploaded:
                    product_images.append(uploaded)  # 使用者上傳的檔案
                elif i < len(image_names):
                    product_images.append(image_names[i])  # AI 切圖的相對路徑
                else:
                    product_images.append(None)  # 沒有圖    

            #原本只會存在 product_image_name[] 這個 hidden
            # product_images = []
            # for i in range(len(names)):
            #     product_images.append(request.FILES.get(f'product_image_{i}'))

            success_count = 0
            for i in range(len(names)):
                try:
                    if not names[i] or not prices[i] or not qtys[i]:
                        continue  # 跳過空白欄位
                    Product.objects.create(
                        shop=shop,
                        name=names[i],
                        price=prices[i],
                        stock=qtys[i],
                        amount=qtys[i],
                        img=product_images[i] if i < len(product_images) else None
                    )
                    success_count += 1
                except Exception as e:
                    print(f"商品新增失敗（第 {i+1} 筆）：{e}")
            
            request.session.pop('final_selected_images', None)
            messages.success(request, f'商店已建立，{success_count} 個商品成功新增。')
            return redirect('shop', shop_id=shop.id)
        else:
            print('表單驗證失敗:', form.errors)
            messages.error(request, '表單資料有誤')
    return render(request, 'add_shop.html', {'form': form, 'selected_images': selected_images})

# -------------------------
# 修改商店資訊（多個）
# -------------------------
@login_required(login_url='login')
@shop_owner_required
def edit_shop(request, shop):
    form = ShopForm(request.POST or None, request.FILES or None, instance=shop, user=request.user)

    if request.method == 'POST':
        if form.is_valid():
            shop = form.save(commit=False)
            shop.update = timezone.now()
            shop.save()

            #TAG
            # 清除原有的標籤
            ShopTag.objects.filter(shop=shop).delete()

            # 重新儲存選擇的標籤
            tag_names = request.POST.get('tag_names', '')
            for name in tag_names.split(','):
                name = name.strip()
                if name:
                    tag_obj, _ = Tag.objects.get_or_create(name=name)
                    ShopTag.objects.get_or_create(shop=shop, tag=tag_obj)
            #===
            
            # 封面圖片處理（只有有上傳才刪掉重建）
            images = request.FILES.getlist('images')
            if images:
                shop.images.all().delete()

                cover_index_raw = request.POST.get('cover_index')
                cover_index = int(cover_index_raw) if cover_index_raw and cover_index_raw.isdigit() else 0
                order_str = request.POST.get('image_order')
                if order_str:
                    order_list = list(map(int, order_str.split(',')))
                    sorted_images = [images[i] for i in order_list if i < len(images)]
                else:
                    sorted_images = images

                for idx, img in enumerate(sorted_images):
                    ShopImg.objects.create(
                        shop=shop,
                        img=img,
                        is_cover=(idx == cover_index),
                        position=idx
                    )

            # 商品處理
            names = request.POST.getlist('product_name[]')
            prices = request.POST.getlist('product_price[]')
            qtys = request.POST.getlist('product_qty[]')

            # AI 切割圖路徑
            product_images = []
            image_names = request.POST.getlist('product_image_name[]')  

            for i in range(len(names)):
                uploaded = request.FILES.get(f'product_image_{i}')
                if uploaded:
                    product_images.append(uploaded)  # 使用者上傳的檔案
                elif i < len(image_names):
                    product_images.append(image_names[i])  # AI 切圖的相對路徑
                else:
                    product_images.append(None)  # 沒有圖

            # product_images = []
            # for i in range(len(names)):
            #     product_images.append(request.FILES.get(f'product_image_{i}'))

            old_products = list(shop.product_set.filter(is_delete=False))
            shop.product_set.filter(is_delete=False).update(is_delete=True)

            for i in range(len(names)):
                try:
                    if not names[i] or not prices[i] or not qtys[i]:
                        continue

                    product = Product(
                        shop=shop,
                        name=names[i],
                        price=prices[i],
                        stock=qtys[i],
                        amount=qtys[i],
                    )

                    if i < len(product_images) and product_images[i]:
                        product.img = product_images[i]
                    elif i < len(old_products):
                        product.img = old_products[i].img

                    product.save()
                except Exception as e:
                    print(f"商品第 {i+1} 筆新增失敗：{e}")

            messages.success(request, '商店資訊修改成功')
            return redirect('shop', shop_id=shop.id)
        else:
            messages.error(request, '表單資料有誤')

    return render(request, 'edit_shop.html', {
        'form': form,
        'shop': shop,
        'predefined_tags': Tag.objects.values_list('name', flat=True),
        'selected_tags': shop.shoptag_set.values_list('tag__name', flat=True),
        'products': shop.product_set.filter(is_delete=False),
        'shop_images': shop.images.all(),
    })

# -------------------------
# 刪除商店（軟刪除）
# -------------------------
@login_required(login_url='login')
@shop_owner_required
def deleteShop(request, shop):
    has_unfinished_orders = Order.objects.filter(shop=shop, order_state__in=[1,2,3,4,5]).exists()

    if has_unfinished_orders:
        messages.error(request, '賣場有未完成訂單，無法刪除。請先當前訂單。')
        return redirect('shop', shop_id=shop.id)

    shop.permission = Permission.objects.get(id=3)
    shop.save()
    messages.success(request, '賣場已刪除')
    return redirect('view_profile', user_id=shop.owner.id)

# -------------------------
# 商店刪除圖片
# -------------------------
@login_required(login_url='login')
@shop_owner_required
def delete_shop_image(request, shop, image_id):
    image = get_object_or_404(ShopImg, id=image_id, shop=shop)
    image.delete()
    messages.success(request, '圖片已刪除')
    return redirect('shop_edit', shop_id=shop.id)

# -------------------------
# 重新設定封面
# -------------------------
@login_required(login_url='login')
@shop_owner_required
def set_cover_image(request, shop, image_id):
    ShopImg.objects.filter(shop=shop).update(is_cover=False)
    ShopImg.objects.filter(id=image_id, shop=shop).update(is_cover=True)
    messages.success(request, '封面已更新')
    return redirect('shop_edit', shop_id=shop.id)

# -------------------------
# 前端需要 - 前端直接呼叫裁切並自動填資料
# -------------------------
@csrf_exempt
def crop_image_api(request):
    if request.method == "POST" and request.FILES.get("image"):
        # 取得圖片
        image_file = request.FILES["image"]

        # 建立儲存資料夾（upload/crop/user_{id}/）
        user_folder = f"user_{request.user.id if request.user.is_authenticated else 'temp'}"
        crop_folder = os.path.join(settings.MEDIA_ROOT, "crop", user_folder)
        cropped_folder = os.path.join(settings.MEDIA_ROOT, "cropped", user_folder)

        os.makedirs(crop_folder, exist_ok=True)
        os.makedirs(cropped_folder, exist_ok=True)

        # 儲存資料夾
        filename = f"{uuid.uuid4().hex[:8]}.jpg"
        save_path = os.path.join(crop_folder, filename)
        # 將圖片一塊一塊存到 save_path 路徑
        with open(save_path, "wb") as f:
            for chunk in image_file.chunks():
                f.write(chunk)

        # 呼叫裁切
        cropped_names = crop_detected_objects(save_path, cropped_folder)

        # 將路徑轉成相對於 MEDIA_URL 的路徑（回傳給前端）
        adjusted_paths = [
            os.path.join("cropped", user_folder, os.path.basename(name)).replace("\\", "/")
            for name in cropped_names
        ]

        # 回傳給前端js
        return JsonResponse({"success": True, "images": adjusted_paths})
     # 回傳給前端js
    return JsonResponse({"success": False, "error": "Invalid request"})