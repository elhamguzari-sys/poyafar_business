# apps/purchasesale/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import Purchase, Sale, CustomerReturn, SupplierReturn, Waste
from .forms import PurchaseForm, SaleForm, CustomerReturnForm, SupplierReturnForm, WasteForm
from apps.product.models import Product
from apps.stock.models import Location, Inventory
from apps.treasury.exceptions import InsufficientTreasuryBalance


# ======================================================================
# Helper: موجودی قدیمی یک سند از items ذخیره‌شده
# ======================================================================
def _extract_old_quantities(items):
    """✅ FIXED: از items یک سند ذخیره‌شده، دیکشنری { "product_id_location_id": quantity } می‌سازد."""
    old_quantities = {}
    if not items:
        return old_quantities
    for item in items:
        key = f"{item.get('product_id')}_{item.get('location_id')}"
        old_quantities[key] = old_quantities.get(key, 0) + int(item.get('quantity', 0) or 0)
    return old_quantities


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
# Purchase Views
# ======================================================================
def purchase_list(request):
    """لیست خریدها با فیلتر و جستجو"""
    purchases_list = Purchase.objects.all().order_by('-purchase_date')

    search_query = request.GET.get('search', '').strip()
    supplier_filter = request.GET.get('supplier', '').strip()
    supplier_number_filter = request.GET.get('supplier_number', '').strip()
    payment_status = request.GET.get('payment_status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    min_amount = request.GET.get('min_amount', '').strip()
    max_amount = request.GET.get('max_amount', '').strip()

    if search_query:
        purchases_list = purchases_list.filter(
            Q(purchase_number__icontains=search_query) |
            Q(supplier_name__icontains=search_query) |
            Q(supplier_number__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if supplier_filter:
        purchases_list = purchases_list.filter(supplier_name__icontains=supplier_filter)

    if supplier_number_filter:
        purchases_list = purchases_list.filter(supplier_number__icontains=supplier_number_filter)

    if payment_status == 'paid':
        purchases_list = purchases_list.filter(remaining_amount__lte=0)
    elif payment_status == 'partial':
        purchases_list = purchases_list.filter(paid_amount__gt=0, remaining_amount__gt=0)
    elif payment_status == 'unpaid':
        purchases_list = purchases_list.filter(paid_amount=0)

    if date_from:
        purchases_list = purchases_list.filter(purchase_date__date__gte=date_from)
    if date_to:
        purchases_list = purchases_list.filter(purchase_date__date__lte=date_to)

    if min_amount:
        try:
            purchases_list = purchases_list.filter(total_amount__gte=float(min_amount))
        except ValueError:
            pass
    if max_amount:
        try:
            purchases_list = purchases_list.filter(total_amount__lte=float(max_amount))
        except ValueError:
            pass

    total_purchases = purchases_list.count()
    today = timezone.now().date()
    today_purchases = purchases_list.filter(purchase_date__date=today).count()

    total_amount = purchases_list.aggregate(total=Sum('total_amount'))['total'] or 0
    total_paid = purchases_list.aggregate(total=Sum('paid_amount'))['total'] or 0
    total_remaining = purchases_list.aggregate(total=Sum('remaining_amount'))['total'] or 0
    total_dollar = purchases_list.aggregate(total=Sum('total_dollar_amount'))['total'] or 0

    today_amount = purchases_list.filter(purchase_date__date=today).aggregate(total=Sum('total_amount'))['total'] or 0

    seven_days_ago = today - timedelta(days=7)
    recent_purchases = purchases_list.filter(purchase_date__date__gte=seven_days_ago).count()

    total_items = sum(len(p.items) for p in purchases_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(purchases_list, 15)
    try:
        purchases = paginator.page(page_number)
    except PageNotAnInteger:
        purchases = paginator.page(1)
    except EmptyPage:
        purchases = paginator.page(paginator.num_pages)

    suppliers = Purchase.objects.values_list('supplier_name', flat=True).distinct().order_by('supplier_name')
    products_dict = {p.id: p.name for p in Product.objects.all()}

    locations_map = {loc.id: loc.name for loc in Location.objects.all()}
    for purchase in purchases:
        for item in purchase.items:
            if 'location_name' not in item:
                item['location_name'] = locations_map.get(item.get('location_id'), '---')

    context = {
        'purchases': purchases,
        'paginator': paginator,
        'page_title': 'لیست خریدها',
        'search_query': search_query,
        'supplier_filter': supplier_filter,
        'supplier_number_filter': supplier_number_filter,
        'payment_status': payment_status,
        'date_from': date_from,
        'date_to': date_to,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'suppliers': suppliers,
        'total_purchases': total_purchases,
        'today_purchases': today_purchases,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
        'total_dollar': total_dollar,
        'today_amount': today_amount,
        'total_items': total_items,
        'recent_purchases': recent_purchases,
        'today': today,
        'products_dict': products_dict,
    }

    return render(request, 'purchase/purchase_list.html', context)


def create_purchase(request):
    """ثبت خرید جدید — با چک موجودی خزانه"""
    if request.method == 'POST':
        form = PurchaseForm(request.POST)
        if form.is_valid():
            try:
                purchase = form.save()
                total_items = len(purchase.items)
                total_quantity = sum(item.get('quantity', 0) for item in purchase.items)

                msg = (f'✅ خرید "{purchase.purchase_number}" موفقانه ثبت شد.\n'
                       f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}\n'
                       f'مجموع کل: {purchase.total_amount} افغانی')
                if purchase.total_dollar_amount > 0:
                    msg += f'\nمعادل دالری: {purchase.total_dollar_amount} دالر (نرخ: {purchase.dollar_rate})'
                messages.success(request, msg)
                return redirect('purchase_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}\n'
                    f'لطفاً ابتدا موجودی خزانه را افزایش دهید.'
                )
            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = PurchaseForm()

    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity

    context = {
        'form': form,
        'page_title': 'ثبت خرید جدید',
        'total_items': 0,
        'products': Product.objects.all().order_by('name'),
        'today_purchases': Purchase.objects.filter(purchase_date__date=timezone.now().date()).count(),
        'is_create': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'purchase/create_purchase.html', context)


def update_purchase(request, purchase_id):
    """ویرایش خرید — با چک موجودی خزانه"""
    purchase = get_object_or_404(Purchase, pk=purchase_id)

    if request.method == 'POST':
        form = PurchaseForm(request.POST, instance=purchase)
        if form.is_valid():
            try:
                updated_purchase = form.save()
                total_items = len(updated_purchase.items)
                total_quantity = sum(item.get('quantity', 0) for item in updated_purchase.items)

                msg = (f'✅ خرید "{updated_purchase.purchase_number}" موفقانه ویرایش شد.\n'
                       f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}\n'
                       f'مجموع کل: {updated_purchase.total_amount} افغانی')
                if updated_purchase.total_dollar_amount > 0:
                    msg += f'\nمعادل دالری: {updated_purchase.total_dollar_amount} دالر (نرخ: {updated_purchase.dollar_rate})'
                messages.success(request, msg)
                return redirect('purchase_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}\n'
                    f'لطفاً ابتدا موجودی خزانه را افزایش دهید.'
                )
            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = PurchaseForm(instance=purchase)

    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity

    context = {
        'form': form,
        'products': Product.objects.all().order_by('name'),
        'purchase': purchase,
        'page_title': f'ویرایش خرید - {purchase.purchase_number}',
        'total_items': len(purchase.items) if purchase.items else 0,
        'today_purchases': Purchase.objects.filter(purchase_date__date=timezone.now().date()).count(),
        'is_edit': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'purchase/update_purchase.html', context)


def delete_purchase(request, purchase_id):
    """حذف خرید — با چک پرداخت‌های قسطی و ProtectedError"""
    purchase = get_object_or_404(Purchase, pk=purchase_id)

    if request.method == 'POST':
        purchase_number = purchase.purchase_number

        if not purchase.can_be_deleted():
            debts_count = purchase.debts.count()
            messages.error(
                request,
                f'❌ خرید "{purchase_number}" دارای {debts_count} پرداخت قسطی است.\n'
                f'👉 ابتدا پرداخت‌های قسطی را حذف کنید، سپس خرید را حذف کنید.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('purchase_list')

        try:
            purchase.delete()
            messages.success(request, f'✓ خرید "{purchase_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف خرید "{purchase_number}" ممکن نیست. '
                f'وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('purchase_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('purchase_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('purchase_list')

    context = {
        'purchase': purchase,
        'page_title': f'حذف خرید - {purchase.purchase_number}',
    }
    return render(request, 'purchase/purchase_list.html', context)


# ======================================================================
# Sale Views
# ======================================================================
def sale_list(request):
    """لیست فروش‌ها با فیلتر و جستجو"""
    sales_list = Sale.objects.all().order_by('-sale_date')

    search_query = request.GET.get('search', '').strip()
    customer_filter = request.GET.get('customer', '').strip()
    customer_number_filter = request.GET.get('customer_number', '').strip()
    payment_status = request.GET.get('payment_status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    min_amount = request.GET.get('min_amount', '').strip()
    max_amount = request.GET.get('max_amount', '').strip()

    if search_query:
        sales_list = sales_list.filter(
            Q(sale_number__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(customer_number__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if customer_filter:
        sales_list = sales_list.filter(customer_name__icontains=customer_filter)

    if customer_number_filter:
        sales_list = sales_list.filter(customer_number__icontains=customer_number_filter)

    if payment_status == 'paid':
        sales_list = sales_list.filter(remaining_amount__lte=0)
    elif payment_status == 'partial':
        sales_list = sales_list.filter(received_amount__gt=0, remaining_amount__gt=0)
    elif payment_status == 'unpaid':
        sales_list = sales_list.filter(received_amount=0)

    if date_from:
        sales_list = sales_list.filter(sale_date__date__gte=date_from)
    if date_to:
        sales_list = sales_list.filter(sale_date__date__lte=date_to)

    if min_amount:
        try:
            sales_list = sales_list.filter(total_amount__gte=float(min_amount))
        except ValueError:
            pass
    if max_amount:
        try:
            sales_list = sales_list.filter(total_amount__lte=float(max_amount))
        except ValueError:
            pass

    total_sales_count = sales_list.count()
    today = timezone.now().date()
    today_sales_count = sales_list.filter(sale_date__date=today).count()

    total_amount = sales_list.aggregate(total=Sum('total_amount'))['total'] or 0
    total_received = sales_list.aggregate(total=Sum('received_amount'))['total'] or 0
    total_remaining = sales_list.aggregate(total=Sum('remaining_amount'))['total'] or 0
    total_dollar = sales_list.aggregate(total=Sum('total_dollar_amount'))['total'] or 0

    today_amount = sales_list.filter(sale_date__date=today).aggregate(total=Sum('total_amount'))['total'] or 0

    seven_days_ago = today - timedelta(days=7)
    recent_sales = sales_list.filter(sale_date__date__gte=seven_days_ago).count()

    total_items = sum(len(s.items) for s in sales_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(sales_list, 15)
    try:
        sales = paginator.page(page_number)
    except PageNotAnInteger:
        sales = paginator.page(1)
    except EmptyPage:
        sales = paginator.page(paginator.num_pages)

    customers = Sale.objects.values_list('customer_name', flat=True).distinct().order_by('customer_name')
    products_dict = {p.id: p.name for p in Product.objects.all()}

    locations_map = {loc.id: loc.name for loc in Location.objects.all()}
    for sale in sales:
        for item in sale.items:
            if 'location_name' not in item:
                item['location_name'] = locations_map.get(item.get('location_id'), '---')

    context = {
        'sales': sales,
        'paginator': paginator,
        'page_title': 'لیست فروش‌ها',
        'search_query': search_query,
        'customer_filter': customer_filter,
        'customer_number_filter': customer_number_filter,
        'payment_status': payment_status,
        'date_from': date_from,
        'date_to': date_to,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'customers': customers,
        'total_sales': total_sales_count,
        'today_sales': today_sales_count,
        'total_amount': total_amount,
        'total_received': total_received,
        'total_remaining': total_remaining,
        'total_dollar': total_dollar,
        'today_amount': today_amount,
        'total_items': total_items,
        'recent_sales': recent_sales,
        'today': today,
        'products_dict': products_dict,
    }

    return render(request, 'sale/sale_list.html', context)


def create_sale(request):
    """ثبت فروش جدید با چند قلم و ارز"""
    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save()
            total_items = len(sale.items)
            total_quantity = sum(item.get('quantity', 0) for item in sale.items)

            msg = (f'فروش "{sale.sale_number}" موفقانه ثبت شد.\n'
                   f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}\n'
                   f'مجموع کل: {sale.total_amount} افغانی')
            if sale.total_dollar_amount > 0:
                msg += f'\nمعادل دالری: {sale.total_dollar_amount} دالر (نرخ: {sale.dollar_rate})'
            messages.success(request, msg)
            return redirect('sale_list')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = SaleForm()

    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity

    context = {
        'form': form,
        'page_title': 'ثبت فروش جدید',
        'total_items': 0,
        'products': Product.objects.all().order_by('name'),
        'today_sales': Sale.objects.filter(sale_date__date=timezone.now().date()).count(),
        'is_create': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'sale/create_sale.html', context)


def update_sale(request, sale_id):
    """
    ✅ FIXED: ویرایش فروش.
    stock_data شامل موجودی فعلی + مقدار قدیمی این سند می‌شود
    تا JavaScript تمپلیت بداند چه مقدار قابل فروش است.
    """
    sale = get_object_or_404(Sale, pk=sale_id)

    if request.method == 'POST':
        form = SaleForm(request.POST, instance=sale)
        if form.is_valid():
            updated_sale = form.save()
            total_items = len(updated_sale.items)
            total_quantity = sum(item.get('quantity', 0) for item in updated_sale.items)

            msg = (f'فروش "{updated_sale.sale_number}" موفقانه ویرایش شد.\n'
                   f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}\n'
                   f'مجموع کل: {updated_sale.total_amount} افغانی')
            if updated_sale.total_dollar_amount > 0:
                msg += f'\nمعادل دالری: {updated_sale.total_dollar_amount} دالر (نرخ: {updated_sale.dollar_rate})'
            messages.success(request, msg)
            return redirect('sale_list')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = SaleForm(instance=sale)

    # ✅ FIXED: موجودی قدیمی به stock_data اضافه شود
    old_quantities = _extract_old_quantities(sale.items)
    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity + old_quantities.get(key, 0)

    context = {
        'form': form,
        'products': Product.objects.all().order_by('name'),
        'sale': sale,
        'page_title': f'ویرایش فروش - {sale.sale_number}',
        'total_items': len(sale.items) if sale.items else 0,
        'today_sales': Sale.objects.filter(sale_date__date=timezone.now().date()).count(),
        'is_edit': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'sale/update_sale.html', context)


def delete_sale(request, sale_id):
    """حذف فروش — با چک دریافت‌های قسطی و ProtectedError"""
    sale = get_object_or_404(Sale, pk=sale_id)

    if request.method == 'POST':
        sale_number = sale.sale_number

        if not sale.can_be_deleted():
            debts_count = sale.debts.count()
            messages.error(
                request,
                f'❌ فروش "{sale_number}" دارای {debts_count} دریافت قسطی است.\n'
                f'👉 ابتدا دریافت‌های قسطی را حذف کنید، سپس فروش را حذف کنید.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('sale_list')

        try:
            sale.delete()
            messages.success(request, f'✓ فروش "{sale_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف فروش "{sale_number}" ممکن نیست. '
                f'وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('sale_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('sale_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('sale_list')

    context = {
        'sale': sale,
        'page_title': f'حذف فروش - {sale.sale_number}',
    }
    return render(request, 'sale/sale_list.html', context)


# ======================================================================
# CustomerReturn Views
# ======================================================================
def customer_return_list(request):
    """لیست مرجوعی‌های مشتریان"""
    returns_list = CustomerReturn.objects.all().order_by('-return_date')

    search_query = request.GET.get('search', '').strip()
    customer_filter = request.GET.get('customer', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if search_query:
        returns_list = returns_list.filter(
            Q(return_number__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if customer_filter:
        returns_list = returns_list.filter(customer_name__icontains=customer_filter)

    if date_from:
        returns_list = returns_list.filter(return_date__date__gte=date_from)
    if date_to:
        returns_list = returns_list.filter(return_date__date__lte=date_to)

    total_returns = returns_list.count()
    today = timezone.now().date()
    today_returns = returns_list.filter(return_date__date=today).count()

    seven_days_ago = today - timedelta(days=7)
    recent_returns = returns_list.filter(return_date__date__gte=seven_days_ago).count()

    total_items = sum(len(r.items) for r in returns_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(returns_list, 15)
    try:
        returns = paginator.page(page_number)
    except PageNotAnInteger:
        returns = paginator.page(1)
    except EmptyPage:
        returns = paginator.page(paginator.num_pages)

    customers = CustomerReturn.objects.values_list('customer_name', flat=True).distinct().order_by('customer_name')
    products_dict = {p.id: p.name for p in Product.objects.all()}

    locations_map = {loc.id: loc.name for loc in Location.objects.all()}
    for ret in returns:
        for item in ret.items:
            if 'location_name' not in item:
                item['location_name'] = locations_map.get(item.get('location_id'), '---')

    context = {
        'returns': returns,
        'paginator': paginator,
        'page_title': 'لیست مرجوعی‌های مشتریان',
        'search_query': search_query,
        'customer_filter': customer_filter,
        'date_from': date_from,
        'date_to': date_to,
        'customers': customers,
        'total_returns': total_returns,
        'today_returns': today_returns,
        'total_items': total_items,
        'recent_returns': recent_returns,
        'today': today,
        'products_dict': products_dict,
    }

    return render(request, 'customer_return/customer_return_list.html', context)


def _build_sales_with_items(limit=500):
    """✅ FIXED: ساخت داده کامل فروش‌ها برای JavaScript"""
    sales_with_items = []
    for sale in Sale.objects.all().order_by('-sale_date')[:limit]:
        sales_with_items.append({
            'id': sale.id,
            'number': sale.sale_number,
            'customer': sale.customer_name,
            'customer_number': sale.customer_number or '',
            'date': sale.sale_date.strftime('%Y/%m/%d') if sale.sale_date else '',
            'note': sale.note or '',
            'total_amount': float(sale.total_amount or 0),
            'total_dollar_amount': float(sale.total_dollar_amount or 0),
            'dollar_rate': float(sale.dollar_rate or 0),
            'received_amount': float(sale.received_amount or 0),
            'remaining_amount': float(sale.remaining_amount or 0),
            'total_returned_amount': float(sale.total_returned_amount or 0),
            'items': [
                {
                    'product_id': it.get('product_id'),
                    'product_name': it.get('product_name') or '',
                    'quantity': int(it.get('quantity', 0) or 0),
                    'sale_price': float(it.get('sale_price', 0) or 0),
                    'currency': it.get('currency', 'AFN'),
                    'location_id': it.get('location_id'),
                    'location_name': it.get('location_name') or '',
                }
                for it in (sale.items or [])
            ],
        })
    return sales_with_items


def create_customer_return(request):
    """ثبت مرجوعی جدید از مشتری — با نمایش کامل جزئیات فروش"""
    if request.method == 'POST':
        form = CustomerReturnForm(request.POST)
        if form.is_valid():
            try:
                customer_return = form.save()
                total_items = len(customer_return.items)
                total_quantity = sum(item.get('quantity', 0) for item in customer_return.items)
                messages.success(
                    request,
                    f'✅ مرجوعی "{customer_return.return_number}" موفقانه ثبت شد.\n'
                    f'فروش اصلی: {customer_return.original_sale.sale_number}\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
                )
                return redirect('customer_return_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}'
                )
            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = CustomerReturnForm()

    sales_with_items = _build_sales_with_items()

    context = {
        'form': form,
        'page_title': 'ثبت مرجوعی جدید از مشتری',
        'today_returns': CustomerReturn.objects.filter(return_date__date=timezone.now().date()).count(),
        'is_create': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'sales_data': sales_with_items,
        'products': Product.objects.all().order_by('name'),
    }
    return render(request, 'customer_return/create_customer_return.html', context)


def update_customer_return(request, return_id):
    """
    ✅ FIXED: ویرایش مرجوعی از مشتری.
    stock_data اضافه شد (اگرچه برای CustomerReturn چک موجودی نیست،
    اما برای یکدستی و آینده مفید است).
    """
    customer_return = get_object_or_404(CustomerReturn, pk=return_id)

    if request.method == 'POST':
        form = CustomerReturnForm(request.POST, instance=customer_return)
        if form.is_valid():
            try:
                updated_return = form.save()
                total_items = len(updated_return.items)
                total_quantity = sum(item.get('quantity', 0) for item in updated_return.items)
                messages.success(
                    request,
                    f'✅ مرجوعی "{updated_return.return_number}" موفقانه ویرایش شد.\n'
                    f'فروش اصلی: {updated_return.original_sale.sale_number}\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
                )
                return redirect('customer_return_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}'
                )
            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = CustomerReturnForm(instance=customer_return)

    sales_with_items = _build_sales_with_items()
    current_items = customer_return.items or []

    context = {
        'form': form,
        'customer_return': customer_return,
        'page_title': f'ویرایش مرجوعی - {customer_return.return_number}',
        'today_returns': CustomerReturn.objects.filter(return_date__date=timezone.now().date()).count(),
        'is_edit': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'sales_data': sales_with_items,
        'products': Product.objects.all().order_by('name'),
        'current_items': current_items,
    }
    return render(request, 'customer_return/update_customer_return.html', context)


def delete_customer_return(request, return_id):
    """حذف مرجوعی از مشتری — با کنترل ProtectedError"""
    customer_return = get_object_or_404(CustomerReturn, pk=return_id)
    if request.method == 'POST':
        return_number = customer_return.return_number
        try:
            customer_return.delete()
            messages.success(request, f'✓ مرجوعی "{return_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف مرجوعی "{return_number}" ممکن نیست. '
                f'وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('customer_return_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('customer_return_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('customer_return_list')

    context = {
        'customer_return': customer_return,
        'page_title': f'حذف مرجوعی - {customer_return.return_number}',
    }
    return render(request, 'customer_return/customer_return_list.html', context)


# ======================================================================
# SupplierReturn Views
# ======================================================================
def supplier_return_list(request):
    """لیست مرجوعی‌های به تأمین‌کنندگان"""
    returns_list = SupplierReturn.objects.all().order_by('-return_date')

    search_query = request.GET.get('search', '').strip()
    supplier_filter = request.GET.get('supplier', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if search_query:
        returns_list = returns_list.filter(
            Q(return_number__icontains=search_query) |
            Q(supplier_name__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if supplier_filter:
        returns_list = returns_list.filter(supplier_name__icontains=supplier_filter)

    if date_from:
        returns_list = returns_list.filter(return_date__date__gte=date_from)
    if date_to:
        returns_list = returns_list.filter(return_date__date__lte=date_to)

    total_returns = returns_list.count()
    today = timezone.now().date()
    today_returns = returns_list.filter(return_date__date=today).count()

    seven_days_ago = today - timedelta(days=7)
    recent_returns = returns_list.filter(return_date__date__gte=seven_days_ago).count()

    total_items = sum(len(r.items) for r in returns_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(returns_list, 15)
    try:
        returns = paginator.page(page_number)
    except PageNotAnInteger:
        returns = paginator.page(1)
    except EmptyPage:
        returns = paginator.page(paginator.num_pages)

    suppliers = SupplierReturn.objects.values_list('supplier_name', flat=True).distinct().order_by('supplier_name')
    products_dict = {p.id: p.name for p in Product.objects.all()}

    locations_map = {loc.id: loc.name for loc in Location.objects.all()}
    for ret in returns:
        for item in ret.items:
            if 'location_name' not in item:
                item['location_name'] = locations_map.get(item.get('location_id'), '---')

    context = {
        'returns': returns,
        'paginator': paginator,
        'page_title': 'لیست مرجوعی‌های به تأمین‌کنندگان',
        'search_query': search_query,
        'supplier_filter': supplier_filter,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'total_returns': total_returns,
        'today_returns': today_returns,
        'total_items': total_items,
        'recent_returns': recent_returns,
        'today': today,
        'products_dict': products_dict,
    }

    return render(request, 'supplier_return/supplier_return_list.html', context)


def _build_purchases_with_items(limit=500):
    """✅ FIXED: ساخت داده کامل خریدها برای JavaScript"""
    purchases_with_items = []
    for purchase in Purchase.objects.all().order_by('-purchase_date')[:limit]:
        purchases_with_items.append({
            'id': purchase.id,
            'number': purchase.purchase_number,
            'supplier': purchase.supplier_name,
            'supplier_number': purchase.supplier_number or '',
            'date': purchase.purchase_date.strftime('%Y/%m/%d') if purchase.purchase_date else '',
            'note': purchase.note or '',
            'total_amount': float(purchase.total_amount or 0),
            'total_dollar_amount': float(purchase.total_dollar_amount or 0),
            'dollar_rate': float(purchase.dollar_rate or 0),
            'paid_amount': float(purchase.paid_amount or 0),
            'remaining_amount': float(purchase.remaining_amount or 0),
            'total_returned_amount': float(purchase.total_returned_amount or 0),
            'items': [
                {
                    'product_id': it.get('product_id'),
                    'product_name': it.get('product_name') or '',
                    'quantity': int(it.get('quantity', 0) or 0),
                    'purchase_price': float(it.get('purchase_price', 0) or 0),
                    'currency': it.get('currency', 'AFN'),
                    'location_id': it.get('location_id'),
                    'location_name': it.get('location_name') or '',
                }
                for it in (purchase.items or [])
            ],
        })
    return purchases_with_items


def create_supplier_return(request):
    """ثبت مرجوعی جدید به تأمین‌کننده — با نمایش کامل جزئیات خرید"""
    from django.core.exceptions import ValidationError

    if request.method == 'POST':
        form = SupplierReturnForm(request.POST)
        if form.is_valid():
            try:
                supplier_return = form.save()
                total_items = len(supplier_return.items)
                total_quantity = sum(item.get('quantity', 0) for item in supplier_return.items)
                messages.success(
                    request,
                    f'✅ مرجوعی "{supplier_return.return_number}" موفقانه ثبت شد.\n'
                    f'خرید اصلی: {supplier_return.original_purchase.purchase_number}\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
                )
                return redirect('supplier_return_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}'
                )

            except ValidationError as e:
                error_msg = e.messages[0] if e.messages else str(e)
                messages.error(request, f'⚠️ {error_msg}')

            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = SupplierReturnForm()

    purchases_with_items = _build_purchases_with_items()

    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity

    context = {
        'form': form,
        'page_title': 'ثبت مرجوعی جدید به تأمین‌کننده',
        'today_returns': SupplierReturn.objects.filter(return_date__date=timezone.now().date()).count(),
        'is_create': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'purchases_data': purchases_with_items,
        'stock_data': stock_data,
        'products': Product.objects.all().order_by('name'),
    }
    return render(request, 'supplier_return/create_supplier_return.html', context)


def update_supplier_return(request, return_id):
    """
    ✅ FIXED: ویرایش مرجوعی به تأمین‌کننده.
    stock_data شامل موجودی فعلی + مقدار برگشتی این سند می‌شود
    تا موجودی قابل برگشت درست محاسبه شود.
    """
    from django.core.exceptions import ValidationError

    supplier_return = get_object_or_404(SupplierReturn, pk=return_id)

    if request.method == 'POST':
        form = SupplierReturnForm(request.POST, instance=supplier_return)
        if form.is_valid():
            try:
                updated_return = form.save()
                total_items = len(updated_return.items)
                total_quantity = sum(item.get('quantity', 0) for item in updated_return.items)
                messages.success(
                    request,
                    f'✅ مرجوعی "{updated_return.return_number}" موفقانه ویرایش شد.\n'
                    f'خرید اصلی: {updated_return.original_purchase.purchase_number}\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
                )
                return redirect('supplier_return_list')

            except InsufficientTreasuryBalance as e:
                currency_label = 'افغانی' if e.currency == 'AFG' else 'دالر'
                messages.error(
                    request,
                    f'⚠️ {e.message}\n'
                    f'💰 موجودی فعلی: {e.current_balance} {currency_label}\n'
                    f'💸 مورد نیاز: {e.required_amount} {currency_label}'
                )

            except ValidationError as e:
                error_msg = e.messages[0] if e.messages else str(e)
                messages.error(request, f'⚠️ {error_msg}')

            except Exception as e:
                messages.error(request, f'⚠️ خطا: {str(e)}')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = SupplierReturnForm(instance=supplier_return)

    purchases_with_items = _build_purchases_with_items()
    current_items = supplier_return.items or []

    # ✅ FIXED: stock_data شامل مقدار قدیمی این سند
    old_quantities = _extract_old_quantities(supplier_return.items)
    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity + old_quantities.get(key, 0)

    context = {
        'form': form,
        'supplier_return': supplier_return,
        'page_title': f'ویرایش مرجوعی - {supplier_return.return_number}',
        'today_returns': SupplierReturn.objects.filter(return_date__date=timezone.now().date()).count(),
        'is_edit': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'purchases_data': purchases_with_items,
        'stock_data': stock_data,
        'products': Product.objects.all().order_by('name'),
        'current_items': current_items,
    }
    return render(request, 'supplier_return/update_supplier_return.html', context)


def delete_supplier_return(request, return_id):
    """حذف مرجوعی به تأمین‌کننده — با کنترل ProtectedError"""
    supplier_return = get_object_or_404(SupplierReturn, pk=return_id)
    if request.method == 'POST':
        return_number = supplier_return.return_number
        try:
            supplier_return.delete()
            messages.success(request, f'✓ مرجوعی "{return_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف مرجوعی "{return_number}" ممکن نیست. '
                f'وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('supplier_return_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('supplier_return_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('supplier_return_list')

    context = {
        'supplier_return': supplier_return,
        'page_title': f'حذف مرجوعی - {supplier_return.return_number}',
    }
    return render(request, 'supplier_return/supplier_return_list.html', context)


# ======================================================================
# Waste Views
# ======================================================================
def waste_list(request):
    """لیست ضایعات کالاها با فیلتر و جستجو"""
    wastes_list = Waste.objects.all().order_by('-waste_date')

    search_query = request.GET.get('search', '').strip()
    reason_filter = request.GET.get('reason', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if search_query:
        wastes_list = wastes_list.filter(
            Q(waste_number__icontains=search_query) |
            Q(reason__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if reason_filter:
        wastes_list = wastes_list.filter(reason__icontains=reason_filter)

    if date_from:
        wastes_list = wastes_list.filter(waste_date__date__gte=date_from)
    if date_to:
        wastes_list = wastes_list.filter(waste_date__date__lte=date_to)

    total_wastes = wastes_list.count()
    today = timezone.now().date()
    today_wastes = wastes_list.filter(waste_date__date=today).count()

    seven_days_ago = today - timedelta(days=7)
    recent_wastes = wastes_list.filter(waste_date__date__gte=seven_days_ago).count()

    total_items = sum(len(w.items) for w in wastes_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(wastes_list, 15)
    try:
        wastes = paginator.page(page_number)
    except PageNotAnInteger:
        wastes = paginator.page(1)
    except EmptyPage:
        wastes = paginator.page(paginator.num_pages)

    reasons = Waste.objects.values_list('reason', flat=True).distinct().order_by('reason')
    products_dict = {p.id: p.name for p in Product.objects.all()}

    locations_map = {loc.id: loc.name for loc in Location.objects.all()}
    for w in wastes:
        for item in w.items:
            if 'location_name' not in item:
                item['location_name'] = locations_map.get(item.get('location_id'), '---')

    context = {
        'wastes': wastes,
        'paginator': paginator,
        'page_title': 'لیست ضایعات کالاها',
        'search_query': search_query,
        'reason_filter': reason_filter,
        'date_from': date_from,
        'date_to': date_to,
        'reasons': reasons,
        'total_wastes': total_wastes,
        'today_wastes': today_wastes,
        'total_items': total_items,
        'recent_wastes': recent_wastes,
        'today': today,
        'products_dict': products_dict,
    }

    return render(request, 'waste/waste_list.html', context)


def create_waste(request):
    """ثبت ضایعات جدید"""
    if request.method == 'POST':
        form = WasteForm(request.POST)
        if form.is_valid():
            waste = form.save()
            total_items = len(waste.items)
            total_quantity = sum(item.get('quantity', 0) for item in waste.items)
            messages.success(
                request,
                f'ضایعات "{waste.waste_number}" موفقانه ثبت شد.\n'
                f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
            )
            return redirect('waste_list')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = WasteForm()

    total_items_count = 0
    today_wastes = Waste.objects.filter(waste_date__date=timezone.now().date()).count()

    # ✅ stock_data برای چک client-side در تمپلیت
    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity

    context = {
        'form': form,
        'page_title': 'ثبت ضایعات جدید',
        'total_items': total_items_count,
        'products': Product.objects.all().order_by('name'),
        'today_wastes': today_wastes,
        'is_create': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'waste/create_waste.html', context)


def update_waste(request, waste_id):
    """
    ✅ FIXED: ویرایش ضایعات.
    stock_data شامل موجودی فعلی + مقدار قدیمی این سند می‌شود.
    """
    waste = get_object_or_404(Waste, pk=waste_id)

    if request.method == 'POST':
        form = WasteForm(request.POST, instance=waste)
        if form.is_valid():
            updated_waste = form.save()
            total_items = len(updated_waste.items)
            total_quantity = sum(item.get('quantity', 0) for item in updated_waste.items)
            messages.success(
                request,
                f'ضایعات "{updated_waste.waste_number}" موفقانه ویرایش شد.\n'
                f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity}'
            )
            return redirect('waste_list')
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field != '__all__':
                        if field == 'items_json':
                            error_messages.append(f'اقلام: {error}')
                        else:
                            field_label = form.fields[field].label if field in form.fields else field
                            error_messages.append(f'{field_label}: {error}')
                    else:
                        error_messages.append(error)
            messages.error(request, 'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages))
    else:
        form = WasteForm(instance=waste)

    # ✅ FIXED: موجودی قدیمی به stock_data اضافه شود
    old_quantities = _extract_old_quantities(waste.items)
    stock_data = {}
    for inv in Inventory.objects.select_related('product', 'location').all():
        key = f"{inv.product_id}_{inv.location_id}"
        stock_data[key] = inv.quantity + old_quantities.get(key, 0)

    today_wastes = Waste.objects.filter(waste_date__date=timezone.now().date()).count()
    total_items_count = len(waste.items) if waste.items else 0

    context = {
        'form': form,
        'products': Product.objects.all().order_by('name'),
        'waste': waste,
        'page_title': f'ویرایش ضایعات - {waste.waste_number}',
        'total_items': total_items_count,
        'today_wastes': today_wastes,
        'is_edit': True,
        'locations': Location.objects.filter(is_active=True).order_by('type', 'code'),
        'stock_data': stock_data,
    }
    return render(request, 'waste/update_waste.html', context)


def delete_waste(request, waste_id):
    """حذف ضایعات — با کنترل ProtectedError"""
    waste = get_object_or_404(Waste, pk=waste_id)
    if request.method == 'POST':
        waste_number = waste.waste_number
        try:
            waste.delete()
            messages.success(request, f'✓ ضایعات "{waste_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ حذف ضایعات "{waste_number}" ممکن نیست. '
                f'وابسته به {details} است.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('waste_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('waste_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('waste_list')

    context = {
        'waste': waste,
        'page_title': f'حذف ضایعات - {waste.waste_number}',
    }
    return render(request, 'waste/waste_list.html', context)