# apps/reports/views.py

from django.shortcuts import render
from django.db.models import Sum, Count, Q, F, Avg, Max, Min
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta, datetime
from calendar import monthrange




# ======================================================================
# Helper: safe import
# ======================================================================
def _safe_import(path):
    try:
        module_path, name = path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[name])
        return getattr(module, name)
    except Exception:
        return None


# ======================================================================
# Helper: بارگذاری همه مدل‌ها
# ======================================================================
def _load_models():
    return {
        'Treasury':         _safe_import('apps.treasury.models.Treasury'),
        'Transaction':      _safe_import('apps.treasury.models.Transaction'),
        'Purchase':         _safe_import('apps.purchasesale.models.Purchase'),
        'Sale':             _safe_import('apps.purchasesale.models.Sale'),
        'CustomerReturn':   _safe_import('apps.purchasesale.models.CustomerReturn'),
        'SupplierReturn':   _safe_import('apps.purchasesale.models.SupplierReturn'),
        'Waste':            _safe_import('apps.purchasesale.models.Waste'),
        'PurchaseDebt':     _safe_import('apps.debts.models.PurchaseDebt'),
        'SaleDebt':         _safe_import('apps.debts.models.SaleDebt'),
        'Expense':          _safe_import('apps.expense.models.Expense'),
        'Employee':         _safe_import('apps.employee.models.Employee'),
        'Salary':           _safe_import('apps.employee.models.Salary'),
        'Product':          _safe_import('apps.product.models.Product'),
        'Category':         _safe_import('apps.product.models.Category'),
        'Location':         _safe_import('apps.stock.models.Location'),
    }


# ======================================================================
# Helper: parse period از GET
# ======================================================================
def _get_period(request):
    """
    دوره را از query string می‌گیرد.
    مقادیر مجاز: today | yesterday | 7 | 30 | 90 | this_week | last_week |
                 this_month | last_month | this_year | last_year | custom
    """
    period = request.GET.get('period', '30')
    today = timezone.now().date()

    # ---- حالت‌های خاص ----
    if period == 'today':
        return {'key': period, 'label': 'امروز', 'start': today, 'end': today, 'days': 1}

    if period == 'yesterday':
        y = today - timedelta(days=1)
        return {'key': period, 'label': 'دیروز', 'start': y, 'end': y, 'days': 1}

    if period == 'this_week':
        # هفته افغانی: شنبه تا جمعه (weekday: Sat=5 in Python)
        # در پایتون: Monday=0 ... Saturday=5, Sunday=6
        # ما از شنبه شروع می‌کنیم
        days_since_sat = (today.weekday() + 2) % 7  # Sat→0, Sun→1, ..., Fri→6
        start = today - timedelta(days=days_since_sat)
        return {'key': period, 'label': 'هفته جاری', 'start': start, 'end': today,
                'days': (today - start).days + 1}

    if period == 'last_week':
        days_since_sat = (today.weekday() + 2) % 7
        this_week_start = today - timedelta(days=days_since_sat)
        start = this_week_start - timedelta(days=7)
        end = this_week_start - timedelta(days=1)
        return {'key': period, 'label': 'هفته گذشته', 'start': start, 'end': end, 'days': 7}

    if period == 'this_month':
        start = today.replace(day=1)
        return {'key': period, 'label': 'ماه جاری', 'start': start, 'end': today,
                'days': (today - start).days + 1}

    if period == 'last_month':
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        return {'key': period, 'label': 'ماه گذشته', 'start': start, 'end': end,
                'days': (end - start).days + 1}

    if period == 'this_year':
        start = today.replace(month=1, day=1)
        return {'key': period, 'label': 'سال جاری', 'start': start, 'end': today,
                'days': (today - start).days + 1}

    if period == 'last_year':
        start = today.replace(year=today.year - 1, month=1, day=1)
        end = today.replace(year=today.year - 1, month=12, day=31)
        return {'key': period, 'label': 'سال گذشته', 'start': start, 'end': end, 'days': 365}

    if period == 'custom':
        try:
            s = datetime.strptime(request.GET.get('start', ''), '%Y-%m-%d').date()
            e = datetime.strptime(request.GET.get('end', ''), '%Y-%m-%d').date()
            return {'key': 'custom', 'label': f'{s} تا {e}', 'start': s, 'end': e,
                    'days': (e - s).days + 1}
        except Exception:
            period = '30'

    # ---- حالت‌های عددی ----
    period_map = {
        '7':   (7,   '۷ روز اخیر'),
        '30':  (30,  '۳۰ روز اخیر'),
        '90':  (90,  '۹۰ روز اخیر'),
        '180': (180, '۶ ماه اخیر'),
        '365': (365, '۱ سال اخیر'),
    }
    days, label = period_map.get(period, (30, '۳۰ روز اخیر'))
    start = today - timedelta(days=days - 1)
    return {'key': period, 'label': label, 'start': start, 'end': today, 'days': days}


