# apps/debts/models.py

from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from apps.purchasesale.models import Purchase
from apps.purchasesale.models import Sale
from decimal import Decimal


# ======================================================================
# Helper: مدیریت خزانه
# ======================================================================
def get_treasury():
    """دریافت یا ساخت خزانه"""
    from apps.treasury.models import Treasury
    treasury = Treasury.objects.first()
    if not treasury:
        treasury = Treasury.objects.create(balance_afg=Decimal('0'), balance_usd=Decimal('0'))
    return treasury


def check_treasury_balance(amount, currency='AFG'):
    """چک موجودی خزانه"""
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
    """
    اتصال FK تراکنش را قطع می‌کند، خزانه را معکوس می‌کند، و ردیف Transaction را حذف می‌کند.
    """
    trx = instance.treasury_transaction
    if not trx:
        return

    from apps.treasury.models import Transaction, Treasury

    amount = Decimal(str(trx.amount or 0))
    currency = trx.currency or 'AFG'
    treasury = Treasury.get_treasury()

    if amount > 0:
        if trx.transaction_type == 'IN':
            treasury.subtract_money(amount, currency)
        else:
            treasury.add_money(amount, currency)

    type(instance).objects.filter(pk=instance.pk).update(treasury_transaction=None)
    Transaction.objects.filter(pk=trx.pk).delete()
    instance.treasury_transaction = None


