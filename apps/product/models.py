from django.db import models
from django.core.validators import MinValueValidator
from django.utils.text import slugify


# ======================================================================
# Category - دسته‌بندی
# ======================================================================
class Category(models.Model):
    name = models.CharField(max_length=150, verbose_name="نام دسته‌بندی")
    code = models.CharField(max_length=50, unique=True, verbose_name="کد دسته‌بندی")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "دسته‌بندی کالا"
        verbose_name_plural = "دسته‌بندی کالاها"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        super().save(*args, **kwargs)

    def generate_code(self):
        last_category = Category.objects.all().order_by('-id').first()
        if last_category and last_category.code:
            try:
                if last_category.code.startswith('CAT_'):
                    last_number = int(last_category.code.split('_')[1])
                    next_number = last_number + 1
                else:
                    next_number = 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1

        code = f'CAT_{next_number}'
        while Category.objects.filter(code=code).exclude(pk=self.pk).exists():
            next_number += 1
            code = f'CAT_{next_number}'
        return code

    # ✅ NEW: Soft-delete helpers
    def can_be_deleted(self):
        """
        فقط دسته‌بندی‌های بدون کالا قابل حذف هستند.
        اگر کالا دارد، باید غیرفعال شود یا کالاها منتقل شوند.
        """
        return not self.products.exists()

    def products_count(self):
        return self.products.count()