# ======================================================================
# Helper: محاسبه جمع فروش در بازه
# ======================================================================
def _sale_stats(Sale, start, end):
    if not Sale:
        return {'total': Decimal('0'), 'received': Decimal('0'),
                'remaining': Decimal('0'), 'count': 0, 'profit': Decimal('0'),
                'avg': Decimal('0')}
    qs = Sale.objects.filter(sale_date__date__gte=start, sale_date__date__lte=end)
    total = qs.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
    received = qs.aggregate(t=Sum('received_amount'))['t'] or Decimal('0')
    remaining = qs.aggregate(t=Sum('remaining_amount'))['t'] or Decimal('0')
    count = qs.count()

    profit = Decimal('0')
    for s in qs:
        try:
            profit += s.calculate_total_profit()
        except Exception:
            pass

    avg = (total / count) if count > 0 else Decimal('0')
    return {'total': total, 'received': received, 'remaining': remaining,
            'count': count, 'profit': profit, 'avg': avg}


# ======================================================================
# Helper: محاسبه جمع خرید در بازه
# ======================================================================
def _purchase_stats(Purchase, start, end):
    if not Purchase:
        return {'total': Decimal('0'), 'paid': Decimal('0'),
                'remaining': Decimal('0'), 'count': 0, 'avg': Decimal('0')}
    qs = Purchase.objects.filter(purchase_date__date__gte=start, purchase_date__date__lte=end)
    total = qs.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
    paid = qs.aggregate(t=Sum('paid_amount'))['t'] or Decimal('0')
    remaining = qs.aggregate(t=Sum('remaining_amount'))['t'] or Decimal('0')
    count = qs.count()
    avg = (total / count) if count > 0 else Decimal('0')
    return {'total': total, 'paid': paid, 'remaining': remaining,
            'count': count, 'avg': avg}


# ======================================================================
# Helper: محاسبه مصارف در بازه
# ======================================================================
def _expense_stats(Expense, start, end):
    if not Expense:
        return {'total': Decimal('0'), 'count': 0, 'avg': Decimal('0')}
    qs = Expense.objects.filter(expense_date__date__gte=start, expense_date__date__lte=end)
    total = qs.aggregate(t=Sum('total_amount'))['t'] or Decimal('0')
    count = qs.count()
    avg = (total / count) if count > 0 else Decimal('0')
    return {'total': total, 'count': count, 'avg': avg}


# ======================================================================
# Helper: محاسبه معاشات در بازه
# ======================================================================
def _salary_stats(Salary, start, end):
    if not Salary:
        return {'total': Decimal('0'), 'count': 0, 'avg': Decimal('0')}
    qs = Salary.objects.filter(payment_date__gte=start, payment_date__lte=end)
    total = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    count = qs.count()
    avg = (total / count) if count > 0 else Decimal('0')
    return {'total': total, 'count': count, 'avg': avg}


