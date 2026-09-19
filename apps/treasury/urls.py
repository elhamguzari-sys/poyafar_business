# apps/purchase/urls.py

from django.urls import path
from . import views


urlpatterns = [
 
    path('treasury_dashboard/', views.treasury_dashboard, name='treasury_dashboard'),
    path('transaction_list/', views.transaction_list, name='transaction_list'),
    path('create_transaction/', views.create_transaction, name='create_transaction'),
    path('update_transaction/<int:transaction_id>/', views.update_transaction, name='update_transaction'),
    path('delete_transaction/<int:transaction_id>/', views.delete_transaction, name='delete_transaction'),
]