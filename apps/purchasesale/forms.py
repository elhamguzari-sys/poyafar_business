# apps/purchasesale/forms.py
from django import forms
from decimal import Decimal
import json

from datetime import datetime, time
from django.utils import timezone
from django.utils import timezone as dj_timezone

from .models import Purchase, Sale, SupplierReturn, CustomerReturn, Waste
from apps.product.models import Product
from apps.stock.models import Location, Inventory


# ======================================================================
# Helper: date ↔ aware-datetime conversion
# ======================================================================
def _aware_datetime_from_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        naive_dt = d
    else:
        naive_dt = datetime.combine(d, time.min)
    if dj_timezone.is_naive(naive_dt):
        return dj_timezone.make_aware(naive_dt)
    return naive_dt


def _local_date_from_datetime(dt):
    if dt is None:
        return None
    if dj_timezone.is_aware(dt):
        dt = dj_timezone.localtime(dt)
    return dt.date()


# ======================================================================
# Helper: استخراج مقدار قدیمی از items
# ======================================================================
def _extract_old_items_quantities(items):
    """{ 'pid_lid': qty } از items یک سند"""
    result = {}
    if not items:
        return result
    for item in items:
        key = f"{item.get('product_id')}_{item.get('location_id')}"
        result[key] = result.get(key, 0) + int(item.get('quantity', 0) or 0)
    return result


