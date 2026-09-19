from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static
from . import views


urlpatterns = [
    
    path('', views.dashboard, name='dashboard_home'),

    path('admin/', admin.site.urls),
    path('products/', include('apps.product.urls')),
    path('stock/', include('apps.stock.urls')),
    path('purchasesale/', include('apps.purchasesale.urls')),
    path('debts/', include('apps.debts.urls')),
    path('treasury/', include('apps.treasury.urls')),
    path('expense/', include('apps.expense.urls')),
    path('employee/', include('apps.employee.urls')),
    path('reports/', include('apps.reports.urls')),
    path('backup/', include('apps.backup.urls')),
]



if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)