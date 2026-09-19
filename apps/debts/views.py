# apps/debts/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from decimal import Decimal, InvalidOperation

from .models import PurchaseDebt, SaleDebt
from apps.purchasesale.models import Purchase, Sale
from apps.treasury.exceptions import InsufficientTreasuryBalance


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


def _parse_payment_date(value, default=None):
    """
    تلاش برای تبدیل رشته تاریخ/تاریخ-زمان به آبجکت datetime آگاه از timezone.
    اگر ورودی خالی/نامعتبر بود، مقدار پیش‌فرض برگردانده می‌شود.
    """
    if not value:
        return default or timezone.now()

    # تلاش برای datetime کامل
    dt = parse_datetime(value)
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    # تلاش برای date-only
    d = parse_date(value)
    if d is not None:
        dt = timezone.datetime(d.year, d.month, d.day)
        return timezone.make_aware(dt, timezone.get_current_timezone())

    return default or timezone.now()


def _treasury_error_message(e: InsufficientTreasuryBalance) -> str:
    currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
    return (
        f'⚠️ {e.message}\n'
        f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
        f'💸 مورد نیاز: {e.required_amount} {currency_label}\n'
        f'لطفاً ابتدا موجودی خزانه را افزایش دهید.'
    )


# ======================================================================
# PurchaseDebt Views
# ======================================================================
def purchase_debt_list(request):
    """List all purchase debts with search and filtering + settled history"""

    purchases_list = Purchase.objects.filter(
        remaining_amount__gt=0
    ).order_by('-purchase_date')

    search_query = request.GET.get('search', '')
    supplier_filter = request.GET.get('supplier', '')
    payment_status = request.GET.get('payment_status', '')

    if search_query:
        purchases_list = purchases_list.filter(
            Q(purchase_number__icontains=search_query) |
            Q(supplier_name__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if supplier_filter:
        purchases_list = purchases_list.filter(supplier_name__icontains=supplier_filter)

    if payment_status == 'partial':
        purchases_list = purchases_list.filter(paid_amount__gt=0, remaining_amount__gt=0)
    elif payment_status == 'unpaid':
        purchases_list = purchases_list.filter(paid_amount=0)

    # ═══════════════════════════════════════════════════════════════
    # قروض تصفیه‌شده خرید
    # ═══════════════════════════════════════════════════════════════
    settled_purchases = Purchase.objects.filter(
        remaining_amount__lte=0,
        paid_amount__gt=0,
    ).order_by('-updated_at')

    # آمار
    total_debt_purchases = purchases_list.count()
    total_debt_amount = purchases_list.aggregate(
        total=Sum('remaining_amount')
    )['total'] or 0
    total_paid_amount = purchases_list.aggregate(
        total=Sum('paid_amount')
    )['total'] or 0
    total_suppliers_count = purchases_list.values('supplier_name').distinct().count()
    total_payments_count = PurchaseDebt.objects.count()

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(purchases_list, 10)

    try:
        purchases = paginator.page(page_number)
    except PageNotAnInteger:
        purchases = paginator.page(1)
    except EmptyPage:
        purchases = paginator.page(paginator.num_pages)

    suppliers = (
        Purchase.objects
        .filter(remaining_amount__gt=0)
        .exclude(supplier_name__isnull=True)
        .exclude(supplier_name__exact='')
        .order_by('supplier_name')
        .values_list('supplier_name', flat=True)
        .distinct()
    )

    context = {
        'purchases': purchases,
        'settled_purchases': settled_purchases,
        'settled_count': settled_purchases.count(),
        'search_query': search_query,
        'supplier_filter': supplier_filter,
        'payment_status': payment_status,
        'suppliers': suppliers,
        'paginator': paginator,
        'total_debt_purchases': total_debt_purchases,
        'total_debt_amount': total_debt_amount,
        'total_paid_amount': total_paid_amount,
        'total_suppliers_count': total_suppliers_count,
        'total_payments_count': total_payments_count,
        'page_title': 'بدهی تأمین‌کنندگان',
    }

    return render(request, 'purchase_debt/purchase_debt_list.html', context)


def create_purchase_debt(request, purchase_id):
    """Create new debt payment — با چک موجودی خزانه"""
    purchase = get_object_or_404(Purchase, pk=purchase_id)

    if request.method != 'POST':
        return redirect('purchase_debt_list')

    amount_str = request.POST.get('amount', '0')
    payment_date_raw = request.POST.get('payment_date')
    note = request.POST.get('note', '')

    try:
        amount = Decimal(amount_str)
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, 'مبلغ پرداخت باید یک عدد معتبر باشد.')
        return redirect('purchase_debt_list')

    if amount <= 0:
        messages.error(request, 'مبلغ پرداخت باید بزرگتر از صفر باشد.')
        return redirect('purchase_debt_list')

    if amount > purchase.remaining_amount:
        messages.error(
            request,
            f'مبلغ پرداخت نمی‌تواند بیشتر از بدهی باقی‌مانده ({purchase.remaining_amount}) باشد.'
        )
        return redirect('purchase_debt_list')

    try:
        debt = PurchaseDebt.objects.create(
            purchase=purchase,
            amount=amount,
            payment_date=_parse_payment_date(payment_date_raw),
            note=note,
        )
        messages.success(
            request,
            f'پرداخت "{debt.amount}" افغانی برای خرید "{purchase.purchase_number}" موفقانه ثبت شد.'
        )
        return redirect('purchase_debt_list')

    except InsufficientTreasuryBalance as e:
        messages.error(request, _treasury_error_message(e))
        return redirect('purchase_debt_list')

    except Exception as e:
        messages.error(request, f'⚠️ خطا: {str(e)}')
        return redirect('purchase_debt_list')


def update_purchase_debt(request, debt_id):
    """
    Update existing debt payment.

    نکته کلیدی:
    remaining_amount فعلی خرید، مبلغ این پرداخت را هم در خود دارد
    (چون در _sync_purchase_totals از total کم شده است).
    پس سقف مجاز برای مبلغ جدید = remaining_amount + debt.amount (مبلغ قدیمی).
    """
    debt = get_object_or_404(PurchaseDebt, pk=debt_id)
    purchase = debt.purchase

    if request.method != 'POST':
        return redirect('purchase_debt_history', purchase_id=purchase.id)

    try:
        new_amount = Decimal(request.POST.get('amount', 0))
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, 'مبلغ پرداخت باید یک عدد معتبر باشد.')
        return redirect('purchase_debt_history', purchase_id=purchase.id)

    payment_date_raw = request.POST.get('payment_date')
    note = request.POST.get('note', '')

    if new_amount <= 0:
        messages.error(request, 'مبلغ پرداخت باید بزرگتر از صفر باشد.')
        return redirect('purchase_debt_history', purchase_id=purchase.id)

    # ✅ سقف مجاز = باقی‌مانده فعلی + مبلغ قدیمی همین پرداخت
    max_allowed = (purchase.remaining_amount or Decimal('0')) + (debt.amount or Decimal('0'))

    if new_amount > max_allowed:
        messages.error(
            request,
            f'مبلغ پرداخت نمی‌تواند بیشتر از بدهی باقی‌مانده ({max_allowed}) باشد.'
        )
        return redirect('purchase_debt_history', purchase_id=purchase.id)

    try:
        debt.amount = new_amount
        if payment_date_raw:
            debt.payment_date = _parse_payment_date(payment_date_raw, default=debt.payment_date)
        debt.note = note
        debt.save()  # مدل خودش تراکنش و _sync_purchase_totals را انجام می‌دهد

        messages.success(
            request,
            f'پرداخت بدهی "{purchase.purchase_number}" موفقانه ویرایش شد.'
        )

    except InsufficientTreasuryBalance as e:
        messages.error(request, _treasury_error_message(e))

    except Exception as e:
        messages.error(request, f'⚠️ خطا: {str(e)}')

    return redirect('purchase_debt_history', purchase_id=purchase.id)