# ======================================================================
# PurchaseForm
# ======================================================================
class PurchaseForm(forms.ModelForm):
    """فرم ثبت خرید با چند قلم و ارز"""

    items_json = forms.CharField(widget=forms.HiddenInput(), required=False)

    purchase_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'dir': 'rtl'}),
        label="تاریخ خرید", required=True,
        error_messages={'required': 'لطفاً تاریخ خرید را وارد کنید', 'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'}
    )

    supplier_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام تأمین‌کننده را وارد کنید', 'dir': 'rtl'}),
        label="نام تأمین‌کننده", required=True,
        error_messages={'required': 'لطفاً نام تأمین‌کننده را وارد کنید'}
    )

    supplier_number = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'شماره تماس خریدار', 'dir': 'rtl'}),
        label="شماره خریدار", required=False
    )

    dollar_rate = forms.DecimalField(
        max_digits=15, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': 'مثال: 70', 'dir': 'rtl',
            'step': '0.01', 'min': '0', 'id': 'id_dollar_rate',
        }),
        label="نرخ امروز دالر", required=False,
        help_text="هر ۱ دالر = چند افغانی"
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control product-select', 'dir': 'rtl', 'data-field': 'product_id'}),
        label="محصول", required=False
    )

    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control quantity-input', 'placeholder': 'تعداد', 'dir': 'rtl', 'data-field': 'quantity', 'min': '1'}),
        label="تعداد", required=False
    )

    purchase_price = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control price-input', 'placeholder': 'قیمت فی واحد', 'dir': 'rtl', 'data-field': 'purchase_price', 'step': '0.01'}),
        label="قیمت فی واحد", required=False
    )

    location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).order_by('type', 'code'),
        widget=forms.Select(attrs={'class': 'form-control location-select', 'dir': 'rtl', 'data-field': 'location_id'}),
        label="موقعیت", required=False, empty_label="انتخاب موقعیت..."
    )

    paid_amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'مبلغ پرداخت‌شده', 'dir': 'rtl', 'step': '0.01', 'min': '0', 'value': '0'}),
        label="مبلغ پرداخت‌شده", required=False, initial=0
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'یادداشت (اختیاری)', 'dir': 'rtl', 'rows': 3}),
        label="یادداشت", required=False
    )

    class Meta:
        model = Purchase
        fields = ['purchase_number', 'purchase_date', 'supplier_name', 'supplier_number',
                  'dollar_rate', 'items_json', 'paid_amount', 'note']
        widgets = {
            'purchase_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'توسط سیستم تولید می‌شود', 'dir': 'rtl', 'readonly': 'readonly'}),
        }
        labels = {
            'purchase_number': 'شماره خرید',
            'purchase_date': 'تاریخ خرید',
            'supplier_name': 'نام تأمین‌کننده',
            'supplier_number': 'شماره خریدار',
            'dollar_rate': 'نرخ امروز دالر',
            'paid_amount': 'مبلغ پرداخت‌شده',
            'note': 'یادداشت'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.items:
                self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)
            if self.instance.dollar_rate:
                self.initial['dollar_rate'] = self.instance.dollar_rate
            self.initial['paid_amount'] = self.instance.initial_paid_amount or 0
            self.initial['purchase_date'] = _local_date_from_datetime(self.instance.purchase_date)
        else:
            if not self.initial.get('purchase_date'):
                self.initial['purchase_date'] = timezone.now().date()

        self.fields['purchase_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['purchase_number'].required = False

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get('purchase_date'):
            self.add_error('purchase_date', 'لطفاً تاریخ خرید را وارد کنید')
        if not cleaned_data.get('supplier_name'):
            self.add_error('supplier_name', 'لطفاً نام تأمین‌کننده را وارد کنید')
        if not cleaned_data.get('supplier_number'):
            cleaned_data['supplier_number'] = ''

        dollar_rate = cleaned_data.get('dollar_rate') or Decimal('0')
        items_json = cleaned_data.get('items_json')

        if items_json:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    item_keys = []
                    has_dollar = False

                    for idx, item in enumerate(items):
                        product = None
                        location_obj = None

                        if not item.get('product_id'):
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً محصول را انتخاب کنید')
                        else:
                            try:
                                product = Product.objects.get(id=item['product_id'])
                            except Product.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: محصول وجود ندارد')

                        quantity = item.get('quantity')
                        if not quantity or int(quantity) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً تعداد را وارد کنید')

                        price = item.get('purchase_price')
                        if not price or float(price) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً قیمت فی واحد را وارد کنید')

                        if item.get('currency') == 'USD':
                            has_dollar = True

                        location_id = item.get('location_id')
                        if not location_id:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً موقعیت را انتخاب کنید')
                        else:
                            try:
                                location_obj = Location.objects.get(id=location_id)
                            except Location.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: موقعیت معتبر نیست')

                        if product and location_obj:
                            item_key = f"{product.id}_{location_obj.id}"
                            if item_key in item_keys:
                                self.add_error(
                                    'items_json',
                                    f'قلم {idx + 1}: محصول {product.name} با موقعیت {location_obj.name} تکراری است'
                                )
                            item_keys.append(item_key)

                    if has_dollar and (not dollar_rate or dollar_rate <= 0):
                        self.add_error('dollar_rate', 'نرخ امروز دالر را وارد کنید (چون قلم دالری دارید)')

                    if not self.errors:
                        total_amount = Decimal('0')
                        for item in items:
                            q = Decimal(str(item.get('quantity', 0)))
                            p = Decimal(str(item.get('purchase_price', 0)))
                            if item.get('currency') == 'USD' and dollar_rate > 0:
                                total_amount += q * p * dollar_rate
                            else:
                                total_amount += q * p

                        paid_amount = Decimal(str(cleaned_data.get('paid_amount', 0) or 0))
                        if paid_amount > total_amount:
                            self.add_error('paid_amount', 'مبلغ پرداختی نمی‌تواند بیشتر از مجموع خرید باشد')
            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        purchase_date = self.cleaned_data.get('purchase_date')
        if purchase_date:
            instance.purchase_date = _aware_datetime_from_date(purchase_date)

        submitted_paid = self.cleaned_data.get('paid_amount')
        if submitted_paid is not None:
            instance.initial_paid_amount = Decimal(str(submitted_paid))
            instance.paid_amount = instance.initial_paid_amount

        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)
            locations_map = {loc.id: loc.name for loc in Location.objects.all()}
            enhanced_items = []
            for item in items:
                location_id = int(item.get('location_id', 0))
                enhanced_items.append({
                    'product_id': int(item.get('product_id', 0)),
                    'quantity': int(item.get('quantity', 0)),
                    'purchase_price': float(item.get('purchase_price', 0)),
                    'currency': item.get('currency', 'AFN'),
                    'location_id': location_id,
                    'location_name': locations_map.get(location_id, '---'),
                })
            instance.items = enhanced_items

        if commit:
            instance.save()
        return instance


