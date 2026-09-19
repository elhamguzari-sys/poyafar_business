# apps/employee/forms.py

from django import forms
from .models import Employee
from django.utils import timezone


class EmployeeForm(forms.ModelForm):
    """فرم ثبت و ویرایش کارمند"""

    join_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ شمولیت",
        required=True,
        initial=timezone.now().date,
        error_messages={
            'required': 'لطفاً تاریخ شمولیت را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    leave_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ منفکی",
        required=False,
        error_messages={
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )

    class Meta:
        model = Employee
        fields = [
            # اطلاعات شخصی
            'full_name', 'father_name', 'tazkera_number',
            # تماس
            'phone_number', 'address',
            # عکس‌ها
            'image', 'tazkera_image',
            # شغل (فقط متن)
            'position',
            # تاریخ‌ها
            'join_date', 'leave_date',
            # معاش
            'base_salary',
            # یادداشت
            'note',
        ]

        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: احمد ولی',
                'dir': 'rtl'
            }),
            'father_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: محمد ولی',
                'dir': 'rtl'
            }),
            'tazkera_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 1400-1234-5678',
                'dir': 'rtl'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 0700123456',
                'dir': 'rtl'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'آدرس کامل...',
                'dir': 'rtl'
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'tazkera_image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'position': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: فروشنده، حسابدار، گدامدار',
                'dir': 'rtl'
            }),
            'base_salary': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 15000',
                'min': '0',
                'step': '0.01',
                'dir': 'rtl'
            }),
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'یادداشت (اختیاری)',
                'dir': 'rtl'
            }),
        }

        labels = {
            'full_name': 'نام کامل',
            'father_name': 'نام پدر',
            'tazkera_number': 'شماره تذکره',
            'phone_number': 'شماره تماس',
            'address': 'آدرس',
            'image': 'عکس کارمند',
            'tazkera_image': 'عکس تذکره',
            'position': 'وظیفه / سمت',
            'join_date': 'تاریخ شمولیت',
            'leave_date': 'تاریخ منفکی',
            'base_salary': 'معاش پایه (افغانی)',
            'note': 'یادداشت',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # فیلدهای اختیاری
        self.fields['tazkera_number'].required = False
        self.fields['address'].required = False
        self.fields['image'].required = False
        self.fields['tazkera_image'].required = False
        self.fields['position'].required = False
        self.fields['leave_date'].required = False
        self.fields['note'].required = False

        # مقادیر اولیه
        if not self.instance.pk:
            self.fields['base_salary'].initial = 0

    def clean(self):
        cleaned_data = super().clean()

        # معاش پایه نمیتواند منفی باشد
        base_salary = cleaned_data.get('base_salary')
        if base_salary is not None and base_salary < 0:
            self.add_error('base_salary', 'معاش پایه نمیتواند منفی باشد')

        # تاریخ منفکی باید بعد از تاریخ شمولیت باشد
        join_date = cleaned_data.get('join_date')
        leave_date = cleaned_data.get('leave_date')

        if join_date and leave_date and leave_date < join_date:
            self.add_error(
                'leave_date',
                'تاریخ منفکی نمیتواند قبل از تاریخ شمولیت باشد'
            )

        return cleaned_data
    
    
    
    
    
    
    
    
    
from .models import Employee, Salary


class SalaryForm(forms.ModelForm):
    """فرم ثبت و ویرایش معاش"""

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

    class Meta:
        model = Salary
        fields = ['employee', 'salary_month', 'amount', 'payment_date', 'note']

        widgets = {
            'employee': forms.Select(attrs={
                'class': 'form-select',
                'dir': 'rtl'
            }),
            'salary_month': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 1405/01 (حمل)',
                'dir': 'rtl'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: 15000',
                'min': '0',
                'step': '0.01',
                'dir': 'rtl'
            }),
            'note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'یادداشت (اختیاری)',
                'dir': 'rtl'
            }),
        }

        labels = {
            'employee': 'کارمند',
            'salary_month': 'ماه معاش',
            'amount': 'مقدار معاش (افغانی)',
            'payment_date': 'تاریخ پرداخت',
            'note': 'یادداشت',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # فقط کارمندان فعال را نشان بده
        self.fields['employee'].queryset = Employee.objects.filter(
            leave_date__isnull=True
        ).order_by('full_name')

        self.fields['note'].required = False

    def clean(self):
        cleaned_data = super().clean()

        amount = cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            self.add_error('amount', 'مقدار معاش باید بزرگتر از صفر باشد')

        salary_month = cleaned_data.get('salary_month')
        if not salary_month:
            self.add_error('salary_month', 'لطفاً ماه معاش را وارد کنید')

        return cleaned_data