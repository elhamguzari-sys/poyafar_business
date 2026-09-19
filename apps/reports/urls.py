# apps/reports/urls.py

from django.urls import path
from . import views

urlpatterns = [
    
    path('', views.report_overview, name='report_overview'),
    path('sales/', views.report_sales, name='report_sales'),
    path('purchases/', views.report_purchases, name='report_purchases'),
    path('expenses/', views.report_expenses, name='report_expenses'),
    path('salaries/', views.report_salaries, name='report_salaries'),
    path('stock/', views.report_stock, name='report_stock'),
    path('treasury/', views.report_treasury, name='report_treasury'),
    path('returns/', views.report_returns, name='report_returns'),
    path('debts/', views.report_debts, name='report_debts'),
    path('employees/', views.report_employees, name='report_employees'),
]