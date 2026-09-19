from django.urls import path
from . import views


urlpatterns = [
    path('stock_movement_list/', views.stock_movement_list, name='stock_movement_list'),
    path('create_stock_movement/', views.create_stock_movement, name='create_stock_movement'),
    path('update_stock_movement/<int:movement_id>/', views.update_stock_movement, name='update_stock_movement'),
    path('delete_stock_movement/<int:movement_id>/', views.delete_stock_movement, name='delete_stock_movement'),

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    path('location_list/', views.location_list, name='location_list'),
    path('create_location/', views.create_location, name='create_location'),
    path('update_location/<int:location_id>/', views.update_location, name='update_location'),
    path('delete_location/<int:location_id>/', views.delete_location, name='delete_location'),

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    path('inventory_list/', views.inventory_list, name='inventory_list'),
    path('inventory_detail/<int:inventory_id>/', views.inventory_detail, name='inventory_detail'),
    
  
]
