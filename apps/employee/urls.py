# apps/employee/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # ============ کارمندان ============
    path('employee_list/', views.employee_list, name='employee_list'),
    path('create_employee/', views.create_employee, name='create_employee'),
    path('update_employee/<int:employee_id>/', views.update_employee, name='update_employee'),
    path('delete_employee/<int:employee_id>/', views.delete_employee, name='delete_employee'),

    # ============ معاشات ============
    path('salary_list/', views.salary_list, name='salary_list'),
    path('create_salary/', views.create_salary, name='create_salary'),
    path('update_salary/<int:salary_id>/', views.update_salary, name='update_salary'),
    path('delete_salary/<int:salary_id>/', views.delete_salary, name='delete_salary'),
]