# ======================================================================
# SaleForm
# ======================================================================
class SaleForm(forms.ModelForm):
    """فرم ثبت فروش با چند قلم و ارز"""

    items_json = forms.CharField(widget=forms.HiddenInput(), required=False)

    sale_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'dir': 'rtl'}),
        label="تاریخ فروش", required=True,
        error_messages={'required': 'لطفاً تاریخ فروش را وارد کنید', 'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'}
    )

    customer_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام مشتری را وارد کنید', 'dir': 'rtl'}),
        label="نام مشتری", required=True,
        error_messages={'required': 'لطفاً نام مشتری را وارد کنید'}
    )

    customer_number = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'شماره تماس مشتری', 'dir': 'rtl'}),
        label="شماره مشتری", required=False
    )

    dollar_rate = forms.DecimalField(
        max_digits=15, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': 'مثال: 70', 'dir': 'rtl',
            'step': '0.01', 'min': '0', 'id': 'id_dollar_rate',
        }),
        label="نرخ امروز دالر", required=False,
        help_text="هر ۱ دالر = چند افغانی"
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control product-select', 'dir': 'rtl', 'data-field': 'product_id'}),
        label="محصول", required=False
    )

    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control quantity-input', 'placeholder': 'تعداد', 'dir': 'rtl', 'data-field': 'quantity', 'min': '1'}),
        label="تعداد", required=False
    )

    sale_price = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control price-input', 'placeholder': 'قیمت فروش فی واحد', 'dir': 'rtl', 'data-field': 'sale_price', 'step': '0.01'}),
        label="قیمت فروش فی واحد", required=False
    )

    location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).order_by('type', 'code'),
        widget=forms.Select(attrs={'class': 'form-control location-select', 'dir': 'rtl', 'data-field': 'location_id'}),
        label="از موقعیت", required=False, empty_label="انتخاب موقعیت..."
    )

    received_amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'مبلغ دریافت‌شده', 'dir': 'rtl', 'step': '0.01', 'min': '0', 'value': '0'}),
        label="مبلغ دریافت‌شده", required=False, initial=0
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'یادداشت (اختیاری)', 'dir': 'rtl', 'rows': 3}),
        label="یادداشت", required=False
    )

    class Meta:
        model = Sale
        fields = ['sale_number', 'sale_date', 'customer_name', 'customer_number',
                  'dollar_rate', 'items_json', 'received_amount', 'note']
        widgets = {
            'sale_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'توسط سیستم تولید می‌شود', 'dir': 'rtl', 'readonly': 'readonly'}),
        }
        labels = {
            'sale_number': 'شماره فروش',
            'sale_date': 'تاریخ فروش',
            'customer_name': 'نام مشتری',
            'customer_number': 'شماره مشتری',
            'dollar_rate': 'نرخ امروز دالر',
            'received_amount': 'مبلغ دریافت‌شده',
            'note': 'یادداشت'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.items:
                self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)
            if self.instance.dollar_rate:
                self.initial['dollar_rate'] = self.instance.dollar_rate
            self.initial['received_amount'] = self.instance.initial_received_amount or 0
            self.initial['sale_date'] = _local_date_from_datetime(self.instance.sale_date)
        else:
            if not self.initial.get('sale_date'):
                self.initial['sale_date'] = timezone.now().date()

        self.fields['sale_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['sale_number'].required = False

    def _get_old_quantity_for(self, product_id, location_id):
        """
        موجودی قلم قدیمی در حالت ویرایش.
        از دیتابیس می‌خوانیم چون self.instance.items در زمان clean هنوز
        مقدار جدید POST را ندارد (Django instance را با POST به‌روز نمی‌کند تا save).
        """
        if not (self.instance and self.instance.pk):
            return 0
        old_obj = Sale.objects.filter(pk=self.instance.pk).first()
        if not old_obj or not old_obj.items:
            return 0
        total = 0
        for old_item in old_obj.items:
            if (str(old_item.get('product_id')) == str(product_id)
                and str(old_item.get('location_id')) == str(location_id)):
                total += int(old_item.get('quantity', 0) or 0)
        return total

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get('sale_date'):
            self.add_error('sale_date', 'لطفاً تاریخ فروش را وارد کنید')
        if not cleaned_data.get('customer_name'):
            self.add_error('customer_name', 'لطفاً نام مشتری را وارد کنید')
        if not cleaned_data.get('customer_number'):
            cleaned_data['customer_number'] = ''

        dollar_rate = cleaned_data.get('dollar_rate') or Decimal('0')
        items_json = cleaned_data.get('items_json')

        if items_json:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    item_keys = []
                    has_dollar = False

                    for idx, item in enumerate(items):
                        product = None
                        location_obj = None

                        if not item.get('product_id'):
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً محصول را انتخاب کنید')
                        else:
                            try:
                                product = Product.objects.get(id=item['product_id'])
                            except Product.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: محصول وجود ندارد')

                        quantity = item.get('quantity')
                        if not quantity or int(quantity) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً تعداد را وارد کنید')

                        price = item.get('sale_price')
                        if not price or float(price) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً قیمت فروش را وارد کنید')

                        if item.get('currency') == 'USD':
                            has_dollar = True

                        location_id = item.get('location_id')
                        if not location_id:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً موقعیت را انتخاب کنید')
                        else:
                            try:
                                location_obj = Location.objects.get(id=location_id)
                            except Location.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: موقعیت معتبر نیست')

                        if product and location_obj:
                            item_key = f"{product.id}_{location_obj.id}"
                            if item_key in item_keys:
                                self.add_error(
                                    'items_json',
                                    f'قلم {idx + 1}: محصول {product.name} با موقعیت {location_obj.name} تکراری است'
                                )
                            item_keys.append(item_key)

                        if product and location_obj and quantity and int(quantity) > 0:
                            inv = Inventory.objects.filter(product=product, location=location_obj).first()
                            available_stock = inv.quantity if inv else 0
                            # مقدار قدیمی این سند (در ویرایش) به موجودی اضافه شود
                            old_qty = self._get_old_quantity_for(product.id, location_obj.id)
                            available_stock += old_qty

                            if int(quantity) > available_stock:
                                self.add_error(
                                    'items_json',
                                    f'قلم {idx + 1}: موجودی {location_obj.name} کافی نیست! '
                                    f'موجودی فعلی: {available_stock}'
                                )

                    if has_dollar and (not dollar_rate or dollar_rate <= 0):
                        self.add_error('dollar_rate', 'نرخ امروز دالر را وارد کنید (چون قلم دالری دارید)')

                    if not self.errors:
                        total_amount = Decimal('0')
                        for item in items:
                            q = Decimal(str(item.get('quantity', 0)))
                            p = Decimal(str(item.get('sale_price', 0)))
                            if item.get('currency') == 'USD' and dollar_rate > 0:
                                total_amount += q * p * dollar_rate
                            else:
                                total_amount += q * p

                        received_amount = Decimal(str(cleaned_data.get('received_amount', 0) or 0))
                        if received_amount > total_amount:
                            self.add_error('received_amount', 'مبلغ دریافتی نمی‌تواند بیشتر از مجموع فروش باشد')
            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        sale_date = self.cleaned_data.get('sale_date')
        if sale_date:
            instance.sale_date = _aware_datetime_from_date(sale_date)

        submitted_received = self.cleaned_data.get('received_amount')
        if submitted_received is not None:
            instance.initial_received_amount = Decimal(str(submitted_received))
            instance.received_amount = instance.initial_received_amount

        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)
            locations_map = {loc.id: loc.name for loc in Location.objects.all()}
            enhanced_items = []
            for item in items:
                location_id = int(item.get('location_id', 0))
                enhanced_items.append({
                    'product_id': int(item.get('product_id', 0)),
                    'quantity': int(item.get('quantity', 0)),
                    'sale_price': float(item.get('sale_price', 0)),
                    'currency': item.get('currency', 'AFN'),
                    'location_id': location_id,
                    'location_name': locations_map.get(location_id, '---'),
                })
            instance.items = enhanced_items
        if commit:
            instance.save()
        return instance