# ======================================================================
# PurchaseDebt
# ======================================================================
class PurchaseDebt(models.Model):
    """پرداخت قسطی بدهی به تأمین‌کننده"""

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name='debts',
        verbose_name="خرید"
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="مبلغ پرداختی"
    )

    payment_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="تاریخ پرداخت"
    )

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='purchase_debt_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(
        blank=True,
        null=True,
        verbose_name="یادداشت"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت"
    )

    class Meta:
        verbose_name = "پرداخت بدهی خرید"
        verbose_name_plural = "پرداخت‌های بدهی خرید"
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['purchase', 'payment_date']),
        ]

    def __str__(self):
        return f"{self.purchase.purchase_number} - {self.amount} افغانی"

    def _description(self):
        parts = [f'پرداخت قسط خرید {self.purchase.purchase_number}']
        parts.append(f'تأمین‌کننده: {self.purchase.supplier_name}')
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        """Creates the OUT transaction. Treasury deduction handled by Transaction.save()."""
        from apps.treasury.models import Transaction

        amount = Decimal(str(self.amount or 0))

        if amount > 0:
            check_treasury_balance(amount, 'AFG')

        trx = Transaction.objects.create(
            transaction_type='OUT',
            amount=amount,
            currency='AFG',
            from_who=f"{self.purchase.purchase_number} - {self.purchase.supplier_name}",
            money_type='PURCHASE_DEBT',
            date=self.payment_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        new_amount = Decimal(str(self.amount or 0))

        # اگر مبلغ جدید بیشتر شود، باید موجودی خزانه کافی باشد
        if new_amount > old_amount:
            check_treasury_balance(new_amount - old_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.payment_date
        trx.from_who = f"{self.purchase.purchase_number} - {self.purchase.supplier_name}"
        trx.description = self._description()
        trx.save()

    @staticmethod
    def _recalc_purchase(purchase_id):
        """بازمحاسبه paid_amount و remaining_amount یک خرید مشخص"""
        from django.db.models import Sum

        if not purchase_id:
            return

        try:
            purchase = Purchase.objects.get(pk=purchase_id)
        except Purchase.DoesNotExist:
            return

        debts_total = (
            PurchaseDebt.objects
            .filter(purchase_id=purchase_id)
            .aggregate(total=Sum('amount'))
        )['total'] or Decimal('0')

        initial = purchase.initial_paid_amount or Decimal('0')
        new_paid = initial + debts_total
        new_remaining = purchase.total_amount - new_paid

        # ✅ Use QuerySet.update() to bypass Purchase.save() override
        Purchase.objects.filter(pk=purchase_id).update(
            paid_amount=new_paid,
            remaining_amount=new_remaining,
        )

    def _sync_purchase_totals(self):
        """بازمحاسبه paid_amount خرید"""
        if not self.purchase_id:
            return
        self._recalc_purchase(self.purchase_id)

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_purchase_id = None

        if not is_new:
            # قبل از ذخیره، purchase قبلی را نگه دار
            old_purchase_id = (
                type(self).objects
                .filter(pk=self.pk)
                .values_list('purchase_id', flat=True)
                .first()
            )

        if is_new:
            self.treasury_transaction = self.create_transaction()
        else:
            self.update_transaction()

        super().save(*args, **kwargs)

        # sync purchase فعلی
        self._sync_purchase_totals()

        # اگر purchase عوض شده، purchase قبلی را هم sync کن
        if old_purchase_id and old_purchase_id != self.purchase_id:
            self._recalc_purchase(old_purchase_id)

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        purchase_id = self.purchase_id
        _detach_and_delete_transaction(self)
        super().delete(*args, **kwargs)
        self._recalc_purchase(purchase_id)


# ======================================================================
# SaleDebt
# ======================================================================
class SaleDebt(models.Model):
    """دریافت قسطی بدهی از مشتری"""

    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name='debts',
        verbose_name="فروش"
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="مبلغ دریافتی"
    )

    payment_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="تاریخ دریافت"
    )

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='sale_debt_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(
        blank=True,
        null=True,
        verbose_name="یادداشت"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت"
    )

    class Meta:
        verbose_name = "دریافت بدهی فروش"
        verbose_name_plural = "دریافت‌های بدهی فروش"
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['sale', 'payment_date']),
        ]

    def __str__(self):
        return f"{self.sale.sale_number} - {self.amount} افغانی"

    def _description(self):
        parts = [f'دریافت قسط فروش {self.sale.sale_number}']
        parts.append(f'مشتری: {self.sale.customer_name}')
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        """Creates the IN transaction. Treasury credit handled by Transaction.save()."""
        from apps.treasury.models import Transaction

        amount = Decimal(str(self.amount or 0))

        trx = Transaction.objects.create(
            transaction_type='IN',
            amount=amount,
            currency='AFG',
            from_who=f"{self.sale.sale_number} - {self.sale.customer_name}",
            money_type='SALE_DEBT',
            date=self.payment_date,
            description=self._description(),
        )
        return trx

    def update_transaction(self):
        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        new_amount = Decimal(str(self.amount or 0))

        # ✅ برای IN، اگر مبلغ جدید کمتر شود یعنی باید از خزانه برگردد
        if new_amount < old_amount:
            check_treasury_balance(old_amount - new_amount, 'AFG')

        trx.amount = new_amount
        trx.date = self.payment_date
        trx.from_who = f"{self.sale.sale_number} - {self.sale.customer_name}"
        trx.description = self._description()
        trx.save()

    @staticmethod
    def _recalc_sale(sale_id):
        """بازمحاسبه received_amount و remaining_amount یک فروش مشخص"""
        from django.db.models import Sum

        if not sale_id:
            return

        try:
            sale = Sale.objects.get(pk=sale_id)
        except Sale.DoesNotExist:
            return

        debts_total = (
            SaleDebt.objects
            .filter(sale_id=sale_id)
            .aggregate(total=Sum('amount'))
        )['total'] or Decimal('0')

        initial = sale.initial_received_amount or Decimal('0')
        new_received = initial + debts_total
        new_remaining = sale.total_amount - new_received

        Sale.objects.filter(pk=sale_id).update(
            received_amount=new_received,
            remaining_amount=new_remaining,
        )

    def _sync_sale_totals(self):
        """بازمحاسبه received_amount فروش"""
        if not self.sale_id:
            return
        self._recalc_sale(self.sale_id)

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_sale_id = None

        if not is_new:
            old_sale_id = (
                type(self).objects
                .filter(pk=self.pk)
                .values_list('sale_id', flat=True)
                .first()
            )

        if is_new:
            self.treasury_transaction = self.create_transaction()
        else:
            self.update_transaction()

        super().save(*args, **kwargs)

        self._sync_sale_totals()

        if old_sale_id and old_sale_id != self.sale_id:
            self._recalc_sale(old_sale_id)

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        sale_id = self.sale_id
        _detach_and_delete_transaction(self)
        super().delete(*args, **kwargs)
        self._recalc_sale(sale_id)