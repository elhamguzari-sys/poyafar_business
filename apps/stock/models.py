from django.db import models, transaction
from django.utils import timezone
from apps.product.models import Product


# ======================================================================
# Location
# ======================================================================
class Location(models.Model):
    LOCATION_TYPES = [
        ('shop', 'دوکان'),
        ('warehouse', 'گدام'),
    ]

    name = models.CharField(max_length=100, verbose_name="نام")
    code = models.CharField(max_length=10, unique=True, verbose_name="کد")
    type = models.CharField(max_length=20, choices=LOCATION_TYPES, verbose_name="نوع")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "موقعیت"
        verbose_name_plural = "موقعیت‌ها"
        ordering = ['type', 'code']

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def total_quantity(self):
        """جمع موجودی این موقعیت در همه کالاها"""
        return self.inventories.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0

    @property
    def product_count(self):
        """تعداد کالاهای موجود در این موقعیت"""
        return self.inventories.filter(quantity__gt=0).count()

    # ✅ NEW: Guard against deleting a location with stock
    def can_be_deleted(self):
        """
        فقط موقعیت‌هایی که هیچ موجودی و هیچ حرکت کالایی ندارند قابل حذف هستند.
        در غیر این صورت باید غیرفعال (is_active=False) شوند.
        """
        has_inventory = self.inventories.filter(quantity__ne=0).exists() \
            if hasattr(models.Q, 'quantity__ne') else \
            self.inventories.exclude(quantity=0).exists()

        if has_inventory:
            return False

        # اگر StockMovement دارد، نباید حذف شود
        if self.stock_movements.exists():
            return False

        return True

    def deactivate(self):
        """غیرفعال کردن موقعیت بدون حذف"""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    def activate(self):
        """فعال کردن موقعیت"""
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])


# ======================================================================
# Inventory
# ======================================================================
class Inventory(models.Model):
    # ✅ PROTECT — deleting a product must NOT silently wipe its inventory rows.
    #    Use Product.soft_delete() instead.
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        related_name='inventories', verbose_name="کالا"
    )

    # ✅ PROTECT — deleting a location must NOT silently wipe its inventory rows.
    #    Use Location.deactivate() instead, or move stock first.
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT,
        related_name='inventories', verbose_name="موقعیت"
    )

    quantity = models.IntegerField(default=0, verbose_name="موجودی")
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        unique_together = ('product', 'location')
        verbose_name = "موجودی"
        verbose_name_plural = "موجودی‌ها"

    def __str__(self):
        return f"{self.product.name} @ {self.location.code}: {self.quantity}"

    @property
    def is_low(self):
        return self.quantity <= self.product.min_stock

    @property
    def is_out(self):
        return self.quantity <= 0