# ======================================================================
# CustomerReturnForm
# ======================================================================
class CustomerReturnForm(forms.ModelForm):
    """
    ✅ FIXED: کاملاً بازنویسی شد تا مشابه SupplierReturnForm دقیق کار کند.
    """

    items_json = forms.CharField(widget=forms.HiddenInput(), required=False)

    return_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'dir': 'rtl'}),
        label="تاریخ مرجوعی", required=True,
        error_messages={'required': 'لطفاً تاریخ مرجوعی را وارد کنید'}
    )

    original_sale = forms.ModelChoiceField(
        queryset=Sale.objects.all().order_by('-sale_date'),
        widget=forms.Select(attrs={
            'class': 'form-control sale-select',
            'dir': 'rtl',
            'id': 'id_original_sale',
        }),
        label="فروش اصلی", required=True,
        empty_label="--- انتخاب فروش ---",
        error_messages={'required': 'لطفاً فروش اصلی را انتخاب کنید'}
    )

    customer_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'نام مشتری', 'dir': 'rtl',
            'readonly': 'readonly', 'id': 'id_customer_name',
        }),
        label="نام مشتری", required=False
    )

    refund_amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': 'مبلغ بازپرداخت به مشتری',
            'dir': 'rtl', 'step': '0.01', 'min': '0', 'value': '0'
        }),
        label="مبلغ بازپرداخت", required=False, initial=0
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'placeholder': 'دلیل برگشت...', 'dir': 'rtl', 'rows': 3
        }),
        label="یادداشت", required=False
    )

    class Meta:
        model = CustomerReturn
        fields = [
            'return_number', 'return_date', 'original_sale',
            'customer_name', 'refund_amount', 'items_json', 'note'
        ]
        widgets = {
            'return_number': forms.TextInput(attrs={
                'class': 'form-control', 'dir': 'rtl', 'readonly': 'readonly',
                'placeholder': 'توسط سیستم تولید می‌شود',
            }),
        }
        labels = {'return_number': 'شماره مرجوعی'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            if self.instance.items:
                self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)
            self.initial['refund_amount'] = self.instance.refund_amount or 0
            self.initial['return_date'] = _local_date_from_datetime(self.instance.return_date)
            if self.instance.original_sale:
                self.initial['original_sale'] = self.instance.original_sale
                self.initial['customer_name'] = self.instance.customer_name
        else:
            if not self.initial.get('return_date'):
                self.initial['return_date'] = timezone.now().date()

        self.fields['return_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['return_number'].required = False

    def _get_old_returned_qty(self, product_id, location_id):
        """
        مقدار برگشتی این سند (در حالت ویرایش) برای همان قلم.
        """
        if not (self.instance and self.instance.pk):
            return 0
        old_obj = CustomerReturn.objects.filter(pk=self.instance.pk).first()
        if not old_obj or not old_obj.items:
            return 0
        total = 0
        for old_item in old_obj.items:
            if (str(old_item.get('product_id')) == str(product_id)
                and str(old_item.get('location_id')) == str(location_id)):
                total += int(old_item.get('quantity', 0) or 0)
        return total

    def clean(self):
        """
        ✅ FIXED (v2): کاملاً مشابه SupplierReturnForm.clean.
        منطق دقیق بر اساس مقادیر فروش اصلی و برگشتی‌های قبلی.
        """
        cleaned_data = super().clean()

        if not cleaned_data.get('return_date'):
            self.add_error('return_date', 'لطفاً تاریخ مرجوعی را وارد کنید')

        original_sale = cleaned_data.get('original_sale')
        if not original_sale:
            self.add_error('original_sale', 'لطفاً فروش اصلی را انتخاب کنید')

        items_json = cleaned_data.get('items_json')
        if items_json and original_sale:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    # ═══ ۱. نقشه مقادیر فروش اصلی ═══
                    sale_items_map = {}
                    for item in (original_sale.items or []):
                        pid = item.get('product_id')
                        lid = item.get('location_id')
                        qty = int(item.get('quantity', 0) or 0)
                        if pid and lid:
                            sale_items_map.setdefault(int(pid), {})
                            sale_items_map[int(pid)][int(lid)] = \
                                sale_items_map[int(pid)].get(int(lid), 0) + qty

                    # ═══ ۲. مقادیر برگشتی قبلی (اسناد دیگر، به‌جز این سند) ═══
                    previous_returns = {}
                    qs = CustomerReturn.objects.filter(original_sale=original_sale)
                    if self.instance and self.instance.pk:
                        qs = qs.exclude(pk=self.instance.pk)
                    for ret in qs:
                        for item in (ret.items or []):
                            pid = item.get('product_id')
                            lid = item.get('location_id')
                            qty = int(item.get('quantity', 0) or 0)
                            if pid and lid:
                                key = (int(pid), int(lid))
                                previous_returns[key] = previous_returns.get(key, 0) + qty

                    # ═══ ۳. اعتبارسنجی هر قلم ═══
                    seen = set()
                    for idx, item in enumerate(items):
                        pid = item.get('product_id')
                        lid = item.get('location_id')
                        qty = int(item.get('quantity', 0) or 0)

                        if not pid:
                            self.add_error('items_json', f'قلم {idx + 1}: محصول مشخص نیست')
                            continue
                        if not lid:
                            self.add_error('items_json', f'قلم {idx + 1}: موقعیت مشخص نیست')
                            continue
                        if qty <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: تعداد نامعتبر')
                            continue

                        pid = int(pid)
                        lid = int(lid)

                        # ─── الف) قلم باید در فروش اصلی باشد ───
                        if pid not in sale_items_map or lid not in sale_items_map[pid]:
                            self.add_error(
                                'items_json',
                                f'قلم {idx + 1}: این محصول با این موقعیت در فروش اصلی نیست'
                            )
                            continue

                        # ─── ب) سقف قابل برگشت ───
                        sold_qty = sale_items_map[pid][lid]
                        already = previous_returns.get((pid, lid), 0)
                        available = sold_qty - already

                        if qty > available:
                            self.add_error(
                                'items_json',
                                f'قلم {idx + 1}: قابل برگشت فقط {available} عدد '
                                f'(فروش‌رفته: {sold_qty}، قبلاً برگشته: {already})'
                            )

                        # ─── ج) چک تکراری ───
                        key = f"{pid}_{lid}"
                        if key in seen:
                            self.add_error('items_json', f'قلم {idx + 1}: تکراری')
                        seen.add(key)

            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            if not items_json:
                self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        return_date = self.cleaned_data.get('return_date')
        if return_date:
            instance.return_date = _aware_datetime_from_date(return_date)

        original_sale = self.cleaned_data.get('original_sale')
        if original_sale:
            instance.original_sale = original_sale
            instance.customer_name = original_sale.customer_name

        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)
            locations_map = {loc.id: loc.name for loc in Location.objects.all()}
            enhanced_items = []
            for item in items:
                location_id = int(item.get('location_id', 0))
                enhanced_items.append({
                    'product_id': int(item.get('product_id', 0)),
                    'quantity': int(item.get('quantity', 0)),
                    'location_id': location_id,
                    'location_name': locations_map.get(location_id, '---'),
                    'return_price': float(item.get('return_price', 0) or 0),
                })
            instance.items = enhanced_items

        if commit:
            instance.save()
        return instance


