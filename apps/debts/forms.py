from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import PurchaseDebt, SaleDebt
from apps.purchasesale.models import Purchase, Sale


# ======================================================================
# PurchaseDebtForm
# ======================================================================
class PurchaseDebtForm(forms.ModelForm):
    """
    Form for recording purchase debt payment
    """

    purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.filter(remaining_amount__gt=0),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'dir': 'rtl',
            'data-placeholder': 'انتخاب خرید...'
        }),
        label="خرید",
        required=True,
        error_messages={
            'required': 'لطفاً خرید را انتخاب کنید',
            'invalid_choice': 'خرید انتخاب شده معتبر نیست'
        }
    )

    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'مبلغ پرداختی',
            'dir': 'rtl',
            'step': '0.01',
            'min': '0.01'
        }),
        label="مبلغ پرداختی",
        required=True,
        error_messages={
            'required': 'لطفاً مبلغ پرداختی را وارد کنید',
            'min_value': 'مبلغ پرداختی باید بزرگتر از صفر باشد',
            'invalid': 'لطفاً یک مبلغ معتبر وارد کنید'
        }
    )

    payment_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ پرداخت",
        required=True,
        initial=timezone.now().date,
        error_messages={
            'required': 'لطفاً تاریخ پرداخت را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'یادداشت (اختیاری)',
            'dir': 'rtl',
            'rows': 3
        }),
        label="یادداشت",
        required=False
    )

    class Meta:
        model = PurchaseDebt
        fields = ['purchase', 'amount', 'payment_date', 'note']
        labels = {
            'purchase': 'خرید',
            'amount': 'مبلغ پرداختی',
            'payment_date': 'تاریخ پرداخت',
            'note': 'یادداشت',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # در حالت ویرایش، همه خریدها را نشان بده (ولی قابل تغییر نباشد)
        if self.instance and self.instance.pk:
            self.fields['purchase'].queryset = Purchase.objects.all()
            self.fields['purchase'].widget.attrs['disabled'] = True

        # اگر purchase از ابتدا مشخص شده باشد
        initial = kwargs.get('initial') or {}
        if initial.get('purchase'):
            purchase = initial['purchase']
            self.fields['purchase'].queryset = Purchase.objects.filter(id=purchase.id)
            self.fields['purchase'].initial = purchase
            self.fields['purchase'].widget.attrs['disabled'] = True

    def clean(self):
        cleaned_data = super().clean()

        purchase = cleaned_data.get('purchase')
        amount = cleaned_data.get('amount')

        if purchase and amount:
            amount = Decimal(str(amount))

            # سقف مجاز
            max_allowed = Decimal(str(purchase.remaining_amount or 0))

            # اگر در حال ویرایش هستیم و purchase عوض نشده،
            # مبلغ قبلی را به سقف اضافه کن (چون قبلاً از remaining کم شده)
            if self.instance and self.instance.pk:
                if self.instance.purchase_id == purchase.id:
                    old_amount = Decimal(str(self.instance.amount or 0))
                    max_allowed += old_amount

            if amount > max_allowed:
                self.add_error(
                    'amount',
                    f'مبلغ پرداختی نمی‌تواند بیشتر از بدهی باقی‌مانده ({max_allowed} افغانی) باشد'
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        if commit:
            instance.save()

        return instance


# ======================================================================
# SaleDebtForm
# ======================================================================
class SaleDebtForm(forms.ModelForm):
    """
    Form for recording sale debt payment from customer
    """

    sale = forms.ModelChoiceField(
        queryset=Sale.objects.filter(remaining_amount__gt=0),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'dir': 'rtl',
            'data-placeholder': 'انتخاب فروش...'
        }),
        label="فروش",
        required=True,
        error_messages={
            'required': 'لطفاً فروش را انتخاب کنید',
            'invalid_choice': 'فروش انتخاب شده معتبر نیست'
        }
    )

    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'مبلغ دریافتی',
            'dir': 'rtl',
            'step': '0.01',
            'min': '0.01'
        }),
        label="مبلغ دریافتی",
        required=True,
        error_messages={
            'required': 'لطفاً مبلغ دریافتی را وارد کنید',
            'min_value': 'مبلغ دریافتی باید بزرگتر از صفر باشد',
            'invalid': 'لطفاً یک مبلغ معتبر وارد کنید'
        }
    )

    payment_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ دریافت",
        required=True,
        initial=timezone.now().date,
        error_messages={
            'required': 'لطفاً تاریخ دریافت را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'یادداشت (اختیاری)',
            'dir': 'rtl',
            'rows': 3
        }),
        label="یادداشت",
        required=False
    )

    class Meta:
        model = SaleDebt
        fields = ['sale', 'amount', 'payment_date', 'note']
        labels = {
            'sale': 'فروش',
            'amount': 'مبلغ دریافتی',
            'payment_date': 'تاریخ دریافت',
            'note': 'یادداشت',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.fields['sale'].queryset = Sale.objects.all()
            self.fields['sale'].widget.attrs['disabled'] = True

        initial = kwargs.get('initial') or {}
        if initial.get('sale'):
            sale = initial['sale']
            self.fields['sale'].queryset = Sale.objects.filter(id=sale.id)
            self.fields['sale'].initial = sale
            self.fields['sale'].widget.attrs['disabled'] = True

    def clean(self):
        cleaned_data = super().clean()

        sale = cleaned_data.get('sale')
        amount = cleaned_data.get('amount')

        if sale and amount:
            amount = Decimal(str(amount))

            max_allowed = Decimal(str(sale.remaining_amount or 0))

            if self.instance and self.instance.pk:
                if self.instance.sale_id == sale.id:
                    old_amount = Decimal(str(self.instance.amount or 0))
                    max_allowed += old_amount

            if amount > max_allowed:
                self.add_error(
                    'amount',
                    f'مبلغ دریافتی نمی‌تواند بیشتر از بدهی باقی‌مانده ({max_allowed} افغانی) باشد'
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        if commit:
            instance.save()

        return instance