from django import forms
from django.db.models import Sum
from .models import StockMovement, Location, Inventory
from apps.product.models import Product


# ======================================================================
# Location Form
# ======================================================================
class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'code', 'type', 'is_active', 'note']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: گدام مرکزی'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: A یا shop'
            }),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'یادداشت اختیاری...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['note'].required = False

    def clean_code(self):
        code = self.cleaned_data.get('code')
        if code:
            code = code.strip()
            qs = Location.objects.filter(code=code)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('این کد قبلاً استفاده شده است.')
        return code


# ======================================================================
# Inventory Form — فقط خواندنی (نمایش)
# ======================================================================
class InventoryForm(forms.ModelForm):
    """
    فرم فقط‌خواندنی برای نمایش موجودی.
    تغییر موجودی از این فرم انجام نمی‌شود؛
    برای تغییر، از StockMovementForm استفاده کنید.
    """

    class Meta:
        model = Inventory
        fields = ['product', 'location', 'quantity', 'note']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control', 'disabled': True}),
            'location': forms.Select(attrs={'class': 'form-control', 'disabled': True}),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'readonly': 'readonly',
                'min': '0',
            }),
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'readonly': 'readonly',
                'placeholder': 'یادداشت...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.all()
        self.fields['location'].queryset = Location.objects.filter(is_active=True).order_by('type', 'code')
        self.fields['note'].required = False

        # همه فیلدها فقط خواندنی
        for field in self.fields.values():
            field.disabled = True


# ======================================================================
# StockMovement Form — استاندارد
# ======================================================================
class StockMovementForm(forms.ModelForm):
    """
    ثبت ورود / خروج کالا.
    موجودی Inventory به‌صورت خودکار در مدل آپدیت می‌شود
    و کش Product (shop_stock / stock_stock / current_stock) بازسازی می‌گردد.
    """

    class Meta:
        model = StockMovement
        fields = ['product', 'location', 'movement_type', 'quantity', 'reference_number', 'note']
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'انتخاب کالا'
            }),
            'location': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'انتخاب موقعیت'
            }),
            'movement_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 10 (ورود) یا 5 (خروج)',
                'min': '1'
            }),
            'reference_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'خودکار ساخته می‌شود',
                'readonly': 'readonly'
            }),
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'یادداشت اختیاری...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['reference_number'].required = False
        self.fields['note'].required = False

        self.fields['product'].queryset = Product.objects.all()
        self.fields['location'].queryset = Location.objects.filter(is_active=True).order_by('type', 'code')

        self.fields['quantity'].help_text = 'تعداد را همیشه مثبت وارد کنید؛ نوع حرکت (ورود/خروج) علامت را تعیین می‌کند.'
        self.fields['movement_type'].help_text = 'ورود = افزودن به موجودی، خروج = کاهش از موجودی'
        self.fields['location'].help_text = 'موقعیت مقصد/مبدأ را انتخاب کنید'

        # در حالت ویرایش، quantity را مثبت نشان بده
        if self.instance and self.instance.pk and self.instance.quantity is not None:
            self.fields['quantity'].initial = abs(self.instance.quantity)

    def clean_quantity(self):
        """quantity همیشه با علامت برمی‌گردد: IN → مثبت، OUT → منفی"""
        quantity = self.cleaned_data.get('quantity')
        movement_type = self.cleaned_data.get('movement_type')

        if quantity is None or quantity == 0:
            raise forms.ValidationError('تعداد نمی‌تواند صفر باشد')

        if quantity < 0:
            raise forms.ValidationError('تعداد را مثبت وارد کنید')

        if movement_type == 'OUT':
            return -quantity
        return quantity

    def clean_reference_number(self):
        reference_number = self.cleaned_data.get('reference_number')
        return reference_number or None

    def clean(self):
        cleaned_data = super().clean()

        product = cleaned_data.get('product')
        location = cleaned_data.get('location')
        movement_type = cleaned_data.get('movement_type')
        quantity = cleaned_data.get('quantity')

        if not (product and location and movement_type and quantity):
            return cleaned_data

        # موجودی این کالا در این موقعیت از Inventory
        inv = Inventory.objects.filter(product=product, location=location).first()
        location_stock = inv.quantity if inv else 0
        location_name = location.name

        # در حالت ویرایش، اثر حرکت قبلی را برگردان
        if self.instance and self.instance.pk:
            old = StockMovement.objects.get(pk=self.instance.pk)
            if old.location_id == location.id:
                if old.movement_type == 'OUT':
                    location_stock += abs(old.quantity)
                else:
                    location_stock -= abs(old.quantity)

        # برای OUT، موجودی باید کافی باشد
        if movement_type == 'OUT':
            required = abs(quantity)
            if location_stock < required:
                self.add_error(
                    'quantity',
                    f'موجودی {location_name} کافی نیست! موجودی فعلی: {location_stock}'
                )

        return cleaned_data