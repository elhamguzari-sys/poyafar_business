from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, Sum
from django.contrib import messages
from django.http import HttpResponse

from .models import Location, Inventory, StockMovement
from .forms import LocationForm, InventoryForm, StockMovementForm
from apps.product.models import Product
from django.db.models import ProtectedError
from django.db import transaction


# ======================================================================
# LOCATION VIEWS
# ======================================================================
def location_list(request):
    """لیست موقعیت‌ها با جستجو و فیلتر"""
    locations_list = Location.objects.all().order_by('type', 'code')
    search_query = request.GET.get('search', '')
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')

    if search_query:
        locations_list = locations_list.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    # Statistics for cards (before filtering)
    total_locations_count = Location.objects.count()
    shop_count = Location.objects.filter(type='shop').count()
    warehouse_count = Location.objects.filter(type='warehouse').count()
    active_locations_count = Location.objects.filter(is_active=True).count()
    inactive_locations_count = Location.objects.filter(is_active=False).count()

    # Type filter
    if type_filter == 'shop':
        locations_list = locations_list.filter(type='shop')
    elif type_filter == 'warehouse':
        locations_list = locations_list.filter(type='warehouse')

    # Status filter
    if status_filter == 'active':
        locations_list = locations_list.filter(is_active=True)
    elif status_filter == 'inactive':
        locations_list = locations_list.filter(is_active=False)

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(locations_list, 10)

    try:
        locations = paginator.page(page_number)
    except PageNotAnInteger:
        locations = paginator.page(1)
    except EmptyPage:
        locations = paginator.page(paginator.num_pages)

    context = {
        'locations': locations,
        'search_query': search_query,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'paginator': paginator,
        'total_locations_count': total_locations_count,
        'shop_count': shop_count,
        'warehouse_count': warehouse_count,
        'active_locations_count': active_locations_count,
        'inactive_locations_count': inactive_locations_count,
        'page_title': 'لیست موقعیت‌ها',
    }

    return render(request, 'stock/location_list.html', context)


