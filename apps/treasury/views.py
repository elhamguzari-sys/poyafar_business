# apps/treasury/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponse
from datetime import timedelta
from decimal import Decimal
from .models import Treasury, Transaction
from .forms import TransactionForm
from apps.treasury.exceptions import TreasuryReversalBlocked, InsufficientTreasuryBalance


# ======================================================================
# Helper: خلاصه فارسی از ProtectedError
# ======================================================================
FA_LABELS = {
    'Salary': 'رکورد معاش',
    'Employee': 'کارمند',
    'PurchaseDebt': 'پرداخت بدهی خرید',
    'SaleDebt': 'دریافت بدهی فروش',
    'Purchase': 'خرید',
    'Sale': 'فروش',
    'CustomerReturn': 'مرجوعی مشتری',
    'SupplierReturn': 'مرجوعی به تأمین‌کننده',
    'Waste': 'ضایعات',
    'Expense': 'مصرف',
    'Inventory': 'رکورد موجودی',
    'StockMovement': 'حرکت انبار',
    'Product': 'محصول',
    'Category': 'دسته‌بندی',
    'Location': 'موقعیت',
    'Transaction': 'تراکنش',
}


def _protected_summary(exc: ProtectedError) -> str:
    counts = {}
    for obj in exc.protected_objects:
        name = obj.__class__.__name__
        counts[name] = counts.get(name, 0) + 1
    return '، '.join(
        f'{n} {FA_LABELS.get(name, name)}' for name, n in counts.items()
    )


# ======================================================================
# Helper: Find the business document owning a transaction
# ======================================================================
def _find_transaction_owner(transaction):
    """
    Returns (label, identifier) if the transaction is owned by a
    business document, else None.

    Example return: ('خرید', 'PUR_2 - شرکت milad nadery')
    """
    checks = [
        ('خرید', 'purchase_transactions',
         lambda p: f"{p.purchase_number} - {p.supplier_name}"),
        ('فروش', 'sale_transactions',
         lambda s: f"{s.sale_number} - {s.customer_name}"),
        ('مصرف', 'expense_transactions',
         lambda e: f"{e.expense_number} - {e.title}"),
        ('معاش', 'salary_transactions',
         lambda s: f"{s.employee.full_name} - {s.salary_month}"),
        ('پرداخت بدهی خرید', 'purchase_debt_transactions',
         lambda d: f"{d.purchase.purchase_number} - {d.purchase.supplier_name}"),
        ('دریافت بدهی فروش', 'sale_debt_transactions',
         lambda d: f"{d.sale.sale_number} - {d.sale.customer_name}"),
        ('مرجوعی مشتری', 'customer_return_transactions',
         lambda r: f"{r.return_number} - {r.customer_name}"),
        ('مرجوعی به تأمین‌کننده', 'supplier_return_transactions',
         lambda r: f"{r.return_number} - {r.supplier_name}"),
    ]

    for label, related_name, get_identifier in checks:
        try:
            manager = getattr(transaction, related_name, None)
            if manager is None:
                continue
            obj = manager.first()
            if obj:
                return label, get_identifier(obj)
        except Exception:
            continue

    return None


