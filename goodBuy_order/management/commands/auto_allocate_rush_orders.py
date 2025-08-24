from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from collections import defaultdict

from goodBuy_shop.models import Shop
from goodBuy_order.models import Order, ProductOrder
from ...rush_utils import get_rush_summaries

ORDER_STATE_INIT = 1
PAY_STATE_UNPAID = 1

'''
dry run test
python manage.py auto_allocate_rush_orders --dry-run

只看特定商店
python manage.py auto_allocate_rush_orders --dry-run --shop 123

'''

class Command(BaseCommand):
    help = "自動分配多帶商店的訂單（截止）"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='只預覽分配結果，不寫入資料庫')
        parser.add_argument('--shop', type=int, help='只處理特定 shop_id')

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options.get('dry_run', False)
        only_shop = options.get('shop')

        shops = Shop.objects.filter(
            purchase_priority_id__in=[2, 3],  # 金額/數量優先
            end_time__lt=now,                 # 已截止
            is_rush_settled=False             # 尚未結算
        ).order_by('id')

        if only_shop:
            shops = shops.filter(id=only_shop)

        if not shops.exists():
            self.stdout.write(self.style.WARNING('沒有需要處理的商店。'))
            return

        mode = 'DRY-RUN（不寫入）' if dry_run else '正式結算'
        # 若你的 Django 版本沒有 NOTICE，可改用 SUCCESS 或 WARNING
        self.stdout.write(self.style.SUCCESS(f'開始執行：{mode}，共 {shops.count()} 間商店\n'))

        for shop in shops:
            try:
                self.stdout.write(self.style.SUCCESS(f'==> 處理商店：{shop.id} - {shop.name}'))
                if dry_run:
                    self.dry_run_shop(shop)
                else:
                    self.allocate_shop(shop)
                self.stdout.write(self.style.SUCCESS(f'完成：{shop.id} - {shop.name}\n'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'處理商店 {shop.id} 失敗：{e}\n'))
                # 不中斷後續商店

    # ----- 工具：容錯取得 product / quantity -----
    @staticmethod
    def _to_prod_qty(ip):
        """
        讓這支指令同時支援：
        - namedtuple(product, quantity)
        - 物件 .product / .quantity
        - 字典 {'product':..., 'quantity':...}
        """
        if isinstance(ip, dict):
            return ip['product'], int(ip['quantity'])
        # namedtuple / dataclass 可能有屬性
        p = getattr(ip, 'product', None) or (ip[0] if isinstance(ip, tuple) else None)
        q = getattr(ip, 'quantity', None) or (ip[1] if isinstance(ip, tuple) else 0)
        return p, int(q or 0)

    # -------------------------
    # Dry-run：只計算與列印，不寫入
    # -------------------------
    def dry_run_shop(self, shop):
        summaries = get_rush_summaries(shop)  # 已含排序與 cutoff
        product_claimed = defaultdict(int)
        product_stock = {}

        # 收集初始庫存（顯示用）
        for s in summaries:
            for ip in s['products']:
                p, _ = self._to_prod_qty(ip)
                product_stock[p.id] = getattr(p, 'stock', 0)

        total_orders = 0
        total_items = 0
        total_amount = 0

        # 顯示排序關鍵：模式與達標時間
        mode_text = '金額優先' if shop.purchase_priority_id == 2 else '數量優先'
        self.stdout.write(self.style.WARNING(f'[排序模式] {mode_text}'))
        self.stdout.write(self.style.WARNING('（同值時，以最早達到該總額/總量的時間決勝）\n'))

        for s in summaries:
            user = s['user']
            username = getattr(getattr(user, 'profile', None), 'nickname', None) or getattr(user, 'username', user.id)
            key_val = s['total_price'] if shop.purchase_priority_id == 2 else s['total_quantity']
            reached_at = s['reached_amount_at'] if shop.purchase_priority_id == 2 else s['reached_qty_at']
            self.stdout.write(self.style.SUCCESS(f'  使用者 {username}｜主鍵={key_val}｜達標時間={reached_at}'))

            lines = []
            user_total = 0
            for ip in s['products']:
                p, want_qty = self._to_prod_qty(ip)
                available = max(0, product_stock[p.id] - product_claimed[p.id])
                claim_qty = min(want_qty, available)

                if claim_qty > 0:
                    lines.append(f'    - 商品#{p.id} {p.name} x {claim_qty} @ {p.price} = {p.price * claim_qty}')
                    product_claimed[p.id] += claim_qty
                    user_total += p.price * claim_qty
                    total_items += claim_qty

            if user_total > 0:
                total_orders += 1
                total_amount += user_total
                for ln in lines:
                    self.stdout.write(ln)

        # 剩餘庫存概覽
        self.stdout.write(self.style.WARNING('\n商品剩餘庫存：'))
        for pid, stk in product_stock.items():
            remain = stk - product_claimed[pid]
            self.stdout.write(f'  商品#{pid} 已分配 {product_claimed[pid]}，剩餘 {remain}')

        self.stdout.write(self.style.WARNING(
            f'\n[DRY-RUN 統計] 建立訂單數：{total_orders}，分配件數：{total_items}，總金額：{total_amount}\n'
        ))

    # -------------------------
    # 正式結算：寫入資料庫（含鎖定與防重複）
    # -------------------------
    def allocate_shop(self, shop):
        summaries = get_rush_summaries(shop)

        with transaction.atomic():
            # 鎖住該商店，避免多 worker 併發
            locked_shop = Shop.objects.select_for_update().get(pk=shop.pk)
            if locked_shop.is_rush_settled:
                return

            product_claimed = defaultdict(int)
            product_orders_bulk = []

            for s in summaries:
                user = s['user']
                order = Order.objects.create(
                    user=user,
                    shop=locked_shop,
                    total=0,
                    payment_mode='full',
                    pay_state_id=PAY_STATE_UNPAID,
                    order_state_id=ORDER_STATE_INIT,
                )

                total_price = 0
                for ip in s['products']:
                    p, want_qty = self._to_prod_qty(ip)
                    available = max(0, p.stock - product_claimed[p.id])
                    claim_qty = min(want_qty, available)
                    if claim_qty <= 0:
                        continue

                    product_orders_bulk.append(ProductOrder(
                        order=order,
                        product=p,
                        amount=claim_qty,
                        product_name=p.name,
                        product_price=p.price,
                        product_img=(p.img.name if getattr(p, 'img', None) else ''),
                    ))
                    product_claimed[p.id] += claim_qty
                    total_price += p.price * claim_qty

                if total_price == 0:
                    order.delete()
                else:
                    order.total = total_price
                    order.save(update_fields=['total'])

            if product_orders_bulk:
                ProductOrder.objects.bulk_create(product_orders_bulk, batch_size=1000)

            # 切回時間序 + 標記已結算
            locked_shop.purchase_priority_id = 1
            locked_shop.is_rush_settled = True
            locked_shop.save(update_fields=['purchase_priority_id', 'is_rush_settled'])
