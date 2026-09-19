# apps/employee/views.py

from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Sum, F
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import ProtectedError
from .models import Employee, Salary
from .forms import EmployeeForm, SalaryForm
from apps.treasury.exceptions import InsufficientTreasuryBalance


# ==================================================================
# HELPER: ساخت پیام خطای حذف
# ==================================================================

FA_LABELS = {
    'Salary': 'رکورد معاش',
    'Employee': 'کارمند',
    'Inventory': 'رکورد موجودی',
    'StockMovement': 'حرکت انبار',
    'Product': 'محصول',
    'Category': 'دسته‌بندی',
}


def _protected_summary(exc: ProtectedError) -> str:
    """ساخت خلاصه فارسی از آبجکت‌های وابسته که مانع حذف شده‌اند."""
    counts = {}
    for obj in exc.protected_objects:
        name = obj.__class__.__name__
        counts[name] = counts.get(name, 0) + 1
    return '، '.join(
        f'{n} {FA_LABELS.get(name, name)}' for name, n in counts.items()
    )


# ==================================================================
# EMPLOYEE VIEWS
# ==================================================================

def employee_list(request):
    """لیست کارمندان با جستجو و فیلتر"""
    employees_list = Employee.objects.all().order_by('-created_at')

    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    if search_query:
        employees_list = employees_list.filter(
            Q(full_name__icontains=search_query) |
            Q(father_name__icontains=search_query) |
            Q(tazkera_number__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(position__icontains=search_query) |
            Q(address__icontains=search_query)
        )

    if status_filter == 'active':
        employees_list = employees_list.filter(leave_date__isnull=True)
    elif status_filter == 'terminated':
        employees_list = employees_list.filter(leave_date__isnull=False)

    total_employees_count = employees_list.count()
    active_employees_count = employees_list.filter(leave_date__isnull=True).count()
    terminated_employees_count = employees_list.filter(leave_date__isnull=False).count()
    total_salary = employees_list.filter(
        leave_date__isnull=True
    ).aggregate(total=Sum('base_salary'))['total'] or 0

    page_number = request.GET.get('page', 1)
    paginator = Paginator(employees_list, 10)

    try:
        employees = paginator.page(page_number)
    except PageNotAnInteger:
        employees = paginator.page(1)
    except EmptyPage:
        employees = paginator.page(paginator.num_pages)

    context = {
        'employees': employees,
        'search_query': search_query,
        'status_filter': status_filter,
        'paginator': paginator,
        'total_employees_count': total_employees_count,
        'active_employees_count': active_employees_count,
        'terminated_employees_count': terminated_employees_count,
        'total_salary': total_salary,
        'page_title': 'لیست کارمندان',
    }

    return render(request, 'employee/employee_list.html', context)


def create_employee(request):
    """ایجاد کارمند جدید"""
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES)

        if form.is_valid():
            employee = form.save()
            messages.success(
                request,
                f'کارمند "{employee.full_name}" موفقانه اضافه شد.'
            )
            return redirect('employee_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = EmployeeForm()

    return render(request, 'employee/create_employee.html', {
        'form': form,
        'page_title': 'اضافه کردن کارمند جدید',
    })


def update_employee(request, employee_id):
    """ویرایش کارمند"""
    employee = get_object_or_404(Employee, pk=employee_id)

    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee)

        if form.is_valid():
            updated_employee = form.save()
            messages.success(
                request,
                f'کارمند "{updated_employee.full_name}" موفقانه تصحیح شد.'
            )
            return redirect('employee_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = EmployeeForm(instance=employee)

    return render(request, 'employee/update_employee.html', {
        'form': form,
        'employee': employee,
        'page_title': f'ویرایش کارمند - {employee.full_name}',
    })


def delete_employee(request, employee_id):
    """حذف کارمند"""
    employee = get_object_or_404(Employee, id=employee_id)

    if request.method == 'POST':
        employee_name = employee.full_name
        try:
            employee.delete()
            messages.success(request, f'کارمند "{employee_name}" موفقانه حذف شد.')
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'نمی‌توان کارمند "{employee_name}" را حذف کرد. '
                f'این کارمند وابسته به {details} است. '
                f'ابتدا رکوردهای مربوطه را حذف کنید.'
            )
        return redirect('employee_list')

    return HttpResponse(status=405)


# ==================================================================
# SALARY VIEWS
# ==================================================================

