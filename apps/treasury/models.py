# apps/treasury/models.py

from django.db import models, transaction as db_transaction
from django.utils import timezone
from decimal import Decimal
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFit
import os


# ======================================================================
# Helper: بررسی معتبر بودن مقدار تراکنش
# ======================================================================
def should_create_transaction(amount):
    """
    بررسی می‌کند که آیا مقدار تراکنش معتبر است.
    تراکنش با مقدار صفر یا منفی نباید ساخته شود.
    """
    try:
        amount_decimal = Decimal(str(amount or 0))
    except (ValueError, TypeError):
        return False

    return amount_decimal > Decimal('0')


# ======================================================================
# Treasury - خزانه
# ======================================================================
class Treasury(models.Model):
    """خزانه با موجودی افغانی و دالر"""

    balance_afg = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="موجودی افغانی"
    )

    balance_usd = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="موجودی دالر"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخرین بروزرسانی"
    )

    def __str__(self):
        return f"خزانه: {self.balance_afg} افغانی | {self.balance_usd} دالر"

    @classmethod
    def get_treasury(cls):
        """Get or create the single treasury instance (race-safe)"""
        with db_transaction.atomic():
            treasury = cls.objects.select_for_update().first()
            if not treasury:
                treasury = cls.objects.create()
            return treasury

    def add_money(self, amount, currency='AFG'):
        """Add money to treasury"""
        amount = Decimal(str(amount))
        if currency == 'AFG':
            self.balance_afg += amount
            self.save(update_fields=['balance_afg', 'updated_at'])
        else:
            self.balance_usd += amount
            self.save(update_fields=['balance_usd', 'updated_at'])
        return True

    def subtract_money(self, amount, currency='AFG'):
        """Subtract money from treasury if sufficient balance"""
        amount = Decimal(str(amount))
        if currency == 'AFG':
            if self.balance_afg >= amount:
                self.balance_afg -= amount
                self.save(update_fields=['balance_afg', 'updated_at'])
                return True
        else:
            if self.balance_usd >= amount:
                self.balance_usd -= amount
                self.save(update_fields=['balance_usd', 'updated_at'])
                return True
        return False

    @property
    def balance(self):
        """Get current balance (افغانی)"""
        return self.balance_afg

    def delete(self, *args, **kwargs):
        raise PermissionError(
            'خزانه را نمی‌توان حذف کرد. برای صفر کردن موجودی، از عملیات تراکنش استفاده کنید.'
        )

    class Meta:
        verbose_name = "خزانه"
        verbose_name_plural = "خزانه"


