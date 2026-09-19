# apps/purchasesale/models.py

from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from django.core.exceptions import ValidationError
import os

from apps.product.models import Product
from apps.stock.models import StockMovement, Location, Inventory


# ======================================================================
# Helper: مدیریت تراکنش و خزانه
# ======================================================================
def get_treasury():
    from apps.treasury.models import Treasury
    treasury = Treasury.objects.first()
    if not treasury:
        treasury = Treasury.objects.create(balance_afg=Decimal('0'), balance_usd=Decimal('0'))
    return treasury


def check_treasury_balance(amount, currency='AFG'):
    """چک موجودی خزانه — با Exception سفارشی"""
    from apps.treasury.exceptions import InsufficientTreasuryBalance

    treasury = get_treasury()
    amount = Decimal(str(amount))

    if currency == 'AFG':
        if treasury.balance_afg < amount:
            raise InsufficientTreasuryBalance(
                'موجودی خزانه به افغانی کافی نیست!',
                current_balance=treasury.balance_afg,
                required_amount=amount,
                currency='AFG'
            )
    else:
        if treasury.balance_usd < amount:
            raise InsufficientTreasuryBalance(
                'موجودی خزانه به دالر کافی نیست!',
                current_balance=treasury.balance_usd,
                required_amount=amount,
                currency='USD'
            )
    return True


# ======================================================================
# Helper: پاک کردن ایمن تراکنش متصل
# ======================================================================
def _detach_and_delete_transaction(instance):
    """اتصال FK تراکنش را قطع می‌کند، خزانه را معکوس می‌کند، و ردیف Transaction را حذف می‌کند."""
    trx = instance.treasury_transaction
    if not trx:
        return

    from apps.treasury.models import Transaction, Treasury

    type(instance).objects.filter(pk=instance.pk).update(treasury_transaction=None)

    amount = Decimal(str(trx.amount or 0))
    currency = trx.currency or 'AFG'
    treasury = Treasury.get_treasury()

    if amount > 0:
        if trx.transaction_type == 'IN':
            treasury.subtract_money(amount, currency)
        else:
            treasury.add_money(amount, currency)

    Transaction.objects.filter(pk=trx.pk).delete()
    instance.treasury_transaction = None


# ======================================================================
# Helper: استخراج مقدار قدیمی از items
# ======================================================================
def _extract_old_quantities(items):
    """
    از items یک سند ذخیره‌شده، دیکشنری { "product_id_location_id": quantity } می‌سازد.
    """
    old_quantities = {}
    if not items:
        return old_quantities
    for item in items:
        key = f"{item.get('product_id')}_{item.get('location_id')}"
        old_quantities[key] = old_quantities.get(key, 0) + int(item.get('quantity', 0) or 0)
    return old_quantities