# ======================================================================
# StockMovement
# ======================================================================
class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ('IN', 'ورود کالا'),
        ('OUT', 'خروج کالا'),
    ]

    # ✅ PROTECT — never delete a product by cascading its movement history.
    #    Movement history is the audit trail of the entire system.
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        related_name='stock_movements', verbose_name="کالا"
    )

    # ✅ Already PROTECT — correct.
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT,
        related_name='stock_movements', verbose_name="موقعیت"
    )

    movement_type = models.CharField(
        max_length=20, choices=MOVEMENT_TYPES, verbose_name="نوع حرکت"
    )
    quantity = models.IntegerField(
        verbose_name="تعداد",
        help_text="مثبت برای ورود، منفی برای خروج"
    )
    stock_after_movement = models.IntegerField(
        null=True, blank=True, verbose_name="موجودی بعد از حرکت"
    )
    reference_number = models.CharField(
        max_length=100, unique=True, blank=True, verbose_name="شماره مرجع"
    )
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True,
        related_name='stock_movements', verbose_name="ثبت شده توسط"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")

    class Meta:
        verbose_name = "حرکت کالا"
        verbose_name_plural = "حرکات کالا"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', 'created_at']),
            models.Index(fields=['location', 'created_at']),
            models.Index(fields=['movement_type']),
        ]

    def __str__(self):
        return f"{self.reference_number} - {self.product.name} - {self.location.code} ({self.quantity})"

    # ----------------------------------------------------------------
    # Reference number
    # ----------------------------------------------------------------
    def generate_reference_number(self):
        last = StockMovement.objects.all().order_by('-id').first()
        if last and last.reference_number and last.reference_number.startswith('REF_'):
            try:
                next_number = int(last.reference_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1

        reference = f'REF_{next_number}'
        while StockMovement.objects.filter(reference_number=reference).exists():
            next_number += 1
            reference = f'REF_{next_number}'
        return reference

    # ----------------------------------------------------------------
    # ✅ NEW: Detect if this movement is a transfer (part of a pair)
    #    Transfers are: OUT from source + IN to destination, with matching note.
    #    They should NOT touch last_purchase_date / last_sale_date.
    # ----------------------------------------------------------------
    def _is_transfer(self):
        if not self.note:
            return False
        transfer_keywords = (
            'انتقال',
            'انتقال به دوکان',
            'انتقال از دوکان',
            'انتقال به گدام',
            'انتقال از گدام',
        )
        return any(kw in self.note for kw in transfer_keywords)

    # ----------------------------------------------------------------
    # Core: apply on Inventory + sync Product cache
    # ----------------------------------------------------------------
    def _apply(self, location, quantity):
        with transaction.atomic():
            inv, _ = Inventory.objects.select_for_update().get_or_create(
                product=self.product, location=location
            )
            inv.quantity += quantity
            inv.save()

            self.stock_after_movement = inv.quantity

            self._sync_product_cache()

            # ✅ Only touch last_purchase/last_sale if NOT a transfer
            if not self._is_transfer():
                if self.movement_type == 'IN':
                    self.product.last_purchase_date = timezone.now()
                elif self.movement_type == 'OUT':
                    self.product.last_sale_date = timezone.now()
                self.product.save()
            else:
                # For transfers, still save the cache update but don't change dates
                self.product.save(update_fields=[
                    'shop_stock', 'stock_stock', 'current_stock', 'status', 'updated_at'
                ])

    def _sync_product_cache(self):
        shop_qty = self.product.inventories.filter(
            location__type='shop'
        ).aggregate(t=models.Sum('quantity'))['t'] or 0

        warehouse_qty = self.product.inventories.filter(
            location__type='warehouse'
        ).aggregate(t=models.Sum('quantity'))['t'] or 0

        self.product.shop_stock = shop_qty
        self.product.stock_stock = warehouse_qty
        self.product.current_stock = shop_qty + warehouse_qty

        if self.product.current_stock <= 0:
            self.product.status = 'out_of_stock'
        else:
            self.product.status = 'active'

    # ----------------------------------------------------------------
    # ✅ NEW: recompute product's last_purchase_date / last_sale_date
    #    after a movement is deleted. This prevents stale dates.
    # ----------------------------------------------------------------
    def _recompute_product_dates(self):
        """
        بازمحاسبه تاریخ آخرین خرید/فروش بر اساس حرکات باقی‌مانده
        (فقط حرکاتی که انتقال نیستند).
        """
        # All IN movements (purchases), excluding transfers
        last_in = (
            StockMovement.objects
            .filter(product=self.product, movement_type='IN')
            .exclude(note__contains='انتقال')
            .order_by('-created_at')
            .first()
        )
        last_out = (
            StockMovement.objects
            .filter(product=self.product, movement_type='OUT')
            .exclude(note__contains='انتقال')
            .order_by('-created_at')
            .first()
        )

        self.product.last_purchase_date = last_in.created_at if last_in else None
        self.product.last_sale_date = last_out.created_at if last_out else None
        self.product.save(update_fields=['last_purchase_date', 'last_sale_date'])

    # ----------------------------------------------------------------
    # Save
    # ----------------------------------------------------------------
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            if not self.reference_number:
                self.reference_number = self.generate_reference_number()
            self._apply(self.location, self.quantity)
        else:
            old = StockMovement.objects.get(pk=self.pk)
            # Revert old effect, then apply new
            self._apply(old.location, -old.quantity)
            self._apply(self.location, self.quantity)

        super().save(*args, **kwargs)

    # ----------------------------------------------------------------
    # Delete
    # ----------------------------------------------------------------
    def delete(self, *args, **kwargs):
        # Revert the inventory effect
        self._apply(self.location, -self.quantity)

        # ✅ Recompute product dates based on remaining movements
        #    (prevents stale last_purchase_date / last_sale_date)
        product = self.product
        super().delete(*args, **kwargs)
        self._recompute_product_dates()

    # ----------------------------------------------------------------
    # ✅ NEW: Human-readable helpers
    # ----------------------------------------------------------------
    @property
    def is_transfer(self):
        return self._is_transfer()

    @property
    def is_purchase_related(self):
        return (
            self.movement_type == 'IN'
            and not self._is_transfer()
            and self.note
            and self.note.startswith('PURCHASE:')
        )

    @property
    def is_sale_related(self):
        return (
            self.movement_type == 'OUT'
            and not self._is_transfer()
            and self.note
            and self.note.startswith('SALE:')
        )

    @property
    def is_return_related(self):
        if not self.note:
            return False
        return (
            self.note.startswith('CUSTOMER_RETURN:')
            or self.note.startswith('SUPPLIER_RETURN:')
        )

    @property
    def is_waste_related(self):
        return bool(self.note and self.note.startswith('WASTE:'))