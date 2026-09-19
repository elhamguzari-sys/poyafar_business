# apps/expense/models.py

from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
import os


def get_treasury():
    from apps.treasury.models import Treasury
    treasury = Treasury.objects.first()
    if not treasury:
        treasury = Treasury.objects.create(balance_afg=Decimal('0'), balance_usd=Decimal('0'))
    return treasury


def check_treasury_balance(amount, currency='AFN'):
    from apps.treasury.exceptions import InsufficientTreasuryBalance

    treasury = get_treasury()
    amount = Decimal(str(amount))

    if currency in ('AFN', 'AFG'):
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
# Expense - مصارف
# ======================================================================
class Expense(models.Model):
    """مدیریت مصارف — مثل خرید، چند قلم در یک بل"""

    expense_number = models.CharField(
        max_length=100, unique=True, blank=True,
        verbose_name="شماره مصرف"
    )

    expense_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="تاریخ مصرف"
    )

    title = models.CharField(
        max_length=200,
        verbose_name="عنوان مصرف"
    )

    items = models.JSONField(
        default=list,
        verbose_name="اقلام مصرف"
    )

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="مجموع کل (افغانی)"
    )

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='expense_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    image = models.ImageField(
        upload_to='expenses/', blank=True, null=True,
        verbose_name="عکس"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "مصرف"
        verbose_name_plural = "مصارف"
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['expense_date']),
            models.Index(fields=['expense_number']),
        ]

    def __str__(self):
        return f"{self.expense_number} - {self.title}"

    def generate_expense_number(self):
        last = Expense.objects.all().order_by('-id').first()

        if last and last.expense_number:
            try:
                if last.expense_number.startswith('EXP_'):
                    next_number = int(last.expense_number.split('_')[1]) + 1
                else:
                    next_number = 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1

        expense_number = f'EXP_{next_number}'
        while Expense.objects.filter(expense_number=expense_number).exclude(pk=self.pk).exists():
            next_number += 1
            expense_number = f'EXP_{next_number}'
        return expense_number

    def calculate_item_total(self, item):
        quantity = Decimal(str(item.get('quantity', 0) or 0))
        price = Decimal(str(item.get('unit_price', 0) or 0))
        return quantity * price

    def calculate_total_amount(self):
        total = Decimal('0')
        for item in self.items:
            total += self.calculate_item_total(item)
        return total

    def validate_items(self):
        if not self.items:
            raise ValidationError('حداقل یک قلم مصرف باید اضافه شود!')

        for idx, item in enumerate(self.items):
            name = item.get('name')
            if not name:
                raise ValidationError(f'قلم {idx + 1}: نام مصرف الزامی است!')

            quantity = int(item.get('quantity', 0) or 0)
            if quantity <= 0:
                raise ValidationError(f'قلم {idx + 1}: تعداد باید بزرگتر از صفر باشد!')

            price = Decimal(str(item.get('unit_price', 0) or 0))
            if price <= 0:
                raise ValidationError(f'قلم {idx + 1}: مبلغ فی واحد باید بزرگتر از صفر باشد!')

    @property
    def items_count(self):
        return len(self.items)

    def _description(self):
        parts = [f'مصرف: {self.title}']
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        items_summary = []
        for item in self.items:
            name = item.get('name', '---')
            qty = item.get('quantity', 0)
            items_summary.append(f'{name} × {qty}')
        if items_summary:
            parts.append('اقلام: ' + '، '.join(items_summary))
        return ' | '.join(parts)

    def create_transaction(self):
        """Creates the OUT transaction. Treasury deduction handled by Transaction.save()."""
        from apps.treasury.models import Transaction

        amount = Decimal(str(self.total_amount or 0))

        if amount > 0:
            check_treasury_balance(amount, 'AFN')

        trx = Transaction.objects.create(
            transaction_type='OUT',
            amount=amount,
            currency='AFG',
            from_who=f"{self.expense_number} - {self.title}",
            money_type='EXPENSE',
            date=self.expense_date,
            description=self._description(),
        )

        # Copy image to transaction
        if self.image:
            try:
                self.image.seek(0)
                from django.core.files.base import ContentFile
                trx.transaction_image.save(
                    f"expense_{trx.id}_{self.expense_number}.jpg",
                    ContentFile(self.image.read()),
                    save=True
                )
            except Exception as e:
                print(f'Error copying image to transaction: {e}')

        return trx

    def update_transaction(self):
        if not self.treasury_transaction:
            self.treasury_transaction = self.create_transaction()
            return

        trx = self.treasury_transaction
        old_amount = Decimal(str(trx.amount or 0))
        new_amount = Decimal(str(self.total_amount or 0))

        if new_amount > old_amount:
            check_treasury_balance(new_amount - old_amount, 'AFN')

        trx.amount = new_amount
        trx.date = self.expense_date
        trx.from_who = f"{self.expense_number} - {self.title}"
        trx.description = self._description()
        trx.save()

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.expense_number:
            self.expense_number = self.generate_expense_number()

        self.validate_items()
        self.total_amount = self.calculate_total_amount()

        if is_new:
            self.treasury_transaction = self.create_transaction()
        else:
            self.update_transaction()

        super().save(*args, **kwargs)

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        if self.treasury_transaction:
            from apps.treasury.models import Transaction, Treasury
            trx = self.treasury_transaction
            amount = Decimal(str(trx.amount or 0))
            currency = trx.currency or 'AFG'
            treasury = Treasury.get_treasury()

            if amount > 0:
                if trx.transaction_type == 'IN':
                    treasury.subtract_money(amount, currency)
                else:
                    treasury.add_money(amount, currency)

            Expense.objects.filter(pk=self.pk).update(treasury_transaction=None)
            Transaction.objects.filter(pk=trx.pk).delete()

            # Cleanup image
            if trx.transaction_image and trx.transaction_image.name:
                try:
                    if os.path.isfile(trx.transaction_image.path):
                        os.remove(trx.transaction_image.path)
                except Exception:
                    pass

        # Remove the expense's own image file
        if self.image:
            try:
                if os.path.isfile(self.image.path):
                    os.remove(self.image.path)
            except Exception:
                pass

        super().delete(*args, **kwargs)