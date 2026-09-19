from django.urls import path
from . import views


urlpatterns = [
    path('purchase_debt_list/', views.purchase_debt_list, name='purchase_debt_list'),
    path('create_purchase_debt/<int:purchase_id>/', views.create_purchase_debt, name='create_purchase_debt'),
    path('update_purchase_debt/<int:debt_id>/', views.update_purchase_debt, name='update_purchase_debt'),
    path('delete_purchase_debt/<int:debt_id>/', views.delete_purchase_debt, name='delete_purchase_debt'),
    path('purchase_debt_history/<int:purchase_id>/', views.purchase_debt_history, name='purchase_debt_history'),
    
    path('sale_debt_list/', views.sale_debt_list, name='sale_debt_list'),
    path('create_sale_debt/<int:sale_id>/', views.create_sale_debt, name='create_sale_debt'),
    path('update_sale_debt/<int:debt_id>/', views.update_sale_debt, name='update_sale_debt'),
    path('delete_sale_debt/<int:debt_id>/', views.delete_sale_debt, name='delete_sale_debt'),
    path('sale_debt_history/<int:sale_id>/', views.sale_debt_history, name='sale_debt_history'),

  
]
