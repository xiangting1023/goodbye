# @csrf_exempt
# def crop_image_api(request):
#     if request.method == "POST" and request.FILES.get("image"):
#         # 取得圖片
#         image_file = request.FILES["image"]
#         # 儲存資料夾
#         filename = f"{uuid.uuid4().hex[:8]}.jpg"
#         save_path = os.path.join(settings.MEDIA_ROOT,"cropped", filename)
#         # 將圖片一塊一塊存到 save_path 路徑
#         with open(save_path, "wb") as f:
#             for chunk in image_file.chunks():
#                 f.write(chunk)

#         # 裁切完的圖片會存到 /media/upload/cropped/
#         output_folder = os.path.join(settings.MEDIA_ROOT, "cropped")
#         os.makedirs(output_folder, exist_ok=True)
#         # 呼叫裁切
#         cropped_names = crop_detected_objects(save_path, output_folder)
#         # 回傳給前端js
#         return JsonResponse({"success": True, "images": cropped_names})
#      # 回傳給前端js
#     return JsonResponse({"success": False, "error": "Invalid request"})