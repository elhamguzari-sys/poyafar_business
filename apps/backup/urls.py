from django.urls import path
from . import views

urlpatterns = [
    path('', views.backup_list, name='backup_list'),
    path('create-full/', views.backup_create_full, name='backup_create_full'),
    path('create-db/', views.backup_create_db, name='backup_create_db'),
    path('download/<int:backup_id>/', views.backup_download, name='backup_download'),
    path('delete/<int:backup_id>/', views.backup_delete, name='backup_delete'),
    path('restore/<int:backup_id>/', views.backup_restore, name='backup_restore'),
    path('run-now/', views.backup_run_now, name='backup_run_now'),
    path('settings/', views.update_auto_settings, name='update_auto_settings'),
]