# ======================================================================
# Treasury Dashboard
# ======================================================================
def treasury_dashboard(request):
    """Treasury dashboard with overview and statistics"""

    treasury = Treasury.get_treasury()

    date_filter = request.GET.get('date_filter', 'today')
    today = timezone.now().date()

    if date_filter == 'today':
        transactions = Transaction.objects.filter(date__date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        transactions = Transaction.objects.filter(date__date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        transactions = Transaction.objects.filter(date__date__gte=month_ago)
    else:  # all
        transactions = Transaction.objects.all()

    total_in = transactions.filter(transaction_type='IN').aggregate(
        total=Sum('amount')
    )['total'] or 0

    total_out = transactions.filter(transaction_type='OUT').aggregate(
        total=Sum('amount')
    )['total'] or 0

    net_change = total_in - total_out

    recent_transactions = Transaction.objects.all().order_by('-date')[:10]

    top_sources = Transaction.objects.values('from_who') \
        .annotate(total_amount=Sum('amount')) \
        .order_by('-total_amount')[:5]

    in_count = transactions.filter(transaction_type='IN').count()
    out_count = transactions.filter(transaction_type='OUT').count()
    today_transactions = Transaction.objects.filter(date__date=today).count()
    total_transactions = Transaction.objects.count()

    context = {
        'treasury': treasury,
        'date_filter': date_filter,
        'total_in': total_in,
        'total_out': total_out,
        'net_change': net_change,
        'recent_transactions': recent_transactions,
        'top_sources': top_sources,
        'in_count': in_count,
        'out_count': out_count,
        'today_transactions': today_transactions,
        'total_transactions': total_transactions,
        'today': today,
        'page_title': 'داشبورد خزانه',
    }

    return render(request, 'treasury/treasury_dashboard.html', context)


# ======================================================================
# Transaction List
# ======================================================================
def transaction_list(request):
    """List all transactions with search and filtering"""

    transactions = Transaction.objects.all().order_by('-date')

    search_query = request.GET.get('search', '')
    if search_query:
        transactions = transactions.filter(
            Q(transaction_number__icontains=search_query) |
            Q(from_who__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        transactions = transactions.filter(date__date__gte=date_from)
    if date_to:
        transactions = transactions.filter(date__date__lte=date_to)

    transaction_type_filter = request.GET.get('transaction_type', '')
    if transaction_type_filter:
        transactions = transactions.filter(transaction_type=transaction_type_filter)

    money_type_filter = request.GET.get('money_type', '')
    if money_type_filter:
        transactions = transactions.filter(money_type=money_type_filter)

    min_amount = request.GET.get('min_amount', '')
    if min_amount:
        try:
            min_amount = Decimal(min_amount)
            transactions = transactions.filter(amount__gte=min_amount)
        except Exception:
            pass

    max_amount = request.GET.get('max_amount', '')
    if max_amount:
        try:
            max_amount = Decimal(max_amount)
            transactions = transactions.filter(amount__lte=max_amount)
        except Exception:
            pass

    page_number = request.GET.get('page', 1)
    paginator = Paginator(transactions, 20)

    try:
        transactions_page = paginator.page(page_number)
    except PageNotAnInteger:
        transactions_page = paginator.page(1)
    except EmptyPage:
        transactions_page = paginator.page(paginator.num_pages)

    today = timezone.now().date()
    total_transactions = Transaction.objects.count()
    today_transactions = Transaction.objects.filter(date__date=today).count()

    total_in = Transaction.objects.filter(transaction_type='IN').aggregate(
        total=Sum('amount')
    )['total'] or 0

    total_out = Transaction.objects.filter(transaction_type='OUT').aggregate(
        total=Sum('amount')
    )['total'] or 0

    seven_days_ago = timezone.now().date() - timedelta(days=7)
    recent_transactions = Transaction.objects.filter(date__date__gte=seven_days_ago).count()

    context = {
        'transactions': transactions_page,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'transaction_type_filter': transaction_type_filter,
        'money_type_filter': money_type_filter,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'paginator': paginator,
        'page_title': 'لیست تراکنش‌ها',
        'total_count': paginator.count,
        'total_transactions': total_transactions,
        'today_transactions': today_transactions,
        'total_in': total_in,
        'total_out': total_out,
        'recent_transactions': recent_transactions,
        'today': today,
        'transaction_type_choices': Transaction.TRANSACTION_TYPE_CHOICES,
        'money_type_choices': Transaction.TYPE_CHOICES,
    }

    return render(request, 'treasury/transaction_list.html', context)


# ======================================================================
# Create Transaction
# ======================================================================
def create_transaction(request):
    """Create new transaction"""

    if request.method == 'POST':
        form = TransactionForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                with db_transaction.atomic():
                    transaction = form.save()

                    if transaction.transaction_type == 'IN':
                        messages.success(
                            request,
                            f'✓ واریز موفق! شماره تراکنش: {transaction.transaction_number}\n'
                            f'{transaction.amount:,.2f} افغانی به {transaction.get_money_type_display()} اضافه شد'
                        )
                    else:
                        messages.success(
                            request,
                            f'✓ برداشت موفق! شماره تراکنش: {transaction.transaction_number}\n'
                            f'{transaction.amount:,.2f} افغانی از {transaction.get_money_type_display()} کسر شد'
                        )

                    return redirect('transaction_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance:,.2f} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount:,.2f} {currency_label}'
                )
            except ValueError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطا در ثبت تراکنش: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        field_label = form.fields[field].label if field in form.fields else field
                        error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)

            messages.error(
                request,
                'لطفاً اطلاعات را درست وارد کنید:\n' + '\n'.join(error_messages)
            )
    else:
        form = TransactionForm(initial={
            'transaction_date': timezone.now().date()
        })

    treasury = Treasury.get_treasury()

    total_transactions = Transaction.objects.count()
    today_transactions = Transaction.objects.filter(date__date=timezone.now().date()).count()

    context = {
        'form': form,
        'treasury': treasury,
        'page_title': 'ثبت تراکنش جدید',
        'total_transactions': total_transactions,
        'today_transactions': today_transactions,
        'is_create': True,
    }

    return render(request, 'treasury/create_transaction.html', context)


# ======================================================================
# Update Transaction
# ======================================================================
def update_transaction(request, transaction_id):
    """Update an existing transaction"""

    transaction = get_object_or_404(Transaction, pk=transaction_id)

    if request.method == 'POST':
        form = TransactionForm(request.POST, request.FILES, instance=transaction)

        if form.is_valid():
            try:
                with db_transaction.atomic():
                    transaction = form.save()

                    messages.success(
                        request,
                        f'✓ تراکنش {transaction.transaction_number} با موفقیت به‌روزرسانی شد'
                    )

                    return redirect('transaction_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance:,.2f} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount:,.2f} {currency_label}'
                )
            except ValueError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطا در به‌روزرسانی تراکنش: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        field_label = form.fields[field].label if field in form.fields else field
                        error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)

            messages.error(
                request,
                'لطفاً اطلاعات را درست وارد کنید:\n' + '\n'.join(error_messages)
            )
    else:
        form = TransactionForm(instance=transaction)

    treasury = Treasury.get_treasury()

    total_transactions = Transaction.objects.count()
    today_transactions = Transaction.objects.filter(date__date=timezone.now().date()).count()

    context = {
        'form': form,
        'treasury': treasury,
        'page_title': f'ویرایش تراکنش - {transaction.transaction_number}',
        'total_transactions': total_transactions,
        'today_transactions': today_transactions,
        'is_update': True,
        'transaction': transaction,
    }

    return render(request, 'treasury/update_transaction.html', context)


# ======================================================================
# Delete Transaction — Protected by business documents + treasury
# ======================================================================
def delete_transaction(request, transaction_id):
    """
    Delete transaction.
    - اگر تراکنش به یک سند تجاری وصل باشد → پیام راهنما
    - اگر برگشت آن باعث منفی شدن خزانه شود → پیام راهنما
    """

    transaction = get_object_or_404(Transaction, pk=transaction_id)

    if request.method == 'POST':
        # --- 1) Check ownership ---
        owner = _find_transaction_owner(transaction)

        if owner:
            doc_label, doc_identifier = owner
            messages.error(
                request,
                f'❌ این تراکنش به یک سند تجاری متصل است و نمی‌توان آن را مستقیم حذف کرد.\n'
                f'🔗 نوع سند: {doc_label}\n'
                f'📄 شماره: {doc_identifier}\n'
                f'👉 برای حذف، ابتدا آن سند را ویرایش یا حذف کنید.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('transaction_list')

        # --- 2) Try delete ---
        try:
            transaction_number = transaction.transaction_number
            transaction.delete()

            messages.success(request, f'✓ تراکنش {transaction_number} با موفقیت حذف شد')

            if request.headers.get('HX-Request'):
                return HttpResponse(status=200)
            return redirect('transaction_list')

        except TreasuryReversalBlocked as e:
            messages.error(
                request,
                f'❌ {e.message}\n'
                f'💰 موجودی فعلی خزانه: {e.current_balance:,.2f} افغانی\n'
                f'💸 پس از برگشت: {e.would_become:,.2f} افغانی\n'
                f'👉 برای حذف این تراکنش، ابتدا موجودی خزانه را افزایش دهید '
                f'یا تراکنش‌های بعدی را بررسی کنید.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('transaction_list')

        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف ممکن نیست — این تراکنش وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('transaction_list')

        except ValueError as e:
            messages.error(request, f'❌ {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('transaction_list')

        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('transaction_list')

    # GET — confirmation page
    owner = _find_transaction_owner(transaction)

    context = {
        'transaction': transaction,
        'owner': owner,
        'page_title': f'حذف تراکنش - {transaction.transaction_number}',
    }

    return render(request, 'treasury/delete_transaction.html', context)