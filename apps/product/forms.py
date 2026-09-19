from django import forms
from .models import Category, Product


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: الکترونیک'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: ELEC'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'توضیحات مختصر...'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False


class ProductForm(forms.ModelForm):
    """
    فرم کالا.
    توجه: shop_stock و stock_stock فیلدهای کش هستند و مستقیماً از فرم
    ویرایش نمی‌شوند. موجودی اولیه از طریق فیلدهای initial_* ثبت می‌گردد
    و از مسیر StockMovement روی Inventory اعمال می‌شود.
    """

    # موجودی اولیه هر موقعیت (فقط موقع ساخت کالای جدید استفاده می‌شود)
    initial_shop = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه دوکان",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '0',
            'min': '0',
        }),
    )
    initial_A = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه گدام A",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': '0', 'min': '0',
        }),
    )
    initial_B = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه گدام B",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': '0', 'min': '0',
        }),
    )
    initial_C = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه گدام C",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': '0', 'min': '0',
        }),
    )
    initial_D = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه گدام D",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': '0', 'min': '0',
        }),
    )
    initial_E = forms.IntegerField(
        required=False, min_value=0, initial=0,
        label="موجودی اولیه گدام E",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': '0', 'min': '0',
        }),
    )

    class Meta:
        model = Product
        fields = [
            'sku', 'name', 'category', 'description', 'image', 'unit',
            'purchase_price', 'wholesale_price', 'sale_price',
            'min_stock', 'status',
        ]
        widgets = {
            'sku': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: SKU_1',
                'readonly': 'readonly',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: لپتاپ ایسوس',
            }),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'توضیحات جنس...',
            }),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'purchase_price': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'مثال: 1000', 'min': '0',
            }),
            'wholesale_price': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'مثال: 1200', 'min': '0',
            }),
            'sale_price': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'مثال: 1500', 'min': '0',
            }),
            'min_stock': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'مثال: 10', 'min': '0',
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['sku'].required = False
        self.fields['description'].required = False
        self.fields['image'].required = False
        self.fields['purchase_price'].required = False
        self.fields['wholesale_price'].required = False
        self.fields['sale_price'].required = False
        self.fields['min_stock'].required = False

        self.fields['category'].queryset = Category.objects.filter(is_active=True)

        if not self.instance.pk:
            self.fields['purchase_price'].initial = 0
            self.fields['wholesale_price'].initial = 0
            self.fields['sale_price'].initial = 0
            self.fields['min_stock'].initial = 0
            self.fields['status'].initial = 'active'
        else:
            # در حالت ویرایش، موجودی فعلی را از Inventory نشان بده (فقط خواندنی)
            self.fields['initial_shop'].initial = self.instance.stock_in_code('shop')
            for code in ['A', 'B', 'C', 'D', 'E']:
                self.fields[f'initial_{code}'].initial = self.instance.stock_in_code(code)
                self.fields[f'initial_{code}'].widget.attrs['readonly'] = 'readonly'
            self.fields['initial_shop'].widget.attrs['readonly'] = 'readonly'

    def clean_sku(self):
        sku = self.cleaned_data.get('sku')
        return sku or None

    def clean(self):
        cleaned_data = super().clean()

        purchase_price = cleaned_data.get('purchase_price')
        wholesale_price = cleaned_data.get('wholesale_price')
        sale_price = cleaned_data.get('sale_price')

        if purchase_price and sale_price and sale_price < purchase_price:
            self.add_error('sale_price', 'قیمت فروش نمی‌تواند کمتر از قیمت خرید باشد')

        if purchase_price and wholesale_price and wholesale_price < purchase_price:
            self.add_error('wholesale_price', 'قیمت عمده نمی‌تواند کمتر از قیمت خرید باشد')

        min_stock = cleaned_data.get('min_stock')
        if min_stock is not None and min_stock < 0:
            self.add_error('min_stock', 'حداقل موجودی نمی‌تواند منفی باشد')

        return cleaned_data

    def save(self, commit=True):
        """
        ذخیره کالا + ثبت موجودی اولیه از مسیر StockMovement
        (فقط موقع ساخت کالای جدید)
        """
        product = super().save(commit=False)
        is_new = product.pk is None

        if commit:
            product.save()

            if is_new:
                initial = {
                    'shop': self.cleaned_data.get('initial_shop') or 0,
                    'A': self.cleaned_data.get('initial_A') or 0,
                    'B': self.cleaned_data.get('initial_B') or 0,
                    'C': self.cleaned_data.get('initial_C') or 0,
                    'D': self.cleaned_data.get('initial_D') or 0,
                    'E': self.cleaned_data.get('initial_E') or 0,
                }
                for code, qty in initial.items():
                    if qty > 0:
                        product._adjust_inventory(code, +qty, 'IN')

                # کش را دوباره از Inventory پر کن
                product.refresh_from_db()

        return product