# ======================================================================
# Transaction - تراکنش
# ======================================================================
class Transaction(models.Model):
    """Record of all money movements"""

    TYPE_CHOICES = [
        ('SARAFI', 'صرافی'),
        ('BANK', 'بانک'),
        ('PERSONAL', 'شخصی'),
        ('LOAN', 'قرض'),
        ('PURCHASE', 'خرید'),
        ('SALE', 'فروش'),
        ('PURCHASE_DEBT', 'پرداخت بدهی خرید'),
        ('SALE_DEBT', 'دریافت بدهی فروش'),
        ('CUSTOMER_RETURN', 'مرجوعی مشتری'),
        ('SUPPLIER_RETURN', 'مرجوعی به تأمین‌کننده'),
        ('EXPENSE', 'مصرف'),
        ('SALARY', 'معاش'),
        ('OTHER', 'سایر'),
    ]

    TRANSACTION_TYPE_CHOICES = [
        ('IN', 'واریز'),
        ('OUT', 'برداشت'),
    ]

    CURRENCY_CHOICES = [
        ('AFG', 'افغانی'),
        ('USD', 'دالر'),
    ]

    transaction_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="شماره تراکنش"
    )

    transaction_type = models.CharField(
        max_length=3,
        choices=TRANSACTION_TYPE_CHOICES,
        verbose_name="نوع تراکنش"
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name="مقدار"
    )

    currency = models.CharField(
        max_length=5,
        choices=CURRENCY_CHOICES,
        default='AFG',
        verbose_name="ارز"
    )

    from_who = models.CharField(
        max_length=200,
        verbose_name="از چه کسی"
    )

    money_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        verbose_name="نوع پول"
    )

    date = models.DateTimeField(
        default=timezone.now,
        verbose_name="تاریخ"
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="توضیحات"
    )

    transaction_image = ProcessedImageField(
        upload_to='transaction_image/',
        processors=[ResizeToFit(800, 800)],
        format='JPEG',
        options={'quality': 85},
        blank=True,
        null=True,
        verbose_name="تصویر تراکنش"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخرین ویرایش"
    )

    # ----------------------------------------------------------------
    # Reference number
    # ----------------------------------------------------------------
    def generate_transaction_number(self):
        """Generate a unique transaction number (race-safe retry loop)"""
        from datetime import datetime

        date_str = datetime.now().strftime('%Y%m%d')
        base_prefix = f'TRX-{date_str}'

        for attempt in range(20):
            last_transaction = Transaction.objects.filter(
                transaction_number__startswith=base_prefix
            ).order_by('-transaction_number').first()

            if last_transaction:
                try:
                    last_seq = int(last_transaction.transaction_number.split('-')[-1])
                    new_seq = last_seq + 1
                except (ValueError, IndexError):
                    new_seq = 1
            else:
                new_seq = 1

            candidate = f"{base_prefix}-{new_seq:04d}"
            if not Transaction.objects.filter(transaction_number=candidate).exists():
                return candidate

        raise RuntimeError('قادر به تولید شماره تراکنش یکتا نبودیم.')

    # ----------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------
    def clean(self):
        """اعتبارسنجی مدل — مقدار باید بزرگتر از صفر باشد"""
        super().clean()

        from django.core.exceptions import ValidationError

        amount = Decimal(str(self.amount or 0))
        if amount <= Decimal('0'):
            raise ValidationError({
                'amount': 'مقدار تراکنش باید بزرگتر از صفر باشد.'
            })

    # ----------------------------------------------------------------
    # Treasury sync helpers
    # ----------------------------------------------------------------
    def _apply_to_treasury(self, amount, transaction_type, currency):
        """
        Apply a raw delta to treasury (no reversal logic here).
        Raises InsufficientTreasuryBalance if balance insufficient for OUT.
        """
        from apps.treasury.exceptions import InsufficientTreasuryBalance

        treasury = Treasury.get_treasury()
        amount = Decimal(str(amount))

        if transaction_type == 'IN':
            treasury.add_money(amount, currency)
        elif transaction_type == 'OUT':
            ok = treasury.subtract_money(amount, currency)
            if not ok:
                current = treasury.balance_afg if currency == 'AFG' else treasury.balance_usd
                raise InsufficientTreasuryBalance(
                    f'موجودی خزانه به {"افغانی" if currency == "AFG" else "دالر"} کافی نیست!',
                    current_balance=current,
                    required_amount=amount,
                    currency=currency,
                )

    def update_treasury_balance(self, old_amount=None, old_transaction_type=None, old_currency=None):
        """
        Update treasury balance when transaction is modified.
        Reverses old effect (if any), then applies new effect.
        """
        # Step 1: Reverse old effect
        if old_amount is not None and old_transaction_type is not None:
            old_amount_dec = Decimal(str(old_amount or 0))
            if old_amount_dec > 0:
                old_currency = old_currency or 'AFG'
                reverse_type = 'OUT' if old_transaction_type == 'IN' else 'IN'
                self._apply_to_treasury(old_amount_dec, reverse_type, old_currency)

        # Step 2: Apply new effect
        new_amount_dec = Decimal(str(self.amount or 0))
        if new_amount_dec > 0:
            self._apply_to_treasury(new_amount_dec, self.transaction_type, self.currency)

        return True

    # ----------------------------------------------------------------
    # ✅ save — atomic, safe reversal + apply + zero-amount guard
    # ----------------------------------------------------------------
    def save(self, *args, **kwargs):
        """
        Save with zero-amount guard.
        اگر مقدار صفر یا منفی باشد، تراکنش ذخیره نمی‌شود.
        """
        # ✅ جلوگیری از ثبت تراکنش صفر یا منفی
        amount = Decimal(str(self.amount or 0))
        if amount <= Decimal('0'):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                '❌ مقدار تراکنش نمی‌تواند صفر یا منفی باشد. '
                'لطفاً مبلغ معتبر وارد کنید.'
            )

        is_new = self.pk is None

        if is_new and not self.transaction_number:
            self.transaction_number = self.generate_transaction_number()

        with db_transaction.atomic():
            if is_new:
                super().save(*args, **kwargs)
                self.update_treasury_balance()
            else:
                old = Transaction.objects.get(pk=self.pk)
                old_amount = old.amount
                old_type = old.transaction_type
                old_currency = old.currency

                super().save(*args, **kwargs)

                if (
                    old_amount != self.amount
                    or old_type != self.transaction_type
                    or old_currency != self.currency
                ):
                    self.update_treasury_balance(old_amount, old_type, old_currency)

    # ----------------------------------------------------------------
    # can_be_deleted — check if linked to a business document
    # ----------------------------------------------------------------
    def can_be_deleted(self):
        """
        A treasury Transaction should NOT be deleted directly if it's
        linked to a business document (Purchase, Sale, Salary, Expense,
        Debt, Return, etc.).
        """
        business_relations = [
            'purchase_transactions',
            'sale_transactions',
            'expense_transactions',
            'salary_transactions',
            'purchase_debt_transactions',
            'sale_debt_transactions',
            'customer_return_transactions',
            'supplier_return_transactions',
        ]

        for rel in business_relations:
            manager = getattr(self, rel, None)
            if manager is not None and manager.exists():
                return False

        return True

    # ----------------------------------------------------------------
    # delete — reverse treasury + cleanup image + guard
    # ----------------------------------------------------------------
    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        """
        Delete transaction and reverse its effect on treasury.
        Raises TreasuryReversalBlocked if reversal would make treasury negative.
        Raises ProtectedError if linked to a business document.
        """
        from apps.treasury.exceptions import TreasuryReversalBlocked

        with db_transaction.atomic():
            treasury = Treasury.get_treasury()
            amount = Decimal(str(self.amount or 0))
            currency = self.currency or 'AFG'
            reverse_type = 'OUT' if self.transaction_type == 'IN' else 'IN'

            # ✅ اگر مقدار صفر بود، فقط حذف کن بدون معکوس کردن خزانه
            if amount > 0:
                # --- Pre-check reversal impact ---
                if reverse_type == 'OUT':
                    current = treasury.balance_afg if currency == 'AFG' else treasury.balance_usd
                    if current < amount:
                        raise TreasuryReversalBlocked(
                            'برگشت این تراکنش باعث منفی شدن خزانه می‌شود. '
                            'ابتدا تراکنش‌های بعدی را بررسی کنید.',
                            transaction=self,
                            current_balance=current,
                            would_become=current - amount,
                            currency=currency,
                        )

                # --- Perform reversal ---
                if reverse_type == 'IN':
                    treasury.add_money(amount, currency)
                elif reverse_type == 'OUT':
                    ok = treasury.subtract_money(amount, currency)
                    if not ok:
                        current = treasury.balance_afg if currency == 'AFG' else treasury.balance_usd
                        raise TreasuryReversalBlocked(
                            'برگشت این تراکنش باعث منفی شدن خزانه می‌شود.',
                            transaction=self,
                            current_balance=current,
                            would_become=current - amount,
                            currency=currency,
                        )

            # --- Safe image deletion ---
            if self.transaction_image and self.transaction_image.name:
                try:
                    if os.path.isfile(self.transaction_image.path):
                        os.remove(self.transaction_image.path)
                except Exception as e:
                    print(f'⚠️ خطا در حذف تصویر تراکنش: {e}')

            super().delete(*args, **kwargs)

    def __str__(self):
        type_symbol = '+' if self.transaction_type == 'IN' else '-'
        currency_label = 'افغانی' if self.currency == 'AFG' else 'دالر'
        return f"{self.transaction_number} - {type_symbol}{self.amount} {currency_label}"

    class Meta:
        verbose_name = "تراکنش"
        verbose_name_plural = "تراکنش‌ها"
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['money_type']),
            models.Index(fields=['currency']),
        ]