# ======================================================================
# Purchase
# ======================================================================
class Purchase(models.Model):
    """خرید از تأمین‌کننده"""

    purchase_number = models.CharField(max_length=100, unique=True, blank=True, verbose_name="شماره خرید")
    purchase_date = models.DateTimeField(default=timezone.now, verbose_name="تاریخ خرید")
    supplier_name = models.CharField(max_length=200, verbose_name="نام تأمین‌کننده")
    supplier_number = models.CharField(max_length=200, blank=True, null=True, verbose_name="شماره خریدار")

    dollar_rate = models.DecimalField(
        null=True, blank=True,
        max_digits=15, decimal_places=2, default=0,
        verbose_name="نرخ دالر امروز", help_text="هر ۱ دالر = چند افغانی"
    )

    items = models.JSONField(default=list, verbose_name="اقلام خرید")

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مجموع خرید (افغانی)")
    total_dollar_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مجموع دالری")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مبلغ پرداخت‌شده")
    initial_paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="پرداخت اولیه")
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="باقی‌مانده")

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='purchase_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "خرید"
        verbose_name_plural = "خریدها"
        ordering = ['-purchase_date', '-created_at']
        indexes = [
            models.Index(fields=['supplier_name']),
            models.Index(fields=['purchase_date']),
        ]

    def __str__(self):
        return f"{self.purchase_number} - {self.supplier_name}"

    def generate_purchase_number(self):
        last = Purchase.objects.all().order_by('-id').first()
        if last and last.purchase_number and last.purchase_number.startswith('PUR_'):
            try:
                next_number = int(last.purchase_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        number = f'PUR_{next_number}'
        while Purchase.objects.filter(purchase_number=number).exclude(pk=self.pk).exists():
            next_number += 1
            number = f'PUR_{next_number}'
        return number

    # ═══ Properties — پرداخت (بر اساس خالص) ═══
    @property
    def is_fully_paid(self):
        return self.net_remaining <= 0

    @property
    def is_partially_paid(self):
        return self.net_paid > 0 and self.net_remaining > 0

    @property
    def is_unpaid(self):
        return self.net_paid == 0

    def can_be_deleted(self):
        return not self.debts.exists()

    # ═══ Properties — برگشتی‌ها (محاسباتی) ═══
    @property
    def total_returned_amount(self):
        return (
            SupplierReturn.objects
            .filter(original_purchase=self)
            .aggregate(total=Sum('received_amount'))['total'] or Decimal('0')
        )

    @property
    def total_returned_items(self):
        result = {}
        for ret in SupplierReturn.objects.filter(original_purchase=self):
            for item in (ret.items or []):
                pid = item.get('product_id')
                lid = item.get('location_id')
                qty = int(item.get('quantity', 0) or 0)
                if pid and lid:
                    key = f"{pid}_{lid}"
                    result[key] = result.get(key, 0) + qty
        return result

    @property
    def net_total(self):
        return self.total_amount - self.total_returned_amount

    @property
    def net_paid(self):
        return self.paid_amount - self.total_returned_amount

    @property
    def net_remaining(self):
        return self.net_total - self.net_paid

    @property
    def has_returns(self):
        return SupplierReturn.objects.filter(original_purchase=self).exists()

    @property
    def net_items_count(self):
        total = 0
        for item in (self.items or []):
            total += int(item.get('quantity', 0) or 0)
        total -= sum(self.total_returned_items.values())
        return total

    # ═══ محاسبات ═══
    def calculate_item_total(self, item):
        quantity = Decimal(str(item.get('quantity', 0) or 0))
        price = Decimal(str(item.get('purchase_price', 0) or 0))
        currency = item.get('currency', 'AFN')
        if currency == 'USD' and self.dollar_rate and self.dollar_rate > 0:
            return quantity * price * self.dollar_rate
        return quantity * price

    def calculate_total_amount(self):
        total = Decimal('0')
        for item in self.items:
            total += self.calculate_item_total(item)
        return total

    def calculate_total_dollar(self):
        total = Decimal('0')
        for item in self.items:
            if item.get('currency') == 'USD':
                quantity = Decimal(str(item.get('quantity', 0) or 0))
                price = Decimal(str(item.get('purchase_price', 0) or 0))
                total += quantity * price
        return total

    def validate_items(self):
        if not self.items:
            raise ValidationError('حداقل یک قلم جنس باید اضافه شود!')

        item_keys = []
        has_dollar = False

        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                raise ValidationError('محصول برای هر قلم الزامی است!')

            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise ValidationError(f'محصول با شناسه {product_id} وجود ندارد!')

            quantity = int(item.get('quantity', 0) or 0)
            if quantity <= 0:
                raise ValidationError(f'تعداد برای {product.name} باید بزرگتر از صفر باشد!')

            price = Decimal(str(item.get('purchase_price', 0) or 0))
            if price <= 0:
                raise ValidationError(f'قیمت خرید برای {product.name} باید بزرگتر از صفر باشد!')

            currency = item.get('currency', 'AFN')
            if currency == 'USD':
                has_dollar = True

            location_id = item.get('location_id')
            if not location_id:
                raise ValidationError(f'موقعیت برای {product.name} انتخاب نشده است!')

            try:
                location = Location.objects.get(id=location_id)
            except Location.DoesNotExist:
                raise ValidationError(f'موقعیت برای {product.name} معتبر نیست!')

            item_key = f"{product_id}_{location_id}"
            if item_key in item_keys:
                raise ValidationError(f'محصول {product.name} با موقعیت {location.name} تکراری است!')
            item_keys.append(item_key)

        if has_dollar and (not self.dollar_rate or self.dollar_rate <= 0):
            raise ValidationError('لطفاً نرخ امروز دالر را وارد کنید!')

    # ═══ Stock Movements ═══
    def _purchase_note_tag(self):
        return f'PURCHASE:{self.purchase_number}|'

    def create_stock_movements(self):
        tag = self._purchase_note_tag()
        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                continue
            quantity = int(item.get('quantity', 0) or 0)
            location_id = item.get('location_id')
            if quantity > 0 and location_id:
                StockMovement.objects.create(
                    product_id=product_id,
                    location_id=location_id,
                    movement_type='IN',
                    quantity=quantity,
                    note=f'{tag}{self.supplier_name}',
                )

    def reverse_stock_movements(self):
        movements = StockMovement.objects.filter(note__startswith=self._purchase_note_tag())
        for movement in movements:
            movement.delete()

    # ═══ Transaction ═══
    def _description(self):
        parts = [f'خرید از {self.supplier_name}']
        if self.supplier_number:
            parts.append(f'شماره: {self.supplier_number}')
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        from apps.treasury.models import Transaction

        paid_now = Decimal(str(self.initial_paid_amount or 0))
        if paid_now <= 0:
            return None

        check_treasury_balance(paid_now, 'AFG')

        trx = Transaction.objects.create(
            transaction_type='OUT',
            amount=paid_now,
            currency='AFG',
            from_who=f"{self.purchase_number} - {self.supplier_name}",
            money_type='PURCHASE',
            date=self.purchase_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        new_amount = Decimal(str(self.initial_paid_amount or 0))

        if new_amount <= 0:
            if self.treasury_transaction:
                trx = self.treasury_transaction
                from apps.treasury.models import Treasury, Transaction
                treasury = Treasury.get_treasury()
                amount = Decimal(str(trx.amount or 0))
                currency = trx.currency or 'AFG'
                if amount > 0:
                    if trx.transaction_type == 'IN':
                        treasury.subtract_money(amount, currency)
                    else:
                        treasury.add_money(amount, currency)
                type(self).objects.filter(pk=self.pk).update(treasury_transaction=None)
                Transaction.objects.filter(pk=trx.pk).delete()
                self.treasury_transaction = None
            return

        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        if new_amount > old_amount:
            check_treasury_balance(new_amount - old_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.purchase_date
        trx.from_who = f"{self.purchase_number} - {self.supplier_name}"
        trx.description = self._description()
        trx.save()

    # ═══ Save & Delete ═══
    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.purchase_number:
            self.purchase_number = self.generate_purchase_number()

        self.validate_items()
        self.total_amount = self.calculate_total_amount()
        self.total_dollar_amount = self.calculate_total_dollar()

        if is_new:
            self.initial_paid_amount = self.paid_amount or Decimal('0')

        if is_new:
            debts_total = Decimal('0')
        else:
            from apps.debts.models import PurchaseDebt
            debts_total = (
                PurchaseDebt.objects
                .filter(purchase_id=self.pk)
                .aggregate(total=Sum('amount'))
            )['total'] or Decimal('0')

        self.paid_amount = (self.initial_paid_amount or Decimal('0')) + debts_total
        self.remaining_amount = self.total_amount - self.paid_amount

        paid_now = Decimal(str(self.initial_paid_amount or 0))
        if paid_now > 0:
            if is_new:
                self.treasury_transaction = self.create_transaction()
            else:
                self.update_transaction()
        else:
            if not is_new and self.treasury_transaction:
                self.update_transaction()

        super().save(*args, **kwargs)

        if is_new:
            self.create_stock_movements()
        else:
            self.reverse_stock_movements()
            self.create_stock_movements()

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        _detach_and_delete_transaction(self)
        self.reverse_stock_movements()
        super().delete(*args, **kwargs)


# ======================================================================
# Sale
# ======================================================================
class Sale(models.Model):
    """فروش به مشتری"""

    sale_number = models.CharField(max_length=100, unique=True, blank=True, verbose_name="شماره فروش")
    sale_date = models.DateTimeField(default=timezone.now, verbose_name="تاریخ فروش")
    customer_name = models.CharField(max_length=200, verbose_name="نام مشتری")
    customer_number = models.CharField(max_length=200, blank=True, null=True, verbose_name="شماره مشتری")

    dollar_rate = models.DecimalField(
        null=True, blank=True,
        max_digits=15, decimal_places=2, default=0,
        verbose_name="نرخ دالر امروز", help_text="هر ۱ دالر = چند افغانی"
    )

    items = models.JSONField(default=list, verbose_name="اقلام فروش")

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مجموع فروش (افغانی)")
    total_dollar_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مجموع دالری")
    received_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="مبلغ دریافت‌شده")
    initial_received_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="دریافت اولیه")
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="باقی‌مانده")

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='sale_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "فروش"
        verbose_name_plural = "فروش‌ها"
        ordering = ['-sale_date', '-created_at']
        indexes = [
            models.Index(fields=['customer_name']),
            models.Index(fields=['sale_date']),
        ]

    def __str__(self):
        return f"{self.sale_number} - {self.customer_name}"

    def generate_sale_number(self):
        last = Sale.objects.all().order_by('-id').first()
        if last and last.sale_number and last.sale_number.startswith('SAL_'):
            try:
                next_number = int(last.sale_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        number = f'SAL_{next_number}'
        while Sale.objects.filter(sale_number=number).exclude(pk=self.pk).exists():
            next_number += 1
            number = f'SAL_{next_number}'
        return number

    # ═══ Properties ═══
    @property
    def is_fully_paid(self):
        return self.net_remaining <= 0

    @property
    def is_partially_paid(self):
        return self.net_received > 0 and self.net_remaining > 0

    @property
    def is_unpaid(self):
        return self.net_received == 0

    def can_be_deleted(self):
        return not self.debts.exists()

    @property
    def total_returned_amount(self):
        return (
            CustomerReturn.objects
            .filter(original_sale=self)
            .aggregate(total=Sum('refund_amount'))['total'] or Decimal('0')
        )

    @property
    def total_returned_items(self):
        result = {}
        for ret in CustomerReturn.objects.filter(original_sale=self):
            for item in (ret.items or []):
                pid = item.get('product_id')
                lid = item.get('location_id')
                qty = int(item.get('quantity', 0) or 0)
                if pid and lid:
                    key = f"{pid}_{lid}"
                    result[key] = result.get(key, 0) + qty
        return result

    @property
    def net_total(self):
        return self.total_amount - self.total_returned_amount

    @property
    def net_received(self):
        return self.received_amount - self.total_returned_amount

    @property
    def net_remaining(self):
        return self.net_total - self.net_received

    @property
    def has_returns(self):
        return CustomerReturn.objects.filter(original_sale=self).exists()

    @property
    def net_items_count(self):
        total = 0
        for item in (self.items or []):
            total += int(item.get('quantity', 0) or 0)
        total -= sum(self.total_returned_items.values())
        return total

    @property
    def net_profit(self):
        return self.calculate_total_profit() - self.total_returned_amount

    # ═══ محاسبات ═══
    def calculate_item_total(self, item):
        quantity = Decimal(str(item.get('quantity', 0) or 0))
        price = Decimal(str(item.get('sale_price', 0) or 0))
        currency = item.get('currency', 'AFN')
        if currency == 'USD' and self.dollar_rate and self.dollar_rate > 0:
            return quantity * price * self.dollar_rate
        return quantity * price

    def calculate_total_amount(self):
        total = Decimal('0')
        for item in self.items:
            total += self.calculate_item_total(item)
        return total

    def calculate_total_dollar(self):
        total = Decimal('0')
        for item in self.items:
            if item.get('currency') == 'USD':
                quantity = Decimal(str(item.get('quantity', 0) or 0))
                price = Decimal(str(item.get('sale_price', 0) or 0))
                total += quantity * price
        return total

    def calculate_total_profit(self):
        total_profit = Decimal('0')
        for item in self.items:
            product_id = item.get('product_id')
            quantity = Decimal(str(item.get('quantity', 0) or 0))
            sale_price = Decimal(str(item.get('sale_price', 0) or 0))
            currency = item.get('currency', 'AFN')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    if currency == 'USD' and self.dollar_rate and self.dollar_rate > 0:
                        profit = (sale_price * self.dollar_rate - product.purchase_price) * quantity
                    else:
                        profit = (sale_price - product.purchase_price) * quantity
                    total_profit += profit
                except Product.DoesNotExist:
                    pass
        return total_profit

    def validate_items(self):
        """
        چک موجودی حذف شد از validate_items — این کار در فرم انجام می‌شود
        چون فرم به مقدار قدیمی این سند (در حالت ویرایش) دسترسی دارد.
        اینجا فقط ساختار و تکراری بودن چک می‌شود.
        """
        if not self.items:
            raise ValidationError('حداقل یک قلم جنس باید اضافه شود!')

        item_keys = []
        has_dollar = False

        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                raise ValidationError('محصول برای هر قلم الزامی است!')

            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise ValidationError(f'محصول با شناسه {product_id} وجود ندارد!')

            quantity = int(item.get('quantity', 0) or 0)
            if quantity <= 0:
                raise ValidationError(f'تعداد برای {product.name} باید بزرگتر از صفر باشد!')

            sale_price = Decimal(str(item.get('sale_price', 0) or 0))
            if sale_price <= 0:
                raise ValidationError(f'قیمت فروش برای {product.name} باید بزرگتر از صفر باشد!')

            currency = item.get('currency', 'AFN')
            if currency == 'USD':
                has_dollar = True

            location_id = item.get('location_id')
            if not location_id:
                raise ValidationError(f'موقعیت فروش برای {product.name} انتخاب نشده است!')

            try:
                location = Location.objects.get(id=location_id)
            except Location.DoesNotExist:
                raise ValidationError(f'موقعیت فروش برای {product.name} معتبر نیست!')

            item_key = f"{product_id}_{location_id}"
            if item_key in item_keys:
                raise ValidationError(f'محصول {product.name} با موقعیت {location.name} تکراری است!')
            item_keys.append(item_key)

        if has_dollar and (not self.dollar_rate or self.dollar_rate <= 0):
            raise ValidationError('لطفاً نرخ امروز دالر را وارد کنید!')

    # ═══ Stock Movements ═══
    def _sale_note_tag(self):
        return f'SALE:{self.sale_number}|'

    def create_stock_movements(self):
        tag = self._sale_note_tag()
        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                continue
            quantity = int(item.get('quantity', 0) or 0)
            if quantity <= 0:
                continue
            location_id = item.get('location_id')
            if not location_id:
                continue
            StockMovement.objects.create(
                product_id=product_id,
                location_id=location_id,
                movement_type='OUT',
                quantity=-quantity,
                note=f'{tag}{self.customer_name}',
            )

    def reverse_stock_movements(self):
        movements = StockMovement.objects.filter(note__startswith=self._sale_note_tag())
        for movement in movements:
            movement.delete()

    # ═══ Transaction ═══
    def _description(self):
        parts = [f'فروش به {self.customer_name}']
        if self.customer_number:
            parts.append(f'شماره: {self.customer_number}')
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        from apps.treasury.models import Transaction
        received_now = Decimal(str(self.initial_received_amount or 0))

        if received_now <= 0:
            return None

        trx = Transaction.objects.create(
            transaction_type='IN',
            amount=received_now,
            currency='AFG',
            from_who=f"{self.sale_number} - {self.customer_name}",
            money_type='SALE',
            date=self.sale_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        new_amount = Decimal(str(self.initial_received_amount or 0))

        if new_amount <= 0:
            if self.treasury_transaction:
                trx = self.treasury_transaction
                from apps.treasury.models import Treasury, Transaction
                treasury = Treasury.get_treasury()
                amount = Decimal(str(trx.amount or 0))
                currency = trx.currency or 'AFG'
                if amount > 0:
                    if trx.transaction_type == 'IN':
                        treasury.subtract_money(amount, currency)
                    else:
                        treasury.add_money(amount, currency)
                type(self).objects.filter(pk=self.pk).update(treasury_transaction=None)
                Transaction.objects.filter(pk=trx.pk).delete()
                self.treasury_transaction = None
            return

        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        if new_amount < old_amount:
            check_treasury_balance(old_amount - new_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.sale_date
        trx.from_who = f"{self.sale_number} - {self.customer_name}"
        trx.description = self._description()
        trx.save()

    # ═══ Save & Delete ═══
    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.sale_number:
            self.sale_number = self.generate_sale_number()

        enhanced_items = []
        for item in self.items:
            enhanced_item = dict(item)
            product_id = enhanced_item.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    enhanced_item['product_name'] = product.name
                except Product.DoesNotExist:
                    enhanced_item['product_name'] = f"محصول {product_id}"
            else:
                enhanced_item['product_name'] = "نامشخص"
            enhanced_items.append(enhanced_item)
        self.items = enhanced_items

        self.validate_items()
        self.total_amount = self.calculate_total_amount()
        self.total_dollar_amount = self.calculate_total_dollar()

        if is_new:
            self.initial_received_amount = self.received_amount or Decimal('0')

        if is_new:
            debts_total = Decimal('0')
        else:
            from apps.debts.models import SaleDebt
            debts_total = (
                SaleDebt.objects
                .filter(sale_id=self.pk)
                .aggregate(total=Sum('amount'))
            )['total'] or Decimal('0')

        self.received_amount = (self.initial_received_amount or Decimal('0')) + debts_total
        self.remaining_amount = self.total_amount - self.received_amount

        received_now = Decimal(str(self.initial_received_amount or 0))
        if received_now > 0:
            if is_new:
                self.treasury_transaction = self.create_transaction()
            else:
                self.update_transaction()
        else:
            if not is_new and self.treasury_transaction:
                self.update_transaction()

        super().save(*args, **kwargs)

        if is_new:
            self.create_stock_movements()
        else:
            self.reverse_stock_movements()
            self.create_stock_movements()

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        _detach_and_delete_transaction(self)
        self.reverse_stock_movements()
        super().delete(*args, **kwargs)


# ======================================================================
# CustomerReturn - مرجوعی از مشتری
# ======================================================================
class CustomerReturn(models.Model):
    """مرجوعی از مشتری — بر اساس فروش اصلی"""
    return_number = models.CharField(max_length=100, unique=True, blank=True, verbose_name="شماره مرجوعی")
    return_date = models.DateTimeField(default=timezone.now, verbose_name="تاریخ مرجوعی")

    original_sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='customer_returns',
        verbose_name="فروش اصلی"
    )

    customer_name = models.CharField(max_length=200, verbose_name="نام مشتری")

    refund_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="مبلغ بازپرداخت به مشتری"
    )

    items = models.JSONField(default=list, verbose_name="اقلام مرجوعی")
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='customer_return_transactions',
        verbose_name="تراکنش"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "مرجوعی از مشتری"
        verbose_name_plural = "مرجوعی‌های مشتریان"
        ordering = ['-return_date', '-created_at']
        indexes = [
            models.Index(fields=['original_sale', 'return_date']),
        ]

    def __str__(self):
        return f"{self.return_number} - {self.customer_name}"

    def generate_return_number(self):
        last = CustomerReturn.objects.all().order_by('-id').first()
        if last and last.return_number and last.return_number.startswith('CRT_'):
            try:
                next_number = int(last.return_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        number = f'CRT_{next_number}'
        while CustomerReturn.objects.filter(return_number=number).exclude(pk=self.pk).exists():
            next_number += 1
            number = f'CRT_{next_number}'
        return number

    # ═══ Properties ═══
    @property
    def total_returned_items_qty(self):
        """مجموع تعداد اقلام این سند"""
        total = 0
        for item in (self.items or []):
            total += int(item.get('quantity', 0) or 0)
        return total

    def validate_items(self):
        """
        ✅ FIXED (v2): اعتبارسنجی کامل مشابه SupplierReturn.

        محدودیت‌ها:
        1. هر قلم باید در فروش اصلی باشد (product + location).
        2. مقدار برگشتی هر قلم نباید از مقدار فروش‌رفته بیشتر باشد.
        3. مجموع برگشتی‌های قبلی (به‌جز این سند) + مقدار این سند نباید از فروش اصلی بیشتر شود.
        4. قلم تکراری در همین سند نباشد.

        نکته: چک موجودی گدام لازم نیست، چون کالا از مشتری به گدام
        اضافه می‌شود (نه برداشت).
        """
        if not self.items:
            raise ValidationError('حداقل یک قلم باید اضافه شود!')

        if not self.original_sale:
            raise ValidationError('باید فروش اصلی انتخاب شده باشد!')

        # ═══ ۱. نقشه مقادیر فروش اصلی ═══
        sale_items_map = {}
        for item in (self.original_sale.items or []):
            pid = item.get('product_id')
            lid = item.get('location_id')
            qty = int(item.get('quantity', 0) or 0)
            if pid and lid:
                sale_items_map.setdefault(int(pid), {})
                sale_items_map[int(pid)][int(lid)] = \
                    sale_items_map[int(pid)].get(int(lid), 0) + qty

        # ═══ ۲. مقادیر برگشتی قبلی (اسناد دیگر، به‌جز این سند) ═══
        previous_returns = {}
        existing_qs = CustomerReturn.objects.filter(original_sale=self.original_sale)
        if self.pk:
            existing_qs = existing_qs.exclude(pk=self.pk)
        for ret in existing_qs:
            for item in (ret.items or []):
                pid = item.get('product_id')
                lid = item.get('location_id')
                qty = int(item.get('quantity', 0) or 0)
                if pid and lid:
                    key = (int(pid), int(lid))
                    previous_returns[key] = previous_returns.get(key, 0) + qty

        # ═══ ۳. اعتبارسنجی هر قلم ═══
        seen = set()
        for idx, item in enumerate(self.items):
            product_id = item.get('product_id')
            location_id = item.get('location_id')
            quantity = int(item.get('quantity', 0) or 0)

            if not product_id:
                raise ValidationError(f'قلم {idx + 1}: محصول مشخص نیست!')
            if not location_id:
                raise ValidationError(f'قلم {idx + 1}: موقعیت مشخص نیست!')
            if quantity <= 0:
                raise ValidationError(f'قلم {idx + 1}: تعداد باید بزرگتر از صفر باشد!')

            pid = int(product_id)
            lid = int(location_id)

            # ─── الف) قلم باید در فروش اصلی باشد ───
            if pid not in sale_items_map:
                raise ValidationError(f'قلم {idx + 1}: این محصول در فروش اصلی وجود ندارد!')
            if lid not in sale_items_map[pid]:
                raise ValidationError(f'قلم {idx + 1}: این محصول از این موقعیت فروخته نشده است!')

            # ─── ب) سقف قابل برگشت ───
            sold_qty = sale_items_map[pid][lid]
            already_returned = previous_returns.get((pid, lid), 0)
            available_return = sold_qty - already_returned

            if quantity > available_return:
                raise ValidationError(
                    f'قلم {idx + 1}: مقدار قابل برگشت برای این محصول فقط {available_return} عدد است '
                    f'(فروش‌رفته: {sold_qty}، قبلاً برگشته: {already_returned})'
                )

            # ─── ج) چک تکراری ───
            item_key = f"{pid}_{lid}"
            if item_key in seen:
                raise ValidationError(f'قلم {idx + 1}: محصول با این موقعیت تکراری است!')
            seen.add(item_key)

    def _note_tag(self):
        return f'CUSTOMER_RETURN:{self.return_number}|'

    def create_stock_movements(self):
        tag = self._note_tag()
        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                continue
            quantity = int(item.get('quantity', 0) or 0)
            location_id = item.get('location_id')
            if quantity > 0 and location_id:
                StockMovement.objects.create(
                    product_id=product_id,
                    location_id=location_id,
                    movement_type='IN',
                    quantity=quantity,
                    note=f'{tag}{self.customer_name}',
                )

    def reverse_stock_movements(self):
        movements = StockMovement.objects.filter(note__startswith=self._note_tag())
        for movement in movements:
            movement.delete()

    def _description(self):
        parts = [f'مرجوعی از {self.customer_name}']
        if self.original_sale:
            parts.append(f'فروش اصلی: {self.original_sale.sale_number}')
        if self.note:
            parts.append(f'دلیل: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        from apps.treasury.models import Transaction
        refund = Decimal(str(self.refund_amount or 0))

        if refund <= 0:
            return None

        check_treasury_balance(refund, 'AFG')

        trx = Transaction.objects.create(
            transaction_type='OUT',
            amount=refund,
            currency='AFG',
            from_who=f"{self.return_number} - {self.customer_name}",
            money_type='CUSTOMER_RETURN',
            date=self.return_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        new_amount = Decimal(str(self.refund_amount or 0))

        if new_amount <= 0:
            if self.treasury_transaction:
                trx = self.treasury_transaction
                from apps.treasury.models import Treasury, Transaction
                treasury = Treasury.get_treasury()
                amount = Decimal(str(trx.amount or 0))
                currency = trx.currency or 'AFG'
                if amount > 0:
                    if trx.transaction_type == 'IN':
                        treasury.subtract_money(amount, currency)
                    else:
                        treasury.add_money(amount, currency)
                type(self).objects.filter(pk=self.pk).update(treasury_transaction=None)
                Transaction.objects.filter(pk=trx.pk).delete()
                self.treasury_transaction = None
            return

        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        if new_amount > old_amount:
            check_treasury_balance(new_amount - old_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.return_date
        trx.from_who = f"{self.return_number} - {self.customer_name}"
        trx.description = self._description()
        trx.save()

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.return_number:
            self.return_number = self.generate_return_number()

        if self.original_sale and not self.customer_name:
            self.customer_name = self.original_sale.customer_name

        enhanced_items = []
        for item in self.items:
            enhanced_item = dict(item)
            product_id = enhanced_item.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    enhanced_item['product_name'] = product.name
                except Product.DoesNotExist:
                    enhanced_item['product_name'] = f"محصول {product_id}"
            else:
                enhanced_item['product_name'] = "نامشخص"
            enhanced_items.append(enhanced_item)
        self.items = enhanced_items

        self.validate_items()

        refund = Decimal(str(self.refund_amount or 0))
        if refund > 0:
            if is_new:
                self.treasury_transaction = self.create_transaction()
            else:
                self.update_transaction()
        else:
            if not is_new and self.treasury_transaction:
                self.update_transaction()

        super().save(*args, **kwargs)

        if is_new:
            self.create_stock_movements()
        else:
            self.reverse_stock_movements()
            self.create_stock_movements()

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        _detach_and_delete_transaction(self)
        self.reverse_stock_movements()
        super().delete(*args, **kwargs)


# ======================================================================
# SupplierReturn - مرجوعی به تأمین‌کننده
# ======================================================================
class SupplierReturn(models.Model):
    """مرجوعی به تأمین‌کننده — بر اساس خرید اصلی"""
    return_number = models.CharField(max_length=100, unique=True, blank=True, verbose_name="شماره مرجوعی")
    return_date = models.DateTimeField(default=timezone.now, verbose_name="تاریخ مرجوعی")

    original_purchase = models.ForeignKey(
        Purchase,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='supplier_returns',
        verbose_name="خرید اصلی"
    )

    supplier_name = models.CharField(max_length=200, verbose_name="نام تأمین‌کننده")

    received_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="مبلغ دریافتی از تأمین‌کننده"
    )

    items = models.JSONField(default=list, verbose_name="اقلام مرجوعی")
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='supplier_return_transactions',
        verbose_name="تراکنش"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "مرجوعی به تأمین‌کننده"
        verbose_name_plural = "مرجوعی‌های به تأمین‌کنندگان"
        ordering = ['-return_date', '-created_at']
        indexes = [
            models.Index(fields=['original_purchase', 'return_date']),
        ]

    def __str__(self):
        return f"{self.return_number} - {self.supplier_name}"

    def generate_return_number(self):
        last = SupplierReturn.objects.all().order_by('-id').first()
        if last and last.return_number and last.return_number.startswith('SRT_'):
            try:
                next_number = int(last.return_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        number = f'SRT_{next_number}'
        while SupplierReturn.objects.filter(return_number=number).exclude(pk=self.pk).exists():
            next_number += 1
            number = f'SRT_{next_number}'
        return number

    def validate_items(self):
        """
        ✅ FIXED (v2): مقدار قدیمی این سند (در حالت ویرایش) به موجودی اضافه می‌شود.

        محدودیت‌ها:
        1. هر قلم باید در خرید اصلی باشد (product + location).
        2. مقدار برگشتی هر قلم نباید از مقدار خریداری‌شده بیشتر باشد.
        3. موجودی گدام (با در نظر گرفتن مقدار قدیمی این سند در ویرایش) باید کافی باشد.
        4. قلم تکراری در همین سند نباشد.
        """
        if not self.items:
            raise ValidationError('حداقل یک قلم باید اضافه شود!')

        if not self.original_purchase:
            raise ValidationError('باید خرید اصلی انتخاب شده باشد!')

        # ═══ ۱. نقشه مقادیر خرید اصلی ═══
        purchase_items_map = {}
        for item in (self.original_purchase.items or []):
            pid = item.get('product_id')
            lid = item.get('location_id')
            qty = int(item.get('quantity', 0) or 0)
            if pid and lid:
                purchase_items_map.setdefault(int(pid), {})
                purchase_items_map[int(pid)][int(lid)] = \
                    purchase_items_map[int(pid)].get(int(lid), 0) + qty

        # ═══ ۲. مقدار قدیمی این سند (در ویرایش) ═══
        old_returns_self = {}
        if self.pk:
            old_obj = SupplierReturn.objects.filter(pk=self.pk).first()
            if old_obj and old_obj.items:
                for old_item in old_obj.items:
                    key = (int(old_item.get('product_id', 0)),
                           int(old_item.get('location_id', 0)))
                    old_returns_self[key] = \
                        old_returns_self.get(key, 0) + int(old_item.get('quantity', 0) or 0)

        # ═══ ۳. مقادیر برگشتی قبلی (اسناد دیگر) ═══
        previous_returns = {}
        existing_qs = SupplierReturn.objects.filter(original_purchase=self.original_purchase)
        if self.pk:
            existing_qs = existing_qs.exclude(pk=self.pk)
        for ret in existing_qs:
            for item in (ret.items or []):
                pid = item.get('product_id')
                lid = item.get('location_id')
                qty = int(item.get('quantity', 0) or 0)
                if pid and lid:
                    key = (int(pid), int(lid))
                    previous_returns[key] = previous_returns.get(key, 0) + qty

        # ═══ ۴. اعتبارسنجی هر قلم ═══
        seen = set()
        for idx, item in enumerate(self.items):
            product_id = item.get('product_id')
            location_id = item.get('location_id')
            quantity = int(item.get('quantity', 0) or 0)

            if not product_id:
                raise ValidationError(f'قلم {idx + 1}: محصول مشخص نیست!')
            if not location_id:
                raise ValidationError(f'قلم {idx + 1}: موقعیت مشخص نیست!')
            if quantity <= 0:
                raise ValidationError(f'قلم {idx + 1}: تعداد باید بزرگتر از صفر باشد!')

            pid = int(product_id)
            lid = int(location_id)

            # ─── الف) قلم باید در خرید اصلی باشد ───
            if pid not in purchase_items_map:
                raise ValidationError(f'قلم {idx + 1}: این محصول در خرید اصلی وجود ندارد!')
            if lid not in purchase_items_map[pid]:
                raise ValidationError(f'قلم {idx + 1}: این محصول از این موقعیت خریداری نشده است!')

            # ─── ب) چک موجودی گدام ───
            # در زمان validate_items، مقدار قدیمی این سند هنوز در گدام برنگشته
            # (چون reverse_stock_movements در delete/save بعد از validate اجرا می‌شود).
            # پس مقدار قدیمی این سند را به موجودی اضافه می‌کنیم.
            inv = Inventory.objects.filter(product_id=pid, location_id=lid).first()
            available_stock = (inv.quantity if inv else 0)
            available_stock += old_returns_self.get((pid, lid), 0)

            if quantity > available_stock:
                raise ValidationError(
                    f'قلم {idx + 1}: موجودی گدام کافی نیست! '
                    f'موجودی قابل استفاده: {available_stock} (درخواستی: {quantity})'
                )

            # ─── ج) سقف قابل برگشت از خرید اصلی ───
            purchased_qty = purchase_items_map[pid][lid]
            already_returned = previous_returns.get((pid, lid), 0)
            available_return = purchased_qty - already_returned

            if quantity > available_return:
                raise ValidationError(
                    f'قلم {idx + 1}: مقدار قابل برگشت به تأمین‌کننده فقط {available_return} عدد است '
                    f'(خریداری‌شده: {purchased_qty}، قبلاً برگشته: {already_returned})'
                )

            # ─── د) چک تکراری ───
            item_key = f"{pid}_{lid}"
            if item_key in seen:
                raise ValidationError(f'قلم {idx + 1}: محصول با این موقعیت تکراری است!')
            seen.add(item_key)

    def _note_tag(self):
        return f'SUPPLIER_RETURN:{self.return_number}|'

    def create_stock_movements(self):
        tag = self._note_tag()
        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                continue
            quantity = int(item.get('quantity', 0) or 0)
            location_id = item.get('location_id')
            if quantity > 0 and location_id:
                StockMovement.objects.create(
                    product_id=product_id,
                    location_id=location_id,
                    movement_type='OUT',
                    quantity=-quantity,
                    note=f'{tag}{self.supplier_name}',
                )

    def reverse_stock_movements(self):
        movements = StockMovement.objects.filter(note__startswith=self._note_tag())
        for movement in movements:
            movement.delete()

    def _description(self):
        parts = [f'مرجوعی به {self.supplier_name}']
        if self.original_purchase:
            parts.append(f'خرید اصلی: {self.original_purchase.purchase_number}')
        if self.note:
            parts.append(f'دلیل: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        from apps.treasury.models import Transaction
        received = Decimal(str(self.received_amount or 0))

        if received <= 0:
            return None

        trx = Transaction.objects.create(
            transaction_type='IN',
            amount=received,
            currency='AFG',
            from_who=f"{self.return_number} - {self.supplier_name}",
            money_type='SUPPLIER_RETURN',
            date=self.return_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        new_amount = Decimal(str(self.received_amount or 0))

        if new_amount <= 0:
            if self.treasury_transaction:
                trx = self.treasury_transaction
                from apps.treasury.models import Treasury, Transaction
                treasury = Treasury.get_treasury()
                amount = Decimal(str(trx.amount or 0))
                currency = trx.currency or 'AFG'
                if amount > 0:
                    if trx.transaction_type == 'IN':
                        treasury.subtract_money(amount, currency)
                    else:
                        treasury.add_money(amount, currency)
                type(self).objects.filter(pk=self.pk).update(treasury_transaction=None)
                Transaction.objects.filter(pk=trx.pk).delete()
                self.treasury_transaction = None
            return

        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        if new_amount < old_amount:
            check_treasury_balance(old_amount - new_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.return_date
        trx.from_who = f"{self.return_number} - {self.supplier_name}"
        trx.description = self._description()
        trx.save()

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.return_number:
            self.return_number = self.generate_return_number()

        if self.original_purchase and not self.supplier_name:
            self.supplier_name = self.original_purchase.supplier_name

        enhanced_items = []
        for item in self.items:
            enhanced_item = dict(item)
            product_id = enhanced_item.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    enhanced_item['product_name'] = product.name
                except Product.DoesNotExist:
                    enhanced_item['product_name'] = f"محصول {product_id}"
            else:
                enhanced_item['product_name'] = "نامشخص"
            enhanced_items.append(enhanced_item)
        self.items = enhanced_items

        self.validate_items()

        received = Decimal(str(self.received_amount or 0))
        if received > 0:
            if is_new:
                self.treasury_transaction = self.create_transaction()
            else:
                self.update_transaction()
        else:
            if not is_new and self.treasury_transaction:
                self.update_transaction()

        super().save(*args, **kwargs)

        if is_new:
            self.create_stock_movements()
        else:
            self.reverse_stock_movements()
            self.create_stock_movements()

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        _detach_and_delete_transaction(self)
        self.reverse_stock_movements()
        super().delete(*args, **kwargs)


# ======================================================================
# Waste
# ======================================================================
class Waste(models.Model):
    waste_number = models.CharField(max_length=100, unique=True, blank=True, verbose_name="شماره ضایعات")
    waste_date = models.DateTimeField(default=timezone.now, verbose_name="تاریخ ضایعات")
    reason = models.CharField(max_length=200, verbose_name="دلیل ضایعات")

    items = models.JSONField(default=list, verbose_name="اقلام ضایعات")
    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "ضایعات کالا"
        verbose_name_plural = "ضایعات کالاها"
        ordering = ['-waste_date', '-created_at']

    def __str__(self):
        return f"{self.waste_number} - {self.reason}"

    def generate_waste_number(self):
        last = Waste.objects.all().order_by('-id').first()
        if last and last.waste_number and last.waste_number.startswith('WST_'):
            try:
                next_number = int(last.waste_number.split('_')[1]) + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        number = f'WST_{next_number}'
        while Waste.objects.filter(waste_number=number).exclude(pk=self.pk).exists():
            next_number += 1
            number = f'WST_{next_number}'
        return number

    def validate_items(self):
        """
        ✅ FIXED (v2):
        - چک تکراری بر اساس جفت (product_id, location_id)
        - چک موجودی برای اسناد جدید؛ برای ویرایش، مقدار قدیمی این سند اضافه می‌شود.
        """
        if not self.items:
            raise ValidationError('حداقل یک قلم جنس باید اضافه شود!')

        # ═══ ۱. مقادیر قدیمی این سند در حالت ویرایش ═══
        old_quantities_self = {}
        if self.pk:
            old_obj = Waste.objects.filter(pk=self.pk).first()
            if old_obj and old_obj.items:
                for old_item in old_obj.items:
                    key = f"{old_item.get('product_id')}_{old_item.get('location_id')}"
                    old_quantities_self[key] = \
                        old_quantities_self.get(key, 0) + int(old_item.get('quantity', 0) or 0)

        # ═══ ۲. اعتبارسنجی هر قلم ═══
        item_keys = []
        for idx, item in enumerate(self.items):
            product_id = item.get('product_id')
            if not product_id:
                raise ValidationError(f'قلم {idx + 1}: محصول الزامی است!')

            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise ValidationError(f'قلم {idx + 1}: محصول با شناسه {product_id} وجود ندارد!')

            quantity = int(item.get('quantity', 0) or 0)
            if quantity <= 0:
                raise ValidationError(f'قلم {idx + 1}: تعداد برای {product.name} باید بزرگتر از صفر باشد!')

            location_id = item.get('location_id')
            if not location_id:
                raise ValidationError(f'قلم {idx + 1}: موقعیت برای {product.name} انتخاب نشده است!')

            try:
                location = Location.objects.get(id=location_id)
            except Location.DoesNotExist:
                raise ValidationError(f'قلم {idx + 1}: موقعیت برای {product.name} معتبر نیست!')

            # ─── چک تکراری بر اساس جفت (product, location) ───
            item_key = f"{product_id}_{location_id}"
            if item_key in item_keys:
                raise ValidationError(
                    f'قلم {idx + 1}: محصول {product.name} با موقعیت {location.name} تکراری است!'
                )
            item_keys.append(item_key)

            # ─── چک موجودی — با در نظر گرفتن مقدار قدیمی این سند (در ویرایش) ───
            inv = Inventory.objects.filter(product=product, location=location).first()
            available = (inv.quantity if inv else 0) + old_quantities_self.get(item_key, 0)
            if quantity > available:
                raise ValidationError(
                    f'قلم {idx + 1}: موجودی {location.name} برای {product.name} کافی نیست! '
                    f'موجودی فعلی: {available}'
                )

    def _note_tag(self):
        return f'WASTE:{self.waste_number}|'

    def create_stock_movements(self):
        tag = self._note_tag()
        for item in self.items:
            product_id = item.get('product_id')
            if not product_id:
                continue
            quantity = int(item.get('quantity', 0) or 0)
            location_id = item.get('location_id')
            if quantity > 0 and location_id:
                StockMovement.objects.create(
                    product_id=product_id,
                    location_id=location_id,
                    movement_type='OUT',
                    quantity=-quantity,
                    note=f'{tag}{self.reason}',
                )

    def reverse_stock_movements(self):
        movements = StockMovement.objects.filter(note__startswith=self._note_tag())
        for movement in movements:
            movement.delete()

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.waste_number:
            self.waste_number = self.generate_waste_number()

        enhanced_items = []
        for item in self.items:
            enhanced_item = dict(item)
            product_id = enhanced_item.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    enhanced_item['product_name'] = product.name
                except Product.DoesNotExist:
                    enhanced_item['product_name'] = f"محصول {product_id}"
            else:
                enhanced_item['product_name'] = "نامشخص"
            enhanced_items.append(enhanced_item)
        self.items = enhanced_items

        self.validate_items()

        super().save(*args, **kwargs)

        if is_new:
            self.create_stock_movements()
        else:
            self.reverse_stock_movements()
            self.create_stock_movements()

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        self.reverse_stock_movements()
        super().delete(*args, **kwargs)