def salary_list(request):
    """لیست معاشات با جستجو و فیلتر"""
    salaries_list = Salary.objects.all().order_by('-payment_date', '-created_at')

    search_query = request.GET.get('search', '')
    employee_filter = request.GET.get('employee', '')
    month_filter = request.GET.get('month', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if search_query:
        salaries_list = salaries_list.filter(
            Q(employee__full_name__icontains=search_query) |
            Q(employee__father_name__icontains=search_query) |
            Q(salary_month__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if employee_filter:
        salaries_list = salaries_list.filter(employee_id=employee_filter)

    if month_filter:
        salaries_list = salaries_list.filter(salary_month__icontains=month_filter)

    if date_from:
        salaries_list = salaries_list.filter(payment_date__gte=date_from)

    if date_to:
        salaries_list = salaries_list.filter(payment_date__lte=date_to)

    total_salaries_count = salaries_list.count()
    total_amount = salaries_list.aggregate(total=Sum('amount'))['total'] or 0

    today = timezone.now().date()
    current_month_str = today.strftime('%Y/%m')
    this_month_amount = salaries_list.filter(
        salary_month__icontains=current_month_str
    ).aggregate(total=Sum('amount'))['total'] or 0

    employees_paid_count = salaries_list.values('employee').distinct().count()

    page_number = request.GET.get('page', 1)
    paginator = Paginator(salaries_list, 10)

    try:
        salaries = paginator.page(page_number)
    except PageNotAnInteger:
        salaries = paginator.page(1)
    except EmptyPage:
        salaries = paginator.page(paginator.num_pages)

    employees = Employee.objects.all().order_by('full_name')

    context = {
        'salaries': salaries,
        'search_query': search_query,
        'employee_filter': employee_filter,
        'month_filter': month_filter,
        'date_from': date_from,
        'date_to': date_to,
        'employees': employees,
        'paginator': paginator,
        'total_salaries_count': total_salaries_count,
        'total_amount': total_amount,
        'this_month_amount': this_month_amount,
        'employees_paid_count': employees_paid_count,
        'page_title': 'لیست معاشات',
    }

    return render(request, 'salary/salary_list.html', context)


def create_salary(request):
    """ایجاد معاش جدید — با چک موجودی خزانه"""
    if request.method == 'POST':
        form = SalaryForm(request.POST)

        if form.is_valid():
            try:
                salary = form.save()
                messages.success(
                    request,
                    f'✅ معاش "{salary.amount} افغانی" برای "{salary.employee.full_name}" '
                    f'در ماه "{salary.salary_month}" موفقانه ثبت شد.'
                )
                return redirect('salary_list')

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
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = SalaryForm()

    today = timezone.now().date()
    today_salaries_count = Salary.objects.filter(
        payment_date=today
    ).count()

    context = {
        'form': form,
        'page_title': 'ثبت معاش جدید',
        'today_salaries_count': today_salaries_count,
    }

    return render(request, 'salary/create_salary.html', context)


def update_salary(request, salary_id):
    """ویرایش معاش — با چک موجودی خزانه"""
    salary = get_object_or_404(Salary, pk=salary_id)

    if request.method == 'POST':
        form = SalaryForm(request.POST, instance=salary)

        if form.is_valid():
            try:
                updated_salary = form.save()
                messages.success(
                    request,
                    f'✅ معاش "{updated_salary.employee.full_name}" موفقانه تصحیح شد.'
                )
                return redirect('salary_list')

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
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = SalaryForm(instance=salary)

    context = {
        'form': form,
        'salary': salary,
        'page_title': f'ویرایش معاش - {salary.employee.full_name}',
    }

    return render(request, 'salary/update_salary.html', context)


def delete_salary(request, salary_id):
    """حذف معاش"""
    salary = get_object_or_404(Salary, id=salary_id)

    if request.method == 'POST':
        employee_name = salary.employee.full_name
        amount = salary.amount
        try:
            salary.delete()
            messages.success(
                request,
                f'معاش "{amount} افغانی" از "{employee_name}" موفقانه حذف شد.'
            )
        except ProtectedError as e:
            details = _protected_summary(e)
            messages.error(
                request,
                f'نمی‌توان معاش "{amount} افغانی" از "{employee_name}" را حذف کرد. '
                f'این معاش وابسته به {details} است.'
            )
        return redirect('salary_list')

    return HttpResponse(status=405)