# ======================================================================
# SupplierReturnForm
# ======================================================================
class SupplierReturnForm(forms.ModelForm):
    """
    ✅ FIXED (v2): منطق دقیق برای مدیریت موجودی گدام در حالت ویرایش.
    """

    items_json = forms.CharField(widget=forms.HiddenInput(), required=False)

    return_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'dir': 'rtl'}),
        label="تاریخ مرجوعی", required=True,
        error_messages={'required': 'لطفاً تاریخ مرجوعی را وارد کنید'}
    )

    original_purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.all().order_by('-purchase_date'),
        widget=forms.Select(attrs={
            'class': 'form-control purchase-select',
            'dir': 'rtl',
            'id': 'id_original_purchase',
        }),
        label="خرید اصلی", required=True,
        empty_label="--- انتخاب خرید ---",
        error_messages={'required': 'لطفاً خرید اصلی را انتخاب کنید'}
    )

    supplier_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'نام تأمین‌کننده', 'dir': 'rtl',
            'readonly': 'readonly', 'id': 'id_supplier_name',
        }),
        label="نام تأمین‌کننده", required=False
    )

    received_amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': 'مبلغ دریافتی از تأمین‌کننده',
            'dir': 'rtl', 'step': '0.01', 'min': '0', 'value': '0'
        }),
        label="مبلغ دریافتی", required=False, initial=0
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'placeholder': 'دلیل برگشت...', 'dir': 'rtl', 'rows': 3
        }),
        label="یادداشت", required=False
    )

    class Meta:
        model = SupplierReturn
        fields = [
            'return_number', 'return_date', 'original_purchase',
            'supplier_name', 'received_amount', 'items_json', 'note'
        ]
        widgets = {
            'return_number': forms.TextInput(attrs={
                'class': 'form-control', 'dir': 'rtl', 'readonly': 'readonly',
                'placeholder': 'توسط سیستم تولید می‌شود',
            }),
        }
        labels = {'return_number': 'شماره مرجوعی'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            if self.instance.items:
                self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)
            self.initial['received_amount'] = self.instance.received_amount or 0
            self.initial['return_date'] = _local_date_from_datetime(self.instance.return_date)
            if self.instance.original_purchase:
                self.initial['original_purchase'] = self.instance.original_purchase
                self.initial['supplier_name'] = self.instance.supplier_name
        else:
            if not self.initial.get('return_date'):
                self.initial['return_date'] = timezone.now().date()

        self.fields['return_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['return_number'].required = False

    def _get_old_returned_qty(self, product_id, location_id):
        """
        مقدار برگشتی این سند (در حالت ویرایش) برای همان قلم.
        چون این سند قبلاً موجودی را کم کرده، الان باید به سقف موجودی اضافه شود.
        """
        if not (self.instance and self.instance.pk):
            return 0
        old_obj = SupplierReturn.objects.filter(pk=self.instance.pk).first()
        if not old_obj or not old_obj.items:
            return 0
        total = 0
        for old_item in old_obj.items:
            if (str(old_item.get('product_id')) == str(product_id)
                and str(old_item.get('location_id')) == str(location_id)):
                total += int(old_item.get('quantity', 0) or 0)
        return total

    def clean(self):
        """
        ✅ FIXED (v2): سقف موجودی گدام = موجودی فعلی + مقدار قدیمی این سند.
        سقف قابل برگشت از خرید = خریداری‌شده - برگشتی‌های قبلی.
        """
        cleaned_data = super().clean()

        if not cleaned_data.get('return_date'):
            self.add_error('return_date', 'لطفاً تاریخ مرجوعی را وارد کنید')

        original_purchase = cleaned_data.get('original_purchase')
        if not original_purchase:
            self.add_error('original_purchase', 'لطفاً خرید اصلی را انتخاب کنید')

        items_json = cleaned_data.get('items_json')
        if items_json and original_purchase:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    # ═══ ۱. نقشه مقادیر خرید اصلی ═══
                    purchase_items_map = {}
                    for item in (original_purchase.items or []):
                        pid = item.get('product_id')
                        lid = item.get('location_id')
                        qty = int(item.get('quantity', 0) or 0)
                        if pid and lid:
                            purchase_items_map.setdefault(int(pid), {})
                            purchase_items_map[int(pid)][int(lid)] = \
                                purchase_items_map[int(pid)].get(int(lid), 0) + qty

                    # ═══ ۲. مقادیر برگشتی قبلی (اسناد دیگر، به‌جز این سند) ═══
                    previous_returns = {}
                    qs = SupplierReturn.objects.filter(original_purchase=original_purchase)
                    if self.instance and self.instance.pk:
                        qs = qs.exclude(pk=self.instance.pk)
                    for ret in qs:
                        for item in (ret.items or []):
                            pid = item.get('product_id')
                            lid = item.get('location_id')
                            qty = int(item.get('quantity', 0) or 0)
                            if pid and lid:
                                key = (int(pid), int(lid))
                                previous_returns[key] = previous_returns.get(key, 0) + qty

                    # ═══ ۳. اعتبارسنجی هر قلم ═══
                    seen = set()
                    for idx, item in enumerate(items):
                        pid = item.get('product_id')
                        lid = item.get('location_id')
                        qty = int(item.get('quantity', 0) or 0)

                        if not pid:
                            self.add_error('items_json', f'قلم {idx + 1}: محصول مشخص نیست')
                            continue
                        if not lid:
                            self.add_error('items_json', f'قلم {idx + 1}: موقعیت مشخص نیست')
                            continue
                        if qty <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: تعداد نامعتبر')
                            continue

                        pid = int(pid)
                        lid = int(lid)

                        # ─── الف) قلم باید در خرید اصلی باشد ───
                        if pid not in purchase_items_map or lid not in purchase_items_map[pid]:
                            self.add_error(
                                'items_json',
                                f'قلم {idx + 1}: این محصول با این موقعیت در خرید اصلی نیست'
                            )
                            continue

                        # ─── ب) سقف موجودی گدام ───
                        # موجودی گدام فعلی + مقدار قدیمی این سند (در ویرایش)
                        inv = Inventory.objects.filter(product_id=pid, location_id=lid).first()
                        stock = (inv.quantity if inv else 0)
                        old_self = self._get_old_returned_qty(pid, lid)
                        stock += old_self

                        if qty > stock:
                            self.add_error(
                                'items_json',
                                f'قلم {idx + 1}: موجودی گدام کافی نیست '
                                f'(موجودی قابل استفاده: {stock}، درخواستی: {qty})'
                            )

                        # ─── ج) سقف قابل برگشت از خرید اصلی ───
                        purchased_qty = purchase_items_map[pid][lid]
                        already = previous_returns.get((pid, lid), 0)
                        available = purchased_qty - already

                        if qty > available:
                            self.add_error(
                                'items_json',
                                f'قلم {idx + 1}: قابل برگشت فقط {available} عدد '
                                f'(خریداری: {purchased_qty}، قبلاً برگشته: {already})'
                            )

                        # ─── د) چک تکراری ───
                        key = f"{pid}_{lid}"
                        if key in seen:
                            self.add_error('items_json', f'قلم {idx + 1}: تکراری')
                        seen.add(key)

            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            if not items_json:
                self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        return_date = self.cleaned_data.get('return_date')
        if return_date:
            instance.return_date = _aware_datetime_from_date(return_date)

        original_purchase = self.cleaned_data.get('original_purchase')
        if original_purchase:
            instance.original_purchase = original_purchase
            instance.supplier_name = original_purchase.supplier_name

        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)
            locations_map = {loc.id: loc.name for loc in Location.objects.all()}
            enhanced_items = []
            for item in items:
                location_id = int(item.get('location_id', 0))
                enhanced_items.append({
                    'product_id': int(item.get('product_id', 0)),
                    'quantity': int(item.get('quantity', 0)),
                    'location_id': location_id,
                    'location_name': locations_map.get(location_id, '---'),
                    'return_price': float(item.get('return_price', 0) or 0),
                })
            instance.items = enhanced_items

        if commit:
            instance.save()
        return instance


