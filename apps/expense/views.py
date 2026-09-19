# apps/expense/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import Expense
from .forms import ExpenseForm
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


def expense_list(request):
    """لیست مصارف با فیلتر و جستجو"""

    expenses_list = Expense.objects.all().order_by('-expense_date')

    search_query = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    min_amount = request.GET.get('min_amount', '').strip()
    max_amount = request.GET.get('max_amount', '').strip()

    if search_query:
        expenses_list = expenses_list.filter(
            Q(expense_number__icontains=search_query) |
            Q(title__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if date_from:
        expenses_list = expenses_list.filter(expense_date__date__gte=date_from)

    if date_to:
        expenses_list = expenses_list.filter(expense_date__date__lte=date_to)

    if min_amount:
        try:
            expenses_list = expenses_list.filter(total_amount__gte=float(min_amount))
        except ValueError:
            pass

    if max_amount:
        try:
            expenses_list = expenses_list.filter(total_amount__lte=float(max_amount))
        except ValueError:
            pass

    total_expenses = expenses_list.count()
    today = timezone.now().date()
    today_expenses = expenses_list.filter(expense_date__date=today).count()

    total_amount = expenses_list.aggregate(total=Sum('total_amount'))['total'] or 0

    today_amount = (
        expenses_list
        .filter(expense_date__date=today)
        .aggregate(total=Sum('total_amount'))['total'] or 0
    )

    seven_days_ago = today - timedelta(days=7)
    recent_expenses = expenses_list.filter(expense_date__date__gte=seven_days_ago).count()

    total_items = sum(len(e.items) for e in expenses_list)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(expenses_list, 15)

    try:
        expenses = paginator.page(page_number)
    except PageNotAnInteger:
        expenses = paginator.page(1)
    except EmptyPage:
        expenses = paginator.page(paginator.num_pages)

    context = {
        'expenses': expenses,
        'paginator': paginator,
        'page_title': 'لیست مصارف',
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'total_expenses': total_expenses,
        'today_expenses': today_expenses,
        'total_amount': total_amount,
        'today_amount': today_amount,
        'total_items': total_items,
        'recent_expenses': recent_expenses,
        'today': today,
    }

    return render(request, 'expense/expense_list.html', context)


def create_expense(request):
    """ثبت مصرف جدید — با چک موجودی خزانه"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                expense = form.save()

                total_items = len(expense.items)
                total_quantity = sum(item.get('quantity', 0) for item in expense.items)

                messages.success(
                    request,
                    f'✅ مصرف "{expense.expense_number}" موفقانه ثبت شد.\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity} | مجموع قیمت: {expense.total_amount}'
                )
                return redirect('expense_list')

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

            messages.error(
                request,
                'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages)
            )
    else:
        form = ExpenseForm()

    today_expenses = Expense.objects.filter(expense_date__date=timezone.now().date()).count()

    context = {
        'form': form,
        'page_title': 'ثبت مصرف جدید',
        'total_items': 0,
        'today_expenses': today_expenses,
        'is_create': True,
    }

    return render(request, 'expense/create_expense.html', context)


def update_expense(request, expense_id):
    """ویرایش مصرف — با چک موجودی خزانه"""
    expense = get_object_or_404(Expense, pk=expense_id)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)

        if form.is_valid():
            try:
                updated_expense = form.save()

                total_items = len(updated_expense.items)
                total_quantity = sum(item.get('quantity', 0) for item in updated_expense.items)

                messages.success(
                    request,
                    f'✅ مصرف "{updated_expense.expense_number}" موفقانه ویرایش شد.\n'
                    f'تعداد قلم‌ها: {total_items} | مجموع تعداد: {total_quantity} | مجموع قیمت: {updated_expense.total_amount}'
                )
                return redirect('expense_list')

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

            messages.error(
                request,
                'لطفاً معلومات را درست وارد کنید:\n' + '\n'.join(error_messages)
            )
    else:
        form = ExpenseForm(instance=expense)

    today_expenses = Expense.objects.filter(expense_date__date=timezone.now().date()).count()
    total_items_count = len(expense.items) if expense.items else 0

    context = {
        'form': form,
        'expense': expense,
        'page_title': f'ویرایش مصرف - {expense.expense_number}',
        'total_items': total_items_count,
        'today_expenses': today_expenses,
        'is_edit': True,
    }

    return render(request, 'expense/update_expense.html', context)


def delete_expense(request, expense_id):
    """حذف مصرف — با کنترل ProtectedError"""
    expense = get_object_or_404(Expense, pk=expense_id)

    if request.method == 'POST':
        expense_number = expense.expense_number
        try:
            expense.delete()
            messages.success(request, f'مصرف "{expense_number}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'❌ نمی‌توان مصرف "{expense_number}" را حذف کرد. '
                f'وابسته به {details} است. '
                f'ابتدا رکوردهای مربوطه را حذف یا اصلاح کنید.'
            )
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('expense_list')
        except Exception as e:
            messages.error(request, f'⚠️ خطا: {str(e)}')
            if request.headers.get('HX-Request'):
                return HttpResponse(status=409)
            return redirect('expense_list')

        if request.headers.get('HX-Request'):
            return HttpResponse(status=200)
        return redirect('expense_list')

    context = {
        'expense': expense,
        'page_title': f'حذف مصرف - {expense.expense_number}',
    }

    return render(request, 'expense/expense_list.html', context)