def create_location(request):
    """Create new location"""
    if request.method == 'POST':
        form = LocationForm(request.POST)

        if form.is_valid():
            location = form.save()
            messages.success(
                request,
                f'موقعیت "{location.name}" با کد "{location.code}" موفقانه اضافه شد.'
            )
            return redirect('location_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = LocationForm()

    return render(request, 'stock/create_location.html', {
        'form': form,
        'page_title': 'اضافه کردن موقعیت جدید',
    })


def update_location(request, location_id):
    """Update existing location"""
    location = get_object_or_404(Location, pk=location_id)

    if request.method == 'POST':
        form = LocationForm(request.POST, instance=location)

        if form.is_valid():
            updated_location = form.save()
            messages.success(
                request,
                f'موقعیت "{updated_location.name}" موفقانه تصحیح شد.'
            )
            return redirect('location_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = LocationForm(instance=location)

    return render(request, 'stock/update_location.html', {
        'form': form,
        'location': location,
        'page_title': 'ویرایش موقعیت',
    })


def delete_location(request, location_id):
    """
    حذف موقعیت — فقط اگر مجموع موجودی صفر باشد.
    حرکات انبار (StockMovement) همراه با موقعیت حذف می‌شوند.
    """
    location = get_object_or_404(Location, id=location_id)

    if request.method != 'POST':
        return HttpResponse(status=405)

    location_name = location.name
    location_code = location.code

    # ═══════════════════════════════════════════════════════════════
    # ۱. چک موجودی — اگر موجودی صفر نیست، اجازه حذف نده
    # ═══════════════════════════════════════════════════════════════
    non_zero_inventories = location.inventories.exclude(quantity=0)

    if non_zero_inventories.exists():
        total_qty = sum(inv.quantity for inv in non_zero_inventories)
        items_count = non_zero_inventories.count()

        messages.error(
            request,
            f'❌ امکان حذف موقعیت "{location_name}" وجود ندارد!\n'
            f'این موقعیت در حال حاضر {total_qty} واحد موجودی در {items_count} کالا دارد. '
            f'ابتدا موجودی را به موقعیت دیگری منتقل کنید یا آن را غیرفعال نمایید.'
        )
        return redirect('location_list')

    # ═══════════════════════════════════════════════════════════════
    # ۲. حذف واقعی — با ترتیب صحیح
    # ═══════════════════════════════════════════════════════════════
    try:
        with transaction.atomic():
            # ✅ مرحله ۱: حذف حرکات انبار (StockMovement)
            movements_qs = location.stock_movements.all()
            movements_count = movements_qs.count()

            if movements_count > 0:
                # ⚠️ مهم: از QuerySet.delete() استفاده می‌کنیم
                # چون instance.delete() خودش دوباره بررسی می‌کند
                movements_qs.delete()

            # ✅ مرحله ۲: حذف موجودی (Inventory)
            # ابتدا ردیف‌های صفر را پاک کن
            inventory_qs = location.inventories.all()
            inventory_count = inventory_qs.count()

            if inventory_count > 0:
                inventory_qs.delete()

            # ✅ مرحله ۳: حالا Location حذف شود
            # چون هیچ چیز وابسته‌ای باقی نمانده، PROTECT مانع نمی‌شود
            location.delete()

        # پیام موفقیت
        success_msg = (
            f'✅ موقعیت "{location_name}" با کد "{location_code}" موفقانه حذف شد.'
        )

        details = []
        if movements_count > 0:
            details.append(f'{movements_count} سابقه حرکت')
        if inventory_count > 0:
            details.append(f'{inventory_count} ردیف موجودی')

        if details:
            success_msg += f' ({", ".join(details)} نیز حذف شد.)'

        messages.success(request, success_msg)

    except ProtectedError as e:
        # اگر بازهم وابستگی دیگری مانع است
        messages.error(
            request,
            f'❌ امکان حذف "{location_name}" وجود ندارد. '
            f'وابستگی‌های دیگر: {str(e)}'
        )

    except Exception as e:
        messages.error(
            request,
            f'❌ خطا در حذف "{location_name}": {str(e)}'
        )

    return redirect('location_list')


def inventory_list(request):
    """لیست موجودی‌ها با جستجو و فیلتر"""
    inventories_list = Inventory.objects.select_related('product', 'location').order_by(
        'location__code', 'product__name'
    )
    search_query = request.GET.get('search', '')
    location_filter = request.GET.get('location', '')
    stock_filter = request.GET.get('stock_filter', '')

    if search_query:
        inventories_list = inventories_list.filter(
            Q(product__name__icontains=search_query) |
            Q(product__sku__icontains=search_query) |
            Q(location__name__icontains=search_query) |
            Q(location__code__icontains=search_query)
        )

    # Statistics for cards (before filtering)
    total_inventories_count = Inventory.objects.count()
    shop_inventories_count = Inventory.objects.filter(location__type='shop').count()
    warehouse_inventories_count = Inventory.objects.filter(location__type='warehouse').count()
    out_of_stock_count = Inventory.objects.filter(quantity__lte=0).count()

    total_shop_quantity = Inventory.objects.filter(
        location__type='shop'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    total_warehouse_quantity = Inventory.objects.filter(
        location__type='warehouse'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # Location filter
    if location_filter:
        inventories_list = inventories_list.filter(location_id=location_filter)

    # Stock filter
    if stock_filter == 'out':
        inventories_list = inventories_list.filter(quantity__lte=0)
    elif stock_filter == 'low':
        inventories_list = inventories_list.filter(quantity__gt=0)
    elif stock_filter == 'available':
        inventories_list = inventories_list.filter(quantity__gt=0)

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(inventories_list, 20)

    try:
        inventories = paginator.page(page_number)
    except PageNotAnInteger:
        inventories = paginator.page(1)
    except EmptyPage:
        inventories = paginator.page(paginator.num_pages)

    locations = Location.objects.filter(is_active=True).order_by('type', 'code')

    context = {
        'inventories': inventories,
        'search_query': search_query,
        'location_filter': location_filter,
        'stock_filter': stock_filter,
        'locations': locations,
        'paginator': paginator,
        'total_inventories_count': total_inventories_count,
        'shop_inventories_count': shop_inventories_count,
        'warehouse_inventories_count': warehouse_inventories_count,
        'out_of_stock_count': out_of_stock_count,
        'total_shop_quantity': total_shop_quantity,
        'total_warehouse_quantity': total_warehouse_quantity,
        'page_title': 'لیست موجودی‌ها',
    }

    return render(request, 'stock/inventory_list.html', context)


def inventory_detail(request, inventory_id):
    """Inventory detail (read-only)"""
    inventory = get_object_or_404(
        Inventory.objects.select_related('product', 'location'),
        pk=inventory_id
    )
    form = InventoryForm(instance=inventory)

    context = {
        'inventory': inventory,
        'form': form,
        'page_title': f'جزئیات موجودی: {inventory.product.name} @ {inventory.location.name}',
    }

    return render(request, 'stock/inventory_detail.html', context)


# ======================================================================
# STOCK MOVEMENT VIEWS
# ======================================================================
def stock_movement_list(request):
    """List all stock movements with search and filtering"""
    movements_list = StockMovement.objects.select_related(
        'product', 'location', 'created_by'
    ).order_by('-created_at')

    search_query = request.GET.get('search', '')
    type_filter = request.GET.get('type', '')
    location_filter = request.GET.get('location', '')
    product_filter = request.GET.get('product', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if search_query:
        movements_list = movements_list.filter(
            Q(reference_number__icontains=search_query) |
            Q(product__name__icontains=search_query) |
            Q(product__sku__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    # Statistics for cards (before filtering)
    total_movements_count = StockMovement.objects.count()
    stock_in_count = StockMovement.objects.filter(movement_type='IN').count()
    stock_out_count = StockMovement.objects.filter(movement_type='OUT').count()
    shop_movements_count = StockMovement.objects.filter(location__type='shop').count()
    stock_movements_count = StockMovement.objects.filter(location__type='warehouse').count()

    total_in_quantity = StockMovement.objects.filter(movement_type='IN').aggregate(
        total=Sum('quantity')
    )['total'] or 0

    total_out_quantity = StockMovement.objects.filter(movement_type='OUT').aggregate(
        total=Sum('quantity')
    )['total'] or 0
    total_out_quantity = abs(total_out_quantity)

    # Type filter
    if type_filter == 'IN':
        movements_list = movements_list.filter(movement_type='IN')
    elif type_filter == 'OUT':
        movements_list = movements_list.filter(movement_type='OUT')

    # Location filter (by id)
    if location_filter:
        movements_list = movements_list.filter(location_id=location_filter)

    # Product filter
    if product_filter:
        movements_list = movements_list.filter(product_id=product_filter)

    # Date filters
    if date_from:
        movements_list = movements_list.filter(created_at__date__gte=date_from)
    if date_to:
        movements_list = movements_list.filter(created_at__date__lte=date_to)

    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(movements_list, 20)

    try:
        movements = paginator.page(page_number)
    except PageNotAnInteger:
        movements = paginator.page(1)
    except EmptyPage:
        movements = paginator.page(paginator.num_pages)

    products = Product.objects.all().order_by('name')
    locations = Location.objects.filter(is_active=True).order_by('type', 'code')

    context = {
        'movements': movements,
        'search_query': search_query,
        'type_filter': type_filter,
        'location_filter': location_filter,
        'product_filter': product_filter,
        'date_from': date_from,
        'date_to': date_to,
        'products': products,
        'locations': locations,
        'paginator': paginator,
        'total_movements_count': total_movements_count,
        'stock_in_count': stock_in_count,
        'stock_out_count': stock_out_count,
        'shop_movements_count': shop_movements_count,
        'stock_movements_count': stock_movements_count,
        'total_in_quantity': total_in_quantity,
        'total_out_quantity': total_out_quantity,
        'page_title': 'لیست حرکات کالا',
    }

    return render(request, 'stock/stock_movement_list.html', context)


def create_stock_movement(request):
    """Create new stock movement"""
    if request.method == 'POST':
        form = StockMovementForm(request.POST)

        if form.is_valid():
            movement = form.save(commit=False)
            if request.user.is_authenticated:
                movement.created_by = request.user
            movement.save()

            location_name = movement.location.name
            location_type = movement.location.get_type_display()

            if movement.movement_type == 'IN':
                messages.success(
                    request,
                    f'ورود کالا به {location_type} «{location_name}» با شماره '
                    f'"{movement.reference_number}" موفقانه ثبت شد.'
                )
            else:
                messages.success(
                    request,
                    f'خروج کالا از {location_type} «{location_name}» با شماره '
                    f'"{movement.reference_number}" موفقانه ثبت شد.'
                )

            return redirect('stock_movement_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = StockMovementForm()

    return render(request, 'stock/create_stock_movement.html', {
        'form': form,
        'page_title': 'ثبت حرکت جدید کالا',
    })


def update_stock_movement(request, movement_id):
    """
    Update existing stock movement.
    نکته: مدل StockMovement خودش در save() اثر قبلی را برمی‌گرداند
    و اثر جدید را اعمال می‌کند. پس اینجا کاری لازم نیست.
    """
    movement = get_object_or_404(StockMovement, pk=movement_id)

    if request.method == 'POST':
        form = StockMovementForm(request.POST, instance=movement)

        if form.is_valid():
            updated_movement = form.save()
            messages.success(
                request,
                f'حرکت کالا با شماره "{updated_movement.reference_number}" موفقانه تصحیح شد.'
            )
            return redirect('stock_movement_list')
        else:
            messages.error(request, 'لطفاً معلومات را درست وارد کنید.')
    else:
        form = StockMovementForm(instance=movement)

    return render(request, 'stock/update_stock_movement.html', {
        'form': form,
        'movement': movement,
        'page_title': 'ویرایش حرکت کالا',
    })


def delete_stock_movement(request, movement_id):
    """Delete stock movement (مدل خودش اثر را برمی‌گرداند)"""
    movement = get_object_or_404(StockMovement, id=movement_id)

    if request.method == 'POST':
        reference_number = movement.reference_number
        movement.delete()
        messages.success(
            request,
            f'حرکت کالا با شماره "{reference_number}" موفقانه حذف شد.'
        )
        return redirect('stock_movement_list')

    return HttpResponse(status=405)