# ======================================================================
# WasteForm
# ======================================================================
class WasteForm(forms.ModelForm):
    items_json = forms.CharField(widget=forms.HiddenInput(), required=False)

    waste_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ ضایعات",
        required=True,
        error_messages={
            'required': 'لطفاً تاریخ ضایعات را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    reason = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'مثال: خرابی، تاریخ گذشته، شکستگی',
            'dir': 'rtl'
        }),
        label="دلیل ضایعات",
        required=True,
        error_messages={
            'required': 'لطفاً دلیل ضایعات را وارد کنید',
        }
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.Select(attrs={
            'class': 'form-control product-select',
            'dir': 'rtl',
            'data-field': 'product_id',
        }),
        label="محصول",
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

    location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).order_by('type', 'code'),
        widget=forms.Select(attrs={
            'class': 'form-control location-select',
            'dir': 'rtl',
            'data-field': 'location_id'
        }),
        label="از موقعیت",
        required=False,
        empty_label="انتخاب موقعیت..."
    )

    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'توضیحات بیشتر (اختیاری)',
            'dir': 'rtl',
            'rows': 3
        }),
        label="یادداشت",
        required=False
    )

    class Meta:
        model = Waste
        fields = [
            'waste_number', 'waste_date', 'reason',
            'items_json', 'note'
        ]
        widgets = {
            'waste_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'توسط سیستم تولید می‌شود',
                'dir': 'rtl',
                'readonly': 'readonly'
            }),
        }
        labels = {
            'waste_number': 'شماره ضایعات',
            'waste_date': 'تاریخ ضایعات',
            'reason': 'دلیل ضایعات',
            'note': 'یادداشت',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            if self.instance.items:
                self.initial['items_json'] = json.dumps(self.instance.items, ensure_ascii=False)
            self.initial['waste_date'] = _local_date_from_datetime(self.instance.waste_date)
        else:
            if not self.initial.get('waste_date'):
                self.initial['waste_date'] = timezone.now().date()

        self.fields['waste_number'].widget.attrs['readonly'] = 'readonly'
        self.fields['waste_number'].required = False

    def _get_old_quantity_for(self, product_id, location_id):
        """
        مقدار قدیمی این سند (در ویرایش) برای همان (product, location).
        از دیتابیس می‌خوانیم چون self.instance.items در زمان clean
        ممکن است مقدار قدیمی را داشته باشد اما برای اطمینان از DB می‌خوانیم.
        """
        if not (self.instance and self.instance.pk):
            return 0
        old_obj = Waste.objects.filter(pk=self.instance.pk).first()
        if not old_obj or not old_obj.items:
            return 0
        total = 0
        for old_item in old_obj.items:
            if (str(old_item.get('product_id')) == str(product_id)
                and str(old_item.get('location_id')) == str(location_id)):
                total += int(old_item.get('quantity', 0) or 0)
        return total

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get('waste_date'):
            self.add_error('waste_date', 'لطفاً تاریخ ضایعات را وارد کنید')

        if not cleaned_data.get('reason'):
            self.add_error('reason', 'لطفاً دلیل ضایعات را وارد کنید')

        items_json = cleaned_data.get('items_json')

        if items_json:
            try:
                items = json.loads(items_json)
                if not items:
                    self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')
                else:
                    # کلید بر اساس (product_id, location_id)
                    item_keys = []
                    for idx, item in enumerate(items):
                        product = None
                        location_obj = None

                        if not item.get('product_id'):
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً محصول را انتخاب کنید')
                        else:
                            try:
                                product = Product.objects.get(id=item['product_id'])
                            except Product.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: محصول وجود ندارد')

                        quantity = item.get('quantity')
                        if not quantity or int(quantity) <= 0:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً تعداد را وارد کنید')

                        location_id = item.get('location_id')
                        if not location_id:
                            self.add_error('items_json', f'قلم {idx + 1}: لطفاً موقعیت را انتخاب کنید')
                        else:
                            try:
                                location_obj = Location.objects.get(id=location_id)
                            except Location.DoesNotExist:
                                self.add_error('items_json', f'قلم {idx + 1}: موقعیت معتبر نیست')

                        if product and location_obj:
                            # چک تکراری بر اساس جفت (product, location)
                            item_key = f"{product.id}_{location_obj.id}"
                            if item_key in item_keys:
                                self.add_error(
                                    'items_json',
                                    f'قلم {idx + 1}: محصول {product.name} با موقعیت {location_obj.name} تکراری است'
                                )
                            item_keys.append(item_key)

                        if product and location_obj and quantity and int(quantity) > 0:
                            inv = Inventory.objects.filter(
                                product=product, location=location_obj
                            ).first()
                            available_stock = inv.quantity if inv else 0
                            # مقدار قدیمی این سند به موجودی اضافه شود
                            old_qty = self._get_old_quantity_for(product.id, location_obj.id)
                            available_stock += old_qty

                            if int(quantity) > available_stock:
                                self.add_error(
                                    'items_json',
                                    f'قلم {idx + 1}: موجودی {location_obj.name} کافی نیست! '
                                    f'موجودی فعلی: {available_stock} (درخواستی: {quantity})'
                                )
            except json.JSONDecodeError:
                self.add_error('items_json', 'فرمت اقلام معتبر نیست')
        else:
            self.add_error('items_json', 'حداقل یک قلم باید اضافه شود')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        waste_date = self.cleaned_data.get('waste_date')
        if waste_date:
            instance.waste_date = _aware_datetime_from_date(waste_date)

        items_json = self.cleaned_data.get('items_json')
        if items_json:
            items = json.loads(items_json)

            locations_map = {
                loc.id: loc.name for loc in Location.objects.all()
            }

            enhanced_items = []
            for item in items:
                location_id = int(item.get('location_id', 0))
                enhanced_item = {
                    'product_id': int(item.get('product_id', 0)),
                    'quantity': int(item.get('quantity', 0)),
                    'location_id': location_id,
                    'location_name': locations_map.get(location_id, '---'),
                }
                enhanced_items.append(enhanced_item)

            instance.items = enhanced_items

        if commit:
            instance.save()

        return instance