from django import forms
from django.utils import timezone
from .models import Transaction, Treasury


class TransactionForm(forms.ModelForm):
    
    # Date field
    transaction_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'dir': 'rtl'
        }),
        label="تاریخ تراکنش",
        required=True,
        initial=timezone.now().date,
        error_messages={
            'required': 'لطفاً تاریخ تراکنش را وارد کنید',
            'invalid': 'لطفاً یک تاریخ معتبر وارد کنید'
        }
    )
    
    # Transaction fields
    transaction_type = forms.ChoiceField(
        choices=Transaction.TRANSACTION_TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'dir': 'rtl'
        }),
        label="نوع تراکنش",
        required=True,
        error_messages={
            'required': 'لطفاً نوع تراکنش را انتخاب کنید',
            'invalid_choice': 'نوع تراکنش انتخاب شده معتبر نیست'
        }
    )
    
    amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'مقدار پول',
            'dir': 'rtl',
            'step': '0.01',
            'min': '0.01'
        }),
        label="مقدار (افغانی)",
        required=True,
        error_messages={
            'required': 'لطفاً مقدار را وارد کنید',
            'invalid': 'لطفاً یک مقدار معتبر وارد کنید',
            'min_value': 'مقدار نمی‌تواند کمتر از ۰.۰۱ باشد'
        }
    )
    
    from_who = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'مثال: مشتری، دوکان، شرکت',
            'dir': 'rtl'
        }),
        label="از چه کسی",
        required=True,
        error_messages={
            'required': 'لطفاً نام شخص یا شرکت را وارد کنید'
        }
    )
    
    money_type = forms.ChoiceField(
        choices=Transaction.TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'dir': 'rtl'
        }),
        label="نوع پول",
        required=True,
        error_messages={
            'required': 'لطفاً نوع پول را انتخاب کنید',
            'invalid_choice': 'نوع پول انتخاب شده معتبر نیست'
        }
    )
    
    description = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'توضیحات اختیاری',
            'dir': 'rtl'
        }),
        label="توضیحات",
        required=False
    )
    
    transaction_image = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        error_messages={
            'invalid': 'لطفاً یک فایل تصویر معتبر انتخاب کنید'
        },
        label="عکس تراکنش"
    )
    
    class Meta:
        model = Transaction
        fields = ['transaction_number', 'transaction_date', 'transaction_type', 'amount', 
                  'from_who', 'money_type', 'description', 'transaction_image']
        widgets = {
            'transaction_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مثال: TRX-2024-001',
                'dir': 'rtl'
            }),
        }
        labels = {
            'transaction_number': 'شماره تراکنش',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set default values
        if not self.initial.get('transaction_date'):
            self.initial['transaction_date'] = timezone.now().date()
        
        # Add help texts
        self.fields['transaction_number'].help_text = "شماره منحصر به فرد برای این تراکنش (اگر خالی بماند، خودکار تولید می‌شود)"
        self.fields['amount'].help_text = "مقدار پول را به افغانی وارد کنید"
        self.fields['money_type'].help_text = "نوع پول را مشخص کنید (خرید، فروش، بدهی و...)"

    def clean_transaction_number(self):
        """Validate transaction number is unique"""
        transaction_number = self.cleaned_data.get('transaction_number')
        instance = getattr(self, 'instance', None)
        
        # If transaction number is empty, it will be auto-generated
        if not transaction_number:
            return transaction_number
        
        # Check if transaction number exists (exclude current instance when editing)
        if instance and instance.pk:
            if Transaction.objects.filter(
                transaction_number=transaction_number
            ).exclude(pk=instance.pk).exists():
                raise forms.ValidationError("شماره تراکنش تکراری است")
        else:
            if Transaction.objects.filter(transaction_number=transaction_number).exists():
                raise forms.ValidationError("شماره تراکنش تکراری است")
        
        return transaction_number

    def clean_amount(self):
        """Validate amount is positive"""
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise forms.ValidationError("مقدار باید بزرگتر از صفر باشد")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get('transaction_type')
        amount = cleaned_data.get('amount')
        
        # For OUT transactions, check treasury balance
        if transaction_type == 'OUT' and amount:
            treasury = Treasury.get_treasury()
            
            # For updating existing transactions
            instance = getattr(self, 'instance', None)
            
            if instance and instance.pk:
                # This is an update - we need to consider the original transaction
                original = Transaction.objects.get(pk=instance.pk)
                
                # Calculate the net effect on treasury
                # Reverse original effect and add new effect
                if original.transaction_type == 'IN':
                    # Original was IN, so it added money
                    effective_balance = treasury.balance_afg - original.amount
                elif original.transaction_type == 'OUT':
                    # Original was OUT, so it subtracted money
                    effective_balance = treasury.balance_afg + original.amount
                else:
                    effective_balance = treasury.balance_afg
                
                # Now check if new OUT transaction is valid
                if transaction_type == 'OUT':
                    if effective_balance < amount:
                        self.add_error(
                            'amount',
                            f'موجودی کافی نیست! موجودی فعلی: {effective_balance:,.2f} افغانی'
                        )
            else:
                # This is a new transaction
                if treasury.balance_afg < amount:
                    self.add_error(
                        'amount',
                        f'موجودی کافی نیست! موجودی فعلی: {treasury.balance_afg:,.2f} افغانی\n'
                        f'لطفاً ابتدا مقداری پول به خزانه واریز کنید.'
                    )
        
        return cleaned_data

    def save(self, commit=True):
        """Save the transaction"""
        instance = super().save(commit=False)
        
        # Set date from form field
        transaction_date = self.cleaned_data.get('transaction_date')
        if transaction_date:
            from datetime import datetime, time
            # Combine date with current time or keep existing time
            current_time = instance.date.time() if instance.date else timezone.now().time()
            instance.date = datetime.combine(transaction_date, current_time)
        
        if commit:
            instance.save()
        
        return instance