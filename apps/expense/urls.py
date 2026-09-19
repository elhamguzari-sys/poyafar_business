from django.urls import path
from . import views

urlpatterns = [
    path('expense_list/', views.expense_list, name='expense_list'),
    path('create_expense/', views.create_expense, name='create_expense'),
    path('update_expense/<int:expense_id>/', views.update_expense, name='update_expense'),
    path('delete_expense/<int:expense_id>/', views.delete_expense, name='delete_expense'),
]