# ======================================================================
# Helper: ساخت روند روزانه
# ======================================================================
def _daily_trend(m, start, end, max_days=92):
    """روند روزانه فروش/خرید/مصارف — برای بازه‌های کوچک"""
    labels, sales, purchases, expenses, profits = [], [], [], [], []
    total_days = (end - start).days + 1

    if total_days > max_days:
        return labels, sales, purchases, expenses, profits

    for i in range(total_days):
        day = start + timedelta(days=i)
        labels.append(day.strftime('%m/%d'))

        s = (m['Sale'].objects.filter(sale_date__date=day)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Sale'] else 0
        p = (m['Purchase'].objects.filter(purchase_date__date=day)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Purchase'] else 0
        e = (m['Expense'].objects.filter(expense_date__date=day)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Expense'] else 0

        # سود روز
        profit = Decimal('0')
        if m['Sale']:
            for sale in m['Sale'].objects.filter(sale_date__date=day):
                try:
                    profit += sale.calculate_total_profit()
                except Exception:
                    pass

        sales.append(float(s))
        purchases.append(float(p))
        expenses.append(float(e))
        profits.append(float(profit))

    return labels, sales, purchases, expenses, profits


# ======================================================================
# Helper: روند هفتگی (هفته‌های بازه)
# ======================================================================
def _weekly_trend(m, start, end):
    """روند هفتگی — شنبه تا جمعه"""
    labels, sales, purchases, expenses = [], [], [], []

    # پیدا کردن شنبه اول
    days_since_sat = (start.weekday() + 2) % 7
    week_start = start - timedelta(days=days_since_sat)

    while week_start <= end:
        week_end = week_start + timedelta(days=6)
        actual_start = max(week_start, start)
        actual_end = min(week_end, end)

        labels.append(f"{actual_start.strftime('%m/%d')}")

        s = (m['Sale'].objects
             .filter(sale_date__date__gte=actual_start, sale_date__date__lte=actual_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Sale'] else 0
        p = (m['Purchase'].objects
             .filter(purchase_date__date__gte=actual_start, purchase_date__date__lte=actual_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Purchase'] else 0
        e = (m['Expense'].objects
             .filter(expense_date__date__gte=actual_start, expense_date__date__lte=actual_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Expense'] else 0

        sales.append(float(s))
        purchases.append(float(p))
        expenses.append(float(e))

        week_start += timedelta(days=7)

    return labels, sales, purchases, expenses


# ======================================================================
# Helper: روند ماهانه
# ======================================================================
def _monthly_trend(m, months=12):
    """روند ۱۲ ماه اخیر"""
    labels, sales, purchases, expenses, profits = [], [], [], [], []
    today = timezone.now().date()

    for i in range(months - 1, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1

        labels.append(f"{year}/{month:02d}")

        m_start = timezone.datetime(year, month, 1).date()
        if month == 12:
            m_end = timezone.datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            m_end = timezone.datetime(year, month + 1, 1).date() - timedelta(days=1)

        s = (m['Sale'].objects
             .filter(sale_date__date__gte=m_start, sale_date__date__lte=m_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Sale'] else 0
        p = (m['Purchase'].objects
             .filter(purchase_date__date__gte=m_start, purchase_date__date__lte=m_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Purchase'] else 0
        e = (m['Expense'].objects
             .filter(expense_date__date__gte=m_start, expense_date__date__lte=m_end)
             .aggregate(t=Sum('total_amount'))['t'] or 0) if m['Expense'] else 0

        # سود ماه
        profit = Decimal('0')
        if m['Sale']:
            for sale in m['Sale'].objects.filter(
                sale_date__date__gte=m_start, sale_date__date__lte=m_end
            ):
                try:
                    profit += sale.calculate_total_profit()
                except Exception:
                    pass

        sales.append(float(s))
        purchases.append(float(p))
        expenses.append(float(e))
        profits.append(float(profit))

    return labels, sales, purchases, expenses, profits


# ======================================================================
# Helper: Top Products
# ======================================================================
def _top_products(m, start, end, limit=10):
    """پرفروش‌ترین کالاها — از JSONField items در Sale"""
    if not m['Sale']:
        return []

    product_stats = {}  # {product_id: {'name', 'qty', 'amount'}}

    sales = m['Sale'].objects.filter(
        sale_date__date__gte=start, sale_date__date__lte=end
    )
    for sale in sales:
        for item in (sale.items or []):
            pid = item.get('product_id')
            if not pid:
                continue
            name = item.get('product_name') or f'محصول {pid}'
            qty = int(item.get('quantity', 0) or 0)
            price = Decimal(str(item.get('sale_price', 0) or 0))
            currency = item.get('currency', 'AFN')
            dollar_rate = sale.dollar_rate or Decimal('0')

            if currency == 'USD' and dollar_rate > 0:
                amount = Decimal(str(qty)) * price * dollar_rate
            else:
                amount = Decimal(str(qty)) * price

            if pid not in product_stats:
                product_stats[pid] = {'name': name, 'qty': 0, 'amount': Decimal('0')}
            product_stats[pid]['qty'] += qty
            product_stats[pid]['amount'] += amount

    sorted_items = sorted(product_stats.values(), key=lambda x: x['amount'], reverse=True)
    return sorted_items[:limit]


# ======================================================================
# Helper: Top Customers
# ======================================================================
def _top_customers(m, start, end, limit=10):
    if not m['Sale']:
        return []
    try:
        return list(
            m['Sale'].objects
            .filter(sale_date__date__gte=start, sale_date__date__lte=end)
            .exclude(customer_name__isnull=True).exclude(customer_name__exact='')
            .values('customer_name')
            .annotate(total_amount=Sum('total_amount'), total_count=Count('id'))
            .order_by('-total_amount')[:limit]
        )
    except Exception:
        return []


# ======================================================================
# Helper: Top Suppliers
# ======================================================================
def _top_suppliers(m, start, end, limit=10):
    if not m['Purchase']:
        return []
    try:
        return list(
            m['Purchase'].objects
            .filter(purchase_date__date__gte=start, purchase_date__date__lte=end)
            .exclude(supplier_name__isnull=True).exclude(supplier_name__exact='')
            .values('supplier_name')
            .annotate(total_amount=Sum('total_amount'), total_count=Count('id'))
            .order_by('-total_amount')[:limit]
        )
    except Exception:
        return []


# ======================================================================
# Helper: Expense Breakdown (بر اساس title)
# ======================================================================
def _expense_breakdown(m, start, end, limit=10):
    if not m['Expense']:
        return []
    try:
        return list(
            m['Expense'].objects
            .filter(expense_date__date__gte=start, expense_date__date__lte=end)
            .values('title')
            .annotate(total=Sum('total_amount'), count=Count('id'))
            .order_by('-total')[:limit]
        )
    except Exception:
        return []


# ======================================================================
# Helper: Debt Aging
# ======================================================================
def _debt_aging(m):
    aging = {'current': Decimal('0'), 'medium': Decimal('0'),
             'old': Decimal('0'), 'critical': Decimal('0')}
    today = timezone.now().date()

    if not m['PurchaseDebt']:
        return aging

    try:
        d30 = today - timedelta(days=30)
        d60 = today - timedelta(days=60)
        d90 = today - timedelta(days=90)

        aging['current'] = (m['PurchaseDebt'].objects
                            .filter(created_at__date__gte=d30)
                            .aggregate(t=Sum('amount'))['t'] or Decimal('0'))
        aging['medium'] = (m['PurchaseDebt'].objects
                           .filter(created_at__date__gte=d60, created_at__date__lt=d30)
                           .aggregate(t=Sum('amount'))['t'] or Decimal('0'))
        aging['old'] = (m['PurchaseDebt'].objects
                        .filter(created_at__date__gte=d90, created_at__date__lt=d60)
                        .aggregate(t=Sum('amount'))['t'] or Decimal('0'))
        aging['critical'] = (m['PurchaseDebt'].objects
                             .filter(created_at__date__lt=d90)
                             .aggregate(t=Sum('amount'))['t'] or Decimal('0'))
    except Exception:
        pass

    return aging


# ======================================================================
# Helper: آمار خزانه در بازه
# ======================================================================
def _treasury_stats(m, start, end):
    result = {
        'balance_afg': Decimal('0'),
        'balance_usd': Decimal('0'),
        'in_total': Decimal('0'),
        'out_total': Decimal('0'),
        'in_count': 0,
        'out_count': 0,
        'net': Decimal('0'),
    }

    if m['Treasury']:
        try:
            treasury = m['Treasury'].get_treasury()
            result['balance_afg'] = treasury.balance_afg
            result['balance_usd'] = treasury.balance_usd
        except Exception:
            pass

    if m['Transaction']:
        qs = m['Transaction'].objects.filter(
            date__date__gte=start, date__date__lte=end, currency='AFG'
        )
        result['in_total'] = qs.filter(transaction_type='IN').aggregate(
            t=Sum('amount'))['t'] or Decimal('0')
        result['out_total'] = qs.filter(transaction_type='OUT').aggregate(
            t=Sum('amount'))['t'] or Decimal('0')
        result['in_count'] = qs.filter(transaction_type='IN').count()
        result['out_count'] = qs.filter(transaction_type='OUT').count()
        result['net'] = result['in_total'] - result['out_total']

    return result


# ======================================================================
# Helper: Returns & Waste در بازه
# ======================================================================
def _returns_stats(m, start, end):
    result = {
        'customer_returns_total': Decimal('0'),
        'customer_returns_count': 0,
        'supplier_returns_total': Decimal('0'),
        'supplier_returns_count': 0,
        'wastes_count': 0,
        'wastes_items_count': 0,
    }

    if m['CustomerReturn']:
        qs = m['CustomerReturn'].objects.filter(
            return_date__date__gte=start, return_date__date__lte=end
        )
        result['customer_returns_total'] = qs.aggregate(
            t=Sum('refund_amount'))['t'] or Decimal('0')
        result['customer_returns_count'] = qs.count()

    if m['SupplierReturn']:
        qs = m['SupplierReturn'].objects.filter(
            return_date__date__gte=start, return_date__date__lte=end
        )
        result['supplier_returns_total'] = qs.aggregate(
            t=Sum('received_amount'))['t'] or Decimal('0')
        result['supplier_returns_count'] = qs.count()

    if m['Waste']:
        qs = m['Waste'].objects.filter(
            waste_date__date__gte=start, waste_date__date__lte=end
        )
        result['wastes_count'] = qs.count()
        for w in qs:
            result['wastes_items_count'] += len(w.items or [])

    return result


# ======================================================================
# Helper: آمار کارمندان
# ======================================================================
def _employee_stats(m, start, end):
    result = {
        'total': 0, 'active': 0, 'terminated': 0,
        'salaries_total': Decimal('0'), 'salaries_count': 0,
        'avg_salary': Decimal('0'),
        'top_earners': [],
    }

    if m['Employee']:
        try:
            result['total'] = m['Employee'].objects.count()
            result['active'] = m['Employee'].objects.filter(leave_date__isnull=True).count()
            result['terminated'] = m['Employee'].objects.filter(
                leave_date__isnull=False).count()
        except Exception:
            pass

    if m['Salary']:
        try:
            qs = m['Salary'].objects.filter(payment_date__gte=start, payment_date__lte=end)
            result['salaries_total'] = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
            result['salaries_count'] = qs.count()
            if result['salaries_count'] > 0:
                result['avg_salary'] = result['salaries_total'] / result['salaries_count']

            result['top_earners'] = list(
                qs.values('employee__full_name', 'employee__position')
                .annotate(total=Sum('amount'), count=Count('id'))
                .order_by('-total')[:8]
            )
        except Exception:
            pass

    return result


# ======================================================================
# Helper: آمار انبار و کالاها
# ======================================================================
def _stock_stats(m):
    result = {
        'products_total': 0,
        'low_stock': 0,
        'out_of_stock': 0,
        'total_shop_stock': 0,
        'total_warehouse_stock': 0,
        'total_stock_value': Decimal('0'),
        'categories_total': 0,
        'locations_total': 0,
        'top_value_products': [],
    }

    if m['Product']:
        try:
            products = m['Product'].objects.filter(is_deleted=False)
            result['products_total'] = products.count()
            result['low_stock'] = products.filter(
                current_stock__lte=F('min_stock'), current_stock__gt=0
            ).count()
            result['out_of_stock'] = products.filter(current_stock__lte=0).count()
            result['total_shop_stock'] = products.aggregate(
                t=Sum('shop_stock'))['t'] or 0
            result['total_warehouse_stock'] = products.aggregate(
                t=Sum('stock_stock'))['t'] or 0

            # ارزش موجودی
            total_value = Decimal('0')
            for p in products:
                try:
                    total_value += Decimal(str(p.current_stock)) * p.purchase_price
                except Exception:
                    pass
            result['total_stock_value'] = total_value

            # باارزش‌ترین کالاها (بر اساس ارزش موجودی)
            value_list = []
            for p in products:
                try:
                    val = Decimal(str(p.current_stock)) * p.purchase_price
                    value_list.append({
                        'name': p.name,
                        'sku': p.sku,
                        'stock': p.current_stock,
                        'unit_price': p.purchase_price,
                        'value': val,
                    })
                except Exception:
                    pass
            value_list.sort(key=lambda x: x['value'], reverse=True)
            result['top_value_products'] = value_list[:10]
        except Exception:
            pass

    if m['Category']:
        try:
            result['categories_total'] = m['Category'].objects.count()
        except Exception:
            pass

    if m['Location']:
        try:
            result['locations_total'] = m['Location'].objects.count()
        except Exception:
            pass

    return result


# ======================================================================
# Helper: مقایسه با دوره قبل
# ======================================================================
def _compare_with_previous(m, period):
    """مقایسه KPI اصلی با دوره قبل مشابه"""
    start, end = period['start'], period['end']
    days = period['days']

    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    cur_sales = _sale_stats(m['Sale'], start, end)
    prev_sales = _sale_stats(m['Sale'], prev_start, prev_end)

    cur_purchases = _purchase_stats(m['Purchase'], start, end)
    prev_purchases = _purchase_stats(m['Purchase'], prev_start, prev_end)

    cur_expenses = _expense_stats(m['Expense'], start, end)
    prev_expenses = _expense_stats(m['Expense'], prev_start, prev_end)

    def _change(cur, prev):
        if prev == 0:
            return 100 if cur > 0 else 0
        return ((cur - prev) / prev) * 100

    return {
        'prev_start': prev_start,
        'prev_end': prev_end,
        'sales_change': _change(cur_sales['total'], prev_sales['total']),
        'sales_prev': prev_sales['total'],
        'purchases_change': _change(cur_purchases['total'], prev_purchases['total']),
        'purchases_prev': prev_purchases['total'],
        'expenses_change': _change(cur_expenses['total'], prev_expenses['total']),
        'expenses_prev': prev_expenses['total'],
        'profit_change': _change(cur_sales['profit'], prev_sales['profit']),
        'profit_prev': prev_sales['profit'],
    }


# ======================================================================
# VIEW اصلی — راپور جامع
# ======================================================================
def report_overview(request):
    """راپور جامع — روزانه/هفتگی/ماهانه/سالانه"""

    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    # ----------------------------------------------------------------
    # KPI اصلی
    # ----------------------------------------------------------------
    sales = _sale_stats(m['Sale'], start, end)
    purchases = _purchase_stats(m['Purchase'], start, end)
    expenses = _expense_stats(m['Expense'], start, end)
    salaries = _salary_stats(m['Salary'], start, end)
    treasury = _treasury_stats(m, start, end)
    returns = _returns_stats(m, start, end)
    employees = _employee_stats(m, start, end)
    stock = _stock_stats(m)

    # خالص دوره
    net_total = sales['total'] - purchases['total'] - expenses['total'] - salaries['total']
    margin = (sales['profit'] / sales['total'] * 100) if sales['total'] > 0 else Decimal('0')

    # ----------------------------------------------------------------
    # Charts
    # ----------------------------------------------------------------
    daily_labels, daily_sales, daily_purchases, daily_expenses, daily_profits = \
        _daily_trend(m, start, end)

    weekly_labels, weekly_sales, weekly_purchases, weekly_expenses = \
        _weekly_trend(m, start, end)

    monthly_labels, monthly_sales, monthly_purchases, monthly_expenses, monthly_profits = \
        _monthly_trend(m, months=12)

    # ----------------------------------------------------------------
    # Tables
    # ----------------------------------------------------------------
    top_products = _top_products(m, start, end, limit=10)
    top_customers = _top_customers(m, start, end, limit=10)
    top_suppliers = _top_suppliers(m, start, end, limit=10)
    expense_breakdown = _expense_breakdown(m, start, end, limit=10)

    # ----------------------------------------------------------------
    # Debt Aging
    # ----------------------------------------------------------------
    debt_aging = _debt_aging(m)

    # ----------------------------------------------------------------
    # مقایسه با دوره قبل
    # ----------------------------------------------------------------
    comparison = _compare_with_previous(m, period)

    # ----------------------------------------------------------------
    # Context
    # ----------------------------------------------------------------
    context = {
        'page_title': f'راپور جامع — {period["label"]}',
        'period': period,

        # KPI Sales
        'sales_total': sales['total'],
        'sales_count': sales['count'],
        'sales_received': sales['received'],
        'sales_remaining': sales['remaining'],
        'sales_profit': sales['profit'],
        'sales_avg': sales['avg'],

        # KPI Purchases
        'purchases_total': purchases['total'],
        'purchases_count': purchases['count'],
        'purchases_paid': purchases['paid'],
        'purchases_remaining': purchases['remaining'],
        'purchases_avg': purchases['avg'],

        # KPI Expenses
        'expenses_total': expenses['total'],
        'expenses_count': expenses['count'],
        'expenses_avg': expenses['avg'],

        # KPI Salaries
        'salaries_total': salaries['total'],
        'salaries_count': salaries['count'],
        'salaries_avg': salaries['avg'],

        # KPI Net
        'net_total': net_total,
        'margin': margin,

        # Treasury
        'treasury': treasury,

        # Returns & Waste
        'returns': returns,

        # Employees
        'employees': employees,

        # Stock
        'stock': stock,

        # Charts
        'daily_labels': daily_labels,
        'daily_sales': daily_sales,
        'daily_purchases': daily_purchases,
        'daily_expenses': daily_expenses,
        'daily_profits': daily_profits,

        'weekly_labels': weekly_labels,
        'weekly_sales': weekly_sales,
        'weekly_purchases': weekly_purchases,
        'weekly_expenses': weekly_expenses,

        'monthly_labels': monthly_labels,
        'monthly_sales': monthly_sales,
        'monthly_purchases': monthly_purchases,
        'monthly_expenses': monthly_expenses,
        'monthly_profits': monthly_profits,

        # Tables
        'top_products': top_products,
        'top_customers': top_customers,
        'top_suppliers': top_suppliers,
        'expense_breakdown': expense_breakdown,

        # Debt Aging
        'debt_aging': debt_aging,

        # Comparison
        'comparison': comparison,
    }

    return render(request, 'reports/overview.html', context)


# ======================================================================
# VIEW — راپور فروش تفصیلی
# ======================================================================
def report_sales(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    sales_qs = []
    if m['Sale']:
        sales_qs = (m['Sale'].objects
                    .filter(sale_date__date__gte=start, sale_date__date__lte=end)
                    .order_by('-sale_date'))

    stats = _sale_stats(m['Sale'], start, end)
    top_customers = _top_customers(m, start, end, limit=15)
    top_products = _top_products(m, start, end, limit=15)

    # روند روزانه
    daily_labels, daily_sales, _, _, daily_profits = _daily_trend(m, start, end)

    context = {
        'page_title': f'راپور فروش — {period["label"]}',
        'period': period,
        'sales': sales_qs,
        'stats': stats,
        'top_customers': top_customers,
        'top_products': top_products,
        'daily_labels': daily_labels,
        'daily_sales': daily_sales,
        'daily_profits': daily_profits,
    }
    return render(request, 'reports/sales.html', context)


# ======================================================================
# VIEW — راپور خرید تفصیلی
# ======================================================================
def report_purchases(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    purchases_qs = []
    if m['Purchase']:
        purchases_qs = (m['Purchase'].objects
                        .filter(purchase_date__date__gte=start, purchase_date__date__lte=end)
                        .order_by('-purchase_date'))

    stats = _purchase_stats(m['Purchase'], start, end)
    top_suppliers = _top_suppliers(m, start, end, limit=15)

    daily_labels, _, daily_purchases, _, _ = _daily_trend(m, start, end)

    context = {
        'page_title': f'راپور خرید — {period["label"]}',
        'period': period,
        'purchases': purchases_qs,
        'stats': stats,
        'top_suppliers': top_suppliers,
        'daily_labels': daily_labels,
        'daily_purchases': daily_purchases,
    }
    return render(request, 'reports/purchases.html', context)


# ======================================================================
# VIEW — راپور مصارف تفصیلی
# ======================================================================
def report_expenses(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    expenses_qs = []
    if m['Expense']:
        expenses_qs = (m['Expense'].objects
                       .filter(expense_date__date__gte=start, expense_date__date__lte=end)
                       .order_by('-expense_date'))

    stats = _expense_stats(m['Expense'], start, end)
    breakdown = _expense_breakdown(m, start, end, limit=20)

    daily_labels, _, _, daily_expenses, _ = _daily_trend(m, start, end)

    context = {
        'page_title': f'راپور مصارف — {period["label"]}',
        'period': period,
        'expenses': expenses_qs,
        'stats': stats,
        'breakdown': breakdown,
        'daily_labels': daily_labels,
        'daily_expenses': daily_expenses,
    }
    return render(request, 'reports/expenses.html', context)


# ======================================================================
# VIEW — راپور معاشات
# ======================================================================
def report_salaries(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    salaries_qs = []
    if m['Salary']:
        salaries_qs = (m['Salary'].objects
                       .filter(payment_date__gte=start, payment_date__lte=end)
                       .select_related('employee')
                       .order_by('-payment_date'))

    stats = _salary_stats(m['Salary'], start, end)
    employees = _employee_stats(m, start, end)

    context = {
        'page_title': f'راپور معاشات — {period["label"]}',
        'period': period,
        'salaries': salaries_qs,
        'stats': stats,
        'employees': employees,
    }
    return render(request, 'reports/salaries.html', context)


# ======================================================================
# VIEW — راپور انبار
# ======================================================================
def report_stock(request):
    period = _get_period(request)
    m = _load_models()

    stock = _stock_stats(m)

    # کالاهای کم‌موجود
    low_stock_products = []
    out_of_stock_products = []
    all_products = []

    if m['Product']:
        try:
            products = m['Product'].objects.filter(is_deleted=False).select_related('category')
            all_products = products.order_by('name')
            low_stock_products = products.filter(
                current_stock__lte=F('min_stock'), current_stock__gt=0
            ).order_by('current_stock')
            out_of_stock_products = products.filter(
                current_stock__lte=0
            ).order_by('name')
        except Exception:
            pass

    context = {
        'page_title': 'راپور انبار',
        'period': period,
        'stock': stock,
        'all_products': all_products,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
    }
    return render(request, 'reports/stock.html', context)


# ======================================================================
# VIEW — راپور خزانه
# ======================================================================
def report_treasury(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    stats = _treasury_stats(m, start, end)

    transactions = []
    if m['Transaction']:
        transactions = (m['Transaction'].objects
                        .filter(date__date__gte=start, date__date__lte=end)
                        .order_by('-date')[:200])

    # تفکیک بر اساس money_type
    breakdown_by_type = []
    if m['Transaction']:
        try:
            breakdown_by_type = list(
                m['Transaction'].objects
                .filter(date__date__gte=start, date__date__lte=end, currency='AFG')
                .values('money_type', 'transaction_type')
                .annotate(total=Sum('amount'), count=Count('id'))
                .order_by('-total')
            )
        except Exception:
            pass

    context = {
        'page_title': f'راپور خزانه — {period["label"]}',
        'period': period,
        'stats': stats,
        'transactions': transactions,
        'breakdown_by_type': breakdown_by_type,
    }
    return render(request, 'reports/treasury.html', context)


# ======================================================================
# VIEW — راپور مرجوعی‌ها و ضایعات
# ======================================================================
def report_returns(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    customer_returns = []
    supplier_returns = []
    wastes = []

    if m['CustomerReturn']:
        customer_returns = (m['CustomerReturn'].objects
                            .filter(return_date__date__gte=start, return_date__date__lte=end)
                            .order_by('-return_date'))
    if m['SupplierReturn']:
        supplier_returns = (m['SupplierReturn'].objects
                            .filter(return_date__date__gte=start, return_date__date__lte=end)
                            .order_by('-return_date'))
    if m['Waste']:
        wastes = (m['Waste'].objects
                  .filter(waste_date__date__gte=start, waste_date__date__lte=end)
                  .order_by('-waste_date'))

    stats = _returns_stats(m, start, end)

    context = {
        'page_title': f'راپور مرجوعی‌ها و ضایعات — {period["label"]}',
        'period': period,
        'customer_returns': customer_returns,
        'supplier_returns': supplier_returns,
        'wastes': wastes,
        'stats': stats,
    }
    return render(request, 'reports/returns.html', context)


# ======================================================================
# VIEW — راپور قروض
# ======================================================================
def report_debts(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    purchase_debts = []
    sale_debts = []

    if m['PurchaseDebt']:
        purchase_debts = (m['PurchaseDebt'].objects
                          .filter(payment_date__date__gte=start, payment_date__date__lte=end)
                          .select_related('purchase')
                          .order_by('-payment_date'))

    if m['SaleDebt']:
        sale_debts = (m['SaleDebt'].objects
                      .filter(payment_date__date__gte=start, payment_date__date__lte=end)
                      .select_related('sale')
                      .order_by('-payment_date'))

    purchase_total = sum((d.amount for d in purchase_debts), Decimal('0'))
    sale_total = sum((d.amount for d in sale_debts), Decimal('0'))

    aging = _debt_aging(m)

    context = {
        'page_title': f'راپور قروض — {period["label"]}',
        'period': period,
        'purchase_debts': purchase_debts,
        'sale_debts': sale_debts,
        'purchase_total': purchase_total,
        'sale_total': sale_total,
        'purchase_count': len(purchase_debts),
        'sale_count': len(sale_debts),
        'aging': aging,
    }
    return render(request, 'reports/debts.html', context)


# ======================================================================
# VIEW — راپور کارمندان
# ======================================================================
def report_employees(request):
    period = _get_period(request)
    start, end = period['start'], period['end']
    m = _load_models()

    employees = []
    if m['Employee']:
        employees = m['Employee'].objects.all().order_by('full_name')

    stats = _employee_stats(m, start, end)

    context = {
        'page_title': 'راپور کارمندان',
        'period': period,
        'employees': employees,
        'stats': stats,
    }
    return render(request, 'reports/employees.html', context)