def delete_purchase_debt(request, debt_id):
    """Delete debt payment — با کنترل ProtectedError"""
    debt = get_object_or_404(PurchaseDebt, pk=debt_id)
    purchase_id = debt.purchase.id

    if request.method == 'POST':
        amount = debt.amount
        purchase_number = debt.purchase.purchase_number
        try:
            debt.delete()
            messages.success(
                request,
                f'پرداخت "{amount}" افغانی برای خرید "{purchase_number}" موفقانه حذف شد.'
            )
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ نمی‌توان پرداخت "{amount}" افغانی برای خرید '
                f'"{purchase_number}" را حذف کرد. وابسته به {details} است.'
            )
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')

    return redirect('purchase_debt_history', purchase_id=purchase_id)


def purchase_debt_history(request, purchase_id):
    """Payment history for a specific purchase"""
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    debts_list = PurchaseDebt.objects.filter(purchase=purchase).order_by('-payment_date')
    search_query = request.GET.get('search', '')

    if search_query:
        debts_list = debts_list.filter(note__icontains=search_query)

    total_paid = debts_list.aggregate(total=Sum('amount'))['total'] or 0
    payments_count = debts_list.count()
    last_payment = debts_list.first()

    page_number = request.GET.get('page', 1)
    paginator = Paginator(debts_list, 10)

    try:
        debts = paginator.page(page_number)
    except PageNotAnInteger:
        debts = paginator.page(1)
    except EmptyPage:
        debts = paginator.page(paginator.num_pages)

    context = {
        'purchase': purchase,
        'debts': debts,
        'search_query': search_query,
        'paginator': paginator,
        'total_paid': total_paid,
        'payments_count': payments_count,
        'last_payment': last_payment,
        'page_title': f'سابقه پرداخت بدهی - {purchase.purchase_number}',
    }

    return render(request, 'purchase_debt/debt_history.html', context)