# ======================================================================
# Product - کالا
# ======================================================================
class Product(models.Model):
    sku = models.CharField(max_length=100, unique=True, verbose_name="کد کالا / SKU")
    name = models.CharField(max_length=200, verbose_name="نام کالا")

    # ✅ PROTECT — deleting a category must NOT silently null all its products.
    #    User must first move products to another category, then delete.
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='products',
        verbose_name="دسته‌بندی"
    )

    description = models.TextField(blank=True, null=True, verbose_name="توضیحات")
    image = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name="عکس")

    UNIT_CHOICES = [
        ('number', 'عدد'),
        ('package', 'بسته'),
        ('carton', 'کارتن'),
        ('kg', 'کیلوگرام'),
        ('liter', 'لیتر'),
        ('meter', 'متر'),
    ]
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='number', verbose_name="واحد")

    # قیمت‌ها
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="قیمت خرید")
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="قیمت عمده")
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="قیمت فروش")

    # این دو فقط کش هستند و از Inventory پر می‌شوند
    shop_stock = models.IntegerField(default=0, verbose_name="موجودی دوکان")
    stock_stock = models.IntegerField(default=0, verbose_name="موجودی گدام")
    current_stock = models.IntegerField(default=0, verbose_name="موجودی کل")

    min_stock = models.IntegerField(default=0, verbose_name="حداقل موجودی")

    STATUS_CHOICES = [
        ('active', 'فعال'),
        ('inactive', 'غیرفعال'),
        ('out_of_stock', 'ناموجود'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="وضعیت")

    # ✅ Soft delete flag — never actually hard-delete products with history
    is_deleted = models.BooleanField(default=False, verbose_name="حذف شده")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_purchase_date = models.DateTimeField(blank=True, null=True, verbose_name="تاریخ آخرین خرید")
    last_sale_date = models.DateTimeField(blank=True, null=True, verbose_name="تاریخ آخرین فروش")

    class Meta:
        verbose_name = "کالا"
        verbose_name_plural = "کالاها"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = self.generate_sku()

        self.current_stock = self.shop_stock + self.stock_stock

        if self.current_stock <= 0:
            self.status = 'out_of_stock'
        elif self.status == 'out_of_stock' and self.current_stock > 0:
            self.status = 'active'

        super().save(*args, **kwargs)

    def generate_sku(self):
        last_product = Product.objects.all().order_by('-id').first()
        if last_product and last_product.sku:
            try:
                if last_product.sku.startswith('SKU_'):
                    last_number = int(last_product.sku.split('_')[1])
                    next_number = last_number + 1
                else:
                    next_number = 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1

        sku = f'SKU_{next_number}'
        while Product.objects.filter(sku=sku).exclude(pk=self.pk).exists():
            next_number += 1
            sku = f'SKU_{next_number}'
        return sku

    # ==================================================================
    # ✅ NEW: Safe-delete helpers
    # ==================================================================
    def can_be_deleted(self):
        """
        فقط کالایی که هیچ حرکت انبار و هیچ فروش/خریدی ندارد قابل حذف است.
        در غیر این صورت باید «غیرفعال» (inactive) شود.
        """
        from apps.stock.models import StockMovement
        has_movements = StockMovement.objects.filter(product=self).exists()

        # اگر StockMovement دارد، اصلاً نباید حذف شود
        if has_movements:
            return False

        # اگر موجودی دارد
        if self.current_stock > 0:
            return False

        return True

    def soft_delete(self):
        """غیرفعال کردن کالا بدون حذف فیزیکی"""
        self.is_deleted = True
        self.status = 'inactive'
        self.save(update_fields=['is_deleted', 'status', 'updated_at'])

    def restore(self):
        """بازگرداندن کالای حذف‌شده"""
        self.is_deleted = False
        self.status = 'active' if self.current_stock > 0 else 'out_of_stock'
        self.save(update_fields=['is_deleted', 'status', 'updated_at'])

    # ==================================================================
    # Helper: همه عملیات از مسیر StockMovement می‌رود
    # ==================================================================
    def _adjust_inventory(self, location_code, delta, movement_type):
        """یک حرکت روی Inventory ثبت می‌کند و کش Product را به‌روز می‌کند."""
        from apps.stock.models import Location, StockMovement

        loc, _ = Location.objects.get_or_create(
            code=location_code,
            defaults={
                'name': 'دوکان' if location_code == 'shop' else f'گدام {location_code}',
                'type': 'shop' if location_code == 'shop' else 'warehouse',
            }
        )
        StockMovement.objects.create(
            product=self,
            location=loc,
            movement_type=movement_type,
            quantity=delta,
        )
        self.refresh_from_db()

    # ------------------------------------------------------------------
    # عملیات دوکان
    # ------------------------------------------------------------------
    def add_to_shop(self, quantity):
        """افزودن به دوکان"""
        self._adjust_inventory('shop', +quantity, 'IN')

    def remove_from_shop(self, quantity):
        """کاهش از دوکان"""
        # ✅ Re-read the *actual* stock from Inventory (avoids stale cache)
        current_shop = self.stock_in_code('shop')
        if quantity > current_shop:
            raise ValueError(f'موجودی دوکان کافی نیست! موجودی: {current_shop}')
        self._adjust_inventory('shop', -quantity, 'OUT')

    # ------------------------------------------------------------------
    # عملیات گدام
    # ------------------------------------------------------------------
    def add_to_stock(self, quantity, location_code='A'):
        """افزودن به یک گدام مشخص (پیش‌فرض: A)"""
        self._adjust_inventory(location_code, +quantity, 'IN')

    def remove_from_stock(self, quantity, location_code='A'):
        """کاهش از یک گدام مشخص"""
        # ✅ Re-read actual stock from Inventory
        available = self.stock_in_code(location_code)
        if quantity > available:
            raise ValueError(f'موجودی گدام {location_code} کافی نیست! موجودی: {available}')
        self._adjust_inventory(location_code, -quantity, 'OUT')

    # ------------------------------------------------------------------
    # انتقال‌ها
    # ------------------------------------------------------------------
    def transfer_stock_to_shop(self, quantity, from_location_code='A'):
        """انتقال از یک گدام به دوکان"""
        from django.db import transaction
        from apps.stock.models import Location, StockMovement

        available = self.stock_in_code(from_location_code)
        if quantity > available:
            raise ValueError(f'موجودی گدام {from_location_code} کافی نیست! موجودی: {available}')

        src = Location.objects.get(code=from_location_code)
        shop = Location.objects.get(code='shop')

        with transaction.atomic():
            StockMovement.objects.create(
                product=self, location=src, movement_type='OUT',
                quantity=-quantity, note='انتقال به دوکان'
            )
            StockMovement.objects.create(
                product=self, location=shop, movement_type='IN',
                quantity=+quantity, note=f'انتقال از گدام {from_location_code}'
            )
        self.refresh_from_db()

    def transfer_shop_to_stock(self, quantity, to_location_code='A'):
        """انتقال از دوکان به یک گدام"""
        from django.db import transaction
        from apps.stock.models import Location, StockMovement

        current_shop = self.stock_in_code('shop')
        if quantity > current_shop:
            raise ValueError(f'موجودی دوکان کافی نیست! موجودی: {current_shop}')

        shop = Location.objects.get(code='shop')
        dst = Location.objects.get(code=to_location_code)

        with transaction.atomic():
            StockMovement.objects.create(
                product=self, location=shop, movement_type='OUT',
                quantity=-quantity, note=f'انتقال به گدام {to_location_code}'
            )
            StockMovement.objects.create(
                product=self, location=dst, movement_type='IN',
                quantity=+quantity, note='انتقال از دوکان'
            )
        self.refresh_from_db()

    def transfer_between_warehouses(self, quantity, from_code, to_code):
        """انتقال بین دو گدام"""
        from django.db import transaction
        from apps.stock.models import Location, StockMovement

        available = self.stock_in_code(from_code)
        if quantity > available:
            raise ValueError(f'موجودی گدام {from_code} کافی نیست! موجودی: {available}')

        src = Location.objects.get(code=from_code)
        dst = Location.objects.get(code=to_code)

        with transaction.atomic():
            StockMovement.objects.create(
                product=self, location=src, movement_type='OUT',
                quantity=-quantity, note=f'انتقال به گدام {to_code}'
            )
            StockMovement.objects.create(
                product=self, location=dst, movement_type='IN',
                quantity=+quantity, note=f'انتقال از گدام {from_code}'
            )
        self.refresh_from_db()

    # ------------------------------------------------------------------
    # خواندن موجودی هر موقعیت
    # ------------------------------------------------------------------
    def stock_in_code(self, location_code):
        """موجودی این کالا در یک موقعیت با کد"""
        inv = self.inventories.filter(location__code=location_code).first()
        return inv.quantity if inv else 0

    def stock_in(self, location):
        """موجودی این کالا در یک موقعیت (شیء Location)"""
        inv = self.inventories.filter(location=location).first()
        return inv.quantity if inv else 0

    def warehouse_breakdown(self):
        """جزئیات موجودی همه گدام‌ها"""
        return list(
            self.inventories.filter(location__type='warehouse')
            .select_related('location')
            .values('location__code', 'location__name', 'quantity')
        )

    def movement_history(self):
        """تاریخچه حرکت این کالا"""
        return self.stock_movements.select_related(
            'location', 'created_by'
        ).order_by('-created_at')

    # ------------------------------------------------------------------
    # property
    # ------------------------------------------------------------------
    @property
    def total_warehouse(self):
        return self.stock_stock

    @property
    def is_low_stock(self):
        return self.current_stock <= self.min_stock

    @property
    def is_out_of_stock(self):
        return self.current_stock <= 0

    @property
    def shop_is_low(self):
        return self.shop_stock <= self.min_stock

    @property
    def stock_is_low(self):
        return self.stock_stock <= self.min_stock
