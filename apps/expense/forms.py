# apps/expense/forms.py

from django import forms
from .models import Expense
from django.utils import timezone
import json
from decimal import Decimal


class ExpenseForm(forms.ModelForm):
    """
    Form for creating expense with multiple items
    """

    items_json = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )

    expense_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ مصرف",
        required=True,
        initial=timezone.now().date,
        error_messages={
            'required': 'لطفاً تاریخ مصرف را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'عنوان مصرف را وارد کنید',
            'dir': 'rtl'
        }),
        label="عنوان مصرف",
        required=True,
        error_messages={
            'required': 'لطفاً عنوان مصرف را وارد کنید',
            'max_length': 'عنوان مصرف نمی‌تواند بیشتر از ۲۰۰ حرف باشد'
        }
    )

    # Form fields for items
    name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control name-input',
            'placeholder': 'نام مصرف',
            'dir': 'rtl',
            'data-field': 'name'
        }),
        label="نام مصرف",
        required=False
    )

    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control quantity-input',
            'placeholder': 'تعداد',
            'dir': 'rtl',
            'data-field': 'quantity',
            'min': '1'
        }),
        label="تعداد",
        required=False
    )

    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control price-input',
            'placeholder': 'مبلغ فی واحد',
            'dir': 'rtl',
            'data-field': 'unit_price',
            'step': '0.01'
        }),
        label="مبلغ فی واحد",
        required=False
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

    image = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'dir': 'rtl',
            'accept': 'image/*'
        }),
        label="عکس",
        required=False
    )

    class Meta:
        model = Expense
        fields = [
            'expense_number', 'expense_date', 'title',
            'items_json', 'note', 'image'
        ]
        widgets = {
            'expense_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'توسط سیستم تولید می‌شود',
                'dir': 'rtl',
                'readonly': 'readonly'
            }),
        }
        labels = {
            'expense_number': 'شماره مصرف',
            'expense_date': 'تاریخ مصرف',
            'title': 'عنوان مصرف',
            'note': 'یادداشت',
            'image': 'عکس'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing an existing instance, populate the JSON data
        if self.instance and self.instance.pk and self.instance.items:
            self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)

        # If expense_date is not set, default to today
        if not self.initial.get('expense_date'):
            self.initial['expense_date'] = timezone.now().date()

        # Make expense_number readonly
        self.fields['expense_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['expense_number'].required = False

    def clean(self):
        cleaned_data = super().clean()

        # Validate expense_date
        expense_date = cleaned_data.get('expense_date')
        if not expense_date:
            self.add_error('expense_date', 'لطفاً تاریخ مصرف را وارد کنید')

        # Validate title
        title = cleaned_data.get('title')
        if not title:
            self.add_error('title', 'لطفاً عنوان مصرف را وارد کنید')

        # Get the items from the hidden JSON field
        items_json = cleaned_data.get('items_json')

        if items_json:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    for idx, item in enumerate(items):
                        # Validate name
                        if not item.get('name'):
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً نام مصرف را وارد کنید')

                        # Validate quantity
                        quantity = item.get('quantity')
                        if not quantity or int(quantity) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً تعداد را وارد کنید')

                        # Validate unit_price
                        unit_price = item.get('unit_price')
                        if not unit_price or float(unit_price) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً مبلغ فی واحد را وارد کنید')
            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Parse items from JSON field
        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)

            enhanced_items = []
            for item in items:
                enhanced_item = {
                    'name': item.get('name', ''),
                    'quantity': int(item.get('quantity', 0)),
                    'unit_price': float(item.get('unit_price', 0)),
                }
                enhanced_items.append(enhanced_item)

            instance.items = enhanced_items

            # Calculate total amount
            instance.total_amount = sum(
                Decimal(str(item['quantity'])) * Decimal(str(item['unit_price']))
                for item in enhanced_items
            )

        if commit:
            instance.save()

        return instance