# ======================================================================
# SaleDebt Views
# ======================================================================
def sale_debt_list(request):
    """List all sale debts with search and filtering + settled history"""

    # ═══════════════════════════════════════════════════════════════
    # ۱. قروض فعال (فروش‌هایی که هنوز پول نگرفته‌اید)
    # ═══════════════════════════════════════════════════════════════
    sales_list = Sale.objects.filter(
        remaining_amount__gt=0
    ).order_by('-sale_date')

    search_query = request.GET.get('search', '')
    customer_filter = request.GET.get('customer', '')
    payment_status = request.GET.get('payment_status', '')

    if search_query:
        sales_list = sales_list.filter(
            Q(sale_number__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if customer_filter:
        sales_list = sales_list.filter(customer_name__icontains=customer_filter)

    if payment_status == 'partial':
        sales_list = sales_list.filter(received_amount__gt=0, remaining_amount__gt=0)
    elif payment_status == 'unpaid':
        sales_list = sales_list.filter(received_amount=0)

    # ═══════════════════════════════════════════════════════════════
    # ۲. قروض تصفیه‌شده فروش
    # ═══════════════════════════════════════════════════════════════
    settled_sales = Sale.objects.filter(
        remaining_amount__lte=0,
        received_amount__gt=0,
    ).order_by('-updated_at')

    # آمار
    total_debt_sales = sales_list.count()
    total_debt_amount = sales_list.aggregate(
        total=Sum('remaining_amount')
    )['total'] or 0
    total_received_amount = sales_list.aggregate(
        total=Sum('received_amount')
    )['total'] or 0
    total_customers_count = sales_list.values('customer_name').distinct().count()
    total_payments_count = SaleDebt.objects.count()

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(sales_list, 10)

    try:
        sales = paginator.page(page_number)
    except PageNotAnInteger:
        sales = paginator.page(1)
    except EmptyPage:
        sales = paginator.page(paginator.num_pages)

    customers = (
        Sale.objects
        .filter(remaining_amount__gt=0)
        .exclude(customer_name__isnull=True)
        .exclude(customer_name__exact='')
        .order_by('customer_name')
        .values_list('customer_name', flat=True)
        .distinct()
    )

    context = {
        'sales': sales,
        'settled_sales': settled_sales,
        'settled_count': settled_sales.count(),
        'search_query': search_query,
        'customer_filter': customer_filter,
        'payment_status': payment_status,
        'customers': customers,
        'paginator': paginator,
        'total_debt_sales': total_debt_sales,
        'total_debt_amount': total_debt_amount,
        'total_received_amount': total_received_amount,
        'total_customers_count': total_customers_count,
        'total_payments_count': total_payments_count,
        'page_title': 'بدهی مشتریان',
    }

    return render(request, 'sale_debt/sale_debt_list.html', context)


def create_sale_debt(request, sale_id):
    """Create new debt payment from customer"""
    sale = get_object_or_404(Sale, pk=sale_id)

    if request.method != 'POST':
        return redirect('sale_debt_list')

    try:
        amount = Decimal(request.POST.get('amount', 0))
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, 'مبلغ دریافت باید یک عدد معتبر باشد.')
        return redirect('sale_debt_list')

    payment_date_raw = request.POST.get('payment_date')
    note = request.POST.get('note', '')

    if amount <= 0:
        messages.error(request, 'مبلغ دریافت باید بزرگتر از صفر باشد.')
        return redirect('sale_debt_list')

    if amount > sale.remaining_amount:
        messages.error(
            request,
            f'مبلغ دریافت نمی‌تواند بیشتر از بدهی باقی‌مانده ({sale.remaining_amount}) باشد.'
        )
        return redirect('sale_debt_list')

    try:
        debt = SaleDebt.objects.create(
            sale=sale,
            amount=amount,
            payment_date=_parse_payment_date(payment_date_raw),
            note=note,
        )
        messages.success(
            request,
            f'دریافت "{debt.amount}" افغانی برای فروش "{sale.sale_number}" موفقانه ثبت شد.'
        )
        return redirect('sale_debt_list')

    except Exception as e:
        messages.error(request, f'⚠️ خطا: {str(e)}')
        return redirect('sale_debt_list')


def update_sale_debt(request, debt_id):
    """
    Update existing debt payment from customer.

    نکته کلیدی:
    remaining_amount فعلی فروش، مبلغ این دریافت را هم در خود دارد.
    پس سقف مجاز = remaining_amount + debt.amount (مبلغ قدیمی).
    """
    debt = get_object_or_404(SaleDebt, pk=debt_id)
    sale = debt.sale

    if request.method != 'POST':
        return redirect('sale_debt_history', sale_id=sale.id)

    try:
        new_amount = Decimal(request.POST.get('amount', 0))
    except (InvalidOperation, ValueError, TypeError):
        messages.error(request, 'مبلغ دریافت باید یک عدد معتبر باشد.')
        return redirect('sale_debt_history', sale_id=sale.id)

    payment_date_raw = request.POST.get('payment_date')
    note = request.POST.get('note', '')

    if new_amount <= 0:
        messages.error(request, 'مبلغ دریافت باید بزرگتر از صفر باشد.')
        return redirect('sale_debt_history', sale_id=sale.id)

    # ✅ سقف مجاز = باقی‌مانده فعلی + مبلغ قدیمی همین دریافت
    max_allowed = (sale.remaining_amount or Decimal('0')) + (debt.amount or Decimal('0'))

    if new_amount > max_allowed:
        messages.error(
            request,
            f'مبلغ دریافت نمی‌تواند بیشتر از بدهی باقی‌مانده ({max_allowed}) باشد.'
        )
        return redirect('sale_debt_history', sale_id=sale.id)

    try:
        debt.amount = new_amount
        if payment_date_raw:
            debt.payment_date = _parse_payment_date(payment_date_raw, default=debt.payment_date)
        debt.note = note
        debt.save()  # مدل خودش تراکنش و _sync_sale_totals را انجام می‌دهد

        messages.success(
            request,
            f'دریافت بدهی "{sale.sale_number}" موفقانه ویرایش شد.'
        )

    except InsufficientTreasuryBalance as e:
        messages.error(request, _treasury_error_message(e))

    except Exception as e:
        messages.error(request, f'⚠️ خطا: {str(e)}')

    return redirect('sale_debt_history', sale_id=sale.id)


def delete_sale_debt(request, debt_id):
    """Delete debt payment from customer — با کنترل ProtectedError"""
    debt = get_object_or_404(SaleDebt, pk=debt_id)
    sale_id = debt.sale.id

    if request.method == 'POST':
        amount = debt.amount
        sale_number = debt.sale.sale_number
        try:
            debt.delete()
            messages.success(
                request,
                f'دریافت "{amount}" افغانی برای فروش "{sale_number}" موفقانه حذف شد.'
            )
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ نمی‌توان دریافت "{amount}" افغانی برای فروش '
                f'"{sale_number}" را حذف کرد. وابسته به {details} است.'
            )
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')

    return redirect('sale_debt_history', sale_id=sale_id)


def sale_debt_history(request, sale_id):
    """Payment history for a specific sale"""
    sale = get_object_or_404(Sale, pk=sale_id)
    debts_list = SaleDebt.objects.filter(sale=sale).order_by('-payment_date')
    search_query = request.GET.get('search', '')

    if search_query:
        debts_list = debts_list.filter(note__icontains=search_query)

    total_received = debts_list.aggregate(total=Sum('amount'))['total'] or 0
    payments_count = debts_list.count()
    last_payment = debts_list.first()

    page_number = request.GET.get('page', 1)
    paginator = Paginator(debts_list, 10)

    try:
        debts = paginator.page(page_number)
    except PageNotAnInteger:
        debts = paginator.page(1)
    except EmptyPage:
        debts = paginator.page(paginator.num_pages)

    context = {
        'sale': sale,
        'debts': debts,
        'search_query': search_query,
        'paginator': paginator,
        'total_received': total_received,
        'payments_count': payments_count,
        'last_payment': last_payment,
        'page_title': f'سابقه دریافت بدهی - {sale.sale_number}',
    }

    return render(request, 'sale_debt/debt_history.html', context)