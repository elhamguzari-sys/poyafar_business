from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Sum, F
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect

from .models import Category, Product
from .forms import CategoryForm, ProductForm
from apps.stock.models import Location
from django.db.models import ProtectedError


# ======================================================================
# Category
# ======================================================================
def category_list(request):
    categories_list = Category.objects.all().order_by('name')
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    if search_query:
        categories_list = categories_list.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    total_categories_count = Category.objects.count()
    active_categories_count = Category.objects.filter(is_active=True).count()
    inactive_categories_count = Category.objects.filter(is_active=False).count()

    if status_filter == 'active':
        categories_list = categories_list.filter(is_active=True)
    elif status_filter == 'inactive':
        categories_list = categories_list.filter(is_active=False)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(categories_list, 10)

    try:
        categories = paginator.page(page_number)
    except PageNotAnInteger:
        categories = paginator.page(1)
    except EmptyPage:
        categories = paginator.page(paginator.num_pages)

    context = {
        'categories': categories,
        'search_query': search_query,
        'status_filter': status_filter,
        'paginator': paginator,
        'total_categories_count': total_categories_count,
        'active_categories_count': active_categories_count,
        'inactive_categories_count': inactive_categories_count,
        'page_title': 'لیست دسته‌بندی کالاها',
    }

    return render(request, 'categories/category_list.html', context)


def create_category(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)

        if form.is_valid():
            category = form.save()
            messages.success(request, f'دسته‌بندی "{category.name}" موفقانه اضافه شد.')
            return redirect('category_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = CategoryForm()

    return render(request, 'categories/create_category.html', {
        'form': form,
        'page_title': 'اضافه کردن دسته‌بندی جدید',
    })


def update_category(request, category_id):
    category = get_object_or_404(Category, pk=category_id)

    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)

        if form.is_valid():
            updated_category = form.save()
            messages.success(request, f'دسته‌بندی "{updated_category.name}" موفقانه تصحیح شد.')
            return redirect('category_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = CategoryForm(instance=category)

    return render(request, 'categories/update_category.html', {
        'form': form,
        'category': category,
        'page_title': 'ویرایش دسته‌بندی'
    })


def delete_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)

    if request.method == 'POST':
        category_name = category.name
        try:
            category.delete()
            messages.success(request, f'دسته‌بندی "{category_name}" موفقانه حذف شد.')
        except ProtectedError:
            product_count = Product.objects.filter(category=category).count()
            messages.error(
                request,
                f'نمی‌توان دسته‌بندی "{category_name}" را حذف کرد. '
                f'{product_count} محصول به این دسته‌بندی وابسته است.'
            )
        return redirect('category_list')

    return HttpResponse(status=405)
# ======================================================================
# Product
# ======================================================================

def product_list(request):
    """لیست کالاها با جستجو و فیلتر"""

    products_list = (
        Product.objects
        .prefetch_related('inventories__location')
        .order_by('-created_at')
    )

    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    category_filter = request.GET.get('category', '')
    stock_filter = request.GET.get('stock_filter', '')

    # فیلترها
    if search_query:
        products_list = products_list.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    if status_filter == 'active':
        products_list = products_list.filter(status='active')
    elif status_filter == 'inactive':
        products_list = products_list.filter(status='inactive')
    elif status_filter == 'out_of_stock':
        products_list = products_list.filter(status='out_of_stock')

    if category_filter:
        products_list = products_list.filter(category_id=category_filter)

    if stock_filter == 'below_min':
        products_list = products_list.filter(current_stock__lte=F('min_stock'))
    elif stock_filter == 'above_min':
        products_list = products_list.filter(current_stock__gt=F('min_stock'))

    # آمار
    total_products_count = products_list.count()
    active_products_count = products_list.filter(status='active').count()
    out_of_stock_count = products_list.filter(status='out_of_stock').count()
    inactive_products_count = products_list.filter(status='inactive').count()
    low_stock_count = products_list.filter(current_stock__lte=F('min_stock')).count()

    total_shop_stock = products_list.aggregate(total=Sum('shop_stock'))['total'] or 0
    total_stock_stock = products_list.aggregate(total=Sum('stock_stock'))['total'] or 0
    total_current_stock = products_list.aggregate(total=Sum('current_stock'))['total'] or 0

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(products_list, 10)

    try:
        products = paginator.page(page_number)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    categories = Category.objects.filter(is_active=True).order_by('name')
    
    
    all_locations = Location.objects.filter(is_active=True).order_by('type', 'code')
    warehouse_locations = [loc for loc in all_locations if loc.type == 'warehouse']

    for product in products:
        inv_dict = {inv.location_id: inv.quantity for inv in product.inventories.all()}
        product.stock_by_location = [
            {
                'location': loc,
                'quantity': inv_dict.get(loc.id, 0),
            }
            for loc in all_locations
        ]

    context = {
        'products': products,
        'search_query': search_query,
        'status_filter': status_filter,
        'category_filter': category_filter,
        'stock_filter': stock_filter,
        'categories': categories,
        'warehouse_locations': warehouse_locations,
        'paginator': paginator,
        'total_products_count': total_products_count,
        'active_products_count': active_products_count,
        'out_of_stock_count': out_of_stock_count,
        'inactive_products_count': inactive_products_count,
        'low_stock_count': low_stock_count,
        'total_shop_stock': total_shop_stock,
        'total_stock_stock': total_stock_stock,
        'total_current_stock': total_current_stock,
        'page_title': 'لیست کالاها',
    }

    return render(request, 'products/product_list.html', context)



def create_product(request):
    """ساخت کالای جدید"""
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            product = form.save()
            messages.success(
                request,
                f'کالای "{product.name}" با کد "{product.sku}" موفقانه اضافه شد.'
            )
            return redirect('product_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = ProductForm()

    return render(request, 'products/create_product.html', {
        'form': form,
        'page_title': 'اضافه کردن کالای جدید',
    })


def update_product(request, product_id):
    """ویرایش کالا"""
    product = get_object_or_404(Product, pk=product_id)

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)

        if form.is_valid():
            updated_product = form.save()
            messages.success(request, f'کالای "{updated_product.name}" موفقانه تصحیح شد.')
            return redirect('product_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = ProductForm(instance=product)

    return render(request, 'products/update_product.html', {
        'form': form,
        'product': product,
        'page_title': 'ویرایش کالا'
    })



def delete_product(request, product_id):
    """حذف کالا"""
    product = get_object_or_404(Product, id=product_id)

    if request.method == 'POST':
        product_name = product.name
        product_sku = product.sku
        try:
            product.delete()
            messages.success(
                request,
                f'کالای "{product_name}" با کد "{product_sku}" موفقانه حذف شد.'
            )
        except ProtectedError as e:
            # Count the blocking records
            blocking = e.protected_objects
            inventory_count = sum(1 for obj in blocking if obj.__class__.__name__ == 'Inventory')
            movement_count = sum(1 for obj in blocking if obj.__class__.__name__ == 'StockMovement')

            details = []
            if inventory_count:
                details.append(f'{inventory_count} رکورد موجودی')
            if movement_count:
                details.append(f'{movement_count} حرکت انبار')

            messages.error(
                request,
                f'نمی‌توان کالای "{product_name}" را حذف کرد. '
                f'این کالا در {", ".join(details)} استفاده شده است.'
            )
        return redirect('product_list')

    return HttpResponse(status=405)