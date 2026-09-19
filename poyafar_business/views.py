# apps/dashboard/views.py

from django.shortcuts import render
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta


# ======================================================================
# Helper: safe import (اگر اپی نصب نبود، خطا ندهد)
# ======================================================================
def _safe_import(path):
    try:
        module_path, name = path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[name])
        return getattr(module, name)
    except Exception:
        return None


# ======================================================================
# Main Dashboard
# ======================================================================
def dashboard(request):
    """داشبورد عمومی — همه بخش‌ها"""

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # ================================================================
    # TREASURY
    # ================================================================
    Treasury = _safe_import('apps.treasury.models.Treasury')
    Transaction = _safe_import('apps.treasury.models.Transaction')

    treasury = None
    if Treasury:
        treasury = Treasury.get_treasury()

    txs = Transaction.objects.all() if Transaction else []
    today_txs = Transaction.objects.filter(date__date=today).count() if Transaction else 0
    month_in = (
        Transaction.objects.filter(transaction_type='IN', date__date__gte=month_ago)
        .aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ) if Transaction else Decimal('0')
    month_out = (
        Transaction.objects.filter(transaction_type='OUT', date__date__gte=month_ago)
        .aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ) if Transaction else Decimal('0')

    # ================================================================
    # PURCHASESALE
    # ================================================================
    Purchase = _safe_import('apps.purchasesale.models.Purchase')
    Sale = _safe_import('apps.purchasesale.models.Sale')
    CustomerReturn = _safe_import('apps.purchasesale.models.CustomerReturn')
    SupplierReturn = _safe_import('apps.purchasesale.models.SupplierReturn')
    Waste = _safe_import('apps.purchasesale.models.Waste')

    # Purchases
    if Purchase:
        total_purchases = Purchase.objects.count()
        purchases_today = Purchase.objects.filter(purchase_date__date=today).count()
        purchases_month_amount = (
            Purchase.objects.filter(purchase_date__date__gte=month_ago)
            .aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        purchases_total_amount = (
            Purchase.objects.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        purchases_total_paid = (
            Purchase.objects.aggregate(t=Sum('paid_amount'))['t'] or Decimal('0')
        )
        purchases_total_remaining = (
            Purchase.objects.aggregate(t=Sum('remaining_amount'))['t'] or Decimal('0')
        )
        recent_purchases = Purchase.objects.all().order_by('-purchase_date')[:5]
    else:
        total_purchases = purchases_today = 0
        purchases_month_amount = purchases_total_amount = Decimal('0')
        purchases_total_paid = purchases_total_remaining = Decimal('0')
        recent_purchases = []

    # Sales
    if Sale:
        total_sales = Sale.objects.count()
        sales_today = Sale.objects.filter(sale_date__date=today).count()
        sales_month_amount = (
            Sale.objects.filter(sale_date__date__gte=month_ago)
            .aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        sales_total_amount = (
            Sale.objects.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        sales_total_received = (
            Sale.objects.aggregate(t=Sum('received_amount'))['t'] or Decimal('0')
        )
        sales_total_remaining = (
            Sale.objects.aggregate(t=Sum('remaining_amount'))['t'] or Decimal('0')
        )
        recent_sales = Sale.objects.all().order_by('-sale_date')[:5]

        # Profit (30 days)
        sales_profit_month = Decimal('0')
        for s in Sale.objects.filter(sale_date__date__gte=month_ago):
            try:
                sales_profit_month += s.calculate_total_profit()
            except Exception:
                pass
    else:
        total_sales = sales_today = 0
        sales_month_amount = sales_total_amount = Decimal('0')
        sales_total_received = sales_total_remaining = Decimal('0')
        sales_profit_month = Decimal('0')
        recent_sales = []

    # Returns
    customer_returns_count = CustomerReturn.objects.count() if CustomerReturn else 0
    customer_returns_amount = (
        CustomerReturn.objects.aggregate(t=Sum('refund_amount'))['t'] or Decimal('0')
    ) if CustomerReturn else Decimal('0')

    supplier_returns_count = SupplierReturn.objects.count() if SupplierReturn else 0
    supplier_returns_amount = (
        SupplierReturn.objects.aggregate(t=Sum('received_amount'))['t'] or Decimal('0')
    ) if SupplierReturn else Decimal('0')

    # Waste
    wastes_count = Waste.objects.count() if Waste else 0
    wastes_today = Waste.objects.filter(waste_date__date=today).count() if Waste else 0

    # ================================================================
    # DEBTS
    # ================================================================
    PurchaseDebt = _safe_import('apps.debts.models.PurchaseDebt')
    SaleDebt = _safe_import('apps.debts.models.SaleDebt')

    purchase_debts_total = (
        PurchaseDebt.objects.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ) if PurchaseDebt else Decimal('0')
    purchase_debts_count = PurchaseDebt.objects.count() if PurchaseDebt else 0

    sale_debts_total = (
        SaleDebt.objects.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    ) if SaleDebt else Decimal('0')
    sale_debts_count = SaleDebt.objects.count() if SaleDebt else 0

    # ================================================================
    # EXPENSES
    # ================================================================
    Expense = _safe_import('apps.expense.models.Expense')

    if Expense:
        total_expenses = Expense.objects.count()
        expenses_today = Expense.objects.filter(expense_date__date=today).count()
        expenses_month_amount = (
            Expense.objects.filter(expense_date__date__gte=month_ago)
            .aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        expenses_total_amount = (
            Expense.objects.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
        )
        recent_expenses = Expense.objects.all().order_by('-expense_date')[:5]
    else:
        total_expenses = expenses_today = 0
        expenses_month_amount = expenses_total_amount = Decimal('0')
        recent_expenses = []

    # ================================================================
    # EMPLOYEES / SALARIES
    # ================================================================
    Employee = _safe_import('apps.employee.models.Employee')
    Salary = _safe_import('apps.employee.models.Salary')

    total_employees = Employee.objects.count() if Employee else 0
    active_employees = (
        Employee.objects.filter(leave_date__isnull=True).count()
    ) if Employee else 0

    if Salary:
        salaries_count = Salary.objects.count()
        salaries_month_amount = (
            Salary.objects.filter(payment_date__gte=month_ago)
            .aggregate(t=Sum('amount'))['t'] or Decimal('0')
        )
        salaries_total_amount = (
            Salary.objects.aggregate(t=Sum('amount'))['t'] or Decimal('0')
        )
        recent_salaries = Salary.objects.all().order_by('-payment_date')[:5]
    else:
        salaries_count = 0
        salaries_month_amount = salaries_total_amount = Decimal('0')
        recent_salaries = []

    # ================================================================
    # PRODUCT / STOCK
    # ================================================================
    Product = _safe_import('apps.product.models.Product')
    Category = _safe_import('apps.product.models.Category')
    Location = _safe_import('apps.stock.models.Location')

    total_products = Product.objects.count() if Product else 0
    total_categories = Category.objects.count() if Category else 0
    total_locations = Location.objects.count() if Location else 0

    if Product:
        low_stock_products = Product.objects.filter(
            current_stock__lte=models_F('min_stock')  # see fallback below
        ).count() if False else None
        # Use safe queryset
        try:
            from django.db.models import F
            low_stock_products = Product.objects.filter(
                current_stock__lte=F('min_stock')
            ).count()
            out_of_stock = Product.objects.filter(current_stock__lte=0).count()
            total_stock_value = (
                Product.objects.aggregate(
                    t=Sum('current_stock')
                )['t'] or 0
            )
        except Exception:
            low_stock_products = 0
            out_of_stock = 0
            total_stock_value = 0
    else:
        low_stock_products = out_of_stock = 0
        total_stock_value = 0

    # ================================================================
    # Chart: فروش و خرید ۷ روز اخیر
    # ================================================================
    chart_labels = []
    chart_purchases = []
    chart_sales = []
    chart_expenses = []

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime('%m/%d'))

        p = (
            Purchase.objects.filter(purchase_date__date=day)
            .aggregate(t=Sum('total_amount'))['t'] or 0
        ) if Purchase else 0
        s = (
            Sale.objects.filter(sale_date__date=day)
            .aggregate(t=Sum('total_amount'))['t'] or 0
        ) if Sale else 0
        e = (
            Expense.objects.filter(expense_date__date=day)
            .aggregate(t=Sum('total_amount'))['t'] or 0
        ) if Expense else 0

        chart_purchases.append(float(p))
        chart_sales.append(float(s))
        chart_expenses.append(float(e))

    context = {
        'today': today,

        # Treasury
        'treasury': treasury,
        'today_txs': today_txs,
        'month_in': month_in,
        'month_out': month_out,

        # Purchases
        'total_purchases': total_purchases,
        'purchases_today': purchases_today,
        'purchases_month_amount': purchases_month_amount,
        'purchases_total_amount': purchases_total_amount,
        'purchases_total_paid': purchases_total_paid,
        'purchases_total_remaining': purchases_total_remaining,

        # Sales
        'total_sales': total_sales,
        'sales_today': sales_today,
        'sales_month_amount': sales_month_amount,
        'sales_total_amount': sales_total_amount,
        'sales_total_received': sales_total_received,
        'sales_total_remaining': sales_total_remaining,
        'sales_profit_month': sales_profit_month,

        # Returns
        'customer_returns_count': customer_returns_count,
        'customer_returns_amount': customer_returns_amount,
        'supplier_returns_count': supplier_returns_count,
        'supplier_returns_amount': supplier_returns_amount,

        # Waste
        'wastes_count': wastes_count,
        'wastes_today': wastes_today,

        # Debts
        'purchase_debts_total': purchase_debts_total,
        'purchase_debts_count': purchase_debts_count,
        'sale_debts_total': sale_debts_total,
        'sale_debts_count': sale_debts_count,

        # Expenses
        'total_expenses': total_expenses,
        'expenses_today': expenses_today,
        'expenses_month_amount': expenses_month_amount,
        'expenses_total_amount': expenses_total_amount,

        # Employees / Salaries
        'total_employees': total_employees,
        'active_employees': active_employees,
        'salaries_count': salaries_count,
        'salaries_month_amount': salaries_month_amount,
        'salaries_total_amount': salaries_total_amount,

        # Product / Stock
        'total_products': total_products,
        'total_categories': total_categories,
        'total_locations': total_locations,
        'low_stock_products': low_stock_products,
        'out_of_stock': out_of_stock,
        'total_stock_value': total_stock_value,

        # Recent
        'recent_sales': recent_sales,
        'recent_purchases': recent_purchases,
        'recent_expenses': recent_expenses,
        'recent_salaries': recent_salaries,

        # Chart
        'chart_labels': chart_labels,
        'chart_purchases': chart_purchases,
        'chart_sales': chart_sales,
        'chart_expenses': chart_expenses,

        'page_title': 'داشبورد عمومی',
    }

    return render(request, 'dashboard.html', context)