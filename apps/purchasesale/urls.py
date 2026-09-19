# apps/purchase/urls.py

from django.urls import path
from . import views


urlpatterns = [
    path('purchase_list/', views.purchase_list, name='purchase_list'),
    path('create_purchase/', views.create_purchase, name='create_purchase'),
    path('update_purchase/<int:purchase_id>/', views.update_purchase, name='update_purchase'),
    path('delete_purchase/<int:purchase_id>/', views.delete_purchase, name='delete_purchase'),
    
    
    path('sale_list/', views.sale_list, name='sale_list'),
    path('create_sale/', views.create_sale, name='create_sale'),
    path('update_sale/<int:sale_id>/', views.update_sale, name='update_sale'),
    path('delete_sale/<int:sale_id>/', views.delete_sale, name='delete_sale'),
    
    path('customer_return_list/', views.customer_return_list, name='customer_return_list'),
    path('create_customer_return/', views.create_customer_return, name='create_customer_return'),
    path('update_customer_return/<int:return_id>/', views.update_customer_return, name='update_customer_return'),
    path('delete_customer_return/<int:return_id>/', views.delete_customer_return, name='delete_customer_return'),

    # SupplierReturn URLs
    path('supplier_return_list/', views.supplier_return_list, name='supplier_return_list'),
    path('create_supplier_return/', views.create_supplier_return, name='create_supplier_return'),
    path('update_supplier_return/<int:return_id>/', views.update_supplier_return, name='update_supplier_return'),
    path('delete_supplier_return/<int:return_id>/', views.delete_supplier_return, name='delete_supplier_return'),
    
    
    
    
    path('waste_list/', views.waste_list, name='waste_list'),
    path('create_waste/', views.create_waste, name='create_waste'),
    path('update_waste/<int:waste_id>/', views.update_waste, name='update_waste'),
    path('delete_waste/<int:waste_id>/', views.delete_waste, name='delete_waste'),
    
]