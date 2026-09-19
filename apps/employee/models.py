# apps/employee/models.py

from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal


# ======================================================================
# Employee
# ======================================================================
class Employee(models.Model):
    """کارمند"""

    full_name = models.CharField(max_length=200, verbose_name="نام کامل")
    father_name = models.CharField(max_length=200, verbose_name="نام پدر")
    tazkera_number = models.CharField(max_length=50, blank=True, null=True, verbose_name="شماره تذکره")
    phone_number = models.CharField(max_length=20, verbose_name="شماره تماس")
    address = models.TextField(blank=True, null=True, verbose_name="آدرس")

    image = models.ImageField(upload_to='employees/', blank=True, null=True, verbose_name="عکس کارمند")
    tazkera_image = models.ImageField(upload_to='employees/tazkera/', blank=True, null=True, verbose_name="عکس تذکره")

    position = models.CharField(max_length=200, blank=True, null=True, verbose_name="وظیفه / سمت")
    join_date = models.DateField(default=timezone.now, verbose_name="تاریخ شمولیت")
    leave_date = models.DateField(blank=True, null=True, verbose_name="تاریخ منفکی")

    base_salary = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        verbose_name="معاش پایه (افغانی)"
    )

    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "کارمند"
        verbose_name_plural = "کارمندان"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['full_name']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['join_date']),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.father_name}"

    @property
    def is_active(self):
        return self.leave_date is None

    @property
    def is_terminated(self):
        return self.leave_date is not None

    @property
    def work_duration_days(self):
        end = self.leave_date or timezone.now().date()
        return (end - self.join_date).days

    @property
    def work_duration_display(self):
        days = self.work_duration_days
        years = days // 365
        months = (days % 365) // 30
        remaining_days = (days % 365) % 30

        parts = []
        if years > 0:
            parts.append(f'{years} سال')
        if months > 0:
            parts.append(f'{months} ماه')
        if remaining_days > 0 or not parts:
            parts.append(f'{remaining_days} روز')

        return ' و '.join(parts)

    def terminate(self, leave_date):
        self.leave_date = leave_date
        self.save(update_fields=['leave_date', 'updated_at'])

    def reactivate(self):
        self.leave_date = None
        self.save(update_fields=['leave_date', 'updated_at'])

    def can_be_deleted(self):
        return not self.salaries.exists()


# ======================================================================
# Salary
# ======================================================================
class Salary(models.Model):
    """پرداخت معاش ماهانه کارمند"""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name='salaries',
        verbose_name="کارمند"
    )

    salary_month = models.CharField(max_length=20, verbose_name="ماه معاش")

    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="مقدار معاش (افغانی)"
    )

    payment_date = models.DateField(default=timezone.now, verbose_name="تاریخ پرداخت")

    treasury_transaction = models.ForeignKey(
        'treasury.Transaction',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='salary_transactions',
        verbose_name="تراکنش"
    )

    note = models.TextField(blank=True, null=True, verbose_name="یادداشت")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")

    class Meta:
        verbose_name = "معاش"
        verbose_name_plural = "معاشات"
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['employee', 'payment_date']),
            models.Index(fields=['salary_month']),
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.amount} افغانی ({self.salary_month})"

    def _get_treasury(self):
        from apps.treasury.models import Treasury
        return Treasury.get_treasury()

    def _check_treasury_balance(self, amount):
        from apps.treasury.exceptions import InsufficientTreasuryBalance
        treasury = self._get_treasury()
        amount = Decimal(str(amount))
        if treasury.balance_afg < amount:
            raise InsufficientTreasuryBalance(
                'موجودی خزانه برای پرداخت معاش کافی نیست!',
                current_balance=treasury.balance_afg,
                required_amount=amount,
                currency='AFG'
            )
        return True

    def _description(self):
        parts = [f'معاش {self.employee.full_name}']
        parts.append(f'ماه: {self.salary_month}')
        if self.note:
            parts.append(f'یادداشت: {self.note}')
        return ' | '.join(parts)

    def create_transaction(self):
        """Creates the OUT transaction. Treasury deduction handled by Transaction.save()."""
        from apps.treasury.models import Transaction

        amount = Decimal(str(self.amount or 0))

        if amount > 0:
            self._check_treasury_balance(amount)

        trx = Transaction.objects.create(
            transaction_type='OUT',
            amount=amount,
            currency='AFG',
            from_who=f"{self.employee.full_name} - {self.salary_month}",
            money_type='SALARY',
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

        if new_amount > old_amount:
            self._check_treasury_balance(new_amount - old_amount)

        trx.amount = new_amount
        trx.date = self.payment_date
        trx.from_who = f"{self.employee.full_name} - {self.salary_month}"
        trx.description = self._description()
        trx.save()

    @db_transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if self.amount is None or self.amount < 0:
            raise ValidationError('مقدار معاش نمی‌تواند منفی باشد!')

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

            Salary.objects.filter(pk=self.pk).update(treasury_transaction=None)
            Transaction.objects.filter(pk=trx.pk).delete()

        super().delete